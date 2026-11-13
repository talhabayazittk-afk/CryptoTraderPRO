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
import json
import logging
import threading
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import ccxt
import numpy as np
import pandas as pd

from .config import ExchangeConfig

logger = logging.getLogger(__name__)

_BINANCE_VISION_BASE = "https://data-api.binance.vision/api/v3"


def _http_get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: float = 6.0) -> Any:
    """Direct lightweight HTTP GET helper with browser User-Agent (bypasses US geo-blocks on data-api.binance.vision)."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
            cfg_opts = {
                "enableRateLimit": False,
                "timeout": self.config.timeout_ms,
                "options": {"defaultType": "spot"},
            }
            if ex_key == "binance":
                # Use Binance's official global market-data mirror so US-hosted cloud servers (e.g. streamlit.app)
                # never hit HTTP 451 geo-restrictions while still getting exact Binance Spot klines/CVD/depth.
                cfg_opts["urls"] = {"api": {"public": "https://data-api.binance.vision/api/v3"}}
            spot_clients[ex_key] = exchange_class(cfg_opts)
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

    def _fetch_direct_ohlcv(
        self,
        ex_id: str,
        target_symbol: str,
        target_tf: str,
        target_limit: int,
    ) -> Optional[pd.DataFrame]:
        """
        Ultra-fast direct HTTP REST kline fetcher for Binance (Global Vision), OKX, Bybit, KuCoin, and Gate.io.
        Completely bypasses CCXT `load_markets()` (which otherwise downloads 3,000+ symbols per thread).
        """
        ex = ex_id.lower()
        parts = target_symbol.replace(":USDT", "").split("/")
        base = parts[0].upper() if parts else "BTC"
        quote = parts[1].upper() if len(parts) > 1 else "USDT"
        tf_low = target_tf.lower()

        if ex == "binance":
            market_id = f"{base}{quote}"
            raw_klines = _http_get_json(
                f"{_BINANCE_VISION_BASE}/klines",
                {"symbol": market_id, "interval": tf_low, "limit": target_limit},
                timeout=4.5,
            )
            if raw_klines and len(raw_klines) > 0:
                return self._normalize_binance_klines(raw_klines, tf_low)

        elif ex == "okx":
            bar_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1Dutc"}
            bar = bar_map.get(tf_low, "1H")
            res = _http_get_json(
                "https://www.okx.com/api/v5/market/candles",
                {"instId": f"{base}-{quote}", "bar": bar, "limit": min(target_limit, 300)},
                timeout=4.5,
            )
            data = res.get("data", []) if isinstance(res, dict) else []
            if data:
                rows = [
                    [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
                    for r in reversed(data)
                ]
                return self._normalize_dataframe(rows, tf_low)

        elif ex == "bybit":
            iv_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
            iv = iv_map.get(tf_low, "60")
            for dom in ("https://api.bytick.com", "https://api.bybit.com"):
                try:
                    res = _http_get_json(
                        f"{dom}/v5/market/kline",
                        {"category": "spot", "symbol": f"{base}{quote}", "interval": iv, "limit": min(target_limit, 200)},
                        timeout=3.5,
                    )
                    lst = res.get("result", {}).get("list", []) if isinstance(res, dict) else []
                    if lst:
                        rows = [
                            [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
                            for r in reversed(lst)
                        ]
                        return self._normalize_dataframe(rows, tf_low)
                except Exception:
                    continue

        elif ex == "kucoin":
            type_map = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1hour", "4h": "4hour", "1d": "1day"}
            k_type = type_map.get(tf_low, "1hour")
            res = _http_get_json(
                "https://api.kucoin.com/api/v1/market/candles",
                {"type": k_type, "symbol": f"{base}-{quote}"},
                timeout=4.5,
            )
            data = res.get("data", []) if isinstance(res, dict) else []
            if data:
                # KuCoin returns newest first: [time_sec, open, close, high, low, volume, turnover]
                sliced = data[:target_limit]
                rows = [
                    [int(r[0]) * 1000, float(r[1]), float(r[3]), float(r[4]), float(r[2]), float(r[5])]
                    for r in reversed(sliced)
                ]
                return self._normalize_dataframe(rows, tf_low)

        elif ex == "gate":
            iv_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
            iv = iv_map.get(tf_low, "1h")
            res = _http_get_json(
                "https://api.gateio.ws/api/v4/spot/candlesticks",
                {"currency_pair": f"{base}_{quote}", "interval": iv, "limit": min(target_limit, 500)},
                timeout=4.5,
            )
            if isinstance(res, list) and len(res) > 0:
                # Gate returns oldest first: [ts_sec, quote_vol, close, high, low, open, base_vol, is_closed]
                rows = [
                    [int(float(r[0])) * 1000, float(r[5]), float(r[3]), float(r[4]), float(r[2]), float(r[6])]
                    for r in res
                ]
                return self._normalize_dataframe(rows, tf_low)

        return None

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
                # 1. Ultra-fast Direct REST API path (no CCXT load_markets overhead)
                try:
                    direct_df = self._fetch_direct_ohlcv(ex_id, target_symbol, target_tf, target_limit)
                    if direct_df is not None and len(direct_df) > 0:
                        return direct_df, ex_id.upper()
                except Exception as dir_exc:
                    logger.debug(f"[{ex_id.upper()}] Direct REST kline fallback: {dir_exc}")

                # 2. CCXT Fallback path (e.g. Kraken, Coinbase)
                exchange = self._get_spot_exchange(ex_id)
                candidate_symbols = [target_symbol]
                if target_symbol.endswith("/USDT"):
                    candidate_symbols.append(target_symbol.replace("/USDT", "/USD"))

                raw_ohlcv = None
                for cand_sym in candidate_symbols:
                    try:
                        raw_ohlcv = exchange.fetch_ohlcv(
                            symbol=cand_sym,
                            timeframe=target_tf,
                            limit=target_limit,
                        )
                        if raw_ohlcv and len(raw_ohlcv) > 0:
                            break
                    except Exception:
                        continue

                if not raw_ohlcv or len(raw_ohlcv) == 0:
                    raise RuntimeError(f"{ex_id} boş OHLCV verisi döndürdü ({target_symbol}).")

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
        parts = target_symbol.replace(":USDT", "").split("/")
        base_ccy = parts[0].upper() if parts else "BTC"
        quote_ccy = parts[1].upper() if len(parts) > 1 else "USDT"
        raw_sym = f"{base_ccy}{quote_ccy}"

        intel = OrderFlowIntel(symbol=target_symbol, exchange=ex_id.upper())

        # 1. Deep Spot Order Book & 24h Ticker (Direct HTTP REST for binance, okx, bybit, kucoin, gate)
        spot_exchanges_to_try = [ex_id] + [fb for fb in ("binance", "okx", "gate", "kucoin", "bybit", "kraken", "coinbase") if fb != ex_id]
        for s_ex in spot_exchanges_to_try:
            try:
                bids: list = []
                asks: list = []
                if s_ex == "binance":
                    ob = _http_get_json(f"{_BINANCE_VISION_BASE}/depth", {"symbol": raw_sym, "limit": 500}, timeout=4.0)
                    bids = ob.get("bids", []) if isinstance(ob, dict) else []
                    asks = ob.get("asks", []) if isinstance(ob, dict) else []
                    t24 = _http_get_json(f"{_BINANCE_VISION_BASE}/ticker/24hr", {"symbol": raw_sym}, timeout=4.0)
                    if isinstance(t24, dict):
                        intel.price_change_24h_pct = float(t24.get("priceChangePercent") or 0.0)
                        intel.high_24h = float(t24.get("highPrice") or 0.0)
                        intel.low_24h = float(t24.get("lowPrice") or 0.0)
                        intel.quote_volume_24h_usd = float(t24.get("quoteVolume") or 0.0)

                elif s_ex == "okx":
                    ob_res = _http_get_json("https://www.okx.com/api/v5/market/books", {"instId": f"{base_ccy}-{quote_ccy}", "sz": 100}, timeout=4.0)
                    ob_data = ob_res.get("data", []) if isinstance(ob_res, dict) else []
                    if ob_data:
                        bids = [[r[0], r[1]] for r in ob_data[0].get("bids", [])]
                        asks = [[r[0], r[1]] for r in ob_data[0].get("asks", [])]
                    tk_res = _http_get_json("https://www.okx.com/api/v5/market/ticker", {"instId": f"{base_ccy}-{quote_ccy}"}, timeout=4.0)
                    tk_data = tk_res.get("data", []) if isinstance(tk_res, dict) else []
                    if tk_data:
                        tk = tk_data[0]
                        last_p = float(tk.get("last") or 0.0)
                        open_24 = float(tk.get("open24h") or 0.0)
                        if open_24 > 0:
                            intel.price_change_24h_pct = ((last_p - open_24) / open_24) * 100.0
                        intel.high_24h = float(tk.get("high24h") or 0.0)
                        intel.low_24h = float(tk.get("low24h") or 0.0)
                        intel.quote_volume_24h_usd = float(tk.get("volCcy24h") or 0.0)

                elif s_ex == "bybit":
                    for dom in ("https://api.bytick.com", "https://api.bybit.com"):
                        try:
                            ob_res = _http_get_json(f"{dom}/v5/market/orderbook", {"category": "spot", "symbol": raw_sym, "limit": 100}, timeout=3.5)
                            ob_r = ob_res.get("result", {}) if isinstance(ob_res, dict) else {}
                            bids = ob_r.get("b", [])
                            asks = ob_r.get("a", [])
                            tk_res = _http_get_json(f"{dom}/v5/market/tickers", {"category": "spot", "symbol": raw_sym}, timeout=3.5)
                            tk_list = tk_res.get("result", {}).get("list", []) if isinstance(tk_res, dict) else []
                            if tk_list:
                                tk = tk_list[0]
                                intel.price_change_24h_pct = float(tk.get("price24hPcnt") or 0.0) * 100.0
                                intel.high_24h = float(tk.get("highPrice24h") or 0.0)
                                intel.low_24h = float(tk.get("lowPrice24h") or 0.0)
                                intel.quote_volume_24h_usd = float(tk.get("turnover24h") or 0.0)
                            if bids and asks:
                                break
                        except Exception:
                            continue

                elif s_ex == "kucoin":
                    ob_res = _http_get_json("https://api.kucoin.com/api/v1/market/orderbook/level2_100", {"symbol": f"{base_ccy}-{quote_ccy}"}, timeout=4.0)
                    ob_d = ob_res.get("data", {}) if isinstance(ob_res, dict) else {}
                    bids = ob_d.get("bids", [])
                    asks = ob_d.get("asks", [])
                    tk_res = _http_get_json("https://api.kucoin.com/api/v1/market/stats", {"symbol": f"{base_ccy}-{quote_ccy}"}, timeout=4.0)
                    tk_d = tk_res.get("data", {}) if isinstance(tk_res, dict) else {}
                    if tk_d:
                        intel.price_change_24h_pct = float(tk_d.get("changeRate") or 0.0) * 100.0
                        intel.high_24h = float(tk_d.get("high") or 0.0)
                        intel.low_24h = float(tk_d.get("low") or 0.0)
                        intel.quote_volume_24h_usd = float(tk_d.get("volValue") or 0.0)

                elif s_ex == "gate":
                    ob = _http_get_json("https://api.gateio.ws/api/v4/spot/order_book", {"currency_pair": f"{base_ccy}_{quote_ccy}", "limit": 100}, timeout=4.0)
                    if isinstance(ob, dict):
                        bids = ob.get("bids", [])
                        asks = ob.get("asks", [])
                    tk_list = _http_get_json("https://api.gateio.ws/api/v4/spot/tickers", {"currency_pair": f"{base_ccy}_{quote_ccy}"}, timeout=4.0)
                    if isinstance(tk_list, list) and len(tk_list) > 0:
                        tk = tk_list[0]
                        intel.price_change_24h_pct = float(tk.get("change_percentage") or 0.0)
                        intel.high_24h = float(tk.get("high_24h") or 0.0)
                        intel.low_24h = float(tk.get("low_24h") or 0.0)
                        intel.quote_volume_24h_usd = float(tk.get("quote_volume") or 0.0)

                else:
                    spot = self._get_spot_exchange(s_ex)
                    cand_syms = [target_symbol]
                    if target_symbol.endswith("/USDT"):
                        cand_syms.append(target_symbol.replace("/USDT", "/USD"))
                    for c_sym in cand_syms:
                        try:
                            ob = spot.fetch_order_book(c_sym, limit=100)
                            if ob and ob.get("bids") and ob.get("asks"):
                                bids = ob["bids"]
                                asks = ob["asks"]
                                ticker = spot.fetch_ticker(c_sym)
                                if ticker:
                                    intel.price_change_24h_pct = float(ticker.get("percentage") or 0.0)
                                    intel.high_24h = float(ticker.get("high") or 0.0)
                                    intel.low_24h = float(ticker.get("low") or 0.0)
                                    intel.quote_volume_24h_usd = float(ticker.get("quoteVolume") or 0.0)
                                break
                        except Exception:
                            continue

                if bids and asks:
                    mid_price = (float(bids[0][0]) + float(asks[0][0])) / 2.0
                    valid_bids = [(float(p), float(q)) for p, q in bids if float(p) >= mid_price * 0.975]
                    valid_asks = [(float(p), float(q)) for p, q in asks if float(p) <= mid_price * 1.025]
                    if not valid_bids:
                        valid_bids = [(float(p), float(q)) for p, q in bids[:50]]
                    if not valid_asks:
                        valid_asks = [(float(p), float(q)) for p, q in asks[:50]]

                    bid_usd = float(sum(p * q for p, q in valid_bids))
                    ask_usd = float(sum(p * q for p, q in valid_asks))

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

                if intel.strongest_bid_wall > 0:
                    break
            except Exception as exc:
                logger.debug(f"[{s_ex.upper()}] Spot OrderBook/Ticker uyarısı ({target_symbol}): {exc}")

        # 2. Perpetual Futures Intelligence (Direct HTTP REST without CCXT load_markets overhead)
        try:
            mark_p_ref = 0.0
            # 2a. Try Bybit Linear Ticker if selected
            if ex_id == "bybit":
                for dom in ("https://api.bytick.com", "https://api.bybit.com"):
                    try:
                        lin_res = _http_get_json(f"{dom}/v5/market/tickers", {"category": "linear", "symbol": raw_sym}, timeout=3.0)
                        lin_list = lin_res.get("result", {}).get("list", []) if isinstance(lin_res, dict) else []
                        if lin_list:
                            lt = lin_list[0]
                            if lt.get("fundingRate"):
                                intel.funding_rate_pct = float(lt["fundingRate"]) * 100.0
                            if lt.get("openInterestValue"):
                                intel.open_interest_usd = float(lt["openInterestValue"])
                            mp = float(lt.get("markPrice") or 0.0)
                            ip = float(lt.get("indexPrice") or 0.0)
                            if mp > 0 and ip > 0:
                                mark_p_ref = mp
                                intel.perp_spot_basis_pct = ((mp - ip) / ip) * 100.0
                            break
                    except Exception:
                        continue

            # 2b. Try Gate.io Futures Contract if selected or needed
            if ex_id == "gate" or intel.funding_rate_pct is None:
                try:
                    g_res = _http_get_json(f"https://api.gateio.ws/api/v4/futures/usdt/contracts/{base_ccy}_USDT", timeout=3.0)
                    if isinstance(g_res, dict):
                        if intel.funding_rate_pct is None and g_res.get("funding_rate") is not None:
                            intel.funding_rate_pct = float(g_res["funding_rate"]) * 100.0
                        mp = float(g_res.get("mark_price") or 0.0)
                        ip = float(g_res.get("index_price") or 0.0)
                        if mp > 0 and ip > 0 and intel.perp_spot_basis_pct is None:
                            mark_p_ref = mp
                            intel.perp_spot_basis_pct = ((mp - ip) / ip) * 100.0
                except Exception:
                    pass

            # 2c. Direct OKX Swap Rubik Stats (works globally & in US on streamlit.app, gives Funding, OI 1h/4h/24h delta, L/S ratio, Taker Vol)
            try:
                inst_id = f"{base_ccy}-USDT-SWAP"
                if intel.funding_rate_pct is None or ex_id == "okx":
                    fr_res = _http_get_json("https://www.okx.com/api/v5/public/funding-rate", {"instId": inst_id}, timeout=3.5)
                    fr_list = fr_res.get("data", []) if isinstance(fr_res, dict) else []
                    if fr_list and fr_list[0].get("fundingRate") is not None:
                        intel.funding_rate_pct = float(fr_list[0]["fundingRate"]) * 100.0

                if intel.oi_change_24h_pct is None:
                    oih_res = _http_get_json("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume", {"ccy": base_ccy, "period": "1H"}, timeout=3.5)
                    oih_list = oih_res.get("data", []) if isinstance(oih_res, dict) else []
                    if oih_list and len(oih_list) >= 2:
                        oi_now = float(oih_list[0][1])
                        oi_1h = float(oih_list[1][1])
                        oi_4h = float(oih_list[min(4, len(oih_list) - 1)][1])
                        oi_24h = float(oih_list[min(24, len(oih_list) - 1)][1])
                        if oi_now > 0:
                            intel.open_interest_usd = oi_now
                        if oi_1h > 0:
                            intel.oi_change_1h_pct = ((oi_now - oi_1h) / oi_1h) * 100.0
                        if oi_4h > 0:
                            intel.oi_change_4h_pct = ((oi_now - oi_4h) / oi_4h) * 100.0
                        if oi_24h > 0:
                            intel.oi_change_24h_pct = ((oi_now - oi_24h) / oi_24h) * 100.0

                if intel.long_short_ratio is None:
                    ls_res = _http_get_json("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio", {"ccy": base_ccy, "period": "1H"}, timeout=3.5)
                    ls_list = ls_res.get("data", []) if isinstance(ls_res, dict) else []
                    if ls_list and len(ls_list) >= 1:
                        intel.long_short_ratio = float(ls_list[0][1])

                if intel.futures_taker_buy_sell_ratio is None:
                    tv_res = _http_get_json("https://www.okx.com/api/v5/rubik/stat/taker-volume", {"ccy": base_ccy, "instType": "CONTRACTS", "period": "1H"}, timeout=3.5)
                    tv_list = tv_res.get("data", []) if isinstance(tv_res, dict) else []
                    if tv_list and len(tv_list) >= 1:
                        sell_v = float(tv_list[0][1] or 0.0)
                        buy_v = float(tv_list[0][2] or 0.0)
                        if sell_v > 0:
                            intel.futures_taker_buy_sell_ratio = buy_v / sell_v
                        ref_p = float(mark_p_ref or intel.high_24h or 1.0)
                        intel.perp_cvd_delta_24h_usd = (buy_v - sell_v) * ref_p
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
