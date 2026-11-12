"""
CCXT-based Institutional Market Data & Order Flow Intelligence Fetcher (v2.0).
Features:
    - Real Taker Buy / Taker Sell Volume extraction from exchange klines (True CVD & Real Money Delta)
    - Closed-Candle Flagging (`is_closed`) to eliminate repainting on unclosed live candles
    - Deep Order Book Liquidity Filtering (500 levels within ±2% price range to filter spoofing)
    - Perpetual Futures Intelligence (Funding Rate, Open Interest USD, 24h OI Change %, Top Trader Long/Short Ratio)
    - Parallel Multi-Timeframe & Multi-Symbol Fetching via ThreadPoolExecutor
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import threading
from typing import Dict, List, Optional, Tuple

import ccxt
import numpy as np
import pandas as pd

from .config import ExchangeConfig

logger = logging.getLogger(__name__)


@dataclass
class OrderFlowIntel:
    """
    Real-time Deep Order Book, Spot 24h Volume, and Futures (Funding Rate, Open Interest,
    OI Delta %, Long/Short Ratio) intelligence for a given crypto pair.
    """
    symbol: str
    exchange: str
    # Deep Order Book (Filtered within ±2% of mid price)
    bid_volume_usd: float = 0.0
    ask_volume_usd: float = 0.0
    imbalance_pct: float = 50.0          # 0-100% (% of filtered depth on Bid/Buyer side)
    imbalance_net_ratio: float = 0.0     # -1.0 to +1.0 ((Bid - Ask) / (Bid + Ask))
    strongest_bid_wall: float = 0.0      # Price of largest buy liquidity cluster
    strongest_ask_wall: float = 0.0      # Price of largest sell liquidity cluster
    strongest_bid_wall_usd: float = 0.0  # USD size of strongest buy liquidity wall
    strongest_ask_wall_usd: float = 0.0  # USD size of strongest sell liquidity wall
    orderbook_status_tr: str = "Dengeli Emir Defteri"

    # 24h Ticker Stats
    price_change_24h_pct: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    quote_volume_24h_usd: float = 0.0    # 24h USDT volume

    # Perpetual Futures Metrics (Funding Rate, Open Interest, OI Change, Long/Short Ratio, Basis, Taker Ratio, OI Matrix, Perp CVD)
    funding_rate_pct: Optional[float] = None
    open_interest_usd: Optional[float] = None
    oi_change_1h_pct: Optional[float] = None
    oi_change_4h_pct: Optional[float] = None
    oi_change_24h_pct: Optional[float] = None
    long_short_ratio: Optional[float] = None
    futures_taker_buy_sell_ratio: Optional[float] = None
    perp_spot_basis_pct: Optional[float] = None
    perp_cvd_delta_24h_usd: Optional[float] = None
    oi_regime_tr: str = "Veri Yok"
    spot_vs_perp_cvd_tr: str = "Dengeli Spot & Vadeli Akışı"
    futures_sentiment_tr: str = "Veri Yok"


_THREAD_LOCAL = threading.local()


class CryptoDataFetcher:
    """
    Fetches real-time OHLCV candlestick data with real Taker Buy/Sell volume (when available),
    deep Order Book depth, 24h volume stats, and Perpetual Futures intelligence.
    """

    def __init__(self, config: Optional[ExchangeConfig] = None):
        self.config = config or ExchangeConfig()

    def _get_spot_exchange(self, exchange_id: str) -> ccxt.Exchange:
        ex_key = exchange_id.lower()
        spot_clients = getattr(_THREAD_LOCAL, "spot_clients", None)
        if spot_clients is None:
            spot_clients = {}
            _THREAD_LOCAL.spot_clients = spot_clients
        if ex_key not in spot_clients:
            exchange_class = getattr(ccxt, ex_key, None)
            if exchange_class is None:
                raise ValueError(f"Desteklenmeyen borsa ID: {exchange_id}")
            spot_clients[ex_key] = exchange_class({
                "enableRateLimit": False,
                "timeout": self.config.timeout_ms,
                "options": {"defaultType": "spot"},
            })
        return spot_clients[ex_key]

    def _get_swap_exchange(self, exchange_id: str) -> ccxt.Exchange:
        ex_key = exchange_id.lower()
        swap_clients = getattr(_THREAD_LOCAL, "swap_clients", None)
        if swap_clients is None:
            swap_clients = {}
            _THREAD_LOCAL.swap_clients = swap_clients
        if ex_key not in swap_clients:
            exchange_class = getattr(ccxt, ex_key, None)
            if exchange_class is None:
                raise ValueError(f"Desteklenmeyen borsa ID: {exchange_id}")
            swap_clients[ex_key] = exchange_class({
                "enableRateLimit": False,
                "timeout": self.config.timeout_ms,
                "options": {"defaultType": "swap"},
            })
        return swap_clients[ex_key]

    def fetch_ohlcv(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: Optional[int] = None,
        exchange_id: Optional[str] = None,
        allow_synthetic_fallback: bool = True,
    ) -> Tuple[pd.DataFrame, str]:
        """
        Fetch OHLCV data (including real Taker Buy/Sell volume from Binance klines when available)
        and mark whether the final candle is still open (`is_closed`).
        """
        target_symbol = symbol or self.config.symbol
        target_tf = timeframe or self.config.timeframe
        target_limit = limit or self.config.limit

        exchanges_to_try: List[str] = []
        if exchange_id:
            exchanges_to_try.append(exchange_id)
        else:
            exchanges_to_try.append(self.config.primary_exchange)
            for fb in self.config.fallback_exchanges:
                if fb not in exchanges_to_try:
                    exchanges_to_try.append(fb)

        last_error: Optional[Exception] = None

        for ex_id in exchanges_to_try:
            try:
                exchange = self._get_spot_exchange(ex_id)

                # If Binance, attempt raw klines first to get exact Taker Buy Base/Quote Volume
                if ex_id.lower() == "binance":
                    try:
                        market_id = target_symbol.replace("/", "").replace(":USDT", "")
                        raw_klines = exchange.publicGetKlines({
                            "symbol": market_id,
                            "interval": target_tf,
                            "limit": target_limit,
                        })
                        if raw_klines and len(raw_klines) > 0:
                            df = self._normalize_binance_klines(raw_klines, target_tf)
                            return df, "BINANCE"
                    except Exception as bin_exc:
                        logger.debug(f"Binance raw kline fallback: {bin_exc}")

                raw_ohlcv = exchange.fetch_ohlcv(
                    symbol=target_symbol,
                    timeframe=target_tf,
                    limit=target_limit,
                )
                if not raw_ohlcv or len(raw_ohlcv) == 0:
                    raise RuntimeError(f"{ex_id} boş OHLCV verisi döndürdü.")

                df = self._normalize_dataframe(raw_ohlcv, target_tf)
                return df, ex_id.upper()

            except Exception as exc:
                last_error = exc
                logger.warning(f"[{ex_id.upper()}] Veri çekme hatası: {exc}. Alternatif deneniyor...")

        if allow_synthetic_fallback:
            logger.warning("Canlı borsa bağlantısı kurulamadı. Gerçekçi simülasyon verisi üretiliyor...")
            return self.generate_synthetic_ohlcv(limit=target_limit, timeframe=target_tf), "SIMULATED_FALLBACK"

        raise RuntimeError(f"Hiçbir borsadan veri alınamadı. Son hata: {last_error}")

    def fetch_multi_timeframe_parallel(
        self,
        symbol: str,
        timeframes: List[str],
        limit: int = 200,
        exchange_id: Optional[str] = None,
        allow_synthetic_fallback: bool = True,
    ) -> Tuple[Dict[str, pd.DataFrame], str]:
        """
        Fetch multiple timeframes (e.g. 15m, 1h, 4h, 1d) concurrently using a thread pool
        for 3x-4x faster execution.
        """
        results: Dict[str, pd.DataFrame] = {}
        source_used = (exchange_id or self.config.primary_exchange).upper()

        with ThreadPoolExecutor(max_workers=min(len(timeframes), 4)) as executor:
            future_to_tf = {
                executor.submit(
                    self.fetch_ohlcv,
                    symbol=symbol,
                    timeframe=tf.lower(),
                    limit=limit,
                    exchange_id=exchange_id,
                    allow_synthetic_fallback=allow_synthetic_fallback,
                ): tf.upper()
                for tf in timeframes
            }
            for fut in as_completed(future_to_tf):
                tf_key = future_to_tf[fut]
                df_tf, src = fut.result()
                results[tf_key] = df_tf
                source_used = src

        # Preserve requested timeframe ordering
        ordered = {tf.upper(): results[tf.upper()] for tf in timeframes if tf.upper() in results}
        return ordered, source_used

    def fetch_order_flow_intel(
        self,
        symbol: Optional[str] = None,
        exchange_id: Optional[str] = None,
    ) -> OrderFlowIntel:
        """
        Fetch Deep Order Book Imbalance (filtered within ±2.5% of mid-price to eliminate
        far-away spoofing orders), 24h Spot Volume, and Perpetual Futures Funding Rate,
        Open Interest, 24h OI Change %, and Top Trader Long/Short Ratio.
        """
        target_symbol = symbol or self.config.symbol
        ex_id = (exchange_id or self.config.primary_exchange).lower()

        intel = OrderFlowIntel(symbol=target_symbol, exchange=ex_id.upper())

        # 1. Deep Spot Order Book & 24h Ticker
        try:
            spot = self._get_spot_exchange(ex_id)
            raw_sym = target_symbol.replace("/", "").replace(":USDT", "")
            depth_limit = 500 if ex_id == "binance" else 100
            if ex_id == "binance":
                ob = spot.publicGetDepth({"symbol": raw_sym, "limit": depth_limit})
            else:
                ob = spot.fetch_order_book(target_symbol, limit=depth_limit)
            bids = ob.get("bids", [])
            asks = ob.get("asks", [])

            if bids and asks:
                mid_price = (float(bids[0][0]) + float(asks[0][0])) / 2.0
                # Filter orders within ±2.5% of mid_price to focus on actionable liquidity
                valid_bids = [(float(p), float(q)) for p, q in bids if float(p) >= mid_price * 0.975]
                valid_asks = [(float(p), float(q)) for p, q in asks if float(p) <= mid_price * 1.025]
                if not valid_bids:
                    valid_bids = [(float(p), float(q)) for p, q in bids[:50]]
                if not valid_asks:
                    valid_asks = [(float(p), float(q)) for p, q in asks[:50]]

                bid_usd = float(sum(p * q for p, q in valid_bids))
                ask_usd = float(sum(p * q for p, q in valid_asks))

                # Inverse-distance exponential weighting: exp(-dist_pct / 0.85) to filter distant spoofing orders
                w_bid_usd = float(
                    sum(
                        (p * q) * np.exp(-abs((mid_price - p) / max(mid_price, 1e-9)) * 100.0 / 0.85)
                        for p, q in valid_bids
                    )
                )
                w_ask_usd = float(
                    sum(
                        (p * q) * np.exp(-abs((p - mid_price) / max(mid_price, 1e-9)) * 100.0 / 0.85)
                        for p, q in valid_asks
                    )
                )
                w_total_usd = w_bid_usd + w_ask_usd

                intel.bid_volume_usd = bid_usd
                intel.ask_volume_usd = ask_usd
                if w_total_usd > 0:
                    intel.imbalance_pct = (w_bid_usd / w_total_usd) * 100.0
                    intel.imbalance_net_ratio = (w_bid_usd - w_ask_usd) / w_total_usd

                # Identify largest Bid Wall & Ask Wall within actionable depth
                best_bid_wall = max(valid_bids, key=lambda x: x[0] * x[1])
                best_ask_wall = max(valid_asks, key=lambda x: x[0] * x[1])
                intel.strongest_bid_wall = float(best_bid_wall[0])
                intel.strongest_ask_wall = float(best_ask_wall[0])
                intel.strongest_bid_wall_usd = float(best_bid_wall[0] * best_bid_wall[1])
                intel.strongest_ask_wall_usd = float(best_ask_wall[0] * best_ask_wall[1])

                if intel.imbalance_pct >= 58.0:
                    intel.orderbook_status_tr = f"Güçlü Alıcı Likiditesi (%{intel.imbalance_pct:.1f} Alış Duvarı)"
                elif intel.imbalance_pct >= 52.5:
                    intel.orderbook_status_tr = f"Alıcı Ağırlıklı Derinlik (%{intel.imbalance_pct:.1f} Alış)"
                elif intel.imbalance_pct <= 42.0:
                    intel.orderbook_status_tr = f"Güçlü Satıcı Likiditesi (%{100 - intel.imbalance_pct:.1f} Satış Duvarı)"
                elif intel.imbalance_pct <= 47.5:
                    intel.orderbook_status_tr = f"Satıcı Ağırlıklı Derinlik (%{100 - intel.imbalance_pct:.1f} Satış)"
                else:
                    intel.orderbook_status_tr = f"Dengeli Emir Defteri (%{intel.imbalance_pct:.1f} Alış / %{100 - intel.imbalance_pct:.1f} Satış)"

            if ex_id == "binance":
                t24 = spot.publicGetTicker24hr({"symbol": raw_sym})
                intel.price_change_24h_pct = float(t24.get("priceChangePercent") or 0.0)
                intel.high_24h = float(t24.get("highPrice") or 0.0)
                intel.low_24h = float(t24.get("lowPrice") or 0.0)
                intel.quote_volume_24h_usd = float(t24.get("quoteVolume") or 0.0)
            else:
                ticker = spot.fetch_ticker(target_symbol)
                intel.price_change_24h_pct = float(ticker.get("percentage") or 0.0)
                intel.high_24h = float(ticker.get("high") or 0.0)
                intel.low_24h = float(ticker.get("low") or 0.0)
                intel.quote_volume_24h_usd = float(ticker.get("quoteVolume") or 0.0)

        except Exception as exc:
            logger.debug(f"[{ex_id.upper()}] Spot OrderBook/Ticker uyarısı ({target_symbol}): {exc}")

        # 2. Perpetual Futures Intelligence (Funding Rate, OI, OI Change %, Long/Short Ratio)
        try:
            swap = self._get_swap_exchange(ex_id)
            raw_sym = target_symbol.replace("/", "").replace(":USDT", "")
            mark_p_ref = 0.0
            if ex_id == "binance":
                try:
                    prem = swap.fapiPublicGetPremiumIndex({"symbol": raw_sym})
                    if prem and prem.get("lastFundingRate") is not None:
                        intel.funding_rate_pct = float(prem["lastFundingRate"]) * 100.0
                    mark_p_ref = float(prem.get("markPrice") or 0.0)
                    idx_p = float(prem.get("indexPrice") or 0.0)
                    if mark_p_ref > 0 and idx_p > 0:
                        intel.perp_spot_basis_pct = ((mark_p_ref - idx_p) / idx_p) * 100.0
                except Exception:
                    pass
            else:
                swap_symbol = f"{target_symbol}:USDT" if ":" not in target_symbol else target_symbol
                fr_data = None
                try:
                    fr_data = swap.fetch_funding_rate(swap_symbol)
                except Exception:
                    fr_data = swap.fetch_funding_rate(target_symbol)
                if fr_data and fr_data.get("fundingRate") is not None:
                    intel.funding_rate_pct = float(fr_data["fundingRate"]) * 100.0
                if fr_data and fr_data.get("markPrice") and fr_data.get("indexPrice"):
                    mark_p_ref = float(fr_data["markPrice"])
                    idx_p = float(fr_data["indexPrice"])
                    if idx_p > 0:
                        intel.perp_spot_basis_pct = ((mark_p_ref - idx_p) / idx_p) * 100.0
                try:
                    oi_data = swap.fetch_open_interest(swap_symbol)
                    if oi_data and oi_data.get("openInterestValue") is not None:
                        intel.open_interest_usd = float(oi_data["openInterestValue"])
                except Exception:
                    pass

            # Try fetching Historical OI Change (last 24h), Long/Short Ratio & Futures Taker Buy/Sell Ratio on Binance Futures
            if ex_id == "binance":
                try:
                    oi_hist = swap.fapiDataGetOpenInterestHist({
                        "symbol": raw_sym,
                        "period": "1h",
                        "limit": 24,
                    })
                    if oi_hist and len(oi_hist) >= 2:
                        oi_start = float(oi_hist[0].get("sumOpenInterestValue", 0.0))
                        oi_end = float(oi_hist[-1].get("sumOpenInterestValue", 0.0))
                        if oi_start > 0:
                            intel.oi_change_24h_pct = ((oi_end - oi_start) / oi_start) * 100.0
                        oi_prev_1h = float(oi_hist[-2].get("sumOpenInterestValue", 0.0))
                        if oi_prev_1h > 0:
                            intel.oi_change_1h_pct = ((oi_end - oi_prev_1h) / oi_prev_1h) * 100.0
                        idx_4h = max(0, len(oi_hist) - 5)
                        oi_prev_4h = float(oi_hist[idx_4h].get("sumOpenInterestValue", 0.0))
                        if oi_prev_4h > 0:
                            intel.oi_change_4h_pct = ((oi_end - oi_prev_4h) / oi_prev_4h) * 100.0
                        if intel.open_interest_usd is None and oi_end > 0:
                            intel.open_interest_usd = oi_end
                except Exception:
                    pass

                try:
                    ls_hist = swap.fapiDataGetTopLongShortPositionRatio({
                        "symbol": raw_sym,
                        "period": "1h",
                        "limit": 1,
                    })
                    if ls_hist and len(ls_hist) >= 1:
                        intel.long_short_ratio = float(ls_hist[-1].get("longShortRatio", 1.0))
                except Exception:
                    pass

                try:
                    taker_hist = swap.fapiDataGetTakerlongshortRatio({
                        "symbol": raw_sym,
                        "period": "1h",
                        "limit": 6,
                    })
                    if taker_hist and len(taker_hist) >= 1:
                        intel.futures_taker_buy_sell_ratio = float(taker_hist[-1].get("buySellRatio", 1.0))
                        buy_vol_sum = sum(float(x.get("buyVol", 0.0)) for x in taker_hist)
                        sell_vol_sum = sum(float(x.get("sellVol", 0.0)) for x in taker_hist)
                        ref_p = float(mark_p_ref or intel.high_24h or 1.0)
                        intel.perp_cvd_delta_24h_usd = (buy_vol_sum - sell_vol_sum) * ref_p
                except Exception:
                    pass

            # Classify 4-Quadrant Open Interest (OI) x Price Regime
            if intel.oi_change_24h_pct is not None:
                p_chg = intel.price_change_24h_pct
                oi_chg = intel.oi_change_24h_pct
                if p_chg >= 0.4 and oi_chg >= 1.0:
                    intel.oi_regime_tr = f"🟢 Yeni Long Girişi (Fiyat {p_chg:+.1f}% ↑ | OI {oi_chg:+.1f}% ↑ — Güçlü Trend)"
                elif p_chg >= 0.4 and oi_chg <= -1.0:
                    intel.oi_regime_tr = f"🟡 Short Squeeze / Kapatma (Fiyat {p_chg:+.1f}% ↑ | OI {oi_chg:+.1f}% ↓ — Yorulma Riski)"
                elif p_chg <= -0.4 and oi_chg >= 1.0:
                    intel.oi_regime_tr = f"🔴 Yeni Agresif Short Girişi (Fiyat {p_chg:+.1f}% ↓ | OI {oi_chg:+.1f}% ↑ — Düşüş Baskısı)"
                elif p_chg <= -0.4 and oi_chg <= -1.0:
                    intel.oi_regime_tr = f"🔵 Long Tasfiyesi / Kapitülasyon (Fiyat {p_chg:+.1f}% ↓ | OI {oi_chg:+.1f}% ↓ — Dip Adayı)"
                else:
                    intel.oi_regime_tr = f"⚪ Dengeli OI Rejimi (Fiyat {p_chg:+.1f}% | OI {oi_chg:+.1f}%)"

            # Classify Spot Depth/Flow vs Perpetual Taker CVD Divergence
            if intel.futures_taker_buy_sell_ratio is not None:
                ft_r = intel.futures_taker_buy_sell_ratio
                ob_pct = intel.imbalance_pct
                if ob_pct >= 52.0 and ft_r <= 0.96:
                    intel.spot_vs_perp_cvd_tr = f"🟢 Spot Alıcı Emilimi / Short Tuzağı (Spot Alış: %{ob_pct:.0f} vs Vadeli Taker: {ft_r:.2f})"
                elif ob_pct <= 48.0 and ft_r >= 1.05:
                    intel.spot_vs_perp_cvd_tr = f"⚠️ Kaldıraç Köpüğü / Boğa Tuzağı Riski (Spot Alış: %{ob_pct:.0f} vs Vadeli Taker: {ft_r:.2f})"
                elif ob_pct >= 52.0 and ft_r >= 1.03:
                    intel.spot_vs_perp_cvd_tr = f"🟢 Senkronize Spot & Vadeli Alım (Spot: %{ob_pct:.0f} | Vadeli Taker: {ft_r:.2f})"
                elif ob_pct <= 48.0 and ft_r <= 0.97:
                    intel.spot_vs_perp_cvd_tr = f"🔴 Senkronize Spot & Vadeli Satış (Spot: %{ob_pct:.0f} | Vadeli Taker: {ft_r:.2f})"
                else:
                    intel.spot_vs_perp_cvd_tr = f"⚪ Dengeli Spot & Vadeli Akışı (Spot: %{ob_pct:.0f} | Vadeli Taker: {ft_r:.2f})"

            if intel.funding_rate_pct is not None:
                fr = intel.funding_rate_pct
                oi_delta_str = f" | 24s OI: {intel.oi_change_24h_pct:+.1f}%" if intel.oi_change_24h_pct is not None else ""
                ls_str = f" | L/S: {intel.long_short_ratio:.2f}" if intel.long_short_ratio is not None else ""
                tkr_str = f" | Taker Al/Sat: {intel.futures_taker_buy_sell_ratio:.2f}" if intel.futures_taker_buy_sell_ratio is not None else ""
                basis_str = f" | Basis: {intel.perp_spot_basis_pct:+.3f}%" if intel.perp_spot_basis_pct is not None else ""

                if fr > 0.03:
                    intel.futures_sentiment_tr = f"Aşırı Long Yoğunluğu (Fonlama: +%{fr:.4f}{oi_delta_str}{ls_str}{tkr_str}{basis_str})"
                elif fr >= 0.005:
                    intel.futures_sentiment_tr = f"Pozitif Fonlama (+%{fr:.4f}{oi_delta_str}{ls_str}{tkr_str}{basis_str})"
                elif fr < -0.015:
                    intel.futures_sentiment_tr = f"Short Yoğunluğu / Squeeze Adayı (Fonlama: %{fr:.4f}{oi_delta_str}{ls_str}{tkr_str}{basis_str})"
                elif fr < 0.0:
                    intel.futures_sentiment_tr = f"Negatif Fonlama (%{fr:.4f}{oi_delta_str}{ls_str}{tkr_str}{basis_str})"
                else:
                    intel.futures_sentiment_tr = f"Nötr Fonlama (+%{fr:.4f}{oi_delta_str}{ls_str}{tkr_str}{basis_str})"

        except Exception as exc:
            logger.debug(f"[{ex_id.upper()}] Vadeli İşlem (Funding/OI) uyarısı ({target_symbol}): {exc}")

        return intel

    @staticmethod
    def _normalize_binance_klines(raw_klines: list, timeframe: str) -> pd.DataFrame:
        """
        Parse Binance 12-column klines including Real Taker Buy Base & Quote Volume:
            0: open_time, 1: open, 2: high, 3: low, 4: close, 5: volume,
            6: close_time, 7: quote_volume, 8: trades,
            9: taker_buy_base_vol, 10: taker_buy_quote_vol, 11: ignore
        """
        df = pd.DataFrame(
            raw_klines,
            columns=[
                "timestamp_ms", "open", "high", "low", "close", "volume",
                "close_time_ms", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore",
            ],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp_ms"].astype(np.int64), unit="ms", utc=True)
        for col in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

        # Calculate Real Taker Sell Quote Volume & Real Net Taker Delta in USDT
        df["taker_sell_quote"] = (df["quote_volume"] - df["taker_buy_quote"]).clip(lower=0.0)
        df["real_net_delta_usd"] = df["taker_buy_quote"] - df["taker_sell_quote"]

        # Flag whether each candle is closed (last candle is usually still forming)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        df["is_closed"] = df["close_time_ms"].astype(np.int64) <= now_ms
        # Guarantee last candle is marked unclosed if close_time is in the future
        if len(df) > 1 and df["is_closed"].iloc[-1]:
            tf_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}.get(timeframe.lower(), 3_600_000)
            if (now_ms - int(df["timestamp_ms"].iloc[-1])) < tf_ms:
                df.loc[df.index[-1], "is_closed"] = False

        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)
        return df[["timestamp", "open", "high", "low", "close", "volume", "quote_volume", "taker_buy_quote", "real_net_delta_usd", "is_closed"]]

    @staticmethod
    def _normalize_dataframe(raw_ohlcv: list, timeframe: str = "1h") -> pd.DataFrame:
        df = pd.DataFrame(
            raw_ohlcv,
            columns=["timestamp_ms", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)
        # Mark all historical candles as closed except the very last forming candle
        df["is_closed"] = True
        if len(df) > 2:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            tf_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}.get(timeframe.lower(), 3_600_000)
            last_ts_ms = int(df["timestamp"].iloc[-1].timestamp() * 1000)
            if (now_ms - last_ts_ms) < tf_ms:
                df.loc[df.index[-1], "is_closed"] = False

        return df[["timestamp", "open", "high", "low", "close", "volume", "is_closed"]]

    @staticmethod
    def generate_synthetic_ohlcv(limit: int = 250, timeframe: str = "1h", seed: int = 42) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(timeframe, 60)

        timestamps = [now - timedelta(minutes=tf_minutes * (limit - 1 - i)) for i in range(limit)]

        base_price = 68000.0
        t = np.linspace(0, 6 * np.pi, limit)
        wave = np.sin(t) * 1800.0 + np.cos(t * 2.3) * 900.0
        noise = np.cumsum(rng.normal(0, 140, size=limit))
        closes = base_price + wave + noise

        opens = np.zeros(limit)
        highs = np.zeros(limit)
        lows = np.zeros(limit)
        volumes = rng.uniform(450, 2800, size=limit)

        opens[0] = closes[0] - rng.normal(0, 80)
        for i in range(1, limit):
            opens[i] = closes[i - 1] + rng.normal(0, 25)

        for i in range(limit):
            body_high = max(opens[i], closes[i])
            body_low = min(opens[i], closes[i])
            body_size = max(abs(closes[i] - opens[i]), 30.0)
            highs[i] = body_high + abs(rng.normal(0, body_size * 0.65))
            lows[i] = body_low - abs(rng.normal(0, body_size * 0.65))

        if limit >= 100:
            idx = limit - 60
            for k in range(idx - 6, idx):
                opens[k] = closes[k - 1]
                closes[k] = opens[k] - 380.0
                highs[k] = opens[k] + 40.0
                lows[k] = closes[k] - 50.0
            opens[idx] = closes[idx - 1]
            closes[idx] = opens[idx] - 180.0
            highs[idx] = opens[idx] + 30.0
            lows[idx] = closes[idx] - 40.0
            opens[idx + 1] = closes[idx] - 35.0
            closes[idx + 1] = opens[idx] + 290.0
            lows[idx + 1] = opens[idx + 1] - 40.0
            highs[idx + 1] = closes[idx + 1] + 60.0
            volumes[idx + 1] *= 2.6

            idx2 = limit - 25
            for k in range(idx2 - 6, idx2):
                opens[k] = closes[k - 1]
                closes[k] = opens[k] + 410.0
                highs[k] = closes[k] + 55.0
                lows[k] = opens[k] - 30.0
            opens[idx2] = closes[idx2 - 1]
            closes[idx2] = opens[idx2] + 8.0
            highs[idx2] = opens[idx2] + 320.0
            lows[idx2] = opens[idx2] - 310.0
            opens[idx2 + 1] = closes[idx2] + 40.0
            closes[idx2 + 1] = opens[idx2 - 1] - 120.0
            highs[idx2 + 1] = opens[idx2 + 1] + 50.0
            lows[idx2 + 1] = closes[idx2 + 1] - 70.0
            volumes[idx2 + 1] *= 2.8

        df = pd.DataFrame({
            "timestamp": pd.to_datetime(timestamps, utc=True),
            "open": np.round(opens, 2),
            "high": np.round(highs, 2),
            "low": np.round(lows, 2),
            "close": np.round(closes, 2),
            "volume": np.round(volumes, 4),
            "is_closed": True,
        })
        return df
