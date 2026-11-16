"""
Market-Wide Real Spot Cash-Flow & Volatility Squeeze Hunter (`MarketWideHunter` — Top 80 Liquid USDT Pairs).

Zero-Hallucination Institutional Design:
  - Uses ONLY real exchange trade-execution data (Binance 12-column Spot & USD-M Perp `klines`
    containing exact `quote_asset_volume` and `taker_buy_quote_asset_volume`, plus `/fapi/v1/premiumIndex`).
  - Zero synthetic fallback: if live exchange klines cannot be verified, raises or skips cleanly.
  - All Z-Scores, RVOL, RSI(14), EMA20/50, and Bollinger/Keltner Squeeze metrics are computed
    strictly on CLOSED candles (`close_time <= now_ms`) to prevent intrabar repainting.
  - Cross-checks top Spot inflow candidates against USD-M Perpetual Taker Delta & Funding Rate
    to separate genuine Institutional Spot Accumulation / Short-Squeeze Fuel from Leverage Foam.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter

EXCLUDED_BASES = {
    "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USDE", "PYUSD", "USD1", "RLUSD", "U", "USDD", "FRAX", "LUSD",
    "USDT", "EUR", "EURI", "AEUR", "GBP", "TRY", "BRL", "JPY", "AUD", "ZAR", "PLN", "RON", "ARS",
    "WBTC", "WBETH", "BETH", "BNSOL", "STETH", "PAXG", "XAUT",
    "NVDAB", "GOOGLB", "AAPLB", "TSLAB", "MSFTB", "AMZNB", "METAB", "COINB", "MSTRB", "SPYB", "QQQB",
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S", "2L", "2S")

_HTTP_SESSION: Optional[requests.Session] = None
_SESSION_LOCK = threading.Lock()


def _get_pooled_session() -> requests.Session:
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        with _SESSION_LOCK:
            if _HTTP_SESSION is None:
                sess = requests.Session()
                sess.headers.update(
                    {
                        "User-Agent": "SmartCryptoQuantHunter/3.0",
                        "Accept": "application/json",
                    }
                )
                adapter = HTTPAdapter(pool_connections=24, pool_maxsize=24, max_retries=1)
                sess.mount("https://", adapter)
                sess.mount("http://", adapter)
                _HTTP_SESSION = sess
    return _HTTP_SESSION

_HUNTER_CACHE_LOCK = threading.Lock()
_HUNTER_CACHE: Dict[Tuple[str, int, int], Tuple[float, "MarketHunterReport"]] = {}
HUNTER_CACHE_TTL_SEC = 90.0


@dataclass
class MarketHunterCandidate:
    """Single liquid USDT pair audited by the Market-Wide Spot Cash-Flow & Squeeze Hunter."""
    symbol: str
    exchange: str
    timeframe: str
    price: float
    change_24h_pct: float
    quote_vol_24h_usd: float
    spot_delta_last_bar_usd: float
    spot_delta_4bar_usd: float
    spot_delta_24h_usd: float
    perp_delta_4bar_usd: Optional[float]
    spot_buy_ratio_4bar_pct: float
    delta_zscore: float
    flow_impulse_z: float
    rvol: float
    squeeze_energy_pct: float
    is_squeezing: bool
    rsi_14: float
    ema20: float
    ema50: float
    funding_rate_pct: Optional[float]
    spot_perp_quality_code: str
    spot_perp_quality_tr: str
    breakout_trigger_price: float
    distance_to_breakout_pct: float
    support_invalid_price: float
    hunter_score: float
    signal_badge_tr: str
    is_qualified_pick: bool
    in_watchlist: bool = False


@dataclass
class MarketHunterReport:
    """Complete Top-80 Market-Wide Spot Cash-Flow Breadth & Anomaly Hunter Report."""
    scanned_at_utc: str
    timeframe: str
    exchange_source: str
    universe_scanned: int
    min_quote_vol_usd: float
    inflow_positive_count: int
    squeezing_count: int
    total_top_spot_net_4bar_usd: float
    total_top_spot_net_24h_usd: float
    top_picks: List[MarketHunterCandidate] = field(default_factory=list)
    all_ranked: List[MarketHunterCandidate] = field(default_factory=list)


def _http_get_json(url: str, timeout: float = 6.0) -> Any:
    sess = _get_pooled_session()
    resp = sess.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fmt_usd_compact(val: Optional[float]) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "Veri Yok"
    sign = "+" if val > 0 else ("-" if val < 0 else "")
    a = abs(float(val))
    if a >= 1_000_000_000:
        return f"{sign}${a / 1_000_000_000:.2f}B"
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"{sign}${a / 1_000:.1f}K"
    return f"{sign}${a:.0f}"


def _is_eligible_usdt_symbol(raw_sym: str) -> Tuple[bool, str]:
    if not raw_sym.endswith("USDT") or len(raw_sym) <= 4:
        return False, ""
    base = raw_sym[:-4].upper()
    if not base or not base.isalnum():
        return False, ""
    if base in EXCLUDED_BASES:
        return False, ""
    for suf in LEVERAGED_SUFFIXES:
        if base.endswith(suf) and len(base) > len(suf) + 1:
            return False, ""
    return True, f"{base}/USDT"


def _wilder_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 2:
        return 50.0
    s = pd.Series(closes, dtype=float)
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    last_loss = float(avg_loss.iloc[-1])
    last_gain = float(avg_gain.iloc[-1])
    if last_loss <= 1e-12:
        return 100.0 if last_gain > 0 else 50.0
    rs = last_gain / last_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _compute_closed_bar_metrics(
    raw_klines: List[List[Any]],
    timeframe: str,
    live_price_hint: float,
    change_24h_pct: float,
    quote_vol_24h_usd: float,
    funding_rate_pct: Optional[float],
    symbol: str,
    exchange_label: str = "BINANCE",
) -> Optional[MarketHunterCandidate]:
    """
    Computes exact Spot Taker Cash-Flow, Z-Scores, RVOL, RSI(14), EMA20/50, and BB/Keltner Squeeze
    exclusively on CLOSED 12-column Binance klines (`close_time <= now_ms`).
    """
    if not raw_klines or len(raw_klines) < 35:
        return None

    now_ms = int(time.time() * 1000)
    closed_rows: List[Tuple[float, float, float, float, float, float]] = []
    latest_close = float(live_price_hint) if live_price_hint > 0 else 0.0

    for row in raw_klines:
        if len(row) < 11:
            continue
        c_price = float(row[4])
        latest_close = c_price if live_price_hint <= 0 else latest_close
        close_ms = int(row[6])
        if close_ms > now_ms:
            # Unclosed forming candle: never include in Z-score, Squeeze, or Cash-Flow totals
            continue
        o_p = float(row[1])
        h_p = float(row[2])
        l_p = float(row[3])
        q_vol = float(row[7])       # Exact USD quote volume
        tb_q_vol = float(row[10])   # Exact Taker Buy USD quote volume
        if c_price <= 0 or h_p < l_p or q_vol < 0:
            continue
        closed_rows.append((o_p, h_p, l_p, c_price, q_vol, tb_q_vol))

    if len(closed_rows) < 32:
        return None

    arr = np.asarray(closed_rows, dtype=float)
    highs = arr[:, 1]
    lows = arr[:, 2]
    closes = arr[:, 3]
    q_vols = arr[:, 4]
    tb_vols = arr[:, 5]
    ts_vols = np.maximum(0.0, q_vols - tb_vols)
    net_deltas = tb_vols - ts_vols  # Exact Real Spot Taker Net USD Flow per closed bar

    curr_price = float(live_price_hint) if live_price_hint > 0 else float(closes[-1])
    # Dynamic stablecoin/peg guard: exclude assets pegged around $1.00 with tiny multi-day range
    if 0.985 <= curr_price <= 1.015:
        full_rng_pct = (float(np.max(highs)) - float(np.min(lows))) / max(curr_price, 1e-9)
        if full_rng_pct < 0.025:
            return None
    tf_up = timeframe.upper()
    bars_24h = 24 if tf_up == "1H" else (6 if tf_up == "4H" else 24)

    spot_delta_last = float(net_deltas[-1])
    spot_delta_4b = float(np.sum(net_deltas[-4:]))
    spot_delta_24h = float(np.sum(net_deltas[-min(len(net_deltas), bars_24h):]))

    q_4b_sum = float(np.sum(q_vols[-4:]))
    tb_4b_sum = float(np.sum(tb_vols[-4:]))
    buy_ratio_4b_pct = (tb_4b_sum / q_4b_sum * 100.0) if q_4b_sum > 0 else 50.0

    # 1. Coin-Normalized Statistical Cash-Flow Z-Scores (against prior baseline to avoid self-dilution)
    hist_window = net_deltas[-52:-1] if len(net_deltas) >= 25 else net_deltas[:-1]
    mean_d = float(np.mean(hist_window)) if len(hist_window) > 5 else 0.0
    std_d = float(np.std(hist_window, ddof=1)) if len(hist_window) > 5 else 1.0
    if std_d <= 1e-6:
        delta_z = 0.0
    else:
        delta_z = float(np.clip((spot_delta_last - mean_d) / std_d, -6.0, 6.0))

    # 3-bar cumulative impulse Z-score
    s_del = pd.Series(net_deltas, dtype=float)
    roll3 = s_del.rolling(3).sum().dropna().to_numpy()
    if len(roll3) >= 15:
        base3 = roll3[:-1]
        m3 = float(np.mean(base3))
        sd3 = float(np.std(base3, ddof=1))
        impulse_z = float(np.clip((roll3[-1] - m3) / sd3, -6.0, 6.0)) if sd3 > 1e-6 else 0.0
    else:
        impulse_z = delta_z

    # 2. Relative Volume (RVOL) on Closed USD Quote Volume
    vol_base = q_vols[-21:-1] if len(q_vols) >= 21 else q_vols[:-1]
    avg_vol_20 = float(np.mean(vol_base)) if len(vol_base) > 0 else 0.0
    rvol = (float(q_vols[-1]) / avg_vol_20) if avg_vol_20 > 0 else 1.0

    # 3. Exact EMA20, EMA50 & Wilder RSI(14) on Closed Bars
    s_close = pd.Series(closes, dtype=float)
    ema20 = float(s_close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(s_close.ewm(span=50, adjust=False).mean().iloc[-1])
    rsi_14 = _wilder_rsi(closes, 14)

    # 4. Bollinger Band (20, 2.0) vs Keltner Channel (20, 1.5*ATR) Volatility Squeeze Energy
    bb_mid = s_close.rolling(20).mean()
    bb_std = s_close.rolling(20).std(ddof=0)
    bb_width = ((bb_std * 4.0) / bb_mid.replace(0, np.nan)).dropna()

    prev_close = s_close.shift(1)
    tr = pd.concat(
        [
            pd.Series(highs) - pd.Series(lows),
            (pd.Series(highs) - prev_close).abs(),
            (pd.Series(lows) - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr20 = tr.ewm(alpha=1.0 / 20.0, adjust=False).mean()
    kc_width = ((atr20 * 3.0) / bb_mid.replace(0, np.nan)).dropna()

    curr_bb_w = float(bb_width.iloc[-1]) if len(bb_width) > 0 else 0.08
    curr_kc_w = float(kc_width.iloc[-1]) if len(kc_width) > 0 else 0.08
    inside_keltner = curr_bb_w <= curr_kc_w

    if len(bb_width) >= 15:
        w_arr = bb_width.tail(50).to_numpy()
        w_min = float(np.min(w_arr))
        w_max = float(np.max(w_arr))
        if w_max > w_min + 1e-9:
            pct_compress = (1.0 - (curr_bb_w - w_min) / (w_max - w_min)) * 100.0
        else:
            pct_compress = 50.0
    else:
        pct_compress = 40.0

    kc_bonus = 18.0 if inside_keltner else 0.0
    squeeze_energy = float(np.clip(pct_compress * 0.82 + kc_bonus, 0.0, 100.0))
    is_squeezing = bool(inside_keltner or squeeze_energy >= 68.0)

    # 5. Closed-Candle Breakout Resistance (20-bar High) & Support Invalidation
    recent_high_20 = float(np.max(highs[-20:]))
    recent_low_10 = float(np.min(lows[-10:]))
    dist_to_brk_pct = ((recent_high_20 - curr_price) / curr_price) * 100.0 if curr_price > 0 else 0.0
    support_inv = min(ema20, recent_low_10) if ema20 < curr_price else recent_low_10

    return MarketHunterCandidate(
        symbol=symbol,
        exchange=exchange_label,
        timeframe=tf_up,
        price=curr_price,
        change_24h_pct=change_24h_pct,
        quote_vol_24h_usd=quote_vol_24h_usd,
        spot_delta_last_bar_usd=spot_delta_last,
        spot_delta_4bar_usd=spot_delta_4b,
        spot_delta_24h_usd=spot_delta_24h,
        perp_delta_4bar_usd=None,
        spot_buy_ratio_4bar_pct=buy_ratio_4b_pct,
        delta_zscore=delta_z,
        flow_impulse_z=impulse_z,
        rvol=rvol,
        squeeze_energy_pct=squeeze_energy,
        is_squeezing=is_squeezing,
        rsi_14=rsi_14,
        ema20=ema20,
        ema50=ema50,
        funding_rate_pct=funding_rate_pct,
        spot_perp_quality_code="NEUTRAL",
        spot_perp_quality_tr="Spot Veri Doğrulandı",
        breakout_trigger_price=recent_high_20,
        distance_to_breakout_pct=dist_to_brk_pct,
        support_invalid_price=support_inv,
        hunter_score=0.0,
        signal_badge_tr="Nötr",
        is_qualified_pick=False,
    )


def _score_and_classify_candidate(c: MarketHunterCandidate) -> MarketHunterCandidate:
    """
    Computes institutional `hunter_score` (0-100), Spot-vs-Perp quality verdict,
    and strict qualification status (`is_qualified_pick`).
    """
    best_z = max(c.delta_zscore, c.flow_impulse_z)
    f_rate = c.funding_rate_pct

    # A. Spot-vs-Perp Institutional Cash-Flow Quality
    sp_code = "SPOT_LED"
    sp_tr = "🟢 Gerçek Spot Alım Öncülüğü"
    sp_pts = 8.0

    if c.spot_delta_4bar_usd < 0 and (
        (c.perp_delta_4bar_usd is not None and c.perp_delta_4bar_usd > abs(c.spot_delta_4bar_usd) * 0.5)
        or (f_rate is not None and f_rate >= 0.022)
    ):
        sp_code = "LEVERAGE_FOAM"
        sp_tr = "⚠️ Kaldıraç Köpüğü (Spot Satışta)"
        sp_pts = -25.0
    elif c.spot_delta_4bar_usd > 0:
        if (f_rate is not None and f_rate <= -0.003) or (
            c.perp_delta_4bar_usd is not None and c.perp_delta_4bar_usd < 0
        ):
            sp_code = "SHORT_SQUEEZE_FUEL"
            sp_tr = "🧲 Spot Birikim + Short Squeeze Yakıtı"
            sp_pts = 18.0
        elif f_rate is None or f_rate <= 0.015:
            sp_code = "SPOT_ORGANIC"
            sp_tr = "✅ Organik Kurumsal Spot Giriş (Köpüksüz)"
            sp_pts = 13.0
        elif f_rate > 0.035:
            sp_code = "CROWDED_FUNDING"
            sp_tr = "⚠️ Spot Giriş Var Ama Fonlama Kalabalık"
            sp_pts = -4.0

    # B. Statistical Spot Cash-Flow Score (0 to 42 pts)
    if c.spot_delta_4bar_usd <= 0 and c.spot_delta_last_bar_usd <= 0:
        flow_pts = max(0.0, (best_z + 1.0) * 4.0)
    else:
        z_pts = float(np.clip(best_z * 11.5 + 8.0, 0.0, 36.0))
        dom_pts = float(np.clip((c.spot_buy_ratio_4bar_pct - 50.0) * 1.1, 0.0, 6.0))
        flow_pts = min(42.0, z_pts + dom_pts)

    # C. Volatility Squeeze & Pre-Breakout Coiling (0 to 26 pts)
    sqz_pts = c.squeeze_energy_pct * 0.18
    if -1.5 <= c.distance_to_breakout_pct <= 3.0:
        # Either coiled right below 20-bar resistance (0..3%) or fresh breakout (0..-1.5%)
        sqz_pts += 8.0
    elif 3.0 < c.distance_to_breakout_pct <= 6.0:
        sqz_pts += 4.0
    sqz_pts = min(26.0, sqz_pts)

    # D. Relative Volume Participation (0 to 14 pts)
    if c.spot_delta_last_bar_usd > 0 or c.spot_delta_4bar_usd > 0:
        rvol_pts = float(np.clip((c.rvol - 0.85) * 9.5, 0.0, 14.0))
    else:
        rvol_pts = 0.0

    # E. Structural Trend & Anti-FOMO RSI Guard (-18 to +8 pts)
    struct_pts = 0.0
    if c.price >= c.ema20 >= c.ema50:
        struct_pts += 6.0
    elif c.price >= c.ema50 * 0.99:
        struct_pts += 3.0
    else:
        struct_pts -= 10.0

    if 46.0 <= c.rsi_14 <= 69.0:
        struct_pts += 2.0
    elif c.rsi_14 > 78.0:
        struct_pts -= 16.0  # Retail FOMO top penalty

    raw_total = flow_pts + sqz_pts + rvol_pts + sp_pts + struct_pts
    total_score = float(np.clip(raw_total, 0.0, 99.0))

    # Strict Qualification Gate for Top Hunter Picks (Zero Hallucination / Zero Foam)
    has_real_spot_inflow = (c.spot_delta_4bar_usd > 0 and best_z >= 0.45) or (
        c.spot_delta_last_bar_usd > 0 and c.delta_zscore >= 1.15
    )
    not_foam = sp_code != "LEVERAGE_FOAM"
    not_overbought = c.rsi_14 <= 77.5
    structure_alive = c.price >= c.ema50 * 0.975
    qualified = bool(has_real_spot_inflow and not_foam and not_overbought and structure_alive and total_score >= 50.0)

    # Actionable Turkish Classification Badge
    if qualified:
        if sp_code == "SHORT_SQUEEZE_FUEL" and c.is_squeezing:
            badge = "🐋 Spot Birikim + Sıkışma + Squeeze Yakıtı"
        elif c.is_squeezing and best_z >= 1.5:
            badge = "💥 Sıkışma İçinde Güçlü Spot Giriş"
        elif sp_code == "SHORT_SQUEEZE_FUEL":
            badge = "🧲 Kurumsal Spot Alım (Short Squeeze Adayı)"
        elif best_z >= 2.0:
            badge = f"🚀 Olağandışı Spot Nakit Girişi ({best_z:+.1f}σ)"
        elif c.is_squeezing:
            badge = "🗜️ Volatilite Sıkışması + Pozitif Nakit"
        else:
            badge = "💸 Düzenli Gerçek Spot Para Girişi"
    else:
        if sp_code == "LEVERAGE_FOAM":
            badge = "⚠️ Kaldıraç Köpüğü (Elenen)"
        elif c.spot_delta_4bar_usd < 0:
            badge = "📉 Spot Nakit Çıkışı"
        elif c.rsi_14 > 77.5:
            badge = "🔥 Aşırı Şişmiş RSI (Geç Kalınmış)"
        else:
            badge = "⚖️ İzlemede / Zayıf Akış"

    c.spot_perp_quality_code = sp_code
    c.spot_perp_quality_tr = sp_tr
    c.hunter_score = round(total_score, 1)
    c.signal_badge_tr = badge
    c.is_qualified_pick = qualified
    return c


class MarketWideHunter:
    """
    Two-Stage High-Speed Institutional Scanner across the Top 80 Most Liquid USDT Pairs.
    """

    SPOT_BASES = (
        "https://api.binance.com/api/v3",
        "https://data-api.binance.vision/api/v3",
    )
    FUTURES_BASE = "https://fapi.binance.com/fapi/v1"

    @classmethod
    def _fetch_spot_24h_tickers(cls) -> Tuple[List[Dict[str, Any]], str]:
        last_err: Optional[Exception] = None
        for base in cls.SPOT_BASES:
            try:
                data = _http_get_json(f"{base}/ticker/24hr?type=MINI", timeout=6.0)
                if isinstance(data, list) and len(data) > 50:
                    return data, base
            except Exception as e:
                last_err = e
        raise RuntimeError(f"Canlı Spot piyasa 24s hacim tablosuna ulaşılamadı: {last_err}")

    @classmethod
    def _fetch_futures_funding_map(cls) -> Dict[str, float]:
        funding_map: Dict[str, float] = {}
        try:
            data = _http_get_json(f"{cls.FUTURES_BASE}/premiumIndex", timeout=5.5)
            if isinstance(data, list):
                for item in data:
                    sym = str(item.get("symbol", "")).upper()
                    fr_str = item.get("lastFundingRate")
                    if sym and fr_str is not None and fr_str != "":
                        funding_map[sym] = float(fr_str) * 100.0
        except Exception:
            pass
        return funding_map

    @classmethod
    def _fetch_spot_klines_single(cls, spot_base: str, raw_sym: str, interval: str, limit: int = 62) -> List[List[Any]]:
        url = f"{spot_base}/klines?symbol={raw_sym}&interval={interval}&limit={limit}"
        data = _http_get_json(url, timeout=6.0)
        return data if isinstance(data, list) else []

    @classmethod
    def _fetch_perp_4bar_delta_single(cls, raw_sym: str, interval: str) -> Optional[float]:
        try:
            url = f"{cls.FUTURES_BASE}/klines?symbol={raw_sym}&interval={interval}&limit=7"
            rows = _http_get_json(url, timeout=4.5)
            if not isinstance(rows, list) or len(rows) < 4:
                return None
            now_ms = int(time.time() * 1000)
            closed_deltas: List[float] = []
            for r in rows:
                if len(r) >= 11 and int(r[6]) <= now_ms:
                    qv = float(r[7])
                    tb = float(r[10])
                    closed_deltas.append(tb - max(0.0, qv - tb))
            if not closed_deltas:
                return None
            return float(sum(closed_deltas[-4:]))
        except Exception:
            return None

    @classmethod
    def scan_market(
        cls,
        timeframe: str = "1h",
        universe_size: int = 80,
        min_quote_vol_usd: float = 2_500_000.0,
        top_n: int = 10,
        watchlist: Optional[Sequence[str]] = None,
        force_refresh: bool = False,
    ) -> MarketHunterReport:
        """
        Executes the full 2-stage real-data market scan across the top `universe_size` (default 80)
        most liquid USDT Spot pairs, cross-checking top Spot inflow candidates against USD-M Perpetuals.
        """
        tf_low = timeframe.lower().strip()
        if tf_low not in ("1h", "4h"):
            tf_low = "1h"
        tf_up = tf_low.upper()
        wl_set = {s.strip().upper() for s in (watchlist or []) if s}

        cache_key = (tf_up, int(universe_size), int(min_quote_vol_usd))
        now_t = time.time()
        if not force_refresh:
            with _HUNTER_CACHE_LOCK:
                cached = _HUNTER_CACHE.get(cache_key)
                if cached and (now_t - cached[0]) <= HUNTER_CACHE_TTL_SEC:
                    rep = cached[1]
                    for item in rep.all_ranked:
                        item.in_watchlist = item.symbol in wl_set
                    return rep

        # STAGE 1: Bulk Spot 24h Liquidity Universe + Bulk USD-M Funding Map in parallel
        with ThreadPoolExecutor(max_workers=2) as pool_bulk:
            fut_spot = pool_bulk.submit(cls._fetch_spot_24h_tickers)
            fut_fund = pool_bulk.submit(cls._fetch_futures_funding_map)
            tickers_24h, spot_base_used = fut_spot.result()
            funding_map = fut_fund.result()

        eligible_rows: List[Dict[str, Any]] = []
        for t in tickers_24h:
            raw_s = str(t.get("symbol", "")).upper()
            ok, norm_sym = _is_eligible_usdt_symbol(raw_s)
            if not ok:
                continue
            try:
                q_vol = float(t.get("quoteVolume") or 0.0)
                last_p = float(t.get("closePrice") or t.get("lastPrice") or 0.0)
                open_p = float(t.get("openPrice") or last_p)
                high_p = float(t.get("highPrice") or last_p)
                low_p = float(t.get("lowPrice") or last_p)
                chg_pct = ((last_p - open_p) / open_p * 100.0) if open_p > 0 else float(t.get("priceChangePercent") or 0.0)
            except Exception:
                continue
            if last_p <= 0 or q_vol < min_quote_vol_usd:
                continue
            # Dynamic peg filter ($1.00 stablecoins)
            if 0.985 <= last_p <= 1.015 and ((high_p - low_p) / last_p) < 0.022:
                continue
            eligible_rows.append(
                {
                    "raw_sym": raw_s,
                    "symbol": norm_sym,
                    "last_price": last_p,
                    "chg_pct": chg_pct,
                    "quote_vol": q_vol,
                    "funding_pct": funding_map.get(raw_s),
                }
            )

        eligible_rows.sort(key=lambda r: r["quote_vol"], reverse=True)
        universe = eligible_rows[: max(10, min(int(universe_size), 120))]

        # STAGE 2A: Fetch closed 12-column Spot klines in parallel across all Top 80 pairs
        preliminary: List[Tuple[str, MarketHunterCandidate]] = []
        with ThreadPoolExecutor(max_workers=12) as pool_k:
            fut_map = {
                pool_k.submit(cls._fetch_spot_klines_single, spot_base_used, u["raw_sym"], tf_low, 62): u
                for u in universe
            }
            for fut in as_completed(fut_map):
                u = fut_map[fut]
                try:
                    klines = fut.result()
                    cand = _compute_closed_bar_metrics(
                        raw_klines=klines,
                        timeframe=tf_up,
                        live_price_hint=u["last_price"],
                        change_24h_pct=u["chg_pct"],
                        quote_vol_24h_usd=u["quote_vol"],
                        funding_rate_pct=u["funding_pct"],
                        symbol=u["symbol"],
                        exchange_label="BINANCE",
                    )
                    if cand is not None:
                        cand.in_watchlist = cand.symbol in wl_set
                        preliminary.append((u["raw_sym"], cand))
                except Exception:
                    continue

        # STAGE 2B: Cross-check Top 24 Spot Inflow / Squeeze leaders with USD-M Perp Closed Taker Delta
        preliminary.sort(
            key=lambda pair: (
                pair[1].spot_delta_4bar_usd > 0,
                max(pair[1].delta_zscore, pair[1].flow_impulse_z),
                pair[1].squeeze_energy_pct,
            ),
            reverse=True,
        )
        perp_targets = [
            (raw_s, c)
            for raw_s, c in preliminary[:24]
            if c.funding_rate_pct is not None  # Has active USD-M Perp contract
        ]
        if perp_targets:
            with ThreadPoolExecutor(max_workers=8) as pool_p:
                pfuts = {
                    pool_p.submit(cls._fetch_perp_4bar_delta_single, raw_s, tf_low): c
                    for raw_s, c in perp_targets
                }
                for pfut in as_completed(pfuts):
                    cand_ref = pfuts[pfut]
                    try:
                        cand_ref.perp_delta_4bar_usd = pfut.result()
                    except Exception:
                        cand_ref.perp_delta_4bar_usd = None

        # Finalize scoring & qualification
        evaluated: List[MarketHunterCandidate] = [_score_and_classify_candidate(c) for _, c in preliminary]
        evaluated.sort(
            key=lambda c: (c.is_qualified_pick, c.hunter_score, max(c.delta_zscore, c.flow_impulse_z)),
            reverse=True,
        )

        qualified_picks = [c for c in evaluated if c.is_qualified_pick][:top_n]
        inflow_pos_n = sum(1 for c in evaluated if c.spot_delta_4bar_usd > 0)
        sqz_n = sum(1 for c in evaluated if c.is_squeezing)
        net_4b_all = float(sum(c.spot_delta_4bar_usd for c in evaluated))
        net_24h_all = float(sum(c.spot_delta_24h_usd for c in evaluated))

        src_lbl = "BINANCE SPOT + USD-M PERP" if funding_map else "BINANCE SPOT"
        report = MarketHunterReport(
            scanned_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            timeframe=tf_up,
            exchange_source=src_lbl,
            universe_scanned=len(evaluated),
            min_quote_vol_usd=min_quote_vol_usd,
            inflow_positive_count=inflow_pos_n,
            squeezing_count=sqz_n,
            total_top_spot_net_4bar_usd=net_4b_all,
            total_top_spot_net_24h_usd=net_24h_all,
            top_picks=qualified_picks,
            all_ranked=evaluated,
        )

        with _HUNTER_CACHE_LOCK:
            _HUNTER_CACHE[cache_key] = (now_t, report)
        return report


def format_market_hunter_telegram_html(
    report: MarketHunterReport,
    only_unlisted: bool = False,
) -> str:
    """Formats the Top-80 Market-Wide Spot Cash-Flow & Squeeze Hunter Report into clean Telegram HTML."""
    tf_lbl = "Son 4 Saat" if report.timeframe == "1H" else "Son 16 Saat (4x4H)"
    picks = [c for c in report.top_picks if (not only_unlisted or not c.in_watchlist)]

    breadth_pct = (report.inflow_positive_count / max(1, report.universe_scanned)) * 100.0
    mood_ic = "🟢" if report.total_top_spot_net_4bar_usd > 0 else "🔴"

    lines = [
        f"🌐 <b>TÜM PİYASA SPOT NAKİT &amp; SIKIŞMA AVCISI [{report.timeframe}]</b>",
        f"<i>En likit {report.universe_scanned} USDT tahtasının gerçek Taker eşleşme taraması ({report.exchange_source}):</i>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"• {mood_ic} <b>Top {report.universe_scanned} Net Spot Akışı ({tf_lbl}):</b> <code>{fmt_usd_compact(report.total_top_spot_net_4bar_usd)}</code> <i>(24S: {fmt_usd_compact(report.total_top_spot_net_24h_usd)})</i>",
        f"• 📊 <b>Piyasa Genişliği:</b> <b>{report.inflow_positive_count}/{report.universe_scanned}</b> coinde pozitif Spot giriş (%{breadth_pct:.0f}) | 🗜️ <b>{report.squeezing_count}</b> coinde sıkışma",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if not picks:
        lines.append(
            "🛑 <b>Şu an kriterleri (Gerçek Spot Giriş + Köpüksüz Vadeli + Sağlıklı Yapı) eksiksiz karşılayan aday bulunmuyor.</b>\n"
            "<i>💡 Piyasa genelinde nakit çıkışı veya kaldıraç köpüğü baskın olduğunda sistem sahte fırsat üretmez; en dirençli izleme adayları:</i>"
        )
        fallback_list = [c for c in report.all_ranked if (not only_unlisted or not c.in_watchlist)][:4]
        for idx, c in enumerate(fallback_list, start=1):
            short_s = c.symbol.replace("/USDT", "")
            best_z = max(c.delta_zscore, c.flow_impulse_z)
            lines.append(
                f"{idx}. <b>{short_s}</b> ({c.hunter_score:.0f}/100) — Spot: <code>{fmt_usd_compact(c.spot_delta_4bar_usd)}</code> ({best_z:+.1f}σ) | Sıkışma: %{c.squeeze_energy_pct:.0f}"
            )
    else:
        hdr = "🆕 <b>LİSTE DIŞI YENİ KEŞİFLER:</b>" if only_unlisted else "🐋 <b>DOĞRULANMIŞ EN GÜÇLÜ ADAYLAR:</b>"
        lines.append(hdr)
        for idx, c in enumerate(picks[:8], start=1):
            short_s = c.symbol.replace("/USDT", "")
            p_fmt = ",.4f" if c.price < 10.0 else ",.2f"
            best_z = max(c.delta_zscore, c.flow_impulse_z)
            wl_tag = "📌" if c.in_watchlist else "🆕"
            fr_str = f" | Fonlama: {c.funding_rate_pct:+.3f}%" if c.funding_rate_pct is not None else ""
            lines.append(
                f"{idx}. {wl_tag} <b>{short_s}</b> — Skor: <b>{c.hunter_score:.0f}/100</b> | Fiyat: <code>{format(c.price, p_fmt)}$</code> ({c.change_24h_pct:+.1f}%)\n"
                f"   • {c.signal_badge_tr}\n"
                f"   • 💵 <b>Gerçek Spot ({tf_lbl}):</b> <code>{fmt_usd_compact(c.spot_delta_4bar_usd)}</code> (<b>{best_z:+.1f}σ</b> | Alıcı %{c.spot_buy_ratio_4bar_pct:.1f} | {c.rvol:.1f}x Hacim)\n"
                f"   • 🗜️ <b>Sıkışma:</b> %{c.squeeze_energy_pct:.0f}{fr_str} | 🎯 <b>Kırılım:</b> <code>{format(c.breakout_trigger_price, p_fmt)}$</code>"
            )

    lines.append(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>👇 Coine dokunarak tam 4-periyot grafikli analizi açabilir veya ➕ ile izleme listenize ekleyebilirsiniz (YTD):</i>"
    )
    return "\n".join(lines)


def build_market_hunter_inline_keyboard(
    report: MarketHunterReport,
    only_unlisted: bool = False,
) -> Dict[str, Any]:
    """Builds interactive Telegram inline keyboard for the Top-80 Market Hunter."""
    tf_up = report.timeframe.upper()
    u_flag = "1" if only_unlisted else "0"
    picks = [c for c in report.top_picks if (not only_unlisted or not c.in_watchlist)]
    if not picks:
        picks = [c for c in report.all_ranked if (not only_unlisted or not c.in_watchlist)][:4]

    kb_rows: List[List[Dict[str, str]]] = []

    # Row(s) 1-2: Direct Analysis open buttons for discovered coins
    an_row: List[Dict[str, str]] = []
    for c in picks[:6]:
        short_s = c.symbol.replace("/USDT", "")
        an_row.append({"text": f"📊 {short_s} ({c.hunter_score:.0f})", "callback_data": f"an:{c.symbol}:4H"})
        if len(an_row) == 3:
            kb_rows.append(an_row)
            an_row = []
    if an_row:
        kb_rows.append(an_row)

    # Quick 1-Tap "+ Watchlist Add" row for newly discovered unlisted coins
    unlisted_picks = [c for c in picks[:6] if not c.in_watchlist]
    if unlisted_picks:
        add_row: List[Dict[str, str]] = []
        for c in unlisted_picks[:3]:
            short_s = c.symbol.replace("/USDT", "")
            add_row.append({"text": f"➕ {short_s} Ekle", "callback_data": f"wl_add:{c.symbol}:4H"})
        kb_rows.append(add_row)

    # Timeframe & Unlisted Filter Switcher
    kb_rows.append(
        [
            {
                "text": "✅ 1H Avcı" if tf_up == "1H" else "⏱️ 1H Avcı",
                "callback_data": f"hunter:1H:{u_flag}:0",
            },
            {
                "text": "✅ 4H Avcı" if tf_up == "4H" else "⏱️ 4H Avcı",
                "callback_data": f"hunter:4H:{u_flag}:0",
            },
            {
                "text": "📋 Tümünü Göster" if only_unlisted else "🆕 Sadece Yeni Keşifler",
                "callback_data": f"hunter:{tf_up}:{'0' if only_unlisted else '1'}:0",
            },
        ]
    )

    # Refresh & X Share row
    kb_rows.append(
        [
            {"text": "🔄 Şimdi Canlı Yenile", "callback_data": f"hunter:{tf_up}:{u_flag}:1"},
            {"text": "🐦 X'te Paylaş", "callback_data": f"x_hunter:{tf_up}"},
        ]
    )
    return {"inline_keyboard": kb_rows}
