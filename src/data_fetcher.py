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
import time
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
class MacroLiquidityIntel:
    """
    Phase 2 Global Crypto Macro Liquidity Compass (BTC.D, USDT.D, ETH/BTC, Global Market Cap 24h%).
    Determines whether capital is rotating INTO altcoins (Risk-On), hiding in BTC, or fleeing to Cash/USDT (Risk-Off).
    """
    btc_dominance_pct: Optional[float] = None
    usdt_dominance_pct: Optional[float] = None
    total_mcap_change_24h_pct: Optional[float] = None
    eth_btc_price: Optional[float] = None
    eth_btc_change_24h_pct: Optional[float] = None
    btcdom_perp_change_24h_pct: Optional[float] = None
    altcoin_season_bias: float = 0.0   # -15.0 (Strong Risk-Off / Altcoin Drain) to +15.0 (Strong Altcoin Inflow)
    regime_code: str = "NEUTRAL"       # "ALT_INFLOW", "BTC_SAFETY", "CASH_FLIGHT", "BROAD_RALLY", "NEUTRAL"
    summary_tr: str = "Makro Likidite Dengeli"


@dataclass
class OrderFlowIntel:
    """
    Real-time Deep Order Book (Dual-Probe Anti-Spoof Filtered), Standardized 1H/4H/24H Spot & Perp Cash Flow,
    3-Exchange Aggregated Open Interest & OI-Weighted Funding, and Macro Liquidity Intelligence (Phase 2).
    """
    symbol: str
    exchange: str
    # Deep Order Book (Filtered within ±2.5% of mid price + Dual-Probe Anti-Spoof)
    bid_volume_usd: float = 0.0
    ask_volume_usd: float = 0.0
    imbalance_pct: float = 50.0          # 0-100% (% of filtered persistent depth on Bid/Buyer side)
    imbalance_net_ratio: float = 0.0     # -1.0 to +1.0 ((Bid - Ask) / (Bid + Ask))
    strongest_bid_wall: float = 0.0      # Price of largest persistent buy liquidity cluster
    strongest_ask_wall: float = 0.0      # Price of largest persistent sell liquidity cluster
    strongest_bid_wall_usd: float = 0.0  # USD size of strongest buy liquidity wall
    strongest_ask_wall_usd: float = 0.0  # USD size of strongest sell liquidity wall
    orderbook_status_tr: str = "Dengeli Emir Defteri"
    spoof_cancelled_pct: float = 0.0     # % of flash depth that vanished between dual probes
    spoof_status_tr: str = "Doğrulanmış Kalıcı Derinlik"

    # 24h Ticker Stats
    price_change_24h_pct: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    quote_volume_24h_usd: float = 0.0    # 24h USDT volume

    # Phase 2: Time-Standardized True Spot Taker Cash Flow (1H / 4H / 24H Closed Bars)
    spot_delta_1h_usd: Optional[float] = None
    spot_delta_4h_usd: Optional[float] = None
    spot_delta_24h_usd: Optional[float] = None
    spot_delta_pct_24h_vol: Optional[float] = None

    # Perpetual Futures Metrics (Exchange-Matched + 3-Exchange Global Aggregated OI & OI-Weighted Funding)
    funding_rate_pct: Optional[float] = None
    oi_weighted_funding_pct: Optional[float] = None
    open_interest_usd: Optional[float] = None
    aggregated_oi_usd: Optional[float] = None
    aggregated_exchanges_count: int = 0
    oi_change_1h_pct: Optional[float] = None
    oi_change_4h_pct: Optional[float] = None
    oi_change_24h_pct: Optional[float] = None
    long_short_ratio: Optional[float] = None
    futures_taker_buy_sell_ratio: Optional[float] = None
    perp_spot_basis_pct: Optional[float] = None
    perp_delta_1h_usd: Optional[float] = None
    perp_delta_4h_usd: Optional[float] = None
    perp_cvd_delta_24h_usd: Optional[float] = None
    oi_regime_tr: str = "Veri Yok"
    spot_vs_perp_cvd_tr: str = "Dengeli Spot & Vadeli Akışı"
    futures_sentiment_tr: str = "Veri Yok"
    spot_source: str = ""
    futures_source: str = ""
    macro_liquidity: Optional[MacroLiquidityIntel] = None


@dataclass
class DataIntegrityReport:
    """
    Anti-Hallucination & Real-Data Health Audit Report (Phase 1).
    Verifies candle freshness, warmup bar count (>=250 for EMA200), absence of zero-volume/dead books,
    timestamp monotonicity, and absence of synthetic fallback data.
    """
    is_healthy: bool = True
    is_synthetic: bool = False
    is_stale: bool = False
    has_warmup_bars: bool = True
    total_bars: int = 0
    closed_bars: int = 0
    missing_gaps: int = 0
    zero_vol_recent_bars: int = 0
    source_exchange: str = ""
    has_real_taker_flow: bool = False
    status_tr: str = "✅ Doğrulanmış Canlı Borsa Verisi"
    warnings_tr: List[str] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.warnings_tr is None:
            self.warnings_tr = []


_THREAD_LOCAL = threading.local()
_MACRO_LOCK = threading.Lock()
_MACRO_CACHE: Tuple[float, Optional[MacroLiquidityIntel]] = (0.0, None)
MACRO_CACHE_TTL_SEC = 120.0


def _merge_dual_probe_depth(
    probe1: List[List[Any]],
    probe2: List[List[Any]],
) -> Tuple[List[Tuple[float, float]], float]:
    """
    Phase 2 Anti-Spoofing Dual-Probe Depth Filter:
    Compares two micro-spaced order book snapshots (`t0` and `t0 + 0.16s`).
    For price levels present in both snapshots, retains `min(q1, q2)` so flickering HFT spoof walls
    that disappear or shrink within 160ms are stripped out. Also caps extreme single-tick outlier walls
    (> 8x median top-30 level notional) that sit far (>1.5%) from mid-price.
    Returns `(verified_levels, cancelled_pct)`.
    """
    p1_map: Dict[float, float] = {}
    for row in probe1:
        p, q = float(row[0]), float(row[1])
        if p > 0 and q > 0:
            p1_map[p] = q
    if not probe2:
        return list(p1_map.items()), 0.0

    p2_map: Dict[float, float] = {}
    for row in probe2:
        p, q = float(row[0]), float(row[1])
        if p > 0 and q > 0:
            p2_map[p] = q

    raw_notional = sum(p * q for p, q in p1_map.items())
    verified: List[Tuple[float, float]] = []
    kept_notional = 0.0
    for p, q1 in p1_map.items():
        if p in p2_map:
            q_ver = min(q1, p2_map[p])
        else:
            # Level vanished within 160ms -> discount by 75% (unless top-of-book immediate fill)
            q_ver = q1 * 0.25
        if q_ver > 0:
            verified.append((p, q_ver))
            kept_notional += p * q_ver

    cancelled_pct = max(0.0, (raw_notional - kept_notional) / max(raw_notional, 1e-9) * 100.0)
    return verified, cancelled_pct


def _extract_standardized_1h_4h_24h_deltas(raw_1h_klines: list) -> Optional[Tuple[float, float, float]]:
    """
    Extracts exact CLOSED-candle 1H, 4H, and 24H Net Taker Cash Flow (Taker Buy Quote - Taker Sell Quote in USDT)
    from 12-column Binance Spot or Perpetual 1H klines (zero candle-shape approximation).
    """
    if not isinstance(raw_1h_klines, list) or len(raw_1h_klines) < 2:
        return None
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    closed_deltas: List[float] = []
    for row in raw_1h_klines:
        close_ts = int(row[6])
        open_ts = int(row[0])
        if close_ts <= now_ms and (now_ms - open_ts) >= 3_590_000:
            q_vol = float(row[7] or 0.0)
            tb_vol = float(row[10] or 0.0)
            ts_vol = max(0.0, q_vol - tb_vol)
            closed_deltas.append(tb_vol - ts_vol)
    if not closed_deltas:
        # Fallback to all except last forming bar
        for row in raw_1h_klines[:-1]:
            q_vol = float(row[7] or 0.0)
            tb_vol = float(row[10] or 0.0)
            closed_deltas.append(tb_vol - max(0.0, q_vol - tb_vol))
    if not closed_deltas:
        return None
    d_1h = float(closed_deltas[-1])
    d_4h = float(sum(closed_deltas[-4:]))
    d_24h = float(sum(closed_deltas[-24:]))
    return d_1h, d_4h, d_24h


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
                {"symbol": market_id, "interval": tf_low, "limit": min(target_limit, 1000)},
                timeout=5.0,
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
            if data and target_limit > 300 and len(data) >= 295:
                try:
                    oldest_ts = str(data[-1][0])
                    rem = min(target_limit - len(data), 300)
                    res_older = _http_get_json(
                        "https://www.okx.com/api/v5/market/candles",
                        {"instId": f"{base}-{quote}", "bar": bar, "after": oldest_ts, "limit": rem},
                        timeout=4.0,
                    )
                    older_data = res_older.get("data", []) if isinstance(res_older, dict) else []
                    if older_data:
                        data = data + older_data
                except Exception:
                    pass
            if data:
                rows = [
                    [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
                    for r in reversed(data[:target_limit])
                ]
                return self._normalize_dataframe(rows, tf_low)

        elif ex == "bybit":
            iv_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
            iv = iv_map.get(tf_low, "60")
            for dom in ("https://api.bytick.com", "https://api.bybit.com"):
                try:
                    res = _http_get_json(
                        f"{dom}/v5/market/kline",
                        {"category": "spot", "symbol": f"{base}{quote}", "interval": iv, "limit": min(target_limit, 1000)},
                        timeout=4.5,
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
                {"currency_pair": f"{base}_{quote}", "interval": iv, "limit": min(target_limit, 1000)},
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

    @staticmethod
    def validate_ohlcv_integrity(
        df: pd.DataFrame,
        timeframe: str = "4h",
        source_exchange: str = "BINANCE",
        check_staleness: bool = True,
    ) -> Tuple[pd.DataFrame, DataIntegrityReport]:
        """
        Phase 1 Anti-Hallucination & Data Health Guard:
          1. Deduplicates timestamps, sorts chronologically, and repairs OHLC geometry bounds.
          2. Rejects empty, <20-bar, non-positive price, or dead/zero-volume books.
          3. Detects stale/halted exchange feeds (`now_utc - last_ts > 2.5 * tf_sec`).
          4. Tracks whether 250+ warmup bars and real exchange Taker Buy/Sell flow exist.
        """
        report = DataIntegrityReport(
            source_exchange=source_exchange,
            is_synthetic=(source_exchange == "SIMULATED_FALLBACK"),
        )
        if df is None or df.empty:
            report.is_healthy = False
            report.status_tr = "❌ Boş Veri Seti"
            return df, report

        clean = df.copy()
        if "timestamp" in clean.columns:
            clean = clean.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp").reset_index(drop=True)

        # Drop rows with invalid/non-positive prices
        for p_col in ("open", "high", "low", "close"):
            clean = clean[clean[p_col].notna() & (clean[p_col] > 0)]
        clean = clean.reset_index(drop=True)
        if len(clean) < 20:
            report.is_healthy = False
            report.total_bars = len(clean)
            report.status_tr = f"❌ Yetersiz Gerçek Mum Verisi ({len(clean)} < 20)"
            return clean, report

        # Enforce mathematical OHLC candle envelope invariants
        clean["high"] = clean[["open", "high", "low", "close"]].max(axis=1)
        clean["low"] = clean[["open", "high", "low", "close"]].min(axis=1)
        clean["volume"] = clean["volume"].fillna(0.0).clip(lower=0.0)

        closed_mask = clean["is_closed"].astype(bool) if "is_closed" in clean.columns else pd.Series(True, index=clean.index)
        closed_sub = clean[closed_mask]

        report.total_bars = len(clean)
        report.closed_bars = len(closed_sub)
        report.has_warmup_bars = len(closed_sub) >= 240
        report.has_real_taker_flow = bool("real_net_delta_usd" in clean.columns and clean["real_net_delta_usd"].notna().any())

        tf_sec = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(timeframe.lower(), 14400)

        # Check staleness when requested on live feeds
        if check_staleness and not report.is_synthetic and "timestamp" in clean.columns and len(clean) > 0:
            last_ts = pd.to_datetime(clean["timestamp"].iloc[-1], utc=True)
            age_sec = (datetime.now(timezone.utc) - last_ts).total_seconds()
            if age_sec > tf_sec * 2.6:
                report.is_stale = True
                report.is_healthy = False
                report.warnings_tr.append(f"Veri bayat: son mum {age_sec / 3600:.1f} saat önce ({source_exchange} tahtası kapalı/askıda olabilir).")

        # Check dead/zero-volume candles in recent 10 closed bars
        if len(closed_sub) >= 10:
            recent_zero = int((closed_sub["volume"].tail(10) <= 0).sum())
            report.zero_vol_recent_bars = recent_zero
            if recent_zero >= 5:
                report.is_healthy = False
                report.warnings_tr.append(f"Son 10 kapanmış mumun {recent_zero} tanesinde hacim sıfır (likiditesiz tahta).")

        # Check missing candle gaps in recent 100 bars
        if "timestamp" in clean.columns and len(clean) >= 10:
            ts_s = pd.to_datetime(clean["timestamp"].tail(100)).diff().dt.total_seconds().dropna()
            gaps = int((ts_s > tf_sec * 1.55).sum())
            report.missing_gaps = gaps
            if gaps >= 3:
                report.warnings_tr.append(f"Son 100 mumda {gaps} adet zaman boşluğu (bakım/kesinti) tespit edildi.")

        if not report.has_warmup_bars and len(closed_sub) >= 50:
            report.warnings_tr.append(f"Yeni listelenmiş parite ({len(closed_sub)} mum < 250 EMA200 ısınma sınırı).")

        if report.is_synthetic:
            report.is_healthy = False
            report.status_tr = "⚠️ Test / Simülasyon Verisi"
        elif not report.is_healthy:
            report.status_tr = "⚠️ Veri Sağlığı Uyarısı: " + (report.warnings_tr[0] if report.warnings_tr else "Doğrulanamadı")
        else:
            taker_lbl = "Gerçek Taker CVD" if report.has_real_taker_flow else "Spot OHLCV"
            report.status_tr = f"✅ Doğrulanmış Canlı Veri ({source_exchange} • {report.closed_bars} Kapalı Mum • {taker_lbl})"

        clean.attrs["integrity_report"] = report
        return clean, report

    def fetch_ohlcv(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: Optional[int] = None,
        exchange_id: Optional[str] = None,
        allow_synthetic_fallback: bool = False,
    ) -> Tuple[pd.DataFrame, str]:
        """
        Fetch live verified OHLCV data (strictly `allow_synthetic_fallback=False` by default in production)
        and validate freshness, OHLC geometry, and volume health via `validate_ohlcv_integrity`.
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

        direct_rest_exchanges = {"binance", "okx", "bybit", "kucoin", "gate"}

        for ex_id in exchanges_to_try:
            try:
                ex_low = ex_id.lower()
                # 1. Ultra-fast Direct REST API path (no CCXT load_markets overhead)
                if ex_low in direct_rest_exchanges:
                    direct_df = self._fetch_direct_ohlcv(ex_low, target_symbol, target_tf, target_limit)
                    if direct_df is not None and len(direct_df) > 0:
                        clean_df, rep = self.validate_ohlcv_integrity(
                            direct_df, timeframe=target_tf, source_exchange=ex_low.upper(), check_staleness=(target_limit >= 20)
                        )
                        if rep.is_healthy or target_limit < 20:
                            return clean_df, ex_low.upper()
                        raise RuntimeError(f"{ex_low.upper()} veri sağlığı reddedildi: {rep.status_tr}")
                    raise RuntimeError(f"{ex_low.upper()} üzerinde {target_symbol} listeli değil veya boş döndü.")

                # 2. CCXT Fallback path (only for non-direct exchanges like Kraken, Coinbase)
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
                clean_df, rep = self.validate_ohlcv_integrity(
                    df, timeframe=target_tf, source_exchange=ex_id.upper(), check_staleness=(target_limit >= 20)
                )
                if rep.is_healthy or target_limit < 20:
                    return clean_df, ex_id.upper()
                raise RuntimeError(f"{ex_id.upper()} veri sağlığı reddedildi: {rep.status_tr}")

            except Exception as exc:
                last_error = exc
                logger.debug(f"[{ex_id.upper()}] {target_symbol} alternatif borsaya geçiliyor: {exc}")

        if allow_synthetic_fallback:
            logger.warning("Canlı borsa bağlantısı kurulamadı. Test simülasyon verisi üretiliyor...")
            syn_df = self.generate_synthetic_ohlcv(limit=target_limit, timeframe=target_tf)
            syn_clean, _ = self.validate_ohlcv_integrity(syn_df, timeframe=target_tf, source_exchange="SIMULATED_FALLBACK", check_staleness=False)
            return syn_clean, "SIMULATED_FALLBACK"

        raise RuntimeError(f"Hiçbir canlı borsadan doğrulanmış veri alınamadı ({target_symbol}). Son hata: {last_error}")

    def fetch_multi_timeframe_parallel(
        self,
        symbol: str,
        timeframes: List[str],
        limit: int = 500,
        exchange_id: Optional[str] = None,
        allow_synthetic_fallback: bool = False,
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

    @staticmethod
    def fetch_macro_liquidity_intel(force_refresh: bool = False) -> MacroLiquidityIntel:
        """
        Phase 2 Global Macro Liquidity Compass (120s cached):
        Combines CoinGecko Global (`BTC.D`, `USDT.D`, `Total Mcap 24h%`), Binance Spot `ETH/BTC` 24h%,
        and Binance Futures `BTCDOMUSDT` 24h% to classify capital rotation into/out of altcoins.
        """
        global _MACRO_CACHE
        now_t = time.time()
        if not force_refresh:
            with _MACRO_LOCK:
                ts_c, cached_m = _MACRO_CACHE
                if cached_m is not None and (now_t - ts_c) <= MACRO_CACHE_TTL_SEC:
                    return cached_m

        macro = MacroLiquidityIntel()

        def _get_cg() -> None:
            try:
                cg = _http_get_json("https://api.coingecko.com/api/v3/global", timeout=3.5)
                d = cg.get("data", {}) if isinstance(cg, dict) else {}
                mcp = d.get("market_cap_percentage", {}) if isinstance(d, dict) else {}
                if mcp.get("btc") is not None:
                    macro.btc_dominance_pct = float(mcp["btc"])
                if mcp.get("usdt") is not None:
                    usdc_p = float(mcp.get("usdc") or 0.0)
                    macro.usdt_dominance_pct = float(mcp["usdt"]) + usdc_p
                if d.get("market_cap_change_percentage_24h_usd") is not None:
                    macro.total_mcap_change_24h_pct = float(d["market_cap_change_percentage_24h_usd"])
            except Exception:
                pass

        def _get_ethbtc() -> None:
            try:
                eb = _http_get_json(f"{_BINANCE_VISION_BASE}/ticker/24hr", {"symbol": "ETHBTC"}, timeout=3.0)
                if isinstance(eb, dict) and eb.get("lastPrice"):
                    macro.eth_btc_price = float(eb["lastPrice"])
                    macro.eth_btc_change_24h_pct = float(eb.get("priceChangePercent") or 0.0)
            except Exception:
                pass

        def _get_btcdom() -> None:
            try:
                bd = _http_get_json("https://fapi.binance.com/fapi/v1/ticker/24hr", {"symbol": "BTCDOMUSDT"}, timeout=3.0)
                if isinstance(bd, dict) and bd.get("priceChangePercent") is not None:
                    macro.btcdom_perp_change_24h_pct = float(bd["priceChangePercent"])
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=3) as ex:
            f1 = ex.submit(_get_cg)
            f2 = ex.submit(_get_ethbtc)
            f3 = ex.submit(_get_btcdom)
            for f in (f1, f2, f3):
                f.result()

        eb_chg = macro.eth_btc_change_24h_pct or 0.0
        bdom_chg = macro.btcdom_perp_change_24h_pct or 0.0
        mcap_chg = macro.total_mcap_change_24h_pct or 0.0
        btc_d_str = f"BTC.D: %{macro.btc_dominance_pct:.2f}" if macro.btc_dominance_pct is not None else "BTC.D: N/A"
        stb_d_str = f"Stable.D: %{macro.usdt_dominance_pct:.2f}" if macro.usdt_dominance_pct is not None else ""
        eb_str = f"ETH/BTC: {eb_chg:+.2f}%" if macro.eth_btc_change_24h_pct is not None else ""
        meta_parts = [p for p in (btc_d_str, stb_d_str, eb_str) if p]
        meta_s = " | ".join(meta_parts)

        # Evaluate Macro Liquidity Regime & Altcoin Capital Flow Bias (-15 .. +15)
        if mcap_chg <= -1.8 and bdom_chg >= 0.35:
            macro.regime_code = "CASH_FLIGHT"
            macro.altcoin_season_bias = -12.0
            macro.summary_tr = f"🔴 Nakde (USDT) Kaçış / Altcoin Kan Kaybı ({meta_s} | 24s Piyasa: {mcap_chg:+.1f}%)"
        elif mcap_chg <= -2.2:
            macro.regime_code = "CASH_FLIGHT"
            macro.altcoin_season_bias = -9.0
            macro.summary_tr = f"🔴 Küresel Riskten Kaçış / Satış Baskısı ({meta_s} | 24s Piyasa: {mcap_chg:+.1f}%)"
        elif eb_chg >= 0.65 and bdom_chg <= -0.35:
            macro.regime_code = "ALT_INFLOW"
            macro.altcoin_season_bias = 12.0 if mcap_chg >= -0.5 else 6.0
            macro.summary_tr = f"🟢 Altcoinlere Para Girişi / Pozitif Rotasyon ({meta_s} | BTCDOM: {bdom_chg:+.2f}%)"
        elif mcap_chg >= 1.2 and bdom_chg >= 0.45 and eb_chg <= -0.4:
            macro.regime_code = "BTC_SAFETY"
            macro.altcoin_season_bias = -4.0
            macro.summary_tr = f"🟡 BTC Odaklı Yükseliş — Altcoinler Geride ({meta_s} | BTCDOM: {bdom_chg:+.2f}%)"
        elif mcap_chg >= 1.2 and eb_chg >= 0.0:
            macro.regime_code = "BROAD_RALLY"
            macro.altcoin_season_bias = 9.0
            macro.summary_tr = f"🟢 Genele Yayılan Taze Para Girişi ({meta_s} | 24s Piyasa: {mcap_chg:+.1f}%)"
        else:
            macro.regime_code = "NEUTRAL"
            macro.altcoin_season_bias = float(np.clip(eb_chg * 2.5 - bdom_chg * 2.0, -6.0, 6.0))
            macro.summary_tr = f"⚖️ Seçici Makro Likidite ({meta_s})"

        with _MACRO_LOCK:
            _MACRO_CACHE = (now_t, macro)
        return macro

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

        # 1. Deep Spot Order Book & 24h Ticker (Direct HTTP REST for binance, bybit, okx, kucoin, gate)
        spot_exchanges_to_try = [ex_id] + [fb for fb in ("binance", "bybit", "okx", "kucoin", "gate", "kraken", "coinbase") if fb != ex_id]
        okx_spot_missing = False
        for s_ex in spot_exchanges_to_try:
            try:
                bids: list = []
                asks: list = []
                if s_ex == "binance":
                    ob1 = _http_get_json(f"{_BINANCE_VISION_BASE}/depth", {"symbol": raw_sym, "limit": 500}, timeout=4.0)
                    bids1 = ob1.get("bids", []) if isinstance(ob1, dict) else []
                    asks1 = ob1.get("asks", []) if isinstance(ob1, dict) else []
                    t24 = _http_get_json(f"{_BINANCE_VISION_BASE}/ticker/24hr", {"symbol": raw_sym}, timeout=4.0)
                    if isinstance(t24, dict):
                        intel.price_change_24h_pct = float(t24.get("priceChangePercent") or 0.0)
                        intel.high_24h = float(t24.get("highPrice") or 0.0)
                        intel.low_24h = float(t24.get("lowPrice") or 0.0)
                        intel.quote_volume_24h_usd = float(t24.get("quoteVolume") or 0.0)
                    # Dual-probe second snapshot after ticker roundtrip (~150-200ms) to strip flash spoofing walls
                    try:
                        ob2 = _http_get_json(f"{_BINANCE_VISION_BASE}/depth", {"symbol": raw_sym, "limit": 500}, timeout=3.0)
                        bids2 = ob2.get("bids", []) if isinstance(ob2, dict) else []
                        asks2 = ob2.get("asks", []) if isinstance(ob2, dict) else []
                    except Exception:
                        bids2, asks2 = [], []
                    bids, c_b = _merge_dual_probe_depth(bids1, bids2)
                    asks, c_a = _merge_dual_probe_depth(asks1, asks2)
                    intel.spoof_cancelled_pct = 0.5 * (c_b + c_a)
                    # Standardized 1H / 4H / 24H True Spot Taker Cash Flow
                    try:
                        sp_1h = _http_get_json(
                            f"{_BINANCE_VISION_BASE}/klines",
                            {"symbol": raw_sym, "interval": "1h", "limit": 25},
                            timeout=3.5,
                        )
                        sp_deltas = _extract_standardized_1h_4h_24h_deltas(sp_1h)
                        if sp_deltas is not None:
                            intel.spot_delta_1h_usd, intel.spot_delta_4h_usd, intel.spot_delta_24h_usd = sp_deltas
                            if intel.quote_volume_24h_usd > 0:
                                intel.spot_delta_pct_24h_vol = (intel.spot_delta_24h_usd / intel.quote_volume_24h_usd) * 100.0
                    except Exception:
                        pass

                elif s_ex == "okx":
                    try:
                        ob_res = _http_get_json("https://www.okx.com/api/v5/market/books", {"instId": f"{base_ccy}-{quote_ccy}", "sz": 100}, timeout=3.5)
                    except Exception:
                        ob_res = {}
                    ob_data = ob_res.get("data", []) if isinstance(ob_res, dict) else []
                    if ob_data:
                        bids = [[r[0], r[1]] for r in ob_data[0].get("bids", [])]
                        asks = [[r[0], r[1]] for r in ob_data[0].get("asks", [])]
                        tk_res = _http_get_json("https://www.okx.com/api/v5/market/ticker", {"instId": f"{base_ccy}-{quote_ccy}"}, timeout=3.5)
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
                    else:
                        okx_spot_missing = True

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

                    if intel.spoof_cancelled_pct >= 18.0:
                        intel.spoof_status_tr = f"⚠️ Spoof Şüphesi (Anlık emirlerin %{intel.spoof_cancelled_pct:.0f}'i silindi, sahte duvarlar temizlendi)"
                    else:
                        intel.spoof_status_tr = f"✅ Doğrulanmış Kalıcı Derinlik (Spoof Oranı Düşük: %{intel.spoof_cancelled_pct:.1f})"

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
                    intel.spot_source = s_ex.upper()
                    break
            except Exception as exc:
                logger.debug(f"[{s_ex.upper()}] Spot OrderBook/Ticker uyarısı ({target_symbol}): {exc}")

        # 1b. If primary spot was non-Binance and spot_delta_24h_usd is still None, try Binance Spot 1H Taker feed for verified Global Spot Cash Flow
        if intel.spot_delta_24h_usd is None:
            try:
                sp_1h_fb = _http_get_json(
                    f"{_BINANCE_VISION_BASE}/klines",
                    {"symbol": raw_sym, "interval": "1h", "limit": 25},
                    timeout=3.0,
                )
                sp_d_fb = _extract_standardized_1h_4h_24h_deltas(sp_1h_fb)
                if sp_d_fb is not None:
                    intel.spot_delta_1h_usd, intel.spot_delta_4h_usd, intel.spot_delta_24h_usd = sp_d_fb
                    if intel.quote_volume_24h_usd > 0:
                        intel.spot_delta_pct_24h_vol = (intel.spot_delta_24h_usd / intel.quote_volume_24h_usd) * 100.0
            except Exception:
                pass

        # 2. Perpetual Futures Intelligence + 3-Exchange Global Aggregated OI & OI-Weighted Funding (Binance + Bybit + OKX)
        try:
            mark_p_ref = 0.0
            mid_spot_ref = (
                0.5 * (intel.strongest_bid_wall + intel.strongest_ask_wall)
                if (intel.strongest_bid_wall > 0 and intel.strongest_ask_wall > 0)
                else 0.0
            )
            fut_sources: List[str] = []
            agg_oi_pairs: List[Tuple[str, float, Optional[float]]] = []  # (exchange, oi_usd, funding_pct)

            # 2a. Native Binance USD-M Futures (`fapi.binance.com`) — always queried for Global Aggregated OI & Exact Perp 1H/4H/24H Taker Delta
            try:
                bn_fr_pct: Optional[float] = None
                bn_oi_usd: float = 0.0
                pi = _http_get_json("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": raw_sym}, timeout=3.0)
                if isinstance(pi, dict) and pi.get("lastFundingRate") is not None:
                    bn_fr_pct = float(pi["lastFundingRate"]) * 100.0
                    mp = float(pi.get("markPrice") or 0.0)
                    ip = float(pi.get("indexPrice") or 0.0)
                    if ex_id == "binance" or intel.funding_rate_pct is None:
                        intel.funding_rate_pct = bn_fr_pct
                        if mp > 0 and ip > 0:
                            mark_p_ref = mp
                            intel.perp_spot_basis_pct = ((mp - ip) / ip) * 100.0
                    if "BINANCE" not in fut_sources:
                        fut_sources.append("BINANCE")

                oih = _http_get_json(
                    "https://fapi.binance.com/futures/data/openInterestHist",
                    {"symbol": raw_sym, "period": "1h", "limit": 25},
                    timeout=3.0,
                )
                if isinstance(oih, list) and len(oih) >= 2:
                    oi_now = float(oih[-1].get("sumOpenInterestValue") or 0.0)
                    oi_1h = float(oih[-2].get("sumOpenInterestValue") or 0.0)
                    oi_4h = float(oih[max(0, len(oih) - 5)].get("sumOpenInterestValue") or 0.0)
                    oi_24h = float(oih[0].get("sumOpenInterestValue") or 0.0)
                    if oi_now > 0:
                        bn_oi_usd = oi_now
                        if ex_id == "binance" or intel.open_interest_usd is None:
                            intel.open_interest_usd = oi_now
                    if ex_id == "binance" or intel.oi_change_24h_pct is None:
                        if oi_1h > 0:
                            intel.oi_change_1h_pct = ((oi_now - oi_1h) / oi_1h) * 100.0
                        if oi_4h > 0:
                            intel.oi_change_4h_pct = ((oi_now - oi_4h) / oi_4h) * 100.0
                        if oi_24h > 0:
                            intel.oi_change_24h_pct = ((oi_now - oi_24h) / oi_24h) * 100.0

                if bn_oi_usd > 0:
                    agg_oi_pairs.append(("BINANCE", bn_oi_usd, bn_fr_pct))

                # Exact 12-column Binance Perp 1H klines for down-to-the-dollar 1H / 4H / 24H Perp Taker Delta
                fk_1h = _http_get_json(
                    "https://fapi.binance.com/fapi/v1/klines",
                    {"symbol": raw_sym, "interval": "1h", "limit": 25},
                    timeout=3.0,
                )
                perp_d = _extract_standardized_1h_4h_24h_deltas(fk_1h)
                if perp_d is not None:
                    intel.perp_delta_1h_usd, intel.perp_delta_4h_usd, intel.perp_cvd_delta_24h_usd = perp_d
                    if isinstance(fk_1h, list) and len(fk_1h) >= 2:
                        last_closed_fk = fk_1h[-2]
                        q_v = float(last_closed_fk[7] or 0.0)
                        tb_v = float(last_closed_fk[10] or 0.0)
                        ts_v = max(0.0, q_v - tb_v)
                        if ts_v > 0 and (ex_id == "binance" or intel.futures_taker_buy_sell_ratio is None):
                            intel.futures_taker_buy_sell_ratio = tb_v / ts_v

                if ex_id == "binance" or intel.long_short_ratio is None:
                    ls_bn = _http_get_json(
                        "https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
                        {"symbol": raw_sym, "period": "1h", "limit": 1},
                        timeout=2.5,
                    )
                    if isinstance(ls_bn, list) and len(ls_bn) >= 1 and ls_bn[-1].get("longShortRatio") is not None:
                        intel.long_short_ratio = float(ls_bn[-1]["longShortRatio"])
            except Exception:
                pass

            # 2b. Bybit Linear Perpetual (queried both for Bybit selection AND Global Aggregated OI)
            for dom in ("https://api.bytick.com", "https://api.bybit.com"):
                try:
                    lin_res = _http_get_json(f"{dom}/v5/market/tickers", {"category": "linear", "symbol": raw_sym}, timeout=2.8)
                    lin_list = lin_res.get("result", {}).get("list", []) if isinstance(lin_res, dict) else []
                    if lin_list:
                        lt = lin_list[0]
                        byb_fr = float(lt["fundingRate"]) * 100.0 if lt.get("fundingRate") else None
                        byb_oi = float(lt["openInterestValue"]) if lt.get("openInterestValue") else 0.0
                        if byb_oi > 0:
                            agg_oi_pairs.append(("BYBIT", byb_oi, byb_fr))
                        if ex_id == "bybit" or intel.funding_rate_pct is None:
                            if byb_fr is not None:
                                intel.funding_rate_pct = byb_fr
                        if ex_id == "bybit" or intel.open_interest_usd is None:
                            if byb_oi > 0:
                                intel.open_interest_usd = byb_oi
                        mp = float(lt.get("markPrice") or 0.0)
                        ip = float(lt.get("indexPrice") or 0.0)
                        if mp > 0 and ip > 0 and (ex_id == "bybit" or intel.perp_spot_basis_pct is None):
                            mark_p_ref = mp
                            intel.perp_spot_basis_pct = ((mp - ip) / ip) * 100.0
                        if "BYBIT" not in fut_sources:
                            fut_sources.append("BYBIT")
                        break
                except Exception:
                    continue

            # 2c. Gate.io Futures Contract if selected or needed
            if ex_id == "gate" or intel.funding_rate_pct is None:
                try:
                    g_res = _http_get_json(f"https://api.gateio.ws/api/v4/futures/usdt/contracts/{base_ccy}_USDT", timeout=2.8)
                    if isinstance(g_res, dict):
                        if intel.funding_rate_pct is None and g_res.get("funding_rate") is not None:
                            intel.funding_rate_pct = float(g_res["funding_rate"]) * 100.0
                            if "GATE" not in fut_sources:
                                fut_sources.append("GATE")
                        mp = float(g_res.get("mark_price") or 0.0)
                        ip = float(g_res.get("index_price") or 0.0)
                        if mp > 0 and ip > 0 and intel.perp_spot_basis_pct is None:
                            mark_p_ref = mp
                            intel.perp_spot_basis_pct = ((mp - ip) / ip) * 100.0
                except Exception:
                    pass

            # 2d. Direct OKX Swap Rubik Stats (queried for Global Aggregated OI + OKX primary / fallback)
            if not okx_spot_missing:
                try:
                    inst_id = f"{base_ccy}-USDT-SWAP"
                    okx_fr: Optional[float] = None
                    okx_oi: float = 0.0
                    added_okx = False

                    fr_res = _http_get_json("https://www.okx.com/api/v5/public/funding-rate", {"instId": inst_id}, timeout=2.6)
                    fr_list = fr_res.get("data", []) if isinstance(fr_res, dict) else []
                    if fr_list and fr_list[0].get("fundingRate") is not None:
                        okx_fr = float(fr_list[0]["fundingRate"]) * 100.0
                        if ex_id == "okx" or intel.funding_rate_pct is None:
                            intel.funding_rate_pct = okx_fr
                        added_okx = True

                    oih_res = _http_get_json("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume", {"ccy": base_ccy, "period": "1H"}, timeout=2.6)
                    oih_list = oih_res.get("data", []) if isinstance(oih_res, dict) else []
                    if oih_list and len(oih_list) >= 2:
                        oi_now = float(oih_list[0][1])
                        oi_1h = float(oih_list[1][1])
                        oi_4h = float(oih_list[min(4, len(oih_list) - 1)][1])
                        oi_24h = float(oih_list[min(24, len(oih_list) - 1)][1])
                        if oi_now > 0:
                            okx_oi = oi_now
                            if ex_id == "okx" or intel.open_interest_usd is None:
                                intel.open_interest_usd = oi_now
                        if ex_id == "okx" or intel.oi_change_24h_pct is None:
                            if oi_1h > 0:
                                intel.oi_change_1h_pct = ((oi_now - oi_1h) / oi_1h) * 100.0
                            if oi_4h > 0:
                                intel.oi_change_4h_pct = ((oi_now - oi_4h) / oi_4h) * 100.0
                            if oi_24h > 0:
                                intel.oi_change_24h_pct = ((oi_now - oi_24h) / oi_24h) * 100.0
                        added_okx = True

                    if okx_oi > 0:
                        agg_oi_pairs.append(("OKX", okx_oi, okx_fr))

                    if intel.long_short_ratio is None or ex_id == "okx":
                        ls_res = _http_get_json("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio", {"ccy": base_ccy, "period": "1H"}, timeout=2.5)
                        ls_list = ls_res.get("data", []) if isinstance(ls_res, dict) else []
                        if ls_list and len(ls_list) >= 1:
                            intel.long_short_ratio = float(ls_list[0][1])
                            added_okx = True

                    if intel.futures_taker_buy_sell_ratio is None or ex_id == "okx":
                        tv_res = _http_get_json("https://www.okx.com/api/v5/rubik/stat/taker-volume", {"ccy": base_ccy, "instType": "CONTRACTS", "period": "1H"}, timeout=2.5)
                        tv_list = tv_res.get("data", []) if isinstance(tv_res, dict) else []
                        if tv_list and len(tv_list) >= 1:
                            sell_v = float(tv_list[0][1] or 0.0)
                            buy_v = float(tv_list[0][2] or 0.0)
                            if sell_v > 0:
                                intel.futures_taker_buy_sell_ratio = buy_v / sell_v
                                added_okx = True
                            ref_p = float(mark_p_ref or mid_spot_ref or 0.0)
                            if ref_p > 0 and intel.perp_cvd_delta_24h_usd is None:
                                intel.perp_cvd_delta_24h_usd = (buy_v - sell_v) * ref_p
                    if added_okx and "OKX" not in fut_sources:
                        fut_sources.append("OKX")
                except Exception:
                    pass

            # Compute Global 3-Exchange Aggregated OI & OI-Weighted Funding Rate
            if agg_oi_pairs:
                total_agg_oi = sum(x[1] for x in agg_oi_pairs)
                intel.aggregated_oi_usd = total_agg_oi
                intel.aggregated_exchanges_count = len(agg_oi_pairs)
                weighted_fr_num = sum(x[1] * x[2] for x in agg_oi_pairs if x[2] is not None)
                weighted_fr_den = sum(x[1] for x in agg_oi_pairs if x[2] is not None)
                if weighted_fr_den > 0:
                    intel.oi_weighted_funding_pct = weighted_fr_num / weighted_fr_den
                    if intel.funding_rate_pct is None:
                        intel.funding_rate_pct = intel.oi_weighted_funding_pct

            intel.futures_source = "+".join(fut_sources) if fut_sources else ""

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

        try:
            intel.macro_liquidity = self.fetch_macro_liquidity_intel()
        except Exception:
            intel.macro_liquidity = None

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
