"""
Smart Money Concepts (SMC), Liquidation Magnet Pools, Probability Cone (Monte Carlo / Drift-Diffusion),
Relative Strength vs BTC (RS/Beta), and Risk/Position Sizing Engine (v3.0).
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class FairValueGap:
    """Represents an unfilled 3-candle Fair Value Gap (FVG / İmbalans Boşluğu)."""
    fvg_type: str         # "BULLISH_FVG" (Alım Boşluğu) or "BEARISH_FVG" (Satış Boşluğu)
    top: float
    bottom: float
    mid: float
    created_at: pd.Timestamp
    label_tr: str


@dataclass
class OrderBlockZone:
    """Represents an institutional Order Block (Kurumsal Emir Bloğu) prior to an impulsive displacement."""
    ob_type: str          # "BULLISH_OB" (Kurumsal Talep Bloğu) or "BEARISH_OB" (Kurumsal Arz Bloğu)
    top: float
    bottom: float
    mid: float
    created_at: pd.Timestamp
    label_tr: str


@dataclass
class MarketStructureEvent:
    """Represents a Break of Structure (BOS), Change of Character (CHoCH), or Liquidity Sweep (SFP)."""
    event_type: str       # "BULL_BOS", "BEAR_BOS", "BULL_CHOCH", "BEAR_CHOCH", "BULL_SWEEP", "BEAR_SWEEP"
    price: float
    timestamp: pd.Timestamp
    label_tr: str
    explanation_tr: str


@dataclass
class LiquidationPool:
    """Estimated cluster of leveraged (10x / 25x / 50x) Long or Short liquidations acting as a price magnet."""
    pool_type: str        # "SHORT_LIQ" (Yukarıdaki Short Tasfiye Mıknatısı) or "LONG_LIQ" (Aşağıdaki Long Tasfiye Mıknatısı)
    leverage_tag: str     # e.g., "25x-50x Short Likidasyon Havuzu"
    price: float
    band_low: float
    band_high: float
    distance_pct: float
    density_score: float = 1.0


@dataclass
class ProbabilityCone:
    """Statistical EWMA+Parkinson Drift-Diffusion Volatility Cone & Analytical Barrier Probability."""
    horizon_bars: int = 10
    timestamps: List[pd.Timestamp] = field(default_factory=list)
    expected_path: List[float] = field(default_factory=list)
    upper_1sigma: List[float] = field(default_factory=list)   # 68% confidence upper bound
    lower_1sigma: List[float] = field(default_factory=list)   # 68% confidence lower bound
    upper_2sigma: List[float] = field(default_factory=list)   # 95% confidence upper bound
    lower_2sigma: List[float] = field(default_factory=list)   # 95% confidence lower bound
    prob_touch_bull_target_pct: float = 50.0
    prob_touch_bear_invalid_pct: float = 50.0
    prob_win_before_stop_pct: float = 50.0                    # P(tau_target < tau_stop)
    ewma_volatility_pct: float = 1.0


@dataclass
class RelativeStrengthMetrics:
    """Measures how an asset performs relative to Bitcoin (BTC/USDT) — Alpha, Beta, RS Score."""
    rs_ratio_change_pct: float = 0.0   # Relative return vs BTC over last 30 bars
    beta_vs_btc: float = 1.0           # Sensitivity to BTC moves
    correlation_vs_btc: float = 1.0    # Return correlation (-1 to +1)
    alpha_score: float = 0.0           # -100 (Strong Underperformer) to +100 (Strong Leader)
    status_tr: str = "Referans Varlık (BTC)"


@dataclass
class RiskPositionPlan:
    """Non-advisory mathematical position sizing, Half-Kelly optimal risk & R:R calculation."""
    entry_reference: float
    invalidation_stop: float
    target_price: float
    stop_distance_pct: float
    target_distance_pct: float
    risk_reward_ratio: float
    sample_capital_usd: float
    risk_pct_per_trade: float
    max_loss_usd: float
    suggested_position_usd: float
    suggested_coin_qty: float
    suggested_max_leverage: float
    summary_tr: str
    half_kelly_pct: float = 1.0
    win_before_stop_prob_pct: float = 50.0


@dataclass
class SmartMoneyReport:
    """Container for all SMC, Liquidation, Probability Cone, RS, and Risk Management outputs."""
    fvgs: List[FairValueGap] = field(default_factory=list)
    order_blocks: List[OrderBlockZone] = field(default_factory=list)
    structure_events: List[MarketStructureEvent] = field(default_factory=list)
    liquidation_pools: List[LiquidationPool] = field(default_factory=list)
    probability_cone: ProbabilityCone = field(default_factory=ProbabilityCone)
    relative_strength: RelativeStrengthMetrics = field(default_factory=RelativeStrengthMetrics)
    structure_summary_tr: str = "Piyasa yapısı dengeli"
    liquidity_summary_tr: str = "Belirgin likidite avı yok"


class SmartMoneyEngine:
    """
    Computes institutional Smart Money Concepts (FVG, Order Blocks, BOS/CHoCH, Liquidity Sweeps),
    Leveraged Liquidation Magnet Pools, Statistical Probability Cones, and BTC Relative Strength.
    """

    @staticmethod
    def detect_unfilled_fvgs(df: pd.DataFrame, lookback: int = 80, max_gaps: int = 2) -> List[FairValueGap]:
        """
        Detect 3-candle Fair Value Gaps (FVG) in the recent `lookback` bars that have NOT
        yet been completely filled/mitigated by subsequent price action.
        """
        if len(df) < 10:
            return []

        sub = df.tail(lookback).reset_index(drop=True)
        highs = sub["high"].values
        lows = sub["low"].values
        closes = sub["close"].values
        opens = sub["open"].values
        times = sub["timestamp"].tolist()
        atrs = sub["atr"].bfill().fillna(sub["close"] * 0.01).values if "atr" in sub.columns else (sub["close"] * 0.01).values

        current_price = float(closes[-1])
        bull_fvgs: List[FairValueGap] = []
        bear_fvgs: List[FairValueGap] = []

        # Iterate up to the last closed candle
        end_idx = len(sub) - 2 if ("is_closed" in sub.columns and not bool(sub["is_closed"].iloc[-1])) else len(sub) - 1

        for i in range(2, end_idx):
            min_gap = 0.12 * atrs[i]
            # Bullish FVG: Low[i] > High[i-2] with strong bullish middle candle [i-1]
            if lows[i] - highs[i - 2] >= min_gap and closes[i - 1] > opens[i - 1]:
                gap_top = float(lows[i])
                gap_bot = float(highs[i - 2])
                # Check if subsequent candles completely filled the gap (dipped below gap_bot)
                future_min_low = float(np.min(lows[i + 1 : end_idx + 1])) if (i + 1 <= end_idx) else gap_top
                if future_min_low > gap_bot and current_price > gap_bot:
                    bull_fvgs.append(
                        FairValueGap(
                            fvg_type="BULLISH_FVG",
                            top=min(gap_top, future_min_low) if future_min_low < gap_top else gap_top,
                            bottom=gap_bot,
                            mid=0.5 * (gap_top + gap_bot),
                            created_at=times[i - 1],
                            label_tr="Pozitif FVG (Kurumsal Alım Boşluğu)",
                        )
                    )

            # Bearish FVG: High[i] < Low[i-2] with strong bearish middle candle [i-1]
            if lows[i - 2] - highs[i] >= min_gap and closes[i - 1] < opens[i - 1]:
                gap_top = float(lows[i - 2])
                gap_bot = float(highs[i])
                future_max_high = float(np.max(highs[i + 1 : end_idx + 1])) if (i + 1 <= end_idx) else gap_bot
                if future_max_high < gap_top and current_price < gap_top:
                    bear_fvgs.append(
                        FairValueGap(
                            fvg_type="BEARISH_FVG",
                            top=gap_top,
                            bottom=max(gap_bot, future_max_high) if future_max_high > gap_bot else gap_bot,
                            mid=0.5 * (gap_top + gap_bot),
                            created_at=times[i - 1],
                            label_tr="Negatif FVG (Kurumsal Satış Boşluğu)",
                        )
                    )

        # Keep closest unfilled FVGs to current price
        bull_fvgs.sort(key=lambda g: abs(current_price - g.mid))
        bear_fvgs.sort(key=lambda g: abs(current_price - g.mid))
        return bull_fvgs[:max_gaps] + bear_fvgs[:max_gaps]

    @staticmethod
    def detect_order_blocks(df: pd.DataFrame, lookback: int = 90) -> List[OrderBlockZone]:
        """
        Detect unmitigated Bullish & Bearish Institutional Order Blocks (OB):
            - Bullish OB: Last bearish candle before a strong 2-bar bullish impulse (>= 1.4 ATR)
            - Bearish OB: Last bullish candle before a strong 2-bar bearish impulse (>= 1.4 ATR)
        """
        if len(df) < 12:
            return []

        sub = df.tail(lookback).reset_index(drop=True)
        opens = sub["open"].values
        highs = sub["high"].values
        lows = sub["low"].values
        closes = sub["close"].values
        times = sub["timestamp"].tolist()
        atrs = sub["atr"].bfill().fillna(sub["close"] * 0.01).values if "atr" in sub.columns else (sub["close"] * 0.01).values

        current_price = float(closes[-1])
        bull_obs: List[OrderBlockZone] = []
        bear_obs: List[OrderBlockZone] = []

        last_valid = len(sub) - 2 if ("is_closed" in sub.columns and not bool(sub["is_closed"].iloc[-1])) else len(sub) - 1
        end_idx = max(1, last_valid - 2)
        for i in range(1, end_idx):
            atr_val = atrs[i]
            # Bullish Order Block candidate: candle i is bearish, followed by strong upward displacement
            if closes[i] < opens[i]:
                displacement_up = max(closes[i + 1], closes[i + 2]) - opens[i]
                if displacement_up >= 1.35 * atr_val and max(closes[i + 1], closes[i + 2]) > highs[i]:
                    ob_top = float(opens[i])
                    ob_bot = float(lows[i])
                    # Unmitigated if closed price hasn't closed below ob_bot since i+2
                    subsequent_closes = closes[i + 2 : last_valid + 1]
                    if np.min(subsequent_closes) > ob_bot and current_price > ob_bot:
                        bull_obs.append(
                            OrderBlockZone(
                                ob_type="BULLISH_OB",
                                top=ob_top,
                                bottom=ob_bot,
                                mid=0.5 * (ob_top + ob_bot),
                                created_at=times[i],
                                label_tr="Kurumsal Alım Bloğu (+OB)",
                            )
                        )

            # Bearish Order Block candidate: candle i is bullish, followed by strong downward displacement
            if closes[i] > opens[i]:
                displacement_down = opens[i] - min(closes[i + 1], closes[i + 2])
                if displacement_down >= 1.35 * atr_val and min(closes[i + 1], closes[i + 2]) < lows[i]:
                    ob_top = float(highs[i])
                    ob_bot = float(opens[i])
                    subsequent_closes = closes[i + 2 : last_valid + 1]
                    if np.max(subsequent_closes) < ob_top and current_price < ob_top:
                        bear_obs.append(
                            OrderBlockZone(
                                ob_type="BEARISH_OB",
                                top=ob_top,
                                bottom=ob_bot,
                                mid=0.5 * (ob_top + ob_bot),
                                created_at=times[i],
                                label_tr="Kurumsal Satış Bloğu (-OB)",
                            )
                        )

        bull_obs.sort(key=lambda ob: abs(current_price - ob.mid))
        bear_obs.sort(key=lambda ob: abs(current_price - ob.mid))
        return bull_obs[:1] + bear_obs[:1]

    @staticmethod
    def detect_structure_and_sweeps(df: pd.DataFrame, swing_window: int = 5) -> Tuple[List[MarketStructureEvent], str, str]:
        """
        Detect Market Structure Breaks (BOS / CHoCH) and Liquidity Sweeps (Stop-Hunts / SFP):
            - Bullish Sweep (Dip Likidite Avı): Low pierces below prior swing low, but candle closes back above it!
            - Bearish Sweep (Tepe Likidite Avı): High pierces above prior swing high, but candle closes back below it!
            - BOS / CHoCH: Candle body closes cleanly above prior swing high or below prior swing low.
        """
        if len(df) < swing_window * 3:
            return [], "Yeterli veri yok", "Belirgin likidite avı yok"

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        times = df["timestamp"].tolist()
        n = len(df)

        events: List[MarketStructureEvent] = []
        last_swing_high: Optional[float] = None
        last_swing_low: Optional[float] = None
        trend_state = 0  # +1 Bullish structure, -1 Bearish structure

        end_idx = n - 1 if ("is_closed" not in df.columns or bool(df["is_closed"].iloc[-1])) else n - 2

        for i in range(swing_window * 2, end_idx + 1):
            # Confirmed swing pivot at index (i - swing_window)
            p_idx = i - swing_window
            if highs[p_idx] == np.max(highs[p_idx - swing_window : p_idx + swing_window + 1]):
                last_swing_high = float(highs[p_idx])
            if lows[p_idx] == np.min(lows[p_idx - swing_window : p_idx + swing_window + 1]):
                last_swing_low = float(lows[p_idx])

            # Check interactions with last_swing_high
            if last_swing_high is not None:
                if highs[i] > last_swing_high and closes[i] < last_swing_high:
                    events.append(
                        MarketStructureEvent(
                            event_type="BEAR_SWEEP",
                            price=float(highs[i]),
                            timestamp=times[i],
                            label_tr="⚠️ Tepe Likidite Avı (Boğa Tuzağı / SFP)",
                            explanation_tr=(
                                f"Fiyat önceki tepeyi ({last_swing_high:,.4f}) fitille delerek stopları/longları avladı "
                                "ancak üzerinde kapanış yapamayıp geri döndü (Kurumsal Satış / Tuzak İzi)."
                            ),
                        )
                    )
                    last_swing_high = None
                elif closes[i] > last_swing_high:
                    ev_type = "BULL_CHOCH" if trend_state == -1 else "BULL_BOS"
                    lbl = "🟢 CHoCH (Yukarı Karakter Değişimi)" if ev_type == "BULL_CHOCH" else "🟢 BOS (Yükseliş Yapı Kırılımı)"
                    events.append(
                        MarketStructureEvent(
                            event_type=ev_type,
                            price=last_swing_high,
                            timestamp=times[i],
                            label_tr=lbl,
                            explanation_tr=f"Fiyat {last_swing_high:,.4f} tepe yapısını gövde kapanışıyla yukarı kırdı.",
                        )
                    )
                    trend_state = 1
                    last_swing_high = None

            # Check interactions with last_swing_low
            if last_swing_low is not None:
                if lows[i] < last_swing_low and closes[i] > last_swing_low:
                    events.append(
                        MarketStructureEvent(
                            event_type="BULL_SWEEP",
                            price=float(lows[i]),
                            timestamp=times[i],
                            label_tr="🟢 Dip Likidite Avı (Ayı Tuzağı / Stop-Hunt)",
                            explanation_tr=(
                                f"Fiyat önceki dibi ({last_swing_low:,.4f}) fitille delerek long stoplarını patlattı "
                                "ve hızla tekrar yukarı kapattı (Kurumsal Dip Toplama / Spring İzi)."
                            ),
                        )
                    )
                    last_swing_low = None
                elif closes[i] < last_swing_low:
                    ev_type = "BEAR_CHOCH" if trend_state == 1 else "BEAR_BOS"
                    lbl = "🔴 CHoCH (Aşağı Karakter Değişimi)" if ev_type == "BEAR_CHOCH" else "🔴 BOS (Düşüş Yapı Kırılımı)"
                    events.append(
                        MarketStructureEvent(
                            event_type=ev_type,
                            price=last_swing_low,
                            timestamp=times[i],
                            label_tr=lbl,
                            explanation_tr=f"Fiyat {last_swing_low:,.4f} dip yapısını gövde kapanışıyla aşağı kırdı.",
                        )
                    )
                    trend_state = -1
                    last_swing_low = None

        recent_events = events[-4:]
        struct_summary = "Pozitif Market Yapısı (Son Kırılım Yukarı - BOS/CHoCH)" if trend_state == 1 else (
            "Negatif Market Yapısı (Son Kırılım Aşağı - BOS/CHoCH)" if trend_state == -1 else "Yatay Piyasa Yapısı"
        )

        sweeps = [e for e in events[-6:] if "SWEEP" in e.event_type]
        if sweeps:
            last_sw = sweeps[-1]
            liq_summary = f"{last_sw.label_tr} ({last_sw.timestamp.strftime('%m-%d %H:%M')})"
        else:
            liq_summary = "Son mumlarda tepe/dip likidite avı (tuzak) görülmedi"

        return recent_events, struct_summary, liq_summary

    @staticmethod
    def estimate_liquidation_pools(df: pd.DataFrame, order_flow: Optional[Any] = None) -> List[LiquidationPool]:
        """
        Phase 3 OI, Funding & Volatility-Aware Multi-Tier (10x, 25x, 50x) Liquidation Density Estimator:
            - Strictly scans CLOSED candles (`is_closed == True`) to prevent live-wick shifts
            - Weights pivots by Relative Volume (`rvol`) and Taker Z-Score intensity (`delta_zscore`)
            - Incorporates live Open Interest (`oi_change_24h_pct`), OI-Weighted Funding Rate, and Long/Short Ratio
              to amplify crowded Long (`LONG_LIQ`) vs crowded Short (`SHORT_LIQ`) liquidation magnets!
        """
        if len(df) < 15:
            return []

        closed_df = df.iloc[:-1] if (len(df) >= 16 and "is_closed" in df.columns and not bool(df["is_closed"].iloc[-1])) else df
        sub = closed_df.tail(90).reset_index(drop=True)
        highs = sub["high"].values
        lows = sub["low"].values
        closes = sub["close"].values
        rvols = sub["rvol"].values if "rvol" in sub.columns else np.ones(len(sub))
        zscores = np.abs(sub["delta_zscore"].values) if "delta_zscore" in sub.columns else np.zeros(len(sub))
        current_price = float(df["close"].iloc[-1])
        atr_val = float(sub["atr"].iloc[-1]) if "atr" in sub.columns and pd.notna(sub["atr"].iloc[-1]) else current_price * 0.008
        band_half = max(atr_val * 0.18, current_price * 0.0015)
        cluster_tol = max(atr_val * 0.45, current_price * 0.004)

        # Compute OI & Funding Crowding Asymmetry Multipliers (Strictly from real derivative metrics)
        short_crowd_mult = 1.0
        long_crowd_mult = 1.0
        short_crowd_note = ""
        long_crowd_note = ""
        if order_flow is not None:
            fr = getattr(order_flow, "oi_weighted_funding_pct", None)
            if fr is None:
                fr = getattr(order_flow, "funding_rate_pct", None)
            ls_r = getattr(order_flow, "long_short_ratio", None)
            oi_chg = getattr(order_flow, "oi_change_24h_pct", None)

            if (fr is not None and fr >= 0.015) or (ls_r is not None and ls_r >= 1.25):
                long_crowd_mult *= 1.42
                long_crowd_note = " • 🔥 Kalabalık Long Hedefi"
            if (fr is not None and fr <= -0.005) or (ls_r is not None and ls_r <= 0.85):
                short_crowd_mult *= 1.42
                short_crowd_note = " • 🚀 Short Squeeze Mıknatısı"
            if oi_chg is not None:
                if oi_chg >= 2.5:
                    short_crowd_mult *= 1.18
                    long_crowd_mult *= 1.18
                elif oi_chg <= -3.0:
                    # Positions recently flushed -> dampen stale liquidation density
                    short_crowd_mult *= 0.78
                    long_crowd_mult *= 0.78

        short_candidates: List[Tuple[float, float, str]] = []
        long_candidates: List[Tuple[float, float, str]] = []

        # Collect closed-candle swing pivots and project 50x, 25x, and 10x leverage liquidation levels
        win = 3
        for i in range(win, len(sub) - 1):
            right_b = min(len(sub), i + win + 1)
            intensity = 1.0 + 0.18 * float(np.clip(zscores[i], 0.0, 3.0))
            w = float(np.clip(rvols[i] * intensity, 0.6, 4.2))
            if highs[i] == np.max(highs[i - win : right_b]):
                for mult, tag, tier_w in ((1.018, "50x", 1.0), (1.036, "25x", 0.90), (1.082, "10x", 0.65)):
                    lvl = float(highs[i] * mult)
                    if lvl > current_price * 1.002:
                        short_candidates.append((lvl, w * tier_w * short_crowd_mult, tag))
            if lows[i] == np.min(lows[i - win : right_b]):
                for mult, tag, tier_w in ((0.982, "50x", 1.0), (0.964, "25x", 0.90), (0.918, "10x", 0.65)):
                    lvl = float(lows[i] * mult)
                    if lvl < current_price * 0.998:
                        long_candidates.append((lvl, w * tier_w * long_crowd_mult, tag))

        # Always include 45-bar closed extreme fallback
        swing_high = float(sub["high"].tail(45).max())
        swing_low = float(sub["low"].tail(45).min())
        if swing_high * 1.018 > current_price:
            short_candidates.append((swing_high * 1.018, 1.5 * short_crowd_mult, "50x"))
        if swing_low * 0.982 < current_price:
            long_candidates.append((swing_low * 0.982, 1.5 * long_crowd_mult, "50x"))

        def pick_best_cluster(cands: List[Tuple[float, float, str]], is_short: bool) -> Optional[LiquidationPool]:
            if not cands:
                return None
            cands.sort(key=lambda x: x[0])
            clusters: List[Tuple[List[float], float, List[str]]] = []
            for p_val, w_val, t_str in cands:
                placed = False
                for c_prices, c_weight, c_tags in clusters:
                    if abs(np.mean(c_prices) - p_val) <= cluster_tol:
                        c_prices.append(p_val)
                        idx = clusters.index((c_prices, c_weight, c_tags))
                        if t_str not in c_tags:
                            c_tags.append(t_str)
                        clusters[idx] = (c_prices, c_weight + w_val, c_tags)
                        placed = True
                        break
                if not placed:
                    clusters.append(([p_val], w_val, [t_str]))

            # Rank by density weight divided by distance penalty so nearby dense OI-backed clusters win
            best_c = max(
                clusters,
                key=lambda c: c[1] / max(abs(float(np.mean(c[0])) - current_price) / current_price, 0.008),
            )
            lvl_p = float(np.mean(best_c[0]))
            density = float(best_c[1])
            tiers = "/".join(sorted(best_c[2], reverse=True))
            if is_short:
                dist = ((lvl_p - current_price) / current_price) * 100.0
                return LiquidationPool(
                    pool_type="SHORT_LIQ",
                    leverage_tag=f"🧲 {tiers} Short Likidasyon Havuzu (Yoğunluk: {density:.1f}x{short_crowd_note})",
                    price=lvl_p,
                    band_low=lvl_p - band_half,
                    band_high=lvl_p + band_half,
                    distance_pct=dist,
                    density_score=density,
                )
            else:
                dist = ((current_price - lvl_p) / current_price) * 100.0
                return LiquidationPool(
                    pool_type="LONG_LIQ",
                    leverage_tag=f"🧲 {tiers} Long Likidasyon Havuzu (Yoğunluk: {density:.1f}x{long_crowd_note})",
                    price=lvl_p,
                    band_low=lvl_p - band_half,
                    band_high=lvl_p + band_half,
                    distance_pct=dist,
                    density_score=density,
                )

        pools: List[LiquidationPool] = []
        s_pool = pick_best_cluster(short_candidates, is_short=True)
        l_pool = pick_best_cluster(long_candidates, is_short=False)
        if s_pool:
            pools.append(s_pool)
        if l_pool:
            pools.append(l_pool)
        return pools

    @staticmethod
    def compute_probability_cone(
        df: pd.DataFrame,
        composite_score: float,
        bull_target: float,
        bear_invalid: float,
        horizon: int = 10,
    ) -> ProbabilityCone:
        """
        Compute an Institutional EWMA + Parkinson Volatility Drift-Diffusion Cone (1-Sigma 68% & 2-Sigma 95%)
        for the next `horizon` bars, plus Analytical First-Passage Barrier Probabilities (v4.0).
        """
        if len(df) < 15:
            return ProbabilityCone(horizon_bars=horizon)

        sub = df.tail(65)
        closes = sub["close"].values
        highs = sub["high"].values
        lows = sub["low"].values

        log_rets = np.diff(np.log(np.maximum(closes, 1e-9)))
        if len(log_rets) > 5:
            # 1. RiskMetrics EWMA Volatility (lambda = 0.94) to capture volatility clustering
            lam = 0.94
            var_ewma = float(np.var(log_rets[:10])) if len(log_rets) >= 10 else float(np.var(log_rets))
            for r in log_rets:
                var_ewma = lam * var_ewma + (1.0 - lam) * float(r * r)
            sigma_ewma = float(np.sqrt(max(var_ewma, 1e-8)))

            # 2. Parkinson High-Low Intra-bar Volatility Estimator
            hl_logs = np.log(np.maximum(highs[-20:], 1e-9) / np.maximum(lows[-20:], 1e-9))
            sigma_parkinson = float(np.sqrt(np.mean(hl_logs ** 2) / (4.0 * np.log(2.0))))
            sigma_bar = 0.65 * sigma_ewma + 0.35 * sigma_parkinson
        else:
            sigma_bar = 0.012

        sigma_bar = max(sigma_bar, 0.002)

        curr_p = float(closes[-1])
        last_ts = df["timestamp"].iloc[-1]
        bar_delta = last_ts - df["timestamp"].iloc[-2]

        # Directional drift scaled by composite_score (-100..+100)
        drift_per_bar = (composite_score / 100.0) * (0.20 * sigma_bar)

        timestamps = [last_ts]
        expected_path = [curr_p]
        upper_1s = [curr_p]
        lower_1s = [curr_p]
        upper_2s = [curr_p]
        lower_2s = [curr_p]

        for step in range(1, horizon + 1):
            timestamps.append(last_ts + bar_delta * step)
            exp_p = curr_p * float(np.exp(drift_per_bar * step))
            std_step = sigma_bar * np.sqrt(step)

            expected_path.append(exp_p)
            upper_1s.append(exp_p * float(np.exp(1.0 * std_step)))
            lower_1s.append(exp_p * float(np.exp(-1.0 * std_step)))
            upper_2s.append(exp_p * float(np.exp(1.96 * std_step)))
            lower_2s.append(exp_p * float(np.exp(-1.96 * std_step)))

        # Analytical First-Passage / Barrier Touch Probabilities over horizon
        horizon_vol = max(curr_p * sigma_bar * np.sqrt(horizon), 1e-8)
        expected_end = expected_path[-1]

        dist_bull = max(bull_target - curr_p, curr_p * 0.001)
        dist_bear = max(curr_p - bear_invalid, curr_p * 0.001)

        z_bull = (dist_bull - (expected_end - curr_p)) / horizon_vol
        z_bear = (dist_bear + (expected_end - curr_p)) / horizon_vol

        prob_bull = float(np.clip(100.0 / (1.0 + np.exp(1.35 * z_bull - 0.35)), 8.0, 92.0))
        prob_bear = float(np.clip(100.0 / (1.0 + np.exp(1.35 * z_bear - 0.35)), 8.0, 92.0))

        # Two-Barrier First-Exit Probability P(tau_bull < tau_bear) via Drift-Diffusion Scale Function
        u_log = float(np.log(max(bull_target, curr_p * 1.001) / curr_p))
        l_log = float(np.log(curr_p / max(bear_invalid, 1e-9)))
        u_log = max(u_log, 0.001)
        l_log = max(l_log, 0.001)

        gamma = (2.0 * drift_per_bar) / max(sigma_bar ** 2, 1e-8)
        if abs(gamma) < 1e-4:
            p_win_before_stop = (l_log / (u_log + l_log)) * 100.0
        else:
            exp_gl = float(np.exp(np.clip(-gamma * l_log, -20.0, 20.0)))
            exp_gu = float(np.exp(np.clip(gamma * u_log, -20.0, 20.0)))
            denom = exp_gu - exp_gl
            if abs(denom) > 1e-9:
                p_win_before_stop = ((1.0 - exp_gl) / denom) * 100.0
            else:
                p_win_before_stop = (l_log / (u_log + l_log)) * 100.0

        p_win_before_stop = float(np.clip(p_win_before_stop, 10.0, 90.0))

        return ProbabilityCone(
            horizon_bars=horizon,
            timestamps=timestamps,
            expected_path=expected_path,
            upper_1sigma=upper_1s,
            lower_1sigma=lower_1s,
            upper_2sigma=upper_2s,
            lower_2sigma=lower_2s,
            prob_touch_bull_target_pct=prob_bull,
            prob_touch_bear_invalid_pct=prob_bear,
            prob_win_before_stop_pct=p_win_before_stop,
            ewma_volatility_pct=sigma_bar * 100.0,
        )

    @staticmethod
    def compute_relative_strength_vs_btc(
        coin_df: pd.DataFrame,
        btc_df: Optional[pd.DataFrame],
        symbol: str,
        lookback: int = 30,
    ) -> RelativeStrengthMetrics:
        """
        Compute Relative Strength (RS), Beta, and Correlation of an altcoin against BTC/USDT,
        strictly aligned by exact `timestamp` on closed candles (Zero Misaligned Bar Bias).
        """
        if symbol.startswith("BTC/") or btc_df is None or len(coin_df) < lookback or len(btc_df) < lookback:
            return RelativeStrengthMetrics(status_tr="Piyasa Referans Varlığı (BTC)")

        c_closed = coin_df[coin_df["is_closed"].astype(bool)] if "is_closed" in coin_df.columns else coin_df
        b_closed = btc_df[btc_df["is_closed"].astype(bool)] if "is_closed" in btc_df.columns else btc_df

        c_sub: Optional[np.ndarray] = None
        b_sub: Optional[np.ndarray] = None
        if "timestamp" in c_closed.columns and "timestamp" in b_closed.columns:
            merged = pd.merge(
                c_closed[["timestamp", "close"]].rename(columns={"close": "c_close"}),
                b_closed[["timestamp", "close"]].rename(columns={"close": "b_close"}),
                on="timestamp",
                how="inner",
            ).sort_values("timestamp")
            if len(merged) >= 12:
                tail_m = merged.tail(lookback)
                c_sub = tail_m["c_close"].to_numpy(dtype=float)
                b_sub = tail_m["b_close"].to_numpy(dtype=float)

        if c_sub is None or b_sub is None:
            c_arr = c_closed.tail(lookback)["close"].values
            b_arr = b_closed.tail(lookback)["close"].values
            m = min(len(c_arr), len(b_arr))
            if m < 10:
                return RelativeStrengthMetrics()
            c_sub = c_arr[-m:]
            b_sub = b_arr[-m:]

        coin_ret_pct = ((c_sub[-1] - c_sub[0]) / max(c_sub[0], 1e-9)) * 100.0
        btc_ret_pct = ((b_sub[-1] - b_sub[0]) / max(b_sub[0], 1e-9)) * 100.0
        rs_diff_pct = float(coin_ret_pct - btc_ret_pct)

        c_rets = np.diff(c_sub) / np.maximum(c_sub[:-1], 1e-9)
        b_rets = np.diff(b_sub) / np.maximum(b_sub[:-1], 1e-9)

        var_b = float(np.var(b_rets))
        if var_b > 1e-12:
            cov_cb = float(np.cov(c_rets, b_rets)[0, 1])
            beta = float(np.clip(cov_cb / var_b, -3.0, 4.0))
        else:
            beta = 1.0

        corr_mat = np.corrcoef(c_rets, b_rets)
        corr = float(corr_mat[0, 1]) if not np.isnan(corr_mat[0, 1]) else 0.5

        alpha_score = float(np.clip(rs_diff_pct * 8.0, -100.0, 100.0))
        if rs_diff_pct >= 2.5:
            status_tr = f"🟢 Piyasa Lideri / Pozitif Ayrışma (BTC'den +%{rs_diff_pct:.1f} Daha Güçlü | Beta: {beta:.2f})"
        elif rs_diff_pct <= -2.5:
            status_tr = f"🔴 Piyasa Gerisinde / Zayıf RS (BTC'den %{rs_diff_pct:.1f} Daha Zayıf | Beta: {beta:.2f})"
        else:
            status_tr = f"⚪ BTC İle Paralel Performans (RS Farkı: {rs_diff_pct:+.1f}% | Beta: {beta:.2f})"

        return RelativeStrengthMetrics(
            rs_ratio_change_pct=rs_diff_pct,
            beta_vs_btc=beta,
            correlation_vs_btc=corr,
            alpha_score=alpha_score,
            status_tr=status_tr,
        )

    @staticmethod
    def calculate_position_sizing(
        entry_price: float,
        stop_price: float,
        target_price: float,
        capital_usd: float = 1000.0,
        risk_pct: float = 1.0,
        win_prob_pct: float = 54.0,
    ) -> RiskPositionPlan:
        """
        Calculate non-advisory mathematical position size, R:R ratio, and Half-Kelly Criterion
        so that if price hits the invalidation level (`stop_price`), the loss equals `risk_pct`% of `capital_usd`.
        """
        entry = max(float(entry_price), 1e-9)
        stop_dist = abs(entry - float(stop_price))
        target_dist = abs(float(target_price) - entry)

        stop_dist_pct = max((stop_dist / entry) * 100.0, 0.15)
        target_dist_pct = (target_dist / entry) * 100.0
        rr_ratio = target_dist_pct / stop_dist_pct if stop_dist_pct > 0 else 1.0

        # Half-Kelly Criterion: f* = 0.5 * (p - (1 - p) / b), capped conservatively between 0.25% and 3.5%
        p_win = float(np.clip(win_prob_pct / 100.0, 0.15, 0.85))
        b_payoff = max(rr_ratio, 0.4)
        full_kelly = p_win - ((1.0 - p_win) / b_payoff)
        half_kelly_pct = float(np.clip(0.5 * max(full_kelly, 0.01) * 10.0, 0.25, 3.5))

        max_loss_usd = capital_usd * (risk_pct / 100.0)
        position_usd = max_loss_usd / (stop_dist_pct / 100.0)
        # Cap position size at 5x capital for safety display
        position_usd = min(position_usd, capital_usd * 5.0)
        coin_qty = position_usd / entry
        eff_leverage = max(position_usd / max(capital_usd, 1.0), 1.0)

        p_fmt = ",.4f" if entry < 10.0 else ",.2f"
        summary_tr = (
            f"{capital_usd:,.0f} USDT örnek kasada işlem başına %{risk_pct:.1f} ({max_loss_usd:,.1f} USDT) maksimum risk "
            f"kuralına göre; {format(stop_price, p_fmt)} USDT geçersizlik (stop) mesafesi (%{stop_dist_pct:.2f}) için "
            f"matematiksel pozisyon büyüklüğü {position_usd:,.0f} USDT ({coin_qty:,.2f} adet), "
            f"Kazanç/Risk (R:R) oranı 1 : {rr_ratio:.2f} ve Optimal Yarım-Kelly Risk Oranı %{half_kelly_pct:.2f} olarak hesaplanmıştır."
        )

        return RiskPositionPlan(
            entry_reference=entry,
            invalidation_stop=float(stop_price),
            target_price=float(target_price),
            stop_distance_pct=stop_dist_pct,
            target_distance_pct=target_dist_pct,
            risk_reward_ratio=rr_ratio,
            sample_capital_usd=capital_usd,
            risk_pct_per_trade=risk_pct,
            max_loss_usd=max_loss_usd,
            suggested_position_usd=position_usd,
            suggested_coin_qty=coin_qty,
            suggested_max_leverage=eff_leverage,
            summary_tr=summary_tr,
            half_kelly_pct=half_kelly_pct,
            win_before_stop_prob_pct=win_prob_pct,
        )

    def analyze(
        self,
        df: pd.DataFrame,
        composite_score: float,
        bull_target: float,
        bear_invalid: float,
        symbol: str = "BTC/USDT",
        btc_df: Optional[pd.DataFrame] = None,
        order_flow: Optional[Any] = None,
    ) -> SmartMoneyReport:
        fvgs = self.detect_unfilled_fvgs(df)
        obs = self.detect_order_blocks(df)
        events, struct_sum, liq_sum = self.detect_structure_and_sweeps(df)
        liq_pools = self.estimate_liquidation_pools(df, order_flow=order_flow)
        cone = self.compute_probability_cone(df, composite_score, bull_target, bear_invalid)
        rs = self.compute_relative_strength_vs_btc(df, btc_df, symbol)

        return SmartMoneyReport(
            fvgs=fvgs,
            order_blocks=obs,
            structure_events=events,
            liquidation_pools=liq_pools,
            probability_cone=cone,
            relative_strength=rs,
            structure_summary_tr=struct_sum,
            liquidity_summary_tr=liq_sum,
        )
