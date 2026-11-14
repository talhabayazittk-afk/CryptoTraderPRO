"""
Institutional Multi-Factor Confluence, Money Flow, Volume Profile & Backtest Validation Engine (v2.0).
Features:
    1. Closed-Candle Guarantee (`iloc[-2]` when `is_closed == False`) so unclosed live candles never repaint signals
    2. Dynamic Regime Weighting based on ADX Trend Strength (Trend Market vs Range Market)
    3. Higher-Timeframe (HTF) & BTC Macro Regime Alignment Filter
    4. Volume Profile (POC / VAH / VAL) + Golden Ratio Fibonacci (0.618 / 0.5) Support & Resistance Engine
    5. Historical Signal Backtest Validator (Win-Rate %, Avg MFE/MAE over next 5 bars)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import IndicatorConfig
from .data_fetcher import OrderFlowIntel
from .indicators import TechnicalIndicators
from .patterns import CandlestickPatternDetector
from .smart_money import RiskPositionPlan, SmartMoneyEngine, SmartMoneyReport


@dataclass
class SupportResistanceLevel:
    """Represents a clustered Support (Talep), Resistance (Arz), or Volume Profile POC zone."""
    price: float
    band_low: float
    band_high: float
    level_type: str  # "DESTEK" or "DİRENÇ"
    touches: int
    strength_label: str
    is_strong: bool = False
    strength_score: float = 40.0
    tier_tr: str = "🟢 Sıradan Destek"  # "🛡️ Güçlü Destek", "🟢 Sıradan Destek", "🧱 Güçlü Direnç", "🔴 Sıradan Direnç"
    confluence_tags: List[str] = field(default_factory=list)
    htf_confirmed: bool = False
    htf_tag_tr: str = ""
    reaction_count: int = 0
    test_count: int = 0
    reaction_rate_pct: float = 0.0
    avg_bounce_pct: float = 0.0
    stats_summary_tr: str = ""


@dataclass
class DynamicTrendlineReport:
    """Represents automatically fitted Ascending Support & Descending Resistance Trendlines on closed candles."""
    has_support_line: bool = False
    sup_x0: Optional[pd.Timestamp] = None
    sup_y0: float = 0.0
    sup_x1: Optional[pd.Timestamp] = None
    sup_y1: float = 0.0
    sup_current_price: float = 0.0
    has_resistance_line: bool = False
    res_x0: Optional[pd.Timestamp] = None
    res_y0: float = 0.0
    res_x1: Optional[pd.Timestamp] = None
    res_y1: float = 0.0
    res_current_price: float = 0.0
    breakout_status: str = "NONE"  # "BULL_BREAKOUT", "BEAR_BREAKDOWN", "CONVERGING_SQUEEZE", "NONE"
    summary_tr: str = "Aktif Dinamik Trend Kırılımı Yok"


@dataclass
class DivergenceSignal:
    """Represents a mathematically detected RSI Bullish or Bearish Divergence."""
    idx_start: int
    idx_end: int
    time_start: pd.Timestamp
    time_end: pd.Timestamp
    price_start: float
    price_end: float
    rsi_start: float
    rsi_end: float
    div_type: str       # "BULLISH_DIV" or "BEARISH_DIV"
    label_tr: str
    explanation_tr: str


@dataclass
class SignalBacktestStats:
    """Path-dependent, fee-adjusted historical validation metrics of signals (v5.0)."""
    total_signals: int = 0
    bullish_count: int = 0
    bearish_count: int = 0
    win_rate_pct: float = 0.0
    tp1_hit_rate_pct: float = 0.0
    bullish_win_rate_pct: float = 0.0
    bearish_win_rate_pct: float = 0.0
    avg_favorable_move_pct: float = 0.0
    avg_adverse_move_pct: float = 0.0
    profit_factor: float = 1.0
    expectancy_r: float = 0.0
    max_drawdown_r: float = 0.0
    confluence_win_rate_pct: float = 0.0
    horizon_bars: int = 5
    equity_curve_r: List[float] = field(default_factory=list)
    equity_timestamps: List[str] = field(default_factory=list)
    summary_tr: str = "Yeterli geçmiş sinyal verisi yok"


@dataclass
class FuturesSetupReport:
    """
    Dedicated Perpetual Futures (Vadeli İşlemler) Setup, Confidence & Risk Gate Engine (v8.0).
    Acts as a strict Futures Radar:
      - If technical structure, S/R room-to-run, R:R, and futures microstructure (OI, Funding, Taker CVD,
        Liquidation Magnets, SMC OB/Sweep) are aligned -> recommends LONG or SHORT with exact Entry, TP1/TP2/TP3,
        Stop-Hunt protected Stop-Loss, Safe Leverage, and Confidence Score (0-100).
      - If the setup is too risky, choppy, against a major S/R wall, or lacks R:R -> sets `is_tradeable = False`
        ("⛔ İŞLEM TAVSİYE EDİLMEZ"), suppresses risky entry/TP/stop signals, and explains why + what to wait for.
    """
    is_tradeable: bool = False
    direction: str = "NO_TRADE"                 # "LONG", "SHORT", or "NO_TRADE"
    direction_label_tr: str = "⛔ İŞLEM TAVSİYE EDİLMEZ (RİSK YÜKSEK)"
    confidence_score: float = 0.0               # 0 to 100
    confidence_grade: str = "D"                 # "A+", "A", "B", "C", "D"
    confidence_verdict_tr: str = "Teknik Yapı Vadeli İşleme Uygun Değil"
    entry_type_tr: str = "Bekle-Gör (İşlem Açılmaz)"
    entry_price: float = 0.0
    entry_zone_low: float = 0.0
    entry_zone_high: float = 0.0
    stop_price: float = 0.0
    stop_distance_pct: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0
    tp3_price: float = 0.0
    tp1_distance_pct: float = 0.0
    tp2_distance_pct: float = 0.0
    tp3_distance_pct: float = 0.0
    rr_ratio: float = 0.0
    max_safe_leverage: int = 1
    sr_context_tr: str = ""
    futures_tech_summary_tr: str = ""
    leverage_squeeze_status_tr: str = "Normal Kaldıraç Dengesi"
    positive_factors_tr: List[str] = field(default_factory=list)
    risk_warnings_tr: List[str] = field(default_factory=list)
    wait_condition_tr: str = ""


@dataclass
class MarketForecast:
    """
    Comprehensive Multi-Factor Quantitative Direction, SMC, Hurst/Kalman, AVWAP, Backtest & Scenario Report (v5.0).
    """
    score: float                  # -100 to +100 composite index
    confidence_pct: float         # 0 to 100% factor agreement / consistency
    verdict_tr: str               # e.g., "GÜÇLÜ POZİTİF EĞİLİM (YUKARI YÖNLÜ OLASILIK ÜSTÜNLÜĞÜ)"
    regime_tr: str                # e.g., "Güçlü Trend Rejimi (ADX: 31.4 - Trend Ağırlıklı Model)"

    # 6 Sub-Factor Scores (-100 to +100)
    trend_score: float = 0.0
    money_flow_score: float = 0.0
    momentum_score: float = 0.0
    structure_score: float = 0.0
    pattern_score: float = 0.0
    macro_htf_score: float = 0.0

    # Plain-language Turkish status summaries
    trend_name_tr: str = ""
    supertrend_status_tr: str = ""
    momentum_tr: str = ""
    money_flow_status_tr: str = ""
    bb_status_tr: str = ""
    last_pattern_tr: str = ""
    divergence_status_tr: str = "Uyumsuzluk Yok"
    cvd_divergence_status_tr: str = "CVD Uyumsuzluğu Yok"
    macro_context_tr: str = ""

    # v4.0 / v5.0 Mathematical Regime, Anchored VWAP, Kalman & Microstructure fields
    hurst_exponent: float = 0.5
    choppiness_index: float = 50.0
    kalman_trend_price: float = 0.0
    avwap_high_price: float = 0.0
    avwap_low_price: float = 0.0
    absorption_status_tr: str = "Normal Akış"
    oi_regime_tr: str = "Veri Yok"
    spot_perp_cvd_tr: str = "Dengeli Akış"

    # Volume Profile, Key Levels & Direction-Aware Staged Targets (TP1 / TP2 / Stop)
    poc_price: float = 0.0
    vah_price: float = 0.0
    val_price: float = 0.0
    fib_618_price: float = 0.0
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    nearest_support_tier_tr: str = "🟢 Sıradan Destek"
    nearest_support_score: float = 42.0
    nearest_support_reason_tr: str = ""
    nearest_resistance_tier_tr: str = "🔴 Sıradan Direnç"
    nearest_resistance_score: float = 42.0
    nearest_resistance_reason_tr: str = ""
    strongest_support: Optional[float] = None
    strongest_resistance: Optional[float] = None
    atr_value: float = 0.0
    bullish_trigger_price: float = 0.0
    bullish_target_price: float = 0.0
    bearish_invalidation_price: float = 0.0
    bearish_target_price: float = 0.0
    active_direction: str = "NEUTRAL"   # "BULLISH", "BEARISH", or "NEUTRAL"
    tp1_price: float = 0.0              # Direction-aware 1st Take Profit (Safe Partial Target)
    tp2_price: float = 0.0              # Direction-aware 2nd Main Target
    stop_price: float = 0.0             # Direction-aware Invalidation / Stop-Loss

    # 5-Criteria Trade Readiness Traffic Light (0/5 to 5/5)
    readiness_score_5: int = 0
    readiness_verdict_tr: str = ""
    readiness_checks: List[Tuple[str, bool, str]] = field(default_factory=list)

    # v6.0 Whale Footprint (0-100), Global Session Clock, Squeeze Energy & 3-Step Action/Alarm Plan
    whale_accumulation_score: float = 50.0
    whale_status_tr: str = ""
    session_status_tr: str = ""
    squeeze_energy_pct: float = 0.0
    expected_breakout_move_pct: float = 0.0
    squeeze_status_tr: str = ""
    step_a_breakout_tr: str = ""
    step_b_pullback_tr: str = ""
    step_c_invalidation_tr: str = ""
    vp_bin_centers: List[float] = field(default_factory=list)
    vp_bin_volumes: List[float] = field(default_factory=list)
    ema20_price: float = 0.0
    cmf_value: float = 0.0
    net_delta_20_usd: float = 0.0
    ob_imbalance_pct: float = 50.0
    ob_bid_wall: Optional[float] = None
    ob_ask_wall: Optional[float] = None

    # Conditional Non-Advisory Scenarios (If/Then)
    bullish_scenario_tr: str = ""
    bearish_scenario_tr: str = ""
    action_summary_tr: str = ""

    # Backtest Performance Validation & Smart Money / Risk Management (v4.0)
    backtest_stats: SignalBacktestStats = field(default_factory=SignalBacktestStats)
    smc: SmartMoneyReport = field(default_factory=SmartMoneyReport)
    risk_plan: Optional[RiskPositionPlan] = None
    futures_setup: FuturesSetupReport = field(default_factory=FuturesSetupReport)

    support_levels: List[SupportResistanceLevel] = field(default_factory=list)
    resistance_levels: List[SupportResistanceLevel] = field(default_factory=list)
    divergences: List[DivergenceSignal] = field(default_factory=list)
    factor_notes_tr: List[str] = field(default_factory=list)

    # v9.2-v9.5 Institutional Price-Action, Swing Structure, Candle Anatomy & Plain Guidance Extensions
    sr_action_type: str = "NONE"  # "BULL_SR_BREAKOUT", "BEAR_SR_BREAKDOWN", "BULL_SFP", "BULL_RETEST", "BEAR_SFP", "BEAR_RETEST", "NONE"
    sr_action_status_tr: str = "Aktif Kırılım Testi (Retest) veya Tuzak (SFP) Yok"
    sr_action_price: float = 0.0
    sr_action_time: Optional[pd.Timestamp] = None
    sr_breakout_rvol: float = 1.0
    sr_breakout_guide_tr: str = ""
    leverage_squeeze_status_tr: str = "Normal Kaldıraç Dengesi"
    trendlines: DynamicTrendlineReport = field(default_factory=DynamicTrendlineReport)
    trend_state: str = "SIDEWAYS"  # "UPTREND", "DOWNTREND", or "SIDEWAYS"
    swing_structure_tr: str = "Yatay Kanal"
    candle_anatomy_tr: str = ""
    plain_guidance_tr: str = ""


class SignalEngine:
    """
    Synthesizes technical indicators, Real Taker Money Flow / CVD, Volume Profile (POC),
    RSI Divergences, context-aware candlestick patterns, and historical backtest validation.
    """

    def __init__(self, config: Optional[IndicatorConfig] = None):
        self.config = config or IndicatorConfig()

    def evaluate(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        rsi = out["rsi"]
        close = out["close"]
        high = out["high"]
        low = out["low"]
        bb_upper = out["bb_upper"]
        bb_lower = out["bb_lower"]
        bb_mid = out["bb_mid"]
        rvol = out.get("rvol", pd.Series(1.0, index=out.index))
        cmf = out.get("cmf", pd.Series(0.0, index=out.index))

        # 1. Overbought / Oversold & Structural Location
        is_rsi_oversold = rsi <= self.config.rsi_oversold
        is_rsi_overbought = rsi >= self.config.rsi_overbought

        is_bb_lower_touch = low <= bb_lower * 1.002
        is_bb_upper_touch = high >= bb_upper * 0.998

        near_oversold = (
            (rsi <= self.config.rsi_near_oversold + 5.0)
            | is_bb_lower_touch
            | (close <= bb_mid)
        )
        near_overbought = (
            (rsi >= self.config.rsi_near_overbought - 5.0)
            | is_bb_upper_touch
            | (close >= bb_mid)
        )

        out["regime_oversold"] = (is_rsi_oversold | is_bb_lower_touch).fillna(False)
        out["regime_overbought"] = (is_rsi_overbought | is_bb_upper_touch).fillna(False)

        # 2. Pattern Groups (including Morning Star, Evening Star, Inverted Hammer, Hanging Man, Tweezer, Marubozu)
        morning_star = out.get("pattern_morning_star", pd.Series(False, index=out.index))
        evening_star = out.get("pattern_evening_star", pd.Series(False, index=out.index))
        inv_hammer = out.get("pattern_inverted_hammer", pd.Series(False, index=out.index))
        hanging_man = out.get("pattern_hanging_man", pd.Series(False, index=out.index))
        tweezer_bot = out.get("pattern_tweezer_bottom", pd.Series(False, index=out.index))
        tweezer_top = out.get("pattern_tweezer_top", pd.Series(False, index=out.index))
        bull_marubozu = out.get("pattern_bullish_marubozu", pd.Series(False, index=out.index))
        bear_marubozu = out.get("pattern_bearish_marubozu", pd.Series(False, index=out.index))

        bullish_patterns = (
            morning_star
            | out["pattern_bullish_engulfing"]
            | out["pattern_hammer"]
            | inv_hammer
            | tweezer_bot
            | bull_marubozu
            | out["pattern_dragonfly_doji"]
        )
        bearish_patterns = (
            evening_star
            | out["pattern_bearish_engulfing"]
            | out["pattern_shooting_star"]
            | hanging_man
            | tweezer_top
            | bear_marubozu
            | out["pattern_gravestone_doji"]
        )
        standard_doji = (
            out["pattern_doji"]
            & (~out["pattern_dragonfly_doji"])
            & (~out["pattern_gravestone_doji"])
        )

        vol_confirmed = (rvol >= 0.85) | out["regime_oversold"] | out["regime_overbought"]

        # 3. High-Conviction Confluence Reversal Signals (strictly on closed candles)
        strong_bullish_reversal = (
            morning_star
            | (out["pattern_bullish_engulfing"] & near_oversold & vol_confirmed)
            | ((out["pattern_hammer"] | out["pattern_dragonfly_doji"] | tweezer_bot) & (out["regime_oversold"] | (rsi <= 43.0)))
            | (inv_hammer & out["regime_oversold"])
            | (standard_doji & out["regime_oversold"] & (cmf >= -0.05))
        ).fillna(False)

        strong_bearish_reversal = (
            evening_star
            | (out["pattern_bearish_engulfing"] & near_overbought & vol_confirmed)
            | ((out["pattern_shooting_star"] | out["pattern_gravestone_doji"] | tweezer_top) & (out["regime_overbought"] | (rsi >= 57.0)))
            | (hanging_man & out["regime_overbought"])
            | (standard_doji & out["regime_overbought"] & (cmf <= 0.05))
        ).fillna(False)

        signal_conditions = [
            strong_bullish_reversal,
            strong_bearish_reversal,
            bullish_patterns,
            bearish_patterns,
            standard_doji,
            is_rsi_oversold & is_bb_lower_touch,
            is_rsi_overbought & is_bb_upper_touch,
        ]
        signal_choices = [
            "BULLISH_REVERSAL",
            "BEARISH_REVERSAL",
            "BULLISH_PATTERN",
            "BEARISH_PATTERN",
            "INDECISION_DOJI",
            "EXTREME_OVERSOLD",
            "EXTREME_OVERBOUGHT",
        ]
        out["signal_type"] = np.select(signal_conditions, signal_choices, default="NONE")

        labels = []
        short_chart_tags = []
        for _, row in out.iterrows():
            sig = row["signal_type"]
            tr_name = row.get("pattern_tr_name", "") or row.get("primary_pattern", "")
            short_tr = row.get("pattern_short_tr", "") or tr_name
            r_val = row["rsi"]
            rv = row.get("rvol", 1.0)
            rsi_str = f"RSI: {r_val:.1f}" if pd.notna(r_val) else ""
            vol_str = f"Hacim: {rv:.1f}x" if pd.notna(rv) else ""

            if sig == "BULLISH_REVERSAL":
                c_p = float(row["close"])
                poc_p = float(row.get("vp_poc", 0.0) or 0.0)
                av_l = float(row.get("avwap_low", 0.0) or 0.0)
                is_aplus = (
                    bool(row["regime_oversold"])
                    or (poc_p > 0 and abs(c_p - poc_p) / c_p <= 0.012)
                    or (av_l > 0 and abs(c_p - av_l) / c_p <= 0.012)
                )
                aplus_tag = "⭐ A+ Kurumsal " if is_aplus else ""
                ctx = "Aşırı Satım / Dip" if row["regime_oversold"] else "Destek / Maliyet Tepkisi"
                labels.append(f"{aplus_tag}ONAYLI YÜKSELİŞ DÖNÜŞÜ: {tr_name} ({ctx} | {rsi_str} | {vol_str})")
                short_chart_tags.append(f"▲ {'⭐' if is_aplus else ''}{short_tr}")
            elif sig == "BEARISH_REVERSAL":
                c_p = float(row["close"])
                poc_p = float(row.get("vp_poc", 0.0) or 0.0)
                av_h = float(row.get("avwap_high", 0.0) or 0.0)
                is_aplus = (
                    bool(row["regime_overbought"])
                    or (poc_p > 0 and abs(c_p - poc_p) / c_p <= 0.012)
                    or (av_h > 0 and abs(c_p - av_h) / c_p <= 0.012)
                )
                aplus_tag = "⭐ A+ Kurumsal " if is_aplus else ""
                ctx = "Aşırı Alım / Tepe" if row["regime_overbought"] else "Direnç / Maliyet Reddi"
                labels.append(f"{aplus_tag}ONAYLI DÜŞÜŞ DÖNÜŞÜ: {tr_name} ({ctx} | {rsi_str} | {vol_str})")
                short_chart_tags.append(f"▼ {'⭐' if is_aplus else ''}{short_tr}")
            elif sig == "BULLISH_PATTERN":
                labels.append(f"Boğa Formasyonu: {tr_name} ({rsi_str})")
                short_chart_tags.append(short_tr)
            elif sig == "BEARISH_PATTERN":
                labels.append(f"Ayı Formasyonu: {tr_name} ({rsi_str})")
                short_chart_tags.append(short_tr)
            elif sig == "INDECISION_DOJI":
                labels.append(f"Kararsızlık Mumu: {tr_name} ({rsi_str})")
                short_chart_tags.append("Doji (Denge)")
            elif sig == "EXTREME_OVERSOLD":
                labels.append(f"Aşırı Satım Bölgesi (RSI + Alt Bollinger Teması | {rsi_str})")
                short_chart_tags.append("Aşırı Satım")
            elif sig == "EXTREME_OVERBOUGHT":
                labels.append(f"Aşırı Alım Bölgesi (RSI + Üst Bollinger Teması | {rsi_str})")
                short_chart_tags.append("Aşırı Alım")
            else:
                labels.append("")
                short_chart_tags.append("")

        out["signal_label"] = labels
        out["chart_tag_tr"] = short_chart_tags
        return out

    @staticmethod
    def backtest_reversal_signals(df: pd.DataFrame, horizon: int = 5) -> SignalBacktestStats:
        """
        Path-Dependent & Fee-Adjusted Historical Backtest Validator (v4.0):
            - Checks bar-by-bar over the next `horizon` bars whether Target (+1.15 ATR)
              or Stop-Loss (-1.00 ATR) is hit FIRST.
            - Deducts realistic round-trip exchange fee + slippage (`0.06R`).
            - Computes Max Drawdown (in R units) and Confluence Win-Rate % (when aligned with CMF/Trend).
        """
        if len(df) <= horizon + 5 or "signal_type" not in df.columns:
            return SignalBacktestStats(horizon_bars=horizon)

        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        sigs = df["signal_type"].values
        times = df["timestamp"].tolist() if "timestamp" in df.columns else list(range(len(df)))
        atrs = df["atr"].bfill().fillna(df["close"] * 0.01).values if "atr" in df.columns else (df["close"] * 0.01).values
        cmfs = df["cmf"].fillna(0.0).values if "cmf" in df.columns else np.zeros(len(df))
        ema50s = df["ema_50"].bfill().values if "ema_50" in df.columns else closes

        bull_wins = 0
        bull_total = 0
        bear_wins = 0
        bear_total = 0
        tp1_hits = 0
        conf_wins = 0
        conf_total = 0
        favorable_moves = []
        adverse_moves = []
        r_outcomes = []
        sig_timestamps = []
        fee_drag_r = 0.06  # Realistic round-trip fee + slippage drag in R units

        # Evaluate only signals that have at least `horizon` subsequent closed bars
        max_idx = len(df) - horizon - 1
        for i in range(5, max_idx):
            sig = sigs[i]
            if sig not in ("BULLISH_REVERSAL", "BEARISH_REVERSAL"):
                continue

            entry = float(closes[i])
            if entry <= 0:
                continue
            risk_1r = max(float(atrs[i]), entry * 0.004)
            tp1_dist = 0.85 * risk_1r
            target_dist = 1.40 * risk_1r

            future_high = float(np.max(highs[i + 1 : i + 1 + horizon]))
            future_low = float(np.min(lows[i + 1 : i + 1 + horizon]))
            future_close = float(closes[i + horizon])
            ts_str = times[i].strftime("%m-%d %H:%M") if hasattr(times[i], "strftime") else str(times[i])

            if sig == "BULLISH_REVERSAL":
                bull_total += 1
                mfe_pct = ((future_high - entry) / entry) * 100.0
                mae_pct = ((entry - future_low) / entry) * 100.0
                favorable_moves.append(mfe_pct)
                adverse_moves.append(mae_pct)

                outcome_r = None
                reached_tp1 = False
                for step in range(1, horizon + 1):
                    bar_low = float(lows[i + step])
                    bar_high = float(highs[i + step])
                    hit_stop = (entry - bar_low) >= (0.0 if reached_tp1 else risk_1r)
                    hit_tp1 = (bar_high - entry) >= tp1_dist
                    hit_target = (bar_high - entry) >= target_dist
                    if not reached_tp1 and hit_stop:
                        outcome_r = -1.0
                        break
                    if hit_target:
                        reached_tp1 = True
                        outcome_r = 0.5 * 0.85 + 0.5 * 1.40  # +1.125R blended TP1 + TP2
                        break
                    if hit_tp1:
                        reached_tp1 = True
                    if reached_tp1 and bar_low <= entry:
                        outcome_r = 0.5 * 0.85  # +0.425R (50% closed at TP1, 50% closed at breakeven)
                        break

                if outcome_r is None:
                    raw_end_r = float(np.clip((future_close - entry) / risk_1r, -1.0, 1.40))
                    outcome_r = (0.5 * 0.85 + 0.5 * max(0.0, raw_end_r)) if reached_tp1 else raw_end_r

                if reached_tp1:
                    tp1_hits += 1
                net_r = outcome_r - fee_drag_r
                r_outcomes.append(net_r)
                sig_timestamps.append(ts_str)
                is_win = net_r > 0
                if is_win:
                    bull_wins += 1
                if cmfs[i] >= -0.02 or entry >= ema50s[i] * 0.99:
                    conf_total += 1
                    if is_win:
                        conf_wins += 1

            elif sig == "BEARISH_REVERSAL":
                bear_total += 1
                mfe_pct = ((entry - future_low) / entry) * 100.0
                mae_pct = ((future_high - entry) / entry) * 100.0
                favorable_moves.append(mfe_pct)
                adverse_moves.append(mae_pct)

                outcome_r = None
                reached_tp1 = False
                for step in range(1, horizon + 1):
                    bar_low = float(lows[i + step])
                    bar_high = float(highs[i + step])
                    hit_stop = (bar_high - entry) >= (0.0 if reached_tp1 else risk_1r)
                    hit_tp1 = (entry - bar_low) >= tp1_dist
                    hit_target = (entry - bar_low) >= target_dist
                    if not reached_tp1 and hit_stop:
                        outcome_r = -1.0
                        break
                    if hit_target:
                        reached_tp1 = True
                        outcome_r = 0.5 * 0.85 + 0.5 * 1.40
                        break
                    if hit_tp1:
                        reached_tp1 = True
                    if reached_tp1 and bar_high >= entry:
                        outcome_r = 0.5 * 0.85
                        break

                if outcome_r is None:
                    raw_end_r = float(np.clip((entry - future_close) / risk_1r, -1.0, 1.40))
                    outcome_r = (0.5 * 0.85 + 0.5 * max(0.0, raw_end_r)) if reached_tp1 else raw_end_r

                if reached_tp1:
                    tp1_hits += 1
                net_r = outcome_r - fee_drag_r
                r_outcomes.append(net_r)
                sig_timestamps.append(ts_str)
                is_win = net_r > 0
                if is_win:
                    bear_wins += 1
                if cmfs[i] <= 0.02 or entry <= ema50s[i] * 1.01:
                    conf_total += 1
                    if is_win:
                        conf_wins += 1

        total = bull_total + bear_total
        if total == 0:
            return SignalBacktestStats(horizon_bars=horizon)

        total_wins = bull_wins + bear_wins
        win_rate = (total_wins / total) * 100.0
        tp1_rate = (tp1_hits / total) * 100.0
        bull_wr = (bull_wins / bull_total) * 100.0 if bull_total > 0 else 0.0
        bear_wr = (bear_wins / bear_total) * 100.0 if bear_total > 0 else 0.0
        conf_wr = (conf_wins / conf_total) * 100.0 if conf_total > 0 else win_rate
        avg_mfe = float(np.mean(favorable_moves)) if favorable_moves else 0.0
        avg_mae = float(np.mean(adverse_moves)) if adverse_moves else 0.0

        gross_profit = sum(r for r in r_outcomes if r > 0)
        gross_loss = abs(sum(r for r in r_outcomes if r < 0))
        profit_factor = float(np.clip(gross_profit / max(gross_loss, 0.15), 0.1, 9.9))
        expectancy_r = float(np.mean(r_outcomes)) if r_outcomes else 0.0

        # Compute Maximum Drawdown (in R units) across the cumulative R equity curve
        cum_r = np.cumsum(r_outcomes)
        peaks = np.maximum.accumulate(np.insert(cum_r, 0, 0.0))[1:]
        drawdowns = peaks - cum_r
        max_dd_r = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        summary_tr = (
            f"Son {total} Onaylı Sinyalin Başarısı: %{win_rate:.1f} (TP1 Temas: %{tp1_rate:.0f} | Çoklu Onaylı: %{conf_wr:.0f}) | "
            f"Kazanç/Kayıp (PF): {profit_factor:.2f} | Beklenti: {expectancy_r:+.2f}R | Max Gerileme: -{max_dd_r:.1f}R"
        )

        return SignalBacktestStats(
            total_signals=total,
            bullish_count=bull_total,
            bearish_count=bear_total,
            win_rate_pct=win_rate,
            tp1_hit_rate_pct=tp1_rate,
            bullish_win_rate_pct=bull_wr,
            bearish_win_rate_pct=bear_wr,
            avg_favorable_move_pct=avg_mfe,
            avg_adverse_move_pct=avg_mae,
            profit_factor=profit_factor,
            expectancy_r=expectancy_r,
            max_drawdown_r=max_dd_r,
            confluence_win_rate_pct=conf_wr,
            horizon_bars=horizon,
            equity_curve_r=[round(float(x), 2) for x in cum_r],
            equity_timestamps=sig_timestamps,
            summary_tr=summary_tr,
        )

    @staticmethod
    def detect_rsi_divergences(df: pd.DataFrame, order: int = 5) -> List[DivergenceSignal]:
        if len(df) < order * 3 or "rsi" not in df.columns:
            return []

        lows = df["low"].values
        highs = df["high"].values
        rsis = df["rsi"].values
        times = df["timestamp"].tolist()
        n = len(df)

        pivot_low_indices = []
        pivot_high_indices = []

        for i in range(order, n - 2):
            right_bound = min(n, i + order + 1)
            if np.isnan(rsis[i]):
                continue
            if lows[i] == np.min(lows[i - order : right_bound]):
                pivot_low_indices.append(i)
            if highs[i] == np.max(highs[i - order : right_bound]):
                pivot_high_indices.append(i)

        divergences: List[DivergenceSignal] = []

        for k in range(1, len(pivot_low_indices)):
            i1 = pivot_low_indices[k - 1]
            i2 = pivot_low_indices[k]
            if 6 <= (i2 - i1) <= 65:
                if lows[i2] < lows[i1] * 0.999 and rsis[i2] > rsis[i1] + 2.2 and rsis[i1] < 48.0:
                    divergences.append(
                        DivergenceSignal(
                            idx_start=i1,
                            idx_end=i2,
                            time_start=times[i1],
                            time_end=times[i2],
                            price_start=float(lows[i1]),
                            price_end=float(lows[i2]),
                            rsi_start=float(rsis[i1]),
                            rsi_end=float(rsis[i2]),
                            div_type="BULLISH_DIV",
                            label_tr="Pozitif Uyumsuzluk (Boğa)",
                            explanation_tr=(
                                "Fiyat daha düşük bir dip yaparken RSI daha yüksek bir dip yaptı. "
                                "Satış baskısının gizlice zayıfladığını ve yukarı yönlü dönüş olasılığının arttığını gösterir."
                            ),
                        )
                    )

        for k in range(1, len(pivot_high_indices)):
            i1 = pivot_high_indices[k - 1]
            i2 = pivot_high_indices[k]
            if 6 <= (i2 - i1) <= 65:
                if highs[i2] > highs[i1] * 1.001 and rsis[i2] < rsis[i1] - 2.2 and rsis[i1] > 52.0:
                    divergences.append(
                        DivergenceSignal(
                            idx_start=i1,
                            idx_end=i2,
                            time_start=times[i1],
                            time_end=times[i2],
                            price_start=float(highs[i1]),
                            price_end=float(highs[i2]),
                            rsi_start=float(rsis[i1]),
                            rsi_end=float(rsis[i2]),
                            div_type="BEARISH_DIV",
                            label_tr="Negatif Uyumsuzluk (Ayı)",
                            explanation_tr=(
                                "Fiyat yeni bir tepe yaparken RSI daha düşük bir tepe yaptı. "
                                "Alıcı momentumunun yorulduğunu ve aşağı yönlü düzeltme olasılığının arttığını gösterir."
                            ),
                        )
                    )

        divergences.sort(key=lambda d: d.idx_end)
        return divergences[-3:]

    @staticmethod
    def detect_cvd_divergences(df: pd.DataFrame, order: int = 5) -> Tuple[str, float]:
        """
        Hidden Whale Accumulation / Distribution Detector (Price vs. Cumulative Volume Delta CVD):
            - Bullish CVD Divergence: Price makes a lower low while CVD makes a higher low (Whales absorbing selling).
            - Bearish CVD Divergence: Price makes a higher high while CVD makes a lower high (Whales distributing into buying).
        """
        if len(df) < order * 3 or "cvd" not in df.columns:
            return "CVD Uyumsuzluğu Yok", 0.0

        lows = df["low"].values
        highs = df["high"].values
        cvds = df["cvd"].values
        n = len(df)

        pivot_lows = []
        pivot_highs = []
        for i in range(order, n - 2):
            rb = min(n, i + order + 1)
            if np.isnan(cvds[i]):
                continue
            if lows[i] == np.min(lows[i - order : rb]):
                pivot_lows.append(i)
            if highs[i] == np.max(highs[i - order : rb]):
                pivot_highs.append(i)

        status_tr = "CVD Uyumsuzluğu Yok"
        score_boost = 0.0

        if len(pivot_lows) >= 2:
            i1, i2 = pivot_lows[-2], pivot_lows[-1]
            if 5 <= (i2 - i1) <= 55 and (n - 1 - i2) <= 16:
                if lows[i2] < lows[i1] * 0.999 and cvds[i2] > cvds[i1]:
                    status_tr = "🐋 Boğa CVD Uyumsuzluğu (Fiyat Düşerken Gizli Balina Toplaması)"
                    score_boost = 16.0

        if len(pivot_highs) >= 2:
            i1, i2 = pivot_highs[-2], pivot_highs[-1]
            if 5 <= (i2 - i1) <= 55 and (n - 1 - i2) <= 16:
                if highs[i2] > highs[i1] * 1.001 and cvds[i2] < cvds[i1]:
                    status_tr = "🐋 Ayı CVD Uyumsuzluğu (Fiyat Çıkarken Gizli Balina Satışı)"
                    score_boost = -16.0

        return status_tr, score_boost

    @staticmethod
    def detect_support_resistance(
        df: pd.DataFrame,
        window: int = 6,
        max_levels: int = 3,
        order_flow: Optional[OrderFlowIntel] = None,
        order_blocks: Optional[List] = None,
        htf_sr_levels: Optional[List[SupportResistanceLevel]] = None,
    ) -> Tuple[List[SupportResistanceLevel], List[SupportResistanceLevel]]:
        """
        Institutional 8-Layer Candle-Anchored & MTF-Validated Support/Resistance Detector (v9.2):
            - Extracts structural pivots, 65-bar extremes, and candle rejections from CLOSED candles (`closed_df`)
            - Combines Major Swing Pivots (`window=6`), Recent Confirmed Local Swings (`local_win=3`), and Wick Rejections
            - Cross-checks against Higher-Timeframe (`4H`/`1D`) S/R zones (`htf_sr_levels`) for MTF Wall Confluence
            - Computes level-specific historical bounce win-rate (%) and average reaction magnitude (%) over 5-bar horizons
            - Enforces ATR-aware minimum separation between 1st and 2nd Support/Resistance zones
        """
        if len(df) < window * 2 + 2:
            return [], []

        closed_df = df.iloc[:-1] if len(df) > window * 2 + 2 else df
        n_closed = len(closed_df)
        highs = closed_df["high"].to_numpy(dtype=float)
        lows = closed_df["low"].to_numpy(dtype=float)
        opens = closed_df["open"].to_numpy(dtype=float)
        closes = closed_df["close"].to_numpy(dtype=float)
        vols = closed_df["volume"].to_numpy(dtype=float) if "volume" in closed_df.columns else np.ones(n_closed)
        avg_vol = float(np.nanmean(vols)) if n_closed > 0 else 1.0

        current_price = float(df["close"].iloc[-1])
        atr_val = (
            float(closed_df["atr"].iloc[-1])
            if "atr" in closed_df.columns and pd.notna(closed_df["atr"].iloc[-1])
            else current_price * 0.008
        )
        lookback_df = closed_df.tail(min(n_closed, 120))
        price_range = float(lookback_df["high"].max() - lookback_df["low"].min())
        cluster_tol = max(atr_val * 0.55, price_range * 0.012, current_price * 0.0038)
        zone_half_width = max(atr_val * 0.22, current_price * 0.0016)

        candidates: List[Tuple[float, str, bool, float, int]] = []
        used_high_bars: set = set()
        used_low_bars: set = set()

        # 1A. 65-Bar Major Structural Extremes (Closed Candles - Highest priority candle anchor)
        start_65 = max(0, n_closed - 65)
        idx_hi65 = int(start_65 + int(np.argmax(highs[start_65:])))
        idx_lo65 = int(start_65 + int(np.argmin(lows[start_65:])))
        candidates.append((float(highs[idx_hi65]), "Ana Tepe/Dip", True, 1.75, idx_hi65))
        candidates.append((float(lows[idx_lo65]), "Ana Tepe/Dip", True, 1.75, idx_lo65))
        used_high_bars.add(idx_hi65)
        used_low_bars.add(idx_lo65)

        # 1B. Major Structural Swing Highs & Lows on Closed Candles (window = 6)
        for i in range(window, n_closed - window):
            rec_w = 1.45 if i >= n_closed - 65 else 1.10
            win_h = highs[i - window : i + window + 1]
            win_l = lows[i - window : i + window + 1]
            if highs[i] >= np.max(win_h) - 1e-12 and all(abs(i - ub) >= 3 for ub in used_high_bars):
                candidates.append((float(highs[i]), "Pivot", True, rec_w, i))
                used_high_bars.add(i)
            if lows[i] <= np.min(win_l) + 1e-12 and all(abs(i - ub) >= 3 for ub in used_low_bars):
                candidates.append((float(lows[i]), "Pivot", True, rec_w, i))
                used_low_bars.add(i)

        # 1C. Recent Confirmed Local Swing Pivots (captures bounces/rejections in the last 36 closed bars!)
        local_win = 3
        start_local = max(local_win, n_closed - 36)
        for i in range(start_local, n_closed - 2):
            r_right = min(local_win, n_closed - 1 - i)
            if r_right < 2:
                continue
            win_h = highs[i - local_win : i + r_right + 1]
            win_l = lows[i - local_win : i + r_right + 1]
            if highs[i] >= np.max(win_h) - 1e-12 and all(abs(i - ub) >= 3 for ub in used_high_bars):
                candidates.append((float(highs[i]), "Yakın Pivot", True, 1.60, i))
                used_high_bars.add(i)
            if lows[i] <= np.min(win_l) + 1e-12 and all(abs(i - ub) >= 3 for ub in used_low_bars):
                candidates.append((float(lows[i]), "Yakın Pivot", True, 1.60, i))
                used_low_bars.add(i)

        # 3. Volume Profile Key Nodes (POC is a high-volume traded price anchor; VAH/VAL are channel boundaries)
        if "vp_poc" in closed_df.columns:
            poc = float(closed_df["vp_poc"].iloc[-1])
            vah = float(closed_df["vp_vah"].iloc[-1])
            val = float(closed_df["vp_val"].iloc[-1])
            if poc > 0:
                candidates.append((poc, "Hacim POC", True, 1.15, -1))
            if vah > 0:
                candidates.append((vah, "Hacim VAH", False, 0.85, -1))
            if val > 0:
                candidates.append((val, "Hacim VAL", False, 0.85, -1))

        # 4. Institutional Cost Basis (AVWAP Low/High) & Macro EMA 200 (Confluence boosters)
        if "avwap_low" in closed_df.columns and pd.notna(closed_df["avwap_low"].iloc[-1]):
            av_l = float(closed_df["avwap_low"].iloc[-1])
            if av_l > 0:
                candidates.append((av_l, "Dip Maliyet (AVWAP)", False, 0.90, -1))
        if "avwap_high" in closed_df.columns and pd.notna(closed_df["avwap_high"].iloc[-1]):
            av_h = float(closed_df["avwap_high"].iloc[-1])
            if av_h > 0:
                candidates.append((av_h, "Tepe Maliyet (AVWAP)", False, 0.90, -1))
        if "ema_200" in closed_df.columns and pd.notna(closed_df["ema_200"].iloc[-1]):
            e200 = float(closed_df["ema_200"].iloc[-1])
            if e200 > 0:
                candidates.append((e200, "EMA 200", False, 0.90, -1))

        # 5. Fibonacci 0.618 & 0.382 Retracements of recent 90 closed bars
        recent_90 = closed_df.tail(min(n_closed, 90))
        recent_high = float(recent_90["high"].max())
        recent_low = float(recent_90["low"].min())
        span_90 = recent_high - recent_low
        if span_90 > 0:
            fib_618 = recent_high - 0.618 * span_90
            fib_382 = recent_high - 0.382 * span_90
            candidates.append((fib_618, "Fib 0.618", False, 0.80, -1))
            candidates.append((fib_382, "Fib 0.382", False, 0.75, -1))

        # 6. Smart Money Order Blocks (Real institutional candle base)
        if order_blocks:
            for ob in order_blocks:
                ob_mid = 0.5 * (float(ob.bottom) + float(ob.top))
                if ob_mid > 0:
                    candidates.append((ob_mid, "Balina OB", True, 1.25, -1))

        # 7. Live Exchange OrderBook Bid/Ask Walls (within ±12% of current price)
        if order_flow is not None:
            if order_flow.strongest_bid_wall and 0 < order_flow.strongest_bid_wall < current_price:
                if abs(current_price - order_flow.strongest_bid_wall) / current_price <= 0.12:
                    candidates.append((float(order_flow.strongest_bid_wall), "Alış Duvarı", False, 1.0, -1))
            if order_flow.strongest_ask_wall and order_flow.strongest_ask_wall > current_price:
                if abs(order_flow.strongest_ask_wall - current_price) / current_price <= 0.12:
                    candidates.append((float(order_flow.strongest_ask_wall), "Satış Duvarı", False, 1.0, -1))

        # Cluster nearby candidates while anchoring cluster center to real candle pivots
        candidates.sort(key=lambda x: x[0])
        clusters: List[List[Tuple[float, str, bool, float, int]]] = []
        for item in candidates:
            price_val = item[0]
            placed = False
            for cl in clusters:
                anchor_prices = [x[0] for x in cl if x[2]]
                ref_price = float(np.mean(anchor_prices)) if anchor_prices else float(np.mean([x[0] for x in cl]))
                if abs(ref_price - price_val) <= cluster_tol:
                    cl.append(item)
                    placed = True
                    break
            if not placed:
                clusters.append([item])

        raw_supports: List[SupportResistanceLevel] = []
        raw_resistances: List[SupportResistanceLevel] = []
        min_dist_from_price = max(atr_val * 0.18, current_price * 0.0018)
        body_lows = np.minimum(opens, closes)
        body_highs = np.maximum(opens, closes)

        for cl in clusters:
            c_tags: List[str] = []
            for _, t_name, _, _, _ in cl:
                if t_name not in c_tags:
                    c_tags.append(t_name)

            pure_pivots = [(p, w, b_idx) for p, t, is_anc, w, b_idx in cl if b_idx >= 0]
            struct_anchors = [(p, w) for p, t, is_anc, w, _ in cl if is_anc]
            if pure_pivots:
                best_piv = max(pure_pivots, key=lambda x: (x[1], x[2]))
                lvl_price = float(best_piv[0])
            elif struct_anchors:
                lvl_price = float(np.average([p for p, _ in struct_anchors], weights=[w for _, w in struct_anchors]))
            else:
                lvl_price = float(np.average([p for p, _, _, _, _ in cl], weights=[w for _, _, _, w, _ in cl]))

            if abs(lvl_price - current_price) < min_dist_from_price:
                continue

            is_support_side = lvl_price < current_price
            b_low = lvl_price - zone_half_width
            b_high = lvl_price + zone_half_width

            # Count TRUE closed-candle rejections (bars that tested the band and closed without breaking through)
            touch_tol = zone_half_width * 1.35
            if is_support_side:
                sup_reject_mask = (lows <= b_high + touch_tol) & (lows >= b_low - touch_tol * 1.5) & (closes >= b_low)
                flip_reject_mask = (highs >= b_low - touch_tol) & (highs <= b_high + touch_tol * 1.5) & (closes <= b_high)
                valid_reject_mask = sup_reject_mask | flip_reject_mask
                wick_sizes = np.where(sup_reject_mask, body_lows - lows, 0.0)
            else:
                res_reject_mask = (highs >= b_low - touch_tol) & (highs <= b_high + touch_tol * 1.5) & (closes <= b_high)
                flip_reject_mask = (lows <= b_high + touch_tol) & (lows >= b_low - touch_tol * 1.5) & (closes >= b_low)
                valid_reject_mask = res_reject_mask | flip_reject_mask
                wick_sizes = np.where(res_reject_mask, highs - body_highs, 0.0)

            rejection_bars = int(np.sum(valid_reject_mask))
            recent_rejection_bars = int(np.sum(valid_reject_mask[-45:])) if n_closed >= 10 else rejection_bars
            pivot_touches = len(pure_pivots)

            if pivot_touches == 0 and rejection_bars == 0 and "Hacim POC" not in c_tags and "Balina OB" not in c_tags:
                continue

            # Module 2: Level-Specific Historical Reaction Backtest (5-bar forward bounce success rate & avg move %)
            episode_indices: List[int] = []
            last_ep = -10
            for idx_b in range(2, max(3, n_closed - 3)):
                if is_support_side:
                    entered_zone = (lows[idx_b] <= b_high + touch_tol) and (highs[idx_b] >= b_low - touch_tol)
                else:
                    entered_zone = (highs[idx_b] >= b_low - touch_tol) and (lows[idx_b] <= b_high + touch_tol)
                if entered_zone and (idx_b - last_ep) >= 4:
                    episode_indices.append(idx_b)
                    last_ep = idx_b

            win_episodes = 0
            bounce_pcts: List[float] = []
            for ep_i in episode_indices:
                end_h = min(n_closed, ep_i + 6)
                if end_h <= ep_i + 1:
                    continue
                if is_support_side:
                    # Did price bounce upward from support without closing decisively below b_low - 0.45*ATR?
                    fwd_high = float(np.max(highs[ep_i : end_h]))
                    fwd_min_close = float(np.min(closes[ep_i + 1 : end_h]))
                    move_pct = max(0.0, (fwd_high - lvl_price) / max(lvl_price, 1e-9) * 100.0)
                    held_zone = (closes[ep_i] >= b_low - 0.15 * atr_val) and (fwd_min_close >= b_low - 0.45 * atr_val)
                    if held_zone and move_pct >= (0.35 * atr_val / max(lvl_price, 1e-9) * 100.0):
                        win_episodes += 1
                        bounce_pcts.append(move_pct)
                else:
                    fwd_low = float(np.min(lows[ep_i : end_h]))
                    fwd_max_close = float(np.max(closes[ep_i + 1 : end_h]))
                    move_pct = max(0.0, (lvl_price - fwd_low) / max(lvl_price, 1e-9) * 100.0)
                    held_zone = (closes[ep_i] <= b_high + 0.15 * atr_val) and (fwd_max_close <= b_high + 0.45 * atr_val)
                    if held_zone and move_pct >= (0.35 * atr_val / max(lvl_price, 1e-9) * 100.0):
                        win_episodes += 1
                        bounce_pcts.append(move_pct)

            test_count = max(len(episode_indices), 1 if (pivot_touches > 0 or rejection_bars > 0) else 0)
            reaction_count = max(win_episodes, 1 if pivot_touches > 0 and win_episodes == 0 else 0)
            if reaction_count > test_count:
                test_count = reaction_count
            reaction_rate_pct = (reaction_count / max(test_count, 1)) * 100.0
            avg_bounce_pct = float(np.mean(bounce_pcts)) if bounce_pcts else (float(0.85 * atr_val / max(lvl_price, 1e-9) * 100.0))
            stats_summary_tr = f"{reaction_count}/{test_count} Başarılı Tepki (%{reaction_rate_pct:.0f}) • Ort. ±%{avg_bounce_pct:.2f}"

            local_vol_ratio = (
                float(np.nanmean(vols[valid_reject_mask])) / max(avg_vol, 1e-9)
                if rejection_bars > 0
                else 1.0
            )
            max_wick_atr = float(np.max(wick_sizes)) / max(atr_val, 1e-9) if len(wick_sizes) > 0 else 0.0

            # Compute 0-100 Quantitative Strength Score grounded in real candle behavior + MTF Confluence
            score_pts = 0.0
            conf_reasons: List[str] = []

            # Module 1: Check Higher-Timeframe (4H / 1D) Wall Confluence
            htf_confirmed = False
            htf_tag_tr = ""
            if htf_sr_levels:
                htf_tol = max(atr_val * 0.80, current_price * 0.0055)
                for h_lvl in htf_sr_levels:
                    if (b_low - htf_tol <= h_lvl.price <= b_high + htf_tol) or (
                        h_lvl.band_low <= lvl_price <= h_lvl.band_high
                    ):
                        htf_confirmed = True
                        htf_tag_tr = "🏛️ Üst Periyot (4H/1D) Duvar Onaylı"
                        score_pts += 20.0
                        conf_reasons.append("🏛️ Üst Periyot Duvarı")
                        break

            distinct_tests = max(pivot_touches, win_episodes)
            eff_touches = max(distinct_tests, 1 if rejection_bars > 0 else 0)
            if distinct_tests >= 3:
                score_pts += 32.0
                conf_reasons.append(f"{distinct_tests} Kez Onaylı Test")
            elif distinct_tests == 2:
                score_pts += 22.0
                conf_reasons.append("2 Kez Test Edildi")
            elif distinct_tests == 1:
                score_pts += 12.0
                conf_reasons.append("Tekil Pivot" if pivot_touches > 0 else "Ara Tepki")
            else:
                score_pts += 8.0
                conf_reasons.append("Ara Seviye")

            if win_episodes >= 2 and reaction_rate_pct >= 70.0:
                score_pts += 8.0

            if max_wick_atr >= 0.65:
                score_pts += 6.0
                conf_reasons.append("Güçlü İğne Reddi")

            if "Ana Tepe/Dip" in c_tags:
                score_pts += 16.0
                if "Ana Dip/Tepe" not in conf_reasons:
                    conf_reasons.append("Ana Dip/Tepe")
            if "Hacim POC" in c_tags:
                score_pts += 18.0
                conf_reasons.append("Hacim Mıknatısı (POC)")
            elif "Hacim VAL" in c_tags or "Hacim VAH" in c_tags:
                score_pts += 10.0
                conf_reasons.append("Hacim Kanal Sınırı")
            if "Dip Maliyet (AVWAP)" in c_tags or "Tepe Maliyet (AVWAP)" in c_tags:
                score_pts += 14.0
                conf_reasons.append("Kurumsal Maliyet (AVWAP)")
            if "EMA 200" in c_tags:
                score_pts += 14.0
                conf_reasons.append("EMA 200")
            if "Balina OB" in c_tags:
                score_pts += 16.0
                conf_reasons.append("Balina Emir Kutusu")
            if "Alış Duvarı" in c_tags or "Satış Duvarı" in c_tags:
                score_pts += 16.0
                conf_reasons.append("Canlı Borsa Duvarı")
            if "Fib 0.618" in c_tags:
                score_pts += 12.0
                conf_reasons.append("Altın Oran (Fib 0.618)")
            elif "Fib 0.382" in c_tags:
                score_pts += 7.0
                conf_reasons.append("Fib 0.382")
            if local_vol_ratio >= 1.30:
                score_pts += 8.0
                conf_reasons.append(f"Yüksek Hacim ({local_vol_ratio:.1f}x)")

            strength_score = float(np.clip(score_pts, 25.0, 98.0))
            is_strong = strength_score >= 62.0
            short_reasons = " + ".join(conf_reasons[:2]) if conf_reasons else "Ara Seviye"

            if is_support_side:
                tier_tr = "🛡️ Güçlü Destek" if is_strong else "🟢 Sıradan Destek"
                strength_lbl = f"{tier_tr} (Güç: {strength_score:.0f}/100 • {short_reasons})"
                raw_supports.append(
                    SupportResistanceLevel(
                        price=lvl_price,
                        band_low=b_low,
                        band_high=b_high,
                        level_type="DESTEK",
                        touches=max(eff_touches, 1),
                        strength_label=strength_lbl,
                        is_strong=is_strong,
                        strength_score=strength_score,
                        tier_tr=tier_tr,
                        confluence_tags=conf_reasons,
                        htf_confirmed=htf_confirmed,
                        htf_tag_tr=htf_tag_tr,
                        reaction_count=reaction_count,
                        test_count=test_count,
                        reaction_rate_pct=reaction_rate_pct,
                        avg_bounce_pct=avg_bounce_pct,
                        stats_summary_tr=stats_summary_tr,
                    )
                )
            else:
                tier_tr = "🧱 Güçlü Direnç" if is_strong else "🔴 Sıradan Direnç"
                strength_lbl = f"{tier_tr} (Güç: {strength_score:.0f}/100 • {short_reasons})"
                raw_resistances.append(
                    SupportResistanceLevel(
                        price=lvl_price,
                        band_low=b_low,
                        band_high=b_high,
                        level_type="DİRENÇ",
                        touches=max(eff_touches, 1),
                        strength_label=strength_lbl,
                        is_strong=is_strong,
                        strength_score=strength_score,
                        tier_tr=tier_tr,
                        confluence_tags=conf_reasons,
                        htf_confirmed=htf_confirmed,
                        htf_tag_tr=htf_tag_tr,
                        reaction_count=reaction_count,
                        test_count=test_count,
                        reaction_rate_pct=reaction_rate_pct,
                        avg_bounce_pct=avg_bounce_pct,
                        stats_summary_tr=stats_summary_tr,
                    )
                )

        # Sort by distance to current_price and enforce minimum ATR separation so 1st & 2nd zones never overlap
        raw_supports.sort(key=lambda x: abs(x.price - current_price))
        raw_resistances.sort(key=lambda x: abs(x.price - current_price))
        min_level_gap = max(atr_val * 0.72, zone_half_width * 2.35, current_price * 0.0052)

        def _dedup_levels(levels: List[SupportResistanceLevel]) -> List[SupportResistanceLevel]:
            selected: List[SupportResistanceLevel] = []
            for cand in levels:
                if not selected:
                    selected.append(cand)
                    continue
                prev = selected[-1]
                if abs(cand.price - prev.price) < min_level_gap:
                    if cand.strength_score > prev.strength_score + 6.0:
                        selected[-1] = cand
                else:
                    selected.append(cand)
                if len(selected) >= max_levels:
                    break
            return selected

        supports = _dedup_levels(raw_supports)
        resistances = _dedup_levels(raw_resistances)

        ext_step = max(atr_val * 1.45, min_level_gap * 1.25, current_price * 0.011)
        while len(supports) < min(2, max_levels):
            base_p = supports[-1].price if supports else current_price
            ext_p = float(base_p - ext_step)
            if ext_p <= 0:
                break
            supports.append(
                SupportResistanceLevel(
                    price=ext_p,
                    band_low=ext_p - zone_half_width,
                    band_high=ext_p + zone_half_width,
                    level_type="DESTEK",
                    touches=1,
                    strength_label="🟢 Sıradan Destek (Güç: 35/100 • Alt Kanal ATR Uzatması)",
                    is_strong=False,
                    strength_score=35.0,
                    tier_tr="🟢 Sıradan Destek",
                    confluence_tags=["Alt Kanal ATR Uzatması"],
                    stats_summary_tr="Volatilite Uzatma Seviyesi",
                )
            )

        while len(resistances) < min(2, max_levels):
            base_p = resistances[-1].price if resistances else current_price
            ext_p = float(base_p + ext_step)
            resistances.append(
                SupportResistanceLevel(
                    price=ext_p,
                    band_low=ext_p - zone_half_width,
                    band_high=ext_p + zone_half_width,
                    level_type="DİRENÇ",
                    touches=1,
                    strength_label="🔴 Sıradan Direnç (Güç: 35/100 • Üst Kanal ATR Uzatması)",
                    is_strong=False,
                    strength_score=35.0,
                    tier_tr="🔴 Sıradan Direnç",
                    confluence_tags=["Üst Kanal ATR Uzatması"],
                    stats_summary_tr="Volatilite Uzatma Seviyesi",
                )
            )

        return supports[:max_levels], resistances[:max_levels]

    @staticmethod
    def detect_retest_and_sfp(
        closed_df: pd.DataFrame,
        live_close: float,
        supports: List[SupportResistanceLevel],
        resistances: List[SupportResistanceLevel],
        atr_val: float,
    ) -> Tuple[str, str, float, Optional[pd.Timestamp], float]:
        """
        Module 3: Detects Confirmed S/R Flip Retests and Swing Failure Patterns (SFP / Trap Fakeouts)
        on the most recent closed candles (`closed_df.tail(5)`).
        Returns: (action_type, status_tr, trigger_price, trigger_timestamp, score_boost)
        """
        if len(closed_df) < 10:
            return "NONE", "Aktif Kırılım Testi (Retest) veya Tuzak (SFP) Yok", 0.0, None, 0.0

        recent = closed_df.tail(5)
        p_fmt = ",.4f" if live_close < 10.0 else ",.2f"
        vol_col = closed_df["volume"].to_numpy(dtype=float) if "volume" in closed_df.columns else np.ones(len(closed_df))
        avg_vol_20 = float(np.mean(vol_col[-21:-1])) if len(vol_col) >= 5 else float(np.mean(vol_col))
        avg_vol_20 = max(avg_vol_20, 1e-9)

        # 0A. Check FRESH RESISTANCE BREAKOUT (Direnç Kırılımı Geldi! -> Eski Direnç Yeni Destek Oldu)
        # When price just broke above a resistance level on the last 1-2 closed candles, that level is now in `supports[0]`.
        if supports and len(closed_df) >= 6:
            sup = supports[0]
            pre_closes = closed_df["close"].iloc[-6:-1].to_numpy(dtype=float)
            # Check if at least 2 of the previous candles were closed BELOW this level's band_high (meaning it acted as Resistance)
            if int(np.sum(pre_closes <= sup.band_high + 0.05 * atr_val)) >= 2:
                for idx_back in (-1, -2):
                    row = closed_df.iloc[idx_back]
                    prev_row = closed_df.iloc[idx_back - 1]
                    cl_v = float(row["close"])
                    op_v = float(row["open"])
                    hi_v = float(row["high"])
                    lo_v = float(row["low"])
                    prev_cl = float(prev_row["close"])
                    vol_v = float(row.get("volume", avg_vol_20))
                    rvol = vol_v / avg_vol_20
                    ts_v = row["timestamp"] if "timestamp" in row else None
                    rng = max(hi_v - lo_v, 1e-9)
                    body_ratio = abs(cl_v - op_v) / rng

                    # True Breakout Logic: Previous close was below/inside resistance, and this closed candle's BODY closed decisively above band_high!
                    if (
                        prev_cl <= sup.band_high + 0.05 * atr_val
                        and cl_v > sup.band_high
                        and cl_v > op_v
                        and body_ratio >= 0.38
                        and live_close >= sup.price
                    ):
                        vol_tag = f"🔥 {rvol:.2f}x Hacimli " if rvol >= 1.20 else f"Gövde Kapanışlı ({rvol:.2f}x Hacim) "
                        return (
                            "BULL_SR_BREAKOUT",
                            f"🚀 DİRENÇ KIRILIMI GELDİ! {format(sup.price, p_fmt)} Tavanı {vol_tag}Mum Kapanışıyla Yukarı Kırıldı (Eski Direnç ➔ Yeni Destek Oldu)",
                            float(sup.price),
                            ts_v,
                            20.0 if rvol >= 1.20 else 15.0,
                        )

        # 0B. Check FRESH SUPPORT BREAKDOWN (Destek Kırılımı Geldi! -> Eski Destek Yeni Direnç Oldu)
        # When price just broke below a support level on the last 1-2 closed candles, that level is now in `resistances[0]`.
        if resistances and len(closed_df) >= 6:
            res = resistances[0]
            pre_closes = closed_df["close"].iloc[-6:-1].to_numpy(dtype=float)
            # Check if at least 2 of the previous candles were closed ABOVE this level's band_low (meaning it acted as Support)
            if int(np.sum(pre_closes >= res.band_low - 0.05 * atr_val)) >= 2:
                for idx_back in (-1, -2):
                    row = closed_df.iloc[idx_back]
                    prev_row = closed_df.iloc[idx_back - 1]
                    cl_v = float(row["close"])
                    op_v = float(row["open"])
                    hi_v = float(row["high"])
                    lo_v = float(row["low"])
                    prev_cl = float(prev_row["close"])
                    vol_v = float(row.get("volume", avg_vol_20))
                    rvol = vol_v / avg_vol_20
                    ts_v = row["timestamp"] if "timestamp" in row else None
                    rng = max(hi_v - lo_v, 1e-9)
                    body_ratio = abs(cl_v - op_v) / rng

                    # True Breakdown Logic: Previous close was above/inside support, and this closed candle's BODY closed decisively below band_low!
                    if (
                        prev_cl >= res.band_low - 0.05 * atr_val
                        and cl_v < res.band_low
                        and cl_v < op_v
                        and body_ratio >= 0.38
                        and live_close <= res.price
                    ):
                        vol_tag = f"🔥 {rvol:.2f}x Hacimli " if rvol >= 1.20 else f"Gövde Kapanışlı ({rvol:.2f}x Hacim) "
                        return (
                            "BEAR_SR_BREAKDOWN",
                            f"🩸 DESTEK KIRILIMI GELDİ! {format(res.price, p_fmt)} Desteği {vol_tag}Mum Kapanışıyla Aşağı Kırıldı (Eski Destek ➔ Yeni Direnç Oldu)",
                            float(res.price),
                            ts_v,
                            -20.0 if rvol >= 1.20 else -15.0,
                        )

        # 1. Check Bullish SFP (Bear Trap) & Bullish S/R Flip Retest at 1st Support
        if supports:
            sup = supports[0]
            for _, row in recent.iloc[::-1].iterrows():
                lo_v = float(row["low"])
                cl_v = float(row["close"])
                op_v = float(row["open"])
                ts_v = row["timestamp"] if "timestamp" in row else None
                lower_wick = min(op_v, cl_v) - lo_v

                # Bullish SFP: Wick swept below support price (or band_low), closed back above support price!
                if lo_v < sup.price - 0.05 * atr_val and cl_v >= sup.price and lower_wick >= 0.30 * atr_val and live_close >= sup.band_low:
                    return (
                        "BULL_SFP",
                        f"🪤 SAHTE DESTEK KIRILIMI (Boğa SFP / Ayı Tuzağı): Fiyat {format(sup.price, p_fmt)} Desteği Altına İğne Atıp Stopları Süpürdü ve Üzerinde Kapattı!",
                        float(lo_v),
                        ts_v,
                        16.0,
                    )

                # Bullish Retest (S/R Flip): Low tested support band [band_low, band_high + 0.25*ATR] and closed bullishly above band_high
                if (sup.band_low - 0.15 * atr_val) <= lo_v <= (sup.band_high + 0.28 * atr_val) and cl_v >= op_v and cl_v >= sup.price and live_close >= sup.price:
                    return (
                        "BULL_RETEST",
                        f"🔄 Onaylı Destek Testi (Retest): Fiyat {format(sup.price, p_fmt)} ({sup.tier_tr}) Bölgesini Test Edip Alıcı Onayı Aldı",
                        float(sup.price),
                        ts_v,
                        12.0,
                    )

        # 2. Check Bearish SFP (Bull Trap) & Bearish S/R Flip Retest at 1st Resistance
        if resistances:
            res = resistances[0]
            for _, row in recent.iloc[::-1].iterrows():
                hi_v = float(row["high"])
                cl_v = float(row["close"])
                op_v = float(row["open"])
                ts_v = row["timestamp"] if "timestamp" in row else None
                upper_wick = hi_v - max(op_v, cl_v)

                # Bearish SFP: Wick spiked above resistance price, closed back below resistance price!
                if hi_v > res.price + 0.05 * atr_val and cl_v <= res.price and upper_wick >= 0.30 * atr_val and live_close <= res.band_high:
                    return (
                        "BEAR_SFP",
                        f"🪤 SAHTE DİRENÇ KIRILIMI (Ayı SFP / Boğa Tuzağı): Fiyat {format(res.price, p_fmt)} Direnci Üstüne İğne Atıp Stopları Süpürdü ve Altında Kapattı!",
                        float(hi_v),
                        ts_v,
                        -16.0,
                    )

                # Bearish Retest: High tested resistance band and closed bearishly below resistance price
                if (res.band_low - 0.28 * atr_val) <= hi_v <= (res.band_high + 0.15 * atr_val) and cl_v <= op_v and cl_v <= res.price and live_close <= res.price:
                    return (
                        "BEAR_RETEST",
                        f"🔄 Onaylı Direnç Reddi (Retest): Fiyat {format(res.price, p_fmt)} ({res.tier_tr}) Tavanını Test Edip Satıcı Reddi Yedi",
                        float(res.price),
                        ts_v,
                        -12.0,
                    )

        return "NONE", "Aktif Kırılım Testi (Retest) veya Tuzak (SFP) Yok", 0.0, None, 0.0

    @staticmethod
    def detect_dynamic_trendlines(
        closed_df: pd.DataFrame,
        live_close: float,
        atr_val: float,
    ) -> Tuple[DynamicTrendlineReport, float]:
        """
        Module 4: Automatic Dynamic Ascending Support & Descending Resistance Trendline & Breakout Engine.
        Connects confirmed closed-candle swing pivots over the last 95 bars and detects live trendline breakouts.
        """
        report = DynamicTrendlineReport()
        if len(closed_df) < 25:
            return report, 0.0

        sub = closed_df.tail(min(len(closed_df), 95)).reset_index(drop=True)
        n = len(sub)
        highs = sub["high"].to_numpy(dtype=float)
        lows = sub["low"].to_numpy(dtype=float)
        closes = sub["close"].to_numpy(dtype=float)
        ts_arr = sub["timestamp"].tolist() if "timestamp" in sub.columns else list(range(n))
        p_fmt = ",.4f" if live_close < 10.0 else ",.2f"

        piv_win = 4
        swing_lows: List[Tuple[int, float]] = []
        swing_highs: List[Tuple[int, float]] = []
        for i in range(piv_win, n - 2):
            r_w = min(piv_win, n - 1 - i)
            if lows[i] <= np.min(lows[i - piv_win : i + r_w + 1]) + 1e-12:
                if not swing_lows or (i - swing_lows[-1][0]) >= 5:
                    swing_lows.append((i, float(lows[i])))
            if highs[i] >= np.max(highs[i - piv_win : i + r_w + 1]) - 1e-12:
                if not swing_highs or (i - swing_highs[-1][0]) >= 5:
                    swing_highs.append((i, float(highs[i])))

        # 1. Fit Ascending Support Trendline (connecting rising swing lows)
        best_sup_pair = None
        for idx_a in range(len(swing_lows) - 1):
            for idx_b in range(idx_a + 1, len(swing_lows)):
                i1, p1 = swing_lows[idx_a]
                i2, p2 = swing_lows[idx_b]
                if (i2 - i1) < 8 or p2 <= p1:
                    continue
                slope = (p2 - p1) / float(i2 - i1)
                # Ensure intermediate closed candle bodies mostly stayed above the line
                line_vals = np.array([p1 + slope * (k - i1) for k in range(i1, n - 1)])
                violations = int(np.sum(closes[i1 : n - 1] < line_vals - 0.35 * atr_val))
                if violations <= 1:
                    best_sup_pair = (i1, p1, i2, p2, slope)

        if best_sup_pair is not None:
            i1, p1, i2, p2, slope = best_sup_pair
            y_now = float(p1 + slope * (n - 1 - i1))
            if y_now > 0 and abs(y_now - live_close) / max(live_close, 1e-9) <= 0.15:
                report.has_support_line = True
                report.sup_x0 = ts_arr[i1]
                report.sup_y0 = float(p1)
                report.sup_x1 = ts_arr[-1]
                report.sup_y1 = y_now
                report.sup_current_price = y_now

        # 2. Fit Descending Resistance Trendline (connecting falling swing highs)
        best_res_pair = None
        for idx_a in range(len(swing_highs) - 1):
            for idx_b in range(idx_a + 1, len(swing_highs)):
                i1, p1 = swing_highs[idx_a]
                i2, p2 = swing_highs[idx_b]
                if (i2 - i1) < 8 or p2 >= p1:
                    continue
                slope = (p2 - p1) / float(i2 - i1)
                line_vals = np.array([p1 + slope * (k - i1) for k in range(i1, n - 1)])
                violations = int(np.sum(closes[i1 : n - 1] > line_vals + 0.35 * atr_val))
                if violations <= 1:
                    best_res_pair = (i1, p1, i2, p2, slope)

        if best_res_pair is not None:
            i1, p1, i2, p2, slope = best_res_pair
            y_now = float(p1 + slope * (n - 1 - i1))
            if y_now > 0 and abs(y_now - live_close) / max(live_close, 1e-9) <= 0.15:
                report.has_resistance_line = True
                report.res_x0 = ts_arr[i1]
                report.res_y0 = float(p1)
                report.res_x1 = ts_arr[-1]
                report.res_y1 = y_now
                report.res_current_price = y_now

        # 3. Evaluate Dynamic Trendline Breakouts / Breakdowns on the latest closed bar
        trend_boost = 0.0
        last_cl = float(closes[-1])
        prev_cl = float(closes[-2]) if n >= 2 else last_cl

        if report.has_resistance_line and prev_cl <= report.res_current_price * 1.002 and last_cl > report.res_current_price + 0.10 * atr_val and live_close > report.res_current_price:
            report.breakout_status = "BULL_BREAKOUT"
            report.summary_tr = f"📐 🟢 DÜŞEN TREND YUKARI KIRILDI! (Kırılım Seviyesi: {format(report.res_current_price, p_fmt)} USDT)"
            trend_boost = 15.0
        elif report.has_support_line and prev_cl >= report.sup_current_price * 0.998 and last_cl < report.sup_current_price - 0.10 * atr_val and live_close < report.sup_current_price:
            report.breakout_status = "BEAR_BREAKDOWN"
            report.summary_tr = f"📐 🔴 YÜKSELEN TREND AŞAĞI KIRILDI! (Kırılan Trend Desteği: {format(report.sup_current_price, p_fmt)} USDT)"
            trend_boost = -15.0
        elif report.has_support_line and report.has_resistance_line and report.sup_current_price < live_close < report.res_current_price:
            report.breakout_status = "CONVERGING_SQUEEZE"
            report.summary_tr = (
                f"📐 Üçgen / Trend Sıkışması: Yükselen Destek {format(report.sup_current_price, p_fmt)} | "
                f"Düşen Direnç {format(report.res_current_price, p_fmt)} USDT"
            )
        elif report.has_resistance_line:
            report.summary_tr = f"📐 Düşen Trend Direnci Aktif: {format(report.res_current_price, p_fmt)} USDT"
        elif report.has_support_line:
            report.summary_tr = f"📐 Yükselen Trend Desteği Aktif: {format(report.sup_current_price, p_fmt)} USDT"

        return report, trend_boost

    @staticmethod
    def analyze_swing_structure(
        closed_df: pd.DataFrame,
        atr_val: float,
    ) -> Tuple[str, str, float]:
        """
        Dow Theory Institutional Swing Structure Detector (HH/HL, LH/LL, Daralan Üçgen, Yatay Kanal).
        Returns: (swing_code, swing_structure_tr, trend_score_boost)
        """
        if len(closed_df) < 16:
            return "RANGE", "Yatay Kanal / Dengeli Pivot", 0.0

        tail = closed_df.tail(85).reset_index(drop=True)
        highs = tail["high"].to_numpy(dtype=float)
        lows = tail["low"].to_numpy(dtype=float)
        closes = tail["close"].to_numpy(dtype=float)
        n = len(tail)
        w = 3
        tol = max(0.18 * atr_val, closes[-1] * 0.0018)

        swing_highs: List[float] = []
        swing_lows: List[float] = []
        for i in range(w, n - w):
            if highs[i] >= np.max(highs[i - w : i + w + 1]) - 1e-9:
                if not swing_highs or abs(highs[i] - swing_highs[-1]) > 0.12 * atr_val:
                    swing_highs.append(float(highs[i]))
            if lows[i] <= np.min(lows[i - w : i + w + 1]) + 1e-9:
                if not swing_lows or abs(lows[i] - swing_lows[-1]) > 0.12 * atr_val:
                    swing_lows.append(float(lows[i]))

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            # Fallback to 2-half comparison
            mid = n // 2
            h1, h2 = float(np.max(highs[:mid])), float(np.max(highs[mid:]))
            l1, l2 = float(np.min(lows[:mid])), float(np.min(lows[mid:]))
        else:
            h1, h2 = swing_highs[-2], swing_highs[-1]
            l1, l2 = swing_lows[-2], swing_lows[-1]

        last_c = float(closes[-1])
        hh = (h2 > h1 + tol) or (last_c > h2 + tol)
        lh = (h2 < h1 - tol) and (last_c <= h2 + tol)
        hl = (l2 > l1 + tol) and (last_c >= l2 - tol)
        ll = (l2 < l1 - tol) or (last_c < l2 - tol)

        if hh and (hl or l2 >= l1 - tol):
            return "HH_HL", "Yükselen Tepe & Dip (HH/HL)", 18.0
        if lh and (ll or h2 <= h1 + tol):
            return "LH_LL", "Alçalan Tepe & Dip (LH/LL)", -18.0
        if lh and hl:
            return "CONVERGING", "Daralan Üçgen / Sıkışma (LH/HL)", 0.0
        if hh and ll:
            return "EXPANDING", "Genişleyen Dalga / Volatil Yapı", 0.0
        return "RANGE", "Yatay Kanal / Dengeli Pivot", 0.0

    def generate_forecast(
        self,
        df: pd.DataFrame,
        order_flow: Optional[OrderFlowIntel] = None,
        htf_score: Optional[float] = None,
        btc_regime_score: Optional[float] = None,
        symbol: str = "BTC/USDT",
        btc_df: Optional[pd.DataFrame] = None,
        sample_capital_usd: float = 1000.0,
        risk_pct: float = 1.0,
        htf_sr_levels: Optional[List[SupportResistanceLevel]] = None,
    ) -> MarketForecast:
        """
        Compute a 6-Layer Dynamic Regime-Weighted Quantitative Forecast (v3.0):
            - Uses the last CLOSED candle (`iloc[-2]` if `iloc[-1]` is still forming) for stable indicator/pattern scoring
            - Dynamically shifts weights between Trend/MoneyFlow and Oscillators/Structure based on ADX
            - Integrates Smart Money Concepts (FVG, Order Blocks, BOS/CHoCH, Liquidity Sweeps) & Liquidation Pools
            - Computes Quantitative Probability Cone (1-sigma/2-sigma) & Barrier Touch Probabilities
            - Incorporates Higher-Timeframe (HTF), BTC Macro Regime & Relative Strength (RS/Beta vs BTC)
            - Runs path-dependent historical backtest validation & non-advisory Position Sizing
        """
        # Use closed candle for stable indicator & pattern evaluation (eliminates live-bar repainting)
        if len(df) >= 2 and "is_closed" in df.columns and not bool(df["is_closed"].iloc[-1]):
            eval_row = df.iloc[-2]
            closed_df = df.iloc[:-1]
        else:
            eval_row = df.iloc[-1]
            closed_df = df

        live_close = float(df["close"].iloc[-1])
        ema20 = float(eval_row["ema_20"])
        ema50 = float(eval_row["ema_50"])
        ema200 = float(eval_row.get("ema_200", ema50))
        rsi = float(eval_row["rsi"]) if pd.notna(eval_row["rsi"]) else 50.0
        pct_b = float(eval_row["bb_pct_b"]) if pd.notna(eval_row["bb_pct_b"]) else 0.5
        bb_squeeze = bool(eval_row.get("bb_squeeze", False))
        atr_val = float(eval_row.get("atr", live_close * 0.012))
        if pd.isna(atr_val) or atr_val <= 0:
            atr_val = live_close * 0.012

        adx_val = float(eval_row.get("adx", 20.0)) if pd.notna(eval_row.get("adx", np.nan)) else 20.0
        hurst_val = float(eval_row.get("hurst_exponent", 0.5)) if pd.notna(eval_row.get("hurst_exponent", np.nan)) else 0.5
        chop_val = float(eval_row.get("choppiness_index", 50.0)) if pd.notna(eval_row.get("choppiness_index", np.nan)) else 50.0
        kalman_price = float(eval_row.get("kalman_trend", live_close)) if pd.notna(eval_row.get("kalman_trend", np.nan)) else live_close
        kalman_slope = float(eval_row.get("kalman_slope", 0.0)) if pd.notna(eval_row.get("kalman_slope", np.nan)) else 0.0
        avwap_high_p = float(eval_row.get("avwap_high", live_close)) if pd.notna(eval_row.get("avwap_high", np.nan)) else live_close
        avwap_low_p = float(eval_row.get("avwap_low", live_close)) if pd.notna(eval_row.get("avwap_low", np.nan)) else live_close

        st_dir = int(eval_row.get("supertrend_dir", 1))
        macd_hist = float(eval_row.get("macd_hist", 0.0)) if pd.notna(eval_row.get("macd_hist", np.nan)) else 0.0
        mfi_val = float(eval_row.get("mfi", 50.0)) if pd.notna(eval_row.get("mfi", np.nan)) else 50.0
        cmf_val = float(eval_row.get("cmf", 0.0)) if pd.notna(eval_row.get("cmf", np.nan)) else 0.0
        obv_bull = bool(eval_row.get("obv", 0.0) >= eval_row.get("obv_ema20", 0.0))
        cvd_bull = bool(eval_row.get("cvd", 0.0) >= eval_row.get("cvd_ema20", 0.0))
        has_real_taker = bool(eval_row.get("has_real_taker_flow", False))
        vwap_val = float(eval_row.get("vwap_20", live_close))

        poc_price = float(df["vp_poc"].iloc[-1]) if "vp_poc" in df.columns else live_close
        vah_price = float(df["vp_vah"].iloc[-1]) if "vp_vah" in df.columns else live_close
        val_price = float(df["vp_val"].iloc[-1]) if "vp_val" in df.columns else live_close

        recent_high = float(df["high"].tail(90).max())
        recent_low = float(df["low"].tail(90).min())
        fib_618_price = recent_high - 0.618 * (recent_high - recent_low)

        notes: List[str] = []

        # ==================================================================
        # LAYER 1: TREND STRUCTURE, DOW SWING SEQUENCE & ZERO-LAG KALMAN (-100 to +100)
        # ==================================================================
        swing_code, swing_structure_tr, swing_boost = self.analyze_swing_structure(closed_df, atr_val)
        candle_anatomy_tr = CandlestickPatternDetector.summarize_candle_anatomy(df)

        t_score = swing_boost
        if live_close > ema20 > ema50:
            t_score += 46.0
            trend_name_tr = f"Yükselen Trend (Fiyat > EMA20 > EMA50 | {swing_structure_tr})"
        elif live_close < ema20 < ema50:
            t_score -= 46.0
            trend_name_tr = f"Düşen Trend (Fiyat < EMA20 < EMA50 | {swing_structure_tr})"
        elif chop_val >= 58.5 and adx_val < 20.0:
            trend_name_tr = f"Yatay / Sıkışma Kanalı ({swing_structure_tr})"
        elif live_close > ema20:
            t_score += 20.0
            trend_name_tr = f"Kısa Vadeli Toparlanma (Fiyat > EMA20 | {swing_structure_tr})"
        else:
            t_score -= 20.0
            trend_name_tr = f"Kısa Vadeli Zayıflama (Fiyat < EMA20 | {swing_structure_tr})"

        # Zero-Lag Kalman Filter confirmation
        if live_close >= kalman_price and kalman_slope >= 0:
            t_score += 12.0
        elif live_close < kalman_price and kalman_slope < 0:
            t_score -= 12.0

        t_score += 12.0 if live_close > ema200 else -12.0

        if st_dir == 1:
            t_score += 22.0
            supertrend_status_tr = "POZİTİF (SuperTrend Alım Yönünde)"
        else:
            t_score -= 22.0
            supertrend_status_tr = "NEGATİF (SuperTrend Satış Yönünde)"

        t_score = float(np.clip(t_score, -100.0, 100.0))

        # ==================================================================
        # LAYER 2: REAL TAKER MONEY FLOW, ABSORPTION, OI MATRIX & SPOT/PERP CVD (-100 to +100)
        # ==================================================================
        mf_score = 0.0
        mf_score += float(np.clip(cmf_val * 190.0, -38.0, 38.0))
        mf_score += 14.0 if cvd_bull else -14.0
        mf_score += 10.0 if obv_bull else -10.0

        if mfi_val >= 55.0 and mfi_val < 80.0:
            mf_score += 14.0
        elif mfi_val <= 45.0 and mfi_val > 20.0:
            mf_score -= 14.0
        elif mfi_val <= 20.0:
            mf_score += 12.0
        elif mfi_val >= 80.0:
            mf_score -= 12.0

        # Check recent 4-bar Limit Order Absorption (Pasif Limit Duvarı Emilimi)
        absorption_status_tr = "Normal Piyasa Akışı (Belirgin Limit Emilimi Yok)"
        if "absorption_signal" in closed_df.columns:
            rec_abs = closed_df["absorption_signal"].tail(4).tolist()
            if "BULL_ABSORPTION" in rec_abs:
                mf_score += 14.0
                absorption_status_tr = "🟢 Kurumsal Alım Emilimi (Pasif Limit Alıcılar Satışı Emdi)"
            elif "BEAR_ABSORPTION" in rec_abs:
                mf_score -= 14.0
                absorption_status_tr = "🔴 Kurumsal Satış Emilimi (Pasif Limit Satıcılar Alışı Emdi)"

        cvd_div_tr, cvd_div_boost = self.detect_cvd_divergences(closed_df)
        mf_score += cvd_div_boost

        oi_regime_tr = "Veri Yok"
        spot_perp_cvd_tr = "Dengeli Spot & Vadeli Akışı"
        if order_flow is not None:
            ob_imb = order_flow.imbalance_net_ratio
            mf_score += float(np.clip(ob_imb * 35.0, -18.0, 18.0))
            oi_regime_tr = order_flow.oi_regime_tr
            spot_perp_cvd_tr = order_flow.spot_vs_perp_cvd_tr
            eff_oi_chg = (
                0.5 * order_flow.oi_change_4h_pct + 0.5 * order_flow.oi_change_24h_pct
                if (order_flow.oi_change_4h_pct is not None and order_flow.oi_change_24h_pct is not None)
                else order_flow.oi_change_24h_pct
            )
            if eff_oi_chg is not None:
                if eff_oi_chg > 1.2:
                    mf_score += 8.0 if live_close >= ema20 else -8.0
                elif eff_oi_chg < -1.2 and live_close < ema20:
                    mf_score += 5.0  # Long capitulation / exhaustion
            if order_flow.futures_taker_buy_sell_ratio is not None:
                if order_flow.futures_taker_buy_sell_ratio >= 1.05:
                    mf_score += 9.0
                elif order_flow.futures_taker_buy_sell_ratio <= 0.95:
                    mf_score -= 9.0

        mf_score = float(np.clip(mf_score, -100.0, 100.0))
        flow_src_tag = "Gerçek Taker CVD" if has_real_taker else "Hacim Akışı"

        if cmf_val > 0.04 and cvd_bull:
            money_flow_status_tr = f"NET PARA GİRİŞİ ({flow_src_tag}: Pozitif | CMF: {cmf_val:+.2f} | MFI: {mfi_val:.1f})"
        elif cmf_val < -0.04 and (not cvd_bull):
            money_flow_status_tr = f"NET PARA ÇIKIŞI ({flow_src_tag}: Negatif | CMF: {cmf_val:+.2f} | MFI: {mfi_val:.1f})"
        elif cvd_bull or cmf_val >= 0:
            money_flow_status_tr = f"Dengeli / Hafif Alıcı Akışı (CMF: {cmf_val:+.2f} | MFI: {mfi_val:.1f})"
        else:
            money_flow_status_tr = f"Dengeli / Hafif Satıcı Akışı (CMF: {cmf_val:+.2f} | MFI: {mfi_val:.1f})"

        # ==================================================================
        # LAYER 3: MOMENTUM & RSI DIVERGENCE (-100 to +100)
        # ==================================================================
        m_score = 0.0
        is_strong_trend = (adx_val >= 25.0) or (hurst_val >= 0.56 and chop_val <= 44.0)
        if rsi <= 30.0:
            m_score += 20.0 if (is_strong_trend and t_score < -40) else 38.0
            momentum_tr = f"Aşırı Satım Bölgesi — Dip Tepkisi Adayı (RSI: {rsi:.1f})"
        elif rsi >= 70.0:
            m_score -= 15.0 if (is_strong_trend and t_score > 40) else 38.0
            momentum_tr = f"Aşırı Alım Bölgesi — Kâr Satışı / Düzeltme Riski (RSI: {rsi:.1f})"
        elif rsi >= 53.0:
            m_score += 28.0
            momentum_tr = f"Pozitif Momentum — Alıcılar Üstün (RSI: {rsi:.1f})"
        elif rsi <= 47.0:
            m_score -= 28.0
            momentum_tr = f"Negatif Momentum — Satıcılar Üstün (RSI: {rsi:.1f})"
        else:
            momentum_tr = f"Nötr / Dengeli Momentum (RSI: {rsi:.1f})"

        prev_macd_hist = float(closed_df["macd_hist"].iloc[-2]) if len(closed_df) >= 2 and pd.notna(closed_df["macd_hist"].iloc[-2]) else macd_hist
        if macd_hist > 0 and macd_hist >= prev_macd_hist:
            m_score += 25.0
        elif macd_hist > 0:
            m_score += 10.0
        elif macd_hist < 0 and macd_hist <= prev_macd_hist:
            m_score -= 25.0
        else:
            m_score -= 10.0

        divergences = self.detect_rsi_divergences(closed_df)
        divergence_status_tr = "Aktif RSI Uyumsuzluğu Yok"
        if divergences:
            latest_div = divergences[-1]
            if (len(closed_df) - 1 - latest_div.idx_end) <= 18:
                if latest_div.div_type == "BULLISH_DIV":
                    m_score += 40.0
                    divergence_status_tr = f"🟢 {latest_div.label_tr} (Fiyat Düşerken RSI Yükseldi)"
                else:
                    m_score -= 40.0
                    divergence_status_tr = f"🔴 {latest_div.label_tr} (Fiyat Yükselirken RSI Düştü)"

        m_score = float(np.clip(m_score, -100.0, 100.0))

        # ==================================================================
        # LAYER 4: TIME-DECAYED VOLUME PROFILE (POC), ANCHORED VWAP & SMC (-100 to +100)
        # ==================================================================
        s_score = 0.0
        s_score += 16.0 if live_close >= vwap_val else -16.0
        s_score += 18.0 if live_close >= poc_price else -18.0

        # Anchored VWAP (Institutional Cost Basis from Major High & Low)
        if live_close >= avwap_low_p and live_close >= avwap_high_p:
            s_score += 12.0
        elif live_close < avwap_low_p and live_close < avwap_high_p:
            s_score -= 12.0

        squeeze_tag = " [Bollinger Sıkışması — Sert Kırılım Hazırlığı]" if bb_squeeze else ""
        if pct_b < 0.10:
            bb_status_tr = f"Alt Bollinger Bandında — İstatistiksel Ucuz Bölge (%B: %{pct_b*100:.0f}){squeeze_tag}"
            s_score += 24.0
        elif pct_b > 0.90:
            bb_status_tr = f"Üst Bollinger Bandında — İstatistiksel Pahalı Bölge (%B: %{pct_b*100:.0f}){squeeze_tag}"
            s_score -= 24.0
        elif pct_b >= 0.55:
            bb_status_tr = f"Bollinger Orta Bandı Üzerinde — Pozitif Kanal (%B: %{pct_b*100:.0f}){squeeze_tag}"
            s_score += 14.0
        elif pct_b <= 0.45:
            bb_status_tr = f"Bollinger Orta Bandı Altında — Zayıf Kanal (%B: %{pct_b*100:.0f}){squeeze_tag}"
            s_score -= 14.0
        else:
            bb_status_tr = f"Bollinger Denge Kanalında (%B: %{pct_b*100:.0f}){squeeze_tag}"

        # Pre-compute SMC structure events & Order Blocks for Layer 4 + S/R strength scoring
        smc_engine = SmartMoneyEngine()
        smc_events, _, _ = smc_engine.detect_structure_and_sweeps(df)
        smc_obs = smc_engine.detect_order_blocks(df)

        supports, resistances = self.detect_support_resistance(
            df,
            window=6,
            max_levels=3,
            order_flow=order_flow,
            order_blocks=smc_obs,
            htf_sr_levels=htf_sr_levels,
        )
        nearest_sup = supports[0].price if supports else (live_close - 2.0 * atr_val)
        nearest_res = resistances[0].price if resistances else (live_close + 2.0 * atr_val)
        sup_tier_tr = supports[0].tier_tr if supports else "🟢 Sıradan Destek"
        sup_score = supports[0].strength_score if supports else 35.0
        sup_reason_tr = " + ".join(supports[0].confluence_tags[:2]) if (supports and supports[0].confluence_tags) else "Ara Pivot"
        res_tier_tr = resistances[0].tier_tr if resistances else "🔴 Sıradan Direnç"
        res_score = resistances[0].strength_score if resistances else 35.0
        res_reason_tr = " + ".join(resistances[0].confluence_tags[:2]) if (resistances and resistances[0].confluence_tags) else "Ara Pivot"
        strongest_sup_obj = max(supports, key=lambda x: x.strength_score) if supports else None
        strongest_res_obj = max(resistances, key=lambda x: x.strength_score) if resistances else None

        # Module 3: Detect Confirmed S/R Breakouts, Flip Retests & SFP Traps on Closed Candles
        sr_action_type, sr_action_status_tr, sr_action_price, sr_action_time, sr_action_boost = self.detect_retest_and_sfp(
            closed_df=closed_df,
            live_close=live_close,
            supports=supports,
            resistances=resistances,
            atr_val=atr_val,
        )
        s_score += sr_action_boost

        # Compute RVOL of last closed candle & "How Does a Breakout Happen?" technical rule guide
        vol_arr_c = closed_df["volume"].to_numpy(dtype=float) if "volume" in closed_df.columns and len(closed_df) >= 2 else np.ones(5)
        avg_v20_c = max(float(np.mean(vol_arr_c[-21:-1])) if len(vol_arr_c) >= 5 else float(np.mean(vol_arr_c)), 1e-9)
        sr_breakout_rvol = float(vol_arr_c[-1]) / avg_v20_c
        res_break_band = resistances[0].band_high if resistances else (nearest_res * 1.002)
        sup_break_band = supports[0].band_low if supports else (nearest_sup * 0.998)
        p_fmt_g = ",.4f" if live_close < 10.0 else ",.2f"
        sr_breakout_guide_tr = (
            f"📈 Direnç Kırılım Şartı: {format(res_break_band, p_fmt_g)} USDT Üstü Mum Gövde Kapanışı + Hacim (RVOL ≥ 1.20x) | "
            f"📉 Destek Kırılım Şartı: {format(sup_break_band, p_fmt_g)} USDT Altı Mum Gövde Kapanışı (Sadece iğne atıp dönerse = 🪤 Sahte Kırılım / SFP)"
        )

        # Module 4: Detect Automatic Dynamic Trendlines & Trendline Breakouts on Closed Candles
        trendlines, trendline_boost = self.detect_dynamic_trendlines(
            closed_df=closed_df,
            live_close=live_close,
            atr_val=atr_val,
        )
        t_score = float(np.clip(t_score + trendline_boost, -100.0, 100.0))

        dist_to_sup = max(live_close - nearest_sup, atr_val * 0.1)
        dist_to_res = max(nearest_res - live_close, atr_val * 0.1)
        rr_ratio = dist_to_res / dist_to_sup
        if rr_ratio >= 1.7:
            s_score += 18.0
        elif rr_ratio <= 0.58:
            s_score -= 18.0

        if smc_events:
            last_ev = smc_events[-1]
            if last_ev.event_type in ("BULL_BOS", "BULL_CHOCH", "BULL_SWEEP"):
                s_score += 18.0
            elif last_ev.event_type in ("BEAR_BOS", "BEAR_CHOCH", "BEAR_SWEEP"):
                s_score -= 18.0

        s_score = float(np.clip(s_score, -100.0, 100.0))

        # ==================================================================
        # LAYER 5: CLOSED-CANDLE PATTERN CONFLUENCE (-100 to +100)
        # ==================================================================
        p_score = 0.0
        recent_bars = closed_df.tail(4)
        last_pattern_tr = "Son kapanan mumlarda onaylı dönüş formasyonu yok"
        for _, r in recent_bars.iloc[::-1].iterrows():
            if r["primary_pattern"]:
                last_pattern_tr = f"{r['pattern_tr_name']}: {r['pattern_meaning_tr']}"
                break

        for weight, (_, r) in zip([0.35, 0.55, 0.80, 1.0], recent_bars.iterrows()):
            sig = r["signal_type"]
            if sig == "BULLISH_REVERSAL":
                p_score += 55.0 * weight
            elif sig == "BEARISH_REVERSAL":
                p_score -= 55.0 * weight
            elif sig == "BULLISH_PATTERN":
                p_score += 25.0 * weight
            elif sig == "BEARISH_PATTERN":
                p_score -= 25.0 * weight

        p_score = float(np.clip(p_score, -100.0, 100.0))

        # ==================================================================
        # LAYER 6: MACRO BTC REGIME, RELATIVE STRENGTH (RS) & HTF ALIGNMENT
        # ==================================================================
        rs_metrics = smc_engine.compute_relative_strength_vs_btc(df, btc_df, symbol)
        macro_score = 0.0
        macro_parts = []
        if htf_score is not None:
            macro_score += 0.55 * htf_score
            htf_dir = "Pozitif" if htf_score >= 15 else ("Negatif" if htf_score <= -15 else "Nötr")
            macro_parts.append(f"Üst Zaman Dilimi (HTF): {htf_dir} ({htf_score:+.0f})")
        if btc_regime_score is not None:
            macro_score += 0.30 * btc_regime_score if htf_score is not None else 0.75 * btc_regime_score
            btc_dir = "Pozitif" if btc_regime_score >= 15 else ("Negatif" if btc_regime_score <= -15 else "Nötr")
            macro_parts.append(f"BTC Makro Rejim: {btc_dir} ({btc_regime_score:+.0f})")
        if not symbol.startswith("BTC/") and btc_df is not None:
            macro_score += 0.15 * rs_metrics.alpha_score
            macro_parts.append(f"BTC Göreceli Güç (RS): {rs_metrics.rs_ratio_change_pct:+.1f}% (Beta: {rs_metrics.beta_vs_btc:.2f})")

        macro_score = float(np.clip(macro_score, -100.0, 100.0))
        macro_context_tr = " | ".join(macro_parts) if macro_parts else "Bağımsız Zaman Dilimi Analizi"

        # ==================================================================
        # DYNAMIC REGIME WEIGHTING (ADX + HURST EXPONENT + CHOPPINESS INDEX)
        # ==================================================================
        has_macro = (htf_score is not None) or (btc_regime_score is not None) or (btc_df is not None and not symbol.startswith("BTC/"))
        if (adx_val >= 25.0 and chop_val <= 54.0) or (hurst_val >= 0.56 and chop_val <= 46.0):
            regime_tr = f"Kalıcı Trend Rejimi (ADX: {adx_val:.1f} | Hurst: {hurst_val:.2f} | CHOP: {chop_val:.1f})"
            w_trend, w_mf, w_mom, w_struct, w_pat, w_mac = (
                (0.32, 0.25, 0.14, 0.09, 0.08, 0.12) if has_macro else (0.36, 0.28, 0.16, 0.10, 0.10, 0.0)
            )
        elif adx_val <= 19.0 or chop_val >= 58.5 or hurst_val <= 0.44:
            regime_tr = f"Yatay / Ortalamaya Dönüş Rejimi (ADX: {adx_val:.1f} | Hurst: {hurst_val:.2f} | CHOP: {chop_val:.1f})"
            w_trend, w_mf, w_mom, w_struct, w_pat, w_mac = (
                (0.14, 0.22, 0.24, 0.20, 0.10, 0.10) if has_macro else (0.16, 0.24, 0.26, 0.22, 0.12, 0.0)
            )
        else:
            regime_tr = f"Dengeli Piyasa Rejimi (ADX: {adx_val:.1f} | Hurst: {hurst_val:.2f} | CHOP: {chop_val:.1f})"
            w_trend, w_mf, w_mom, w_struct, w_pat, w_mac = (
                (0.26, 0.24, 0.18, 0.12, 0.08, 0.12) if has_macro else (0.30, 0.25, 0.20, 0.15, 0.10, 0.0)
            )

        composite = (
            w_trend * t_score
            + w_mf * mf_score
            + w_mom * m_score
            + w_struct * s_score
            + w_pat * p_score
            + w_mac * macro_score
        )
        # Dampen false directional conviction when market is in extreme choppy noise (CHOP > 61.8 and Hurst ~ 0.50)
        if chop_val >= 61.8 and 0.46 <= hurst_val <= 0.54:
            composite *= 0.85

        # Structural Trend & Regime Integrity Filter (prevents counter-trend oscillator bounces from flipping trend label)
        has_bull_break = (
            sr_action_type in ("BULL_SR_BREAKOUT", "BULL_SFP", "BULL_RETEST")
            or (trendlines is not None and trendlines.breakout_status == "BULL_BREAKOUT")
            or bool(smc_events and smc_events[-1].event_type in ("BULL_BOS", "BULL_CHOCH"))
        )
        has_bear_break = (
            sr_action_type in ("BEAR_SR_BREAKDOWN", "BEAR_SFP", "BEAR_RETEST")
            or (trendlines is not None and trendlines.breakout_status == "BEAR_BREAKDOWN")
            or bool(smc_events and smc_events[-1].event_type in ("BEAR_BOS", "BEAR_CHOCH"))
        )
        if t_score <= -35.0 and live_close < ema50 and not has_bull_break and composite > 12.0:
            composite = min(composite, 12.0)
        elif t_score >= 35.0 and live_close > ema50 and not has_bear_break and composite < -12.0:
            composite = max(composite, -12.0)
        elif chop_val >= 59.5 and adx_val < 20.0 and not has_bull_break and not has_bear_break:
            composite *= 0.68

        composite = float(np.clip(composite, -100.0, 100.0))

        # Canonical Trend State Classification: UPTREND, DOWNTREND, SIDEWAYS
        if chop_val >= 59.0 and adx_val < 19.5 and abs(composite) < 22.0 and not has_bull_break and not has_bear_break:
            trend_state = "SIDEWAYS"
        elif composite >= 15.0 and (t_score >= 0.0 or has_bull_break or live_close >= ema20):
            trend_state = "UPTREND"
        elif composite <= -15.0 and (t_score <= 0.0 or has_bear_break or live_close <= ema20):
            trend_state = "DOWNTREND"
        else:
            trend_state = "SIDEWAYS"

        active_layers = [t_score, mf_score, m_score, s_score, p_score] + ([macro_score] if has_macro else [])
        layer_arr = np.array(active_layers)
        if abs(composite) < 10.0:
            confidence_pct = 50.0
        else:
            same_sign = np.sum(np.sign(layer_arr) == np.sign(composite))
            raw_conf = 38.0 + (same_sign / len(layer_arr)) * 46.0 + (abs(composite) * 0.16)
            if chop_val >= 61.8:
                raw_conf -= 6.0  # Penalize overconfidence in choppy sideways regime
            confidence_pct = float(np.clip(raw_conf, 35.0, 96.0))

        # Historical Path-Dependent & Fee-Adjusted Signal Backtest Validation
        bt_stats = self.backtest_reversal_signals(closed_df, horizon=5)

        if trend_state == "UPTREND":
            verdict_tr = (
                "GÜÇLÜ YÜKSELEN TREND (ALICI ÜSTÜNLÜĞÜ)"
                if composite >= 42.0
                else "YÜKSELEN TREND / POZİTİF YAPI"
            )
        elif trend_state == "DOWNTREND":
            verdict_tr = (
                "GÜÇLÜ DÜŞEN TREND (SATICI ÜSTÜNLÜĞÜ)"
                if composite <= -42.0
                else "DÜŞEN TREND / SATIŞ BASKILI YAPI"
            )
        else:
            if composite >= 15.0:
                verdict_tr = "YATAY / DÜZELTME İÇİNDE YUKARI TEPKİ ARAYIŞI"
            elif composite <= -15.0:
                verdict_tr = "YATAY / DÜZELTME İÇİNDE AŞAĞI BASKI"
            else:
                verdict_tr = "YATAY TREND / KARARSIZ DENGE KANALI"

        p_fmt = ",.4f" if live_close < 10.0 else ",.2f"
        sup_str = f"{format(nearest_sup, p_fmt)} USDT"
        res_str = f"{format(nearest_res, p_fmt)} USDT"
        poc_str = f"{format(poc_price, p_fmt)} USDT"

        # Plain-Language Beginner Roadmap (Zero Jargon, Strict YTD)
        sup_kind = "güçlü destek" if (supports and supports[0].is_strong) else "ara destek"
        res_kind = "güçlü direnç" if (resistances and resistances[0].is_strong) else "ara direnç"
        if trend_state == "UPTREND":
            plain_guidance_tr = (
                f"Fiyat {swing_structure_tr} yapısı ve alıcı üstünlüğüyle yükselen trendde ilerliyor. "
                f"Aşağıda {sup_str} ({sup_kind}) korundukça yukarıda {res_str} ({res_kind}) bölgesi izlenir; "
                f"bu tavan hacimli aşılırsa yükseliş ivme kazanır (YTD)."
            )
        elif trend_state == "DOWNTREND":
            plain_guidance_tr = (
                f"Fiyat {swing_structure_tr} yapısı ve satıcı baskısıyla düşen trendde seyrediyor. "
                f"Yukarıda {res_str} ({res_kind}) ve {format(ema20, p_fmt)} ortalaması aşılmadıkça baskı sürer; "
                f"aşağıda {sup_str} ({sup_kind}) kırılırsa düşüş hızlanabilir (YTD)."
            )
        else:
            plain_guidance_tr = (
                f"Fiyat net bir yön seçmeden {sup_str} ({sup_kind}) ile {res_str} ({res_kind}) arasında yatay dengeleniyor. "
                f"Ara bölgede acele edilmemeli; {res_str} üstü mum kapanışı yükselişi, {sup_str} altı kapanış ise düşüşü başlatır (YTD)."
            )

        bull_trigger = max(ema20, live_close) if live_close < ema20 else live_close
        bull_tp1 = min(nearest_res, live_close + 1.15 * atr_val) if nearest_res > live_close * 1.003 else (live_close + 1.15 * atr_val)
        bull_target = max(nearest_res, bull_tp1 + 0.85 * atr_val) if nearest_res > live_close * 1.004 else (live_close + 2.2 * atr_val)
        bear_invalidation = min(nearest_sup, live_close - 1.5 * atr_val)

        bear_tp1 = max(nearest_sup, live_close - 1.15 * atr_val) if nearest_sup < live_close * 0.997 else (live_close - 1.15 * atr_val)
        bear_target = min(supports[1].price if len(supports) > 1 else (nearest_sup - 1.8 * atr_val), bear_tp1 - 0.85 * atr_val)
        short_stop = max(nearest_res, live_close + 1.5 * atr_val)

        if composite >= 15.0:
            active_direction = "BULLISH"
            tp1_price = bull_tp1
            tp2_price = bull_target
            stop_price = bear_invalidation
        elif composite <= -15.0:
            active_direction = "BEARISH"
            tp1_price = bear_tp1
            tp2_price = bear_target
            stop_price = short_stop
        else:
            active_direction = "NEUTRAL"
            tp1_price = bull_tp1 if composite >= 0 else bear_tp1
            tp2_price = bull_target if composite >= 0 else bear_target
            stop_price = bear_invalidation if composite >= 0 else short_stop

        # Full Smart Money Report (FVG, OB, BOS/CHoCH/Sweeps, Multi-Tier Liquidation Pools, EWMA+Parkinson Cone, RS)
        # Pass direction-aware target & stop into analyze so Bearish setups also compute accurate first-passage win probability!
        cone_bull_b = bull_target if composite >= 0 else short_stop
        cone_bear_b = bear_invalidation if composite >= 0 else bear_target
        smc_report = smc_engine.analyze(
            df=df,
            composite_score=composite,
            bull_target=cone_bull_b,
            bear_invalid=cone_bear_b,
            symbol=symbol,
            btc_df=btc_df,
        )

        prob_bull_pct = smc_report.probability_cone.prob_touch_bull_target_pct
        prob_bear_pct = smc_report.probability_cone.prob_touch_bear_invalid_pct
        raw_prob_up_first = smc_report.probability_cone.prob_win_before_stop_pct
        prob_win_first = raw_prob_up_first if composite >= 0 else (100.0 - raw_prob_up_first)

        # Non-Advisory Position Sizing & Half-Kelly Risk Plan
        effective_win_prob = (
            0.55 * bt_stats.win_rate_pct + 0.45 * prob_win_first
            if bt_stats.total_signals >= 5
            else prob_win_first
        )
        if composite >= 0:
            risk_plan = smc_engine.calculate_position_sizing(
                entry_price=live_close,
                stop_price=bear_invalidation,
                target_price=bull_target,
                capital_usd=sample_capital_usd,
                risk_pct=risk_pct,
                win_prob_pct=effective_win_prob,
            )
        else:
            risk_plan = smc_engine.calculate_position_sizing(
                entry_price=live_close,
                stop_price=short_stop,
                target_price=bear_target,
                capital_usd=sample_capital_usd,
                risk_pct=risk_pct,
                win_prob_pct=effective_win_prob,
            )

        # ==================================================================
        # v6.0: WHALE ACCUMULATION / DISTRIBUTION BAROMETER (0..100),
        #       GLOBAL SESSION CLOCK, VOLATILITY SQUEEZE ENERGY & 3-STEP ALARM PLAN
        # ==================================================================
        whale_raw = 50.0 + 0.35 * mf_score
        if "BULL_ABSORPTION" in absorption_status_tr or "Alım Emilimi" in absorption_status_tr:
            whale_raw += 12.0
        elif "Satış Emilimi" in absorption_status_tr:
            whale_raw -= 12.0
        if cvd_div_boost > 0:
            whale_raw += 10.0
        elif cvd_div_boost < 0:
            whale_raw -= 10.0
        if smc_events and "SWEEP" in smc_events[-1].event_type:
            whale_raw += 9.0 if "BULL" in smc_events[-1].event_type else -9.0
        whale_accumulation_score = float(np.clip(whale_raw, 5.0, 96.0))

        if whale_accumulation_score >= 66.0:
            whale_status_tr = f"🟢 Güçlü Balina Toplaması (Skor: {whale_accumulation_score:.0f}/100 — Büyük Oyuncular Mal Topluyor)"
        elif whale_accumulation_score >= 54.0:
            whale_status_tr = f"🟢 Hafif Balina Alım Eğilimi (Skor: {whale_accumulation_score:.0f}/100 — Alıcılar Üstün)"
        elif whale_accumulation_score <= 34.0:
            whale_status_tr = f"🔴 Güçlü Balina Dağıtımı / Satışı (Skor: {whale_accumulation_score:.0f}/100 — Büyük Oyuncular Mal Çıkıyor)"
        elif whale_accumulation_score <= 46.0:
            whale_status_tr = f"🔴 Hafif Balina Satış Eğilimi (Skor: {whale_accumulation_score:.0f}/100 — Satıcılar Üstün)"
        else:
            whale_status_tr = f"⚪ Dengeli Balina Aktivitesi (Skor: {whale_accumulation_score:.0f}/100 — Beklemede)"

        # Global Session & Liquidity Clock (evaluated in UTC)
        now_utc = pd.Timestamp.now(tz="UTC")
        is_weekend = now_utc.weekday() >= 5
        hr_utc = now_utc.hour
        if is_weekend:
            session_status_tr = "⚠️ Hafta Sonu Piyasası (Kurumsal Hacim Düşük — Ani İğne / Tuzak Kırılım Riski Yüksek)"
        elif 13 <= hr_utc < 17:
            session_status_tr = "🔥 Londra + New York Seans Kesişimi (Günün En Yüksek Kurumsal Hacim & Gerçek Trend Saati)"
        elif 7 <= hr_utc < 13:
            session_status_tr = "🇬🇧 Avrupa / Londra Seansı (Kurumsal Likidite Açık — Trend Hareketleri Güçlü)"
        elif 17 <= hr_utc < 22:
            session_status_tr = "🇺🇸 ABD / New York Seansı (Yüksek Volatilite & Wall Street Akışı)"
        else:
            session_status_tr = "🌏 Asya Seansı (Orta/Düşük Likidite — Destek ve Direnç Arası Yatay Hareket Yaygın)"

        # Volatility Squeeze Energy (0-100%) & Expected Breakout Magnitude
        bb_w_series = df["bb_width"].dropna() if "bb_width" in df.columns else pd.Series([2.0])
        if len(bb_w_series) >= 15:
            curr_bw = float(bb_w_series.iloc[-1])
            bw_max = float(bb_w_series.tail(60).max())
            bw_min = float(bb_w_series.tail(60).min())
            bw_comp = 1.0 - ((curr_bw - bw_min) / max(bw_max - bw_min, 1e-6))
            squeeze_energy_pct = float(np.clip(bw_comp * 75.0 + (25.0 if bb_squeeze else 0.0), 5.0, 98.0))
        else:
            squeeze_energy_pct = 50.0

        expected_breakout_move_pct = float(np.clip((2.4 * atr_val / max(live_close, 1e-9)) * 100.0, 0.5, 25.0))
        if squeeze_energy_pct >= 72.0:
            squeeze_status_tr = (
                f"💥 Barut Fıçısı / Yüksek Sıkışma (%{squeeze_energy_pct:.0f} Doluluk) — "
                f"Yakında ±%{expected_breakout_move_pct:.1f} Büyüklüğünde Sert Kırılım Beklenebilir!"
            )
        elif squeeze_energy_pct >= 45.0:
            squeeze_status_tr = (
                f"⚡ Normal Enerji Birikimi (%{squeeze_energy_pct:.0f}) — "
                f"Kırılımda Beklenen Ortalama Dalga Boyu: ±%{expected_breakout_move_pct:.1f}"
            )
        else:
            squeeze_status_tr = (
                f"🌊 Hareket Başlamış / Sıkışma Çözülmüş (%{squeeze_energy_pct:.0f}) — "
                f"Dalga Boyu: ±%{expected_breakout_move_pct:.1f}"
            )

        # ==================================================================
        # BUILD PERPETUAL FUTURES SETUP FIRST SO TARGETS, STOPS, RISK PLAN &
        # 5-CRITERIA READINESS ARE 100% SYNCHRONIZED (ZERO CONTRADICTION)
        # ==================================================================
        futures_setup = self._build_futures_setup_report(
            live_close=live_close,
            composite=composite,
            t_score=t_score,
            mf_score=mf_score,
            htf_score=htf_score,
            chop_val=chop_val,
            hurst_val=hurst_val,
            atr_val=atr_val,
            ema20=ema20,
            kalman_price=kalman_price,
            poc_price=poc_price,
            vah_price=vah_price,
            val_price=val_price,
            avwap_low_p=avwap_low_p,
            avwap_high_p=avwap_high_p,
            nearest_sup=nearest_sup,
            nearest_res=nearest_res,
            supports=supports,
            resistances=resistances,
            cmf_val=cmf_val,
            whale_score=whale_accumulation_score,
            squeeze_pct=squeeze_energy_pct,
            smc_report=smc_report,
            order_flow=order_flow,
            sr_action_type=sr_action_type,
            sr_action_status_tr=sr_action_status_tr,
            trendlines=trendlines,
        )

        # Synchronize canonical TP1 / TP2 / Stop & Risk Plan with Futures Setup when a valid setup exists
        if futures_setup and futures_setup.direction in ("LONG", "SHORT") and futures_setup.tp1_price > 0 and futures_setup.stop_price > 0:
            tp1_price = futures_setup.tp1_price
            tp2_price = futures_setup.tp2_price
            stop_price = futures_setup.stop_price
            if futures_setup.is_tradeable:
                active_direction = "BULLISH" if futures_setup.direction == "LONG" else "BEARISH"
            risk_plan = smc_engine.calculate_position_sizing(
                entry_price=futures_setup.entry_price if futures_setup.entry_price > 0 else live_close,
                stop_price=stop_price,
                target_price=tp2_price,
                capital_usd=sample_capital_usd,
                risk_pct=risk_pct,
                win_prob_pct=effective_win_prob,
            )

        # 3-Step Action & Alarm Level Guide (Step A: Breakout, Step B: Pullback/Support, Step C: Invalidation)
        pullback_zone = max(nearest_sup, min(poc_price, avwap_low_p)) if nearest_sup < live_close else nearest_sup
        breakout_lvl = max(bull_trigger, kalman_price) if composite >= 0 else min(nearest_sup, kalman_price)
        if composite >= 15.0:
            step_a_breakout_tr = f"🟢 <b>1. Kırılım Teyit Alarmı:</b> Fiyat <b>{format(breakout_lvl, p_fmt)} USDT</b> üzerinde kalıcı oldukça hedef <b>{format(tp1_price, p_fmt)}</b> ve <b>{format(tp2_price, p_fmt)} USDT</b>."
            step_b_pullback_tr = f"🟢 <b>2. Ucuzdan (Geri Çekilmede) Takip Bölgesi:</b> Fiyat dinlenirse en güçlü alıcı/destek pususu <b>{format(pullback_zone, p_fmt)} – {sup_str}</b> aralığıdır."
            step_c_invalidation_tr = f"🔴 <b>3. Tehlike / Kaçış Alarmı (Stop):</b> Fiyat <b>{format(stop_price, p_fmt)} USDT</b> altına inerse yükseliş senaryosu iptal olur."
        elif composite <= -15.0:
            step_a_breakout_tr = f"🔴 <b>1. Düşüş Devam Seviyesi:</b> Fiyat <b>{format(ema20, p_fmt)} USDT</b> altında kaldıkça aşağıda <b>{format(tp1_price, p_fmt)}</b> ve <b>{format(tp2_price, p_fmt)} USDT</b> hedeflenir."
            step_b_pullback_tr = f"🟡 <b>2. Tepki Yükselişinde Satış Direnci:</b> Olası yukarı tepkilerde <b>{res_str}</b> tavan bölgesi güçlü satış duvarıdır."
            step_c_invalidation_tr = f"🟢 <b>3. Düşüş İptal / Trend Dönüş Alarmı:</b> Fiyat <b>{format(stop_price, p_fmt)} USDT</b> üzerine çıkarsa düşüş baskısı biter."
        else:
            step_a_breakout_tr = f"🟢 <b>1. Yukarı Kırılım Alarmı:</b> Yükselişin başlaması için <b>{res_str}</b> tavanının hacimli aşılması beklenmeli."
            step_b_pullback_tr = f"🟢 <b>2. Aşağıda Güvenli Taban Alarmı:</b> Geri çekilmede <b>{sup_str}</b> taban bölgesi alıcıların savunma hattıdır."
            step_c_invalidation_tr = f"🔴 <b>3. Aşağı Kırılım Tehlike Alarmı:</b> <b>{format(bear_invalidation, p_fmt)} USDT</b> altı kapanışlarda satış hızlanır."

        vp_dict = TechnicalIndicators.compute_volume_profile(df, bins=24, time_decay=True)
        vp_centers = [float(x) for x in vp_dict["bin_centers"]]
        vp_vols = [float(x) for x in vp_dict["bin_volumes"]]

        # ==================================================================
        # 5-CRITERIA TRADE READINESS TRAFFIC LIGHT (0/5 to 5/5)
        # ==================================================================
        chk1_ok = abs(composite) >= 18.0 and (np.sign(composite) == np.sign(t_score))
        chk1_desc = (
            f"Yön puanı ({composite:+.0f}) ve trend ortalamaları aynı yönde netleşti."
            if chk1_ok
            else f"Fiyat henüz kararsız bölgede ({composite:+.0f}/100) veya ortalamalarla çelişiyor."
        )

        if htf_score is not None:
            chk2_ok = (abs(htf_score) < 12.0) or (np.sign(htf_score) == np.sign(composite) and abs(composite) >= 12.0)
            chk2_desc = (
                f"Üst zaman dilimi ({htf_score:+.0f}) mevcut yönü destekliyor (Ters akıntı yok)."
                if chk2_ok
                else f"Dikkat: Üst zaman dilimi ({htf_score:+.0f}) ile mevcut yön ters düşüyor!"
            )
        else:
            chk2_ok = abs(t_score) >= 25.0
            chk2_desc = "Ana zaman dilimi trend yapısı kendi içinde tutarlı." if chk2_ok else "Ana zaman diliminde trend henüz zayıf."

        chk3_ok = (composite >= 0 and (cmf_val > 0.01 or cvd_bull or cvd_div_boost > 0)) or (
            composite < 0 and (cmf_val < -0.01 or (not cvd_bull) or cvd_div_boost < 0)
        )
        chk3_desc = (
            f"Gerçek nakit akışı (CMF: {cmf_val:+.2f}) fiyat yönünü onaylıyor."
            if chk3_ok
            else f"Para akışı (CMF: {cmf_val:+.2f}) henüz fiyat hareketini tam desteklemiyor."
        )

        chk4_ok = chop_val < 59.5
        chk4_desc = (
            f"Piyasa yatay testere sıkışmasında değil (CHOP: {chop_val:.1f} < 60)."
            if chk4_ok
            else f"Dikkat: Piyasa şu an dar alanda testere/sıkışma içinde (CHOP: {chop_val:.1f})."
        )

        active_rr = futures_setup.rr_ratio if (futures_setup and futures_setup.rr_ratio > 0) else (risk_plan.risk_reward_ratio if risk_plan else 1.0)
        chk5_ok = bool(futures_setup and futures_setup.is_tradeable and active_rr >= 1.35)
        if chk5_ok:
            chk5_desc = f"Destek/Direnç önü açık ve Kazanç/Risk oranı avantajlı (1:{active_rr:.2f})."
        elif futures_setup and futures_setup.risk_warnings_tr:
            chk5_desc = futures_setup.risk_warnings_tr[0]
        else:
            chk5_desc = f"Hedef mesafesi Stop mesafesine göre dar ({active_rr:.2f}R < 1.35R) veya direnç/destek çok yakın."

        readiness_checks: List[Tuple[str, bool, str]] = [
            ("1. Yön & Trend Netliği", bool(chk1_ok), chk1_desc),
            ("2. Üst Zaman Dilimi (Ana Akıntı) Uyumu", bool(chk2_ok), chk2_desc),
            ("3. Gerçek Nakit & Balina Desteği", bool(chk3_ok), chk3_desc),
            ("4. Testere / Sıkışma Filtresi", bool(chk4_ok), chk4_desc),
            ("5. Destek/Direnç Alanı & R:R Oranı", bool(chk5_ok), chk5_desc),
        ]
        readiness_score_5 = sum(1 for _, ok, _ in readiness_checks if ok)
        if futures_setup and futures_setup.is_tradeable and readiness_score_5 >= 4:
            readiness_verdict_tr = f"🟢 YÜKSEK KALİTELİ KURULUM ({readiness_score_5}/5 Kriter Onaylı — Vadeli Güven: {futures_setup.confidence_score:.0f}/100)"
        elif futures_setup and futures_setup.is_tradeable and readiness_score_5 >= 3:
            readiness_verdict_tr = f"🟡 ORTA KALİTELİ KURULUM ({readiness_score_5}/5 Kriter Onaylı — Vadeli Güven: {futures_setup.confidence_score:.0f}/100)"
        else:
            readiness_verdict_tr = f"🔴 BEKLE-GÖR / RİSK KALKANI AKTİF ({readiness_score_5}/5 Kriter Onaylı — Şu An İşlem Önerilmez)"

        bullish_scenario_tr = (
            f"Fiyat {sup_str} destek bölgesi (Mıknatıs POC: {poc_str} | Dip Alıcı Maliyeti: {format(avwap_low_p, p_fmt)}) üzerinde tutunduğu sürece; "
            f"<b>1. Güvenli Kâr Hedefi (TP1): {format(tp1_price if composite >= 0 else bull_tp1, p_fmt)} USDT</b>, "
            f"<b>2. Ana Yükseliş Hedefi (TP2): {format(tp2_price if composite >= 0 else bull_target, p_fmt)} USDT</b> bölgesidir "
            f"(Hedefe Temas İhtimali: ~%{prob_bull_pct:.0f} | Stop'tan Önce Hedef Olasılığı: ~%{prob_win_first:.0f})."
        )
        bearish_scenario_tr = (
            f"Fiyat {sup_str} desteğini hacimli aşağı kırarsa (<b>Yükseliş Zarar-Kes / Stop Sınırı: {format(stop_price if composite >= 0 else bear_invalidation, p_fmt)} USDT</b> | "
            f"Temas Riski: ~%{prob_bear_pct:.0f}), düşüşte <b>1. Hedef (TP1): {format(tp1_price if composite < 0 else bear_tp1, p_fmt)} USDT</b> ve "
            f"<b>2. Ana Düşüş Hedefi (TP2): {format(tp2_price if composite < 0 else bear_target, p_fmt)} USDT</b> talep bölgesidir (Düşüş Stop Eşiği: {format(stop_price if composite < 0 else short_stop, p_fmt)} USDT)."
        )

        if composite >= 15.0:
            action_summary_tr = (
                f"Çok katmanlı model YUKARI yönlü olasılığın üstün olduğunu gösteriyor "
                f"(Bileşik Endeks: {composite:+.0f}/100 | Faktör Uyumu: %{confidence_pct:.0f}). "
                f"{sup_str} desteği korundukça {res_str} hedefi izlenebilir. {bt_stats.summary_tr} (YTD)."
            )
        elif composite <= -15.0:
            action_summary_tr = (
                f"Çok katmanlı model AŞAĞI yönlü baskının üstün olduğunu gösteriyor "
                f"(Bileşik Endeks: {composite:+.0f}/100 | Faktör Uyumu: %{confidence_pct:.0f}). "
                f"Görünümün pozitife dönmesi için {res_str} direncinin ve EMA20 ({format(ema20, p_fmt)} USDT) seviyesinin aşılması gerekir. {bt_stats.summary_tr} (YTD)."
            )
        else:
            action_summary_tr = (
                f"Faktörler arasında denge/kararsızlık hakim (Bileşik Endeks: {composite:+.0f}/100). "
                f"{sup_str} desteği ile {res_str} direnci arasındaki kırılım yönü tayin edecektir. {bt_stats.summary_tr} (YTD)."
            )

        return MarketForecast(
            score=composite,
            confidence_pct=confidence_pct,
            verdict_tr=verdict_tr,
            regime_tr=regime_tr,
            trend_score=t_score,
            money_flow_score=mf_score,
            momentum_score=m_score,
            structure_score=s_score,
            pattern_score=p_score,
            macro_htf_score=macro_score,
            trend_name_tr=trend_name_tr,
            supertrend_status_tr=supertrend_status_tr,
            momentum_tr=momentum_tr,
            money_flow_status_tr=money_flow_status_tr,
            bb_status_tr=bb_status_tr,
            last_pattern_tr=last_pattern_tr,
            divergence_status_tr=divergence_status_tr,
            cvd_divergence_status_tr=cvd_div_tr,
            macro_context_tr=macro_context_tr,
            hurst_exponent=hurst_val,
            choppiness_index=chop_val,
            kalman_trend_price=kalman_price,
            avwap_high_price=avwap_high_p,
            avwap_low_price=avwap_low_p,
            absorption_status_tr=absorption_status_tr,
            oi_regime_tr=oi_regime_tr,
            spot_perp_cvd_tr=spot_perp_cvd_tr,
            poc_price=poc_price,
            vah_price=vah_price,
            val_price=val_price,
            fib_618_price=fib_618_price,
            nearest_support=nearest_sup,
            nearest_resistance=nearest_res,
            nearest_support_tier_tr=sup_tier_tr,
            nearest_support_score=sup_score,
            nearest_support_reason_tr=sup_reason_tr,
            nearest_resistance_tier_tr=res_tier_tr,
            nearest_resistance_score=res_score,
            nearest_resistance_reason_tr=res_reason_tr,
            strongest_support=strongest_sup_obj.price if strongest_sup_obj else nearest_sup,
            strongest_resistance=strongest_res_obj.price if strongest_res_obj else nearest_res,
            atr_value=atr_val,
            bullish_trigger_price=bull_trigger,
            bullish_target_price=bull_target,
            bearish_invalidation_price=bear_invalidation,
            bearish_target_price=bear_target,
            active_direction=active_direction,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            stop_price=stop_price,
            readiness_score_5=readiness_score_5,
            readiness_verdict_tr=readiness_verdict_tr,
            readiness_checks=readiness_checks,
            whale_accumulation_score=whale_accumulation_score,
            whale_status_tr=whale_status_tr,
            session_status_tr=session_status_tr,
            squeeze_energy_pct=squeeze_energy_pct,
            expected_breakout_move_pct=expected_breakout_move_pct,
            squeeze_status_tr=squeeze_status_tr,
            step_a_breakout_tr=step_a_breakout_tr,
            step_b_pullback_tr=step_b_pullback_tr,
            step_c_invalidation_tr=step_c_invalidation_tr,
            vp_bin_centers=vp_centers,
            vp_bin_volumes=vp_vols,
            ema20_price=ema20,
            cmf_value=cmf_val,
            net_delta_20_usd=float(df["net_money_delta_usd"].tail(20).sum()) if "net_money_delta_usd" in df.columns else 0.0,
            ob_imbalance_pct=float(order_flow.imbalance_pct) if order_flow is not None else 50.0,
            ob_bid_wall=order_flow.strongest_bid_wall if order_flow is not None else None,
            ob_ask_wall=order_flow.strongest_ask_wall if order_flow is not None else None,
            bullish_scenario_tr=bullish_scenario_tr,
            bearish_scenario_tr=bearish_scenario_tr,
            action_summary_tr=action_summary_tr,
            backtest_stats=bt_stats,
            smc=smc_report,
            risk_plan=risk_plan,
            futures_setup=futures_setup,
            support_levels=supports,
            resistance_levels=resistances,
            divergences=divergences,
            factor_notes_tr=notes,
            sr_action_type=sr_action_type,
            sr_action_status_tr=sr_action_status_tr,
            sr_action_price=sr_action_price,
            sr_action_time=sr_action_time,
            sr_breakout_rvol=sr_breakout_rvol,
            sr_breakout_guide_tr=sr_breakout_guide_tr,
            leverage_squeeze_status_tr=futures_setup.leverage_squeeze_status_tr if futures_setup else "Normal Kaldıraç Dengesi",
            trendlines=trendlines,
            trend_state=trend_state,
            swing_structure_tr=swing_structure_tr,
            candle_anatomy_tr=candle_anatomy_tr,
            plain_guidance_tr=plain_guidance_tr,
        )

    @staticmethod
    def _build_futures_setup_report(
        live_close: float,
        composite: float,
        t_score: float,
        mf_score: float,
        htf_score: Optional[float],
        chop_val: float,
        hurst_val: float,
        atr_val: float,
        ema20: float,
        kalman_price: float,
        poc_price: float,
        vah_price: float,
        val_price: float,
        avwap_low_p: float,
        avwap_high_p: float,
        nearest_sup: float,
        nearest_res: float,
        supports: List[SupportResistanceLevel],
        resistances: List[SupportResistanceLevel],
        cmf_val: float,
        whale_score: float,
        squeeze_pct: float,
        smc_report: SmartMoneyReport,
        order_flow: Optional[OrderFlowIntel] = None,
        sr_action_type: str = "NONE",
        sr_action_status_tr: str = "",
        trendlines: Optional[DynamicTrendlineReport] = None,
    ) -> FuturesSetupReport:
        """
        Institutional Perpetual Futures (Vadeli İşlemler) Setup, Confidence & Hard Risk Gate Engine (v8.0).
        Evaluates:
          1. Direction & Multi-Timeframe Structure Alignment
          2. Support/Resistance Room-to-Run & Entry Geometry (Market vs Pullback Limit)
          3. Stop-Hunt (Liquidity Sweep) Protected Stop-Loss Placement
          4. Staged TP1 / TP2 / TP3 Anchored to S/R, POC/VAH/VAL & Liquidation Pools
          5. Futures Microstructure (Open Interest 4-Quadrant Regime, Funding Crowd Risk, Futures Taker CVD, Order Book Walls)
          6. Hard Risk Vetoes: If choppy, poor R:R (<1.35), blocked by S/R wall, or low confidence (<62),
             returns `is_tradeable = False` ("⛔ İŞLEM TAVSİYE EDİLMEZ") and withholds risky entry/stop/TP signals.
        """
        p_fmt = ",.4f" if live_close < 10.0 else ",.2f"
        atr_safe = max(atr_val, live_close * 0.004)
        atr_pct = (atr_safe / max(live_close, 1e-9)) * 100.0

        positives: List[str] = []
        warnings: List[str] = []
        veto_reasons: List[str] = []

        # Check SMC structure events & liquidity pools
        last_ev_type = smc_report.structure_events[-1].event_type if (smc_report and smc_report.structure_events) else ""
        short_liq_price: Optional[float] = None
        long_liq_price: Optional[float] = None
        if smc_report and smc_report.liquidation_pools:
            for lp in smc_report.liquidation_pools:
                if lp.pool_type == "SHORT_LIQ":
                    short_liq_price = lp.price
                elif lp.pool_type == "LONG_LIQ":
                    long_liq_price = lp.price

        # 1. Determine Candidate Direction ("LONG", "SHORT", or "NO_TRADE")
        tl_status = trendlines.breakout_status if trendlines is not None else "NONE"
        cand_dir = "NO_TRADE"
        if composite >= 15.0:
            cand_dir = "LONG"
        elif composite <= -15.0:
            cand_dir = "SHORT"
        elif composite >= 8.0 and (
            "BULL_SWEEP" in last_ev_type
            or "BULL_CHOCH" in last_ev_type
            or sr_action_type in ("BULL_SFP", "BULL_RETEST")
            or tl_status == "BULL_BREAKOUT"
        ) and mf_score >= 5.0:
            cand_dir = "LONG"
        elif composite <= -8.0 and (
            "BEAR_SWEEP" in last_ev_type
            or "BEAR_CHOCH" in last_ev_type
            or sr_action_type in ("BEAR_SFP", "BEAR_RETEST")
            or tl_status == "BEAR_BREAKDOWN"
        ) and mf_score <= -5.0:
            cand_dir = "SHORT"

        if cand_dir == "NO_TRADE":
            veto_reasons.append(
                f"Yön belirsizliği var (Genel Puan: {composite:+.0f}/100); alıcı ve satıcılar dengede olduğu için vadeli işlemde stop olma riski yüksek."
            )

        # Module 5: Perpetual Futures Short Squeeze / Long Squeeze (Kaldıraç Sıkıştırma) Detection (STRICT REAL DATA ONLY)
        fr_val = order_flow.funding_rate_pct if order_flow is not None else None
        oi_1h_val = order_flow.oi_change_1h_pct if order_flow is not None else None
        oi_24h_val = order_flow.oi_change_24h_pct if order_flow is not None else None
        t_ratio_val = order_flow.futures_taker_buy_sell_ratio if order_flow is not None else None
        has_deriv_metrics = any(v is not None for v in (fr_val, oi_1h_val, oi_24h_val, t_ratio_val))

        is_short_squeeze = bool(
            has_deriv_metrics
            and (
                (fr_val is not None and fr_val <= -0.005)
                or (oi_1h_val is not None and t_ratio_val is not None and oi_1h_val >= 0.5 and t_ratio_val >= 1.04)
            )
            and (cmf_val >= 0.01 or whale_score >= 53.0 or composite >= 12.0)
        )
        is_long_squeeze = bool(
            has_deriv_metrics
            and (
                (fr_val is not None and fr_val >= 0.025)
                or (oi_1h_val is not None and t_ratio_val is not None and oi_1h_val >= 0.5 and t_ratio_val <= 0.96)
            )
            and (cmf_val <= -0.01 or whale_score <= 47.0 or composite <= -12.0)
        )

        deriv_parts: List[str] = []
        if fr_val is not None:
            deriv_parts.append(f"Fonlama: %{fr_val:+.4f}")
        if t_ratio_val is not None:
            deriv_parts.append(f"Taker: {t_ratio_val:.2f}x")
        if oi_1h_val is not None:
            deriv_parts.append(f"OI 1S: %{oi_1h_val:+.1f}")
        deriv_tag = f" ({' | '.join(deriv_parts)})" if deriv_parts else ""

        if is_short_squeeze:
            leverage_squeeze_status_tr = (
                f"🔥 SHORT SQUEEZE (Şort Patlatma) POTANSİYELİ{deriv_tag} — "
                f"Direnç üstündeki açık Short pozisyonlar yukarı kırılımı hızlandırabilir!"
            )
        elif is_long_squeeze:
            leverage_squeeze_status_tr = (
                f"⚠️ LONG SQUEEZE (Long Tasfiye) RİSKİ{deriv_tag} — "
                f"Destek altındaki kalabalık Long stopları sert satış iğnesi tetikleyebilir!"
            )
        elif has_deriv_metrics:
            leverage_squeeze_status_tr = f"⚖️ Dengeli Kaldıraç Yapısı{deriv_tag}"
        else:
            leverage_squeeze_status_tr = "📊 Spot & Teknik Yapı Baz Alındı (Anlık Türev Fonlama Verisi Yok)"

        # 2. Support / Resistance Geometry, Entry Mode, Stop-Hunt Protected Stop & Staged TP1/TP2/TP3
        sup_safe = nearest_sup if (nearest_sup and nearest_sup < live_close) else (live_close - 1.3 * atr_safe)
        res_safe = nearest_res if (nearest_res and nearest_res > live_close) else (live_close + 1.3 * atr_safe)
        sup2_safe = supports[1].price if (len(supports) > 1 and supports[1].price < sup_safe) else (sup_safe - 1.4 * atr_safe)
        res2_safe = resistances[1].price if (len(resistances) > 1 and resistances[1].price > res_safe) else (res_safe + 1.4 * atr_safe)

        dist_to_sup_pct = max((live_close - sup_safe) / max(live_close, 1e-9) * 100.0, 0.05)
        dist_to_res_pct = max((res_safe - live_close) / max(live_close, 1e-9) * 100.0, 0.05)

        sup1_tier = supports[0].tier_tr if supports else "🟢 Sıradan Destek"
        sup1_strong = bool(supports[0].is_strong) if supports else False
        sup1_score = float(supports[0].strength_score) if supports else 35.0
        sup1_htf = bool(getattr(supports[0], "htf_confirmed", False)) if supports else False
        res1_tier = resistances[0].tier_tr if resistances else "🔴 Sıradan Direnç"
        res1_strong = bool(resistances[0].is_strong) if resistances else False
        res1_score = float(resistances[0].strength_score) if resistances else 35.0
        res1_htf = bool(getattr(resistances[0], "htf_confirmed", False)) if resistances else False

        entry_price = live_close
        entry_zone_low = live_close
        entry_zone_high = live_close
        stop_price = 0.0
        tp1_price = 0.0
        tp2_price = 0.0
        tp3_price = 0.0
        entry_type_tr = "Bekle-Gör (İşlem Açılmaz)"
        sr_context_tr = (
            f"Fiyat ({format(live_close, p_fmt)}) şu an {sup1_tier} ({format(sup_safe, p_fmt)}) ile "
            f"{res1_tier} ({format(res_safe, p_fmt)}) arasında kararsız bölgede."
        )

        if cand_dir == "LONG":
            # Check if price is jammed right under resistance ceiling without breakout momentum or short squeeze fuel
            res_block_thresh = (0.52 * atr_pct) if res1_strong else (0.35 * atr_pct)
            if (
                dist_to_res_pct < res_block_thresh
                and composite < 38.0
                and "BULL_BOS" not in last_ev_type
                and tl_status != "BULL_BREAKOUT"
                and not is_short_squeeze
            ):
                veto_reasons.append(
                    f"Fiyat {res1_tier} ({format(res_safe, p_fmt)} — Güç: {res1_score:.0f}/100) tavanına çok yakın (mesafe sadece %{dist_to_res_pct:.2f}); direnç altında Long açmak tavan reddi riski taşır."
                )

            if (
                dist_to_sup_pct <= 1.35 * atr_pct
                or "BULL_BOS" in last_ev_type
                or "BULL_SWEEP" in last_ev_type
                or sr_action_type in ("BULL_SFP", "BULL_RETEST")
                or tl_status == "BULL_BREAKOUT"
            ):
                entry_type_tr = "⚡ Piyasa / Yakın Bölge Girişi (Destek / Retest / Kırılım Onaylı)"
                entry_price = live_close
                entry_zone_low = max(sup_safe, live_close - 0.25 * atr_safe)
                entry_zone_high = live_close * 1.0015
            else:
                pullback_anchor = max(sup_safe + 0.20 * atr_safe, min(ema20, kalman_price, live_close - 0.35 * atr_safe))
                entry_type_tr = "🎯 Kademeli Limit / Geri Çekilme Girişi (Destek & Ortalamaya Yakın)"
                entry_price = float(np.clip(pullback_anchor, sup_safe, live_close))
                entry_zone_low = max(sup_safe, entry_price - 0.20 * atr_safe)
                entry_zone_high = min(live_close, entry_price + 0.20 * atr_safe)

            # Stop-Hunt Protected Stop-Loss: placed below structural support + ATR wick buffer
            raw_stop = min(sup_safe - 0.38 * atr_safe, entry_price - 1.15 * atr_safe)
            min_stop = entry_price * 0.9945
            max_stop = entry_price * 0.952
            stop_price = float(np.clip(raw_stop, max_stop, min_stop))
            stop_dist = max(entry_price - stop_price, entry_price * 0.004)

            # TP1, TP2, TP3 respecting Resistance, 4H/1D MTF Wall & Short Liquidation Pool
            tp1_cand = res_safe if (res_safe >= entry_price + 0.95 * stop_dist) else (entry_price + 1.15 * stop_dist)
            if res1_htf and res1_strong and res_safe > entry_price * 1.004:
                # Module 1: Front-run the 4H/1D macro wall slightly so TP1 fills safely before the wall
                tp1_cand = min(tp1_cand, res_safe * 0.9985)
            tp1_price = max(min(tp1_cand, entry_price + 1.45 * stop_dist), entry_price * 1.003)
            tp2_cand = max(res_safe, poc_price if poc_price > entry_price else 0.0, vah_price if vah_price > entry_price else 0.0)
            if tp2_cand < entry_price + 1.45 * stop_dist:
                tp2_cand = max(res2_safe, entry_price + 1.85 * stop_dist)
            tp2_price = max(tp2_cand, tp1_price + 0.65 * atr_safe)
            tp3_cand = max(short_liq_price or 0.0, res2_safe, tp2_price + 1.10 * atr_safe)
            tp3_price = max(tp3_cand, tp2_price + 0.75 * atr_safe)

            sr_context_tr = (
                f"{sup1_tier} (<b>{format(sup_safe, p_fmt)}</b> — Güç: {sup1_score:.0f}/100) baz alınarak Stop seviyesi iğne avının "
                f"altına (<b>{format(stop_price, p_fmt)}</b>) korundu; yukarıda {res1_tier} (<b>{format(res_safe, p_fmt)}</b>) "
                f"ve <b>{format(tp2_price, p_fmt)}</b> hedefi gözetildi."
            )
            if sup1_strong:
                htf_note = " [🏛️ 4H/1D Üst Periyot Onaylı]" if sup1_htf else ""
                positives.append(f"Altımızda {sup1_tier} ({format(sup_safe, p_fmt)} — Güç: {sup1_score:.0f}/100){htf_note} sağlam taban koruması sağlıyor.")

        elif cand_dir == "SHORT":
            sup_block_thresh = (0.52 * atr_pct) if sup1_strong else (0.35 * atr_pct)
            if (
                dist_to_sup_pct < sup_block_thresh
                and composite > -38.0
                and "BEAR_BOS" not in last_ev_type
                and tl_status != "BEAR_BREAKDOWN"
                and not is_long_squeeze
            ):
                veto_reasons.append(
                    f"Fiyat {sup1_tier} ({format(sup_safe, p_fmt)} — Güç: {sup1_score:.0f}/100) tabanına çok yakın (mesafe sadece %{dist_to_sup_pct:.2f}); destek üstünde Short açmak sert tepki riski taşır."
                )

            if (
                dist_to_res_pct <= 1.35 * atr_pct
                or "BEAR_BOS" in last_ev_type
                or "BEAR_SWEEP" in last_ev_type
                or sr_action_type in ("BEAR_SFP", "BEAR_RETEST")
                or tl_status == "BEAR_BREAKDOWN"
            ):
                entry_type_tr = "⚡ Piyasa / Yakın Bölge Girişi (Direnç / Retest / Kırılım Onaylı)"
                entry_price = live_close
                entry_zone_low = live_close * 0.9985
                entry_zone_high = min(res_safe, live_close + 0.25 * atr_safe)
            else:
                pullback_anchor = min(res_safe - 0.20 * atr_safe, max(ema20, kalman_price, live_close + 0.35 * atr_safe))
                entry_type_tr = "🎯 Kademeli Limit / Tepki Girişi (Direnç & Ortalamaya Yakın)"
                entry_price = float(np.clip(pullback_anchor, live_close, res_safe))
                entry_zone_low = max(live_close, entry_price - 0.20 * atr_safe)
                entry_zone_high = min(res_safe, entry_price + 0.20 * atr_safe)

            # Stop-Hunt Protected Stop-Loss: placed above structural resistance + ATR wick buffer
            raw_stop = max(res_safe + 0.38 * atr_safe, entry_price + 1.15 * atr_safe)
            min_stop = entry_price * 1.0055
            max_stop = entry_price * 1.048
            stop_price = float(np.clip(raw_stop, min_stop, max_stop))
            stop_dist = max(stop_price - entry_price, entry_price * 0.004)

            tp1_cand = sup_safe if (sup_safe <= entry_price - 0.95 * stop_dist) else (entry_price - 1.15 * stop_dist)
            if sup1_htf and sup1_strong and sup_safe < entry_price * 0.996:
                tp1_cand = max(tp1_cand, sup_safe * 1.0015)
            tp1_price = min(max(tp1_cand, entry_price - 1.45 * stop_dist), entry_price * 0.997)
            tp2_cand_list = [sup_safe]
            if 0 < poc_price < entry_price:
                tp2_cand_list.append(poc_price)
            if 0 < val_price < entry_price:
                tp2_cand_list.append(val_price)
            tp2_cand = min(tp2_cand_list)
            if tp2_cand > entry_price - 1.45 * stop_dist:
                tp2_cand = min(sup2_safe, entry_price - 1.85 * stop_dist)
            tp2_price = max(min(tp2_cand, tp1_price - 0.65 * atr_safe), entry_price * 0.5)
            tp3_cand = min(long_liq_price if (long_liq_price and long_liq_price > 0) else sup2_safe, sup2_safe, tp2_price - 1.10 * atr_safe)
            tp3_price = max(min(tp3_cand, tp2_price - 0.75 * atr_safe), entry_price * 0.4)

            sr_context_tr = (
                f"{res1_tier} (<b>{format(res_safe, p_fmt)}</b> — Güç: {res1_score:.0f}/100) baz alınarak Stop seviyesi iğne avının "
                f"üstüne (<b>{format(stop_price, p_fmt)}</b>) korundu; aşağıda {sup1_tier} (<b>{format(sup_safe, p_fmt)}</b>) "
                f"ve <b>{format(tp2_price, p_fmt)}</b> hedefi gözetildi."
            )
            if res1_strong:
                htf_note = " [🏛️ 4H/1D Üst Periyot Onaylı]" if res1_htf else ""
                positives.append(f"Üstümüzde {res1_tier} ({format(res_safe, p_fmt)} — Güç: {res1_score:.0f}/100){htf_note} güçlü satış tavanı oluşturuyor.")

        stop_distance_pct = abs(entry_price - stop_price) / max(entry_price, 1e-9) * 100.0 if stop_price > 0 else 0.0
        tp1_distance_pct = abs(tp1_price - entry_price) / max(entry_price, 1e-9) * 100.0 if tp1_price > 0 else 0.0
        tp2_distance_pct = abs(tp2_price - entry_price) / max(entry_price, 1e-9) * 100.0 if tp2_price > 0 else 0.0
        tp3_distance_pct = abs(tp3_price - entry_price) / max(entry_price, 1e-9) * 100.0 if tp3_price > 0 else 0.0
        rr_ratio = tp2_distance_pct / max(stop_distance_pct, 0.05) if stop_distance_pct > 0 else 0.0

        # 3. Score 7 Futures Pillars (0 to 100 Confidence Score)
        conf_pts = 0.0
        is_long = cand_dir == "LONG"
        is_short = cand_dir == "SHORT"

        # Pillar A: Trend & Composite Conviction (0 - 24 pts)
        if cand_dir in ("LONG", "SHORT"):
            abs_comp = abs(composite)
            conf_pts += min(24.0, 8.0 + abs_comp * 0.28)
            if (is_long and t_score >= 25.0) or (is_short and t_score <= -25.0):
                positives.append(f"Trend ortalamaları (EMA20/EMA50 & Kalman) {cand_dir} yönünü güçlü destekliyor.")
            else:
                warnings.append("Kısa vadeli ortalamalar henüz tam hizalanmadı.")

        # Pillar B: Higher Timeframe (HTF) Alignment (0 - 16 pts)
        if htf_score is not None and cand_dir in ("LONG", "SHORT"):
            if (is_long and htf_score >= 12.0) or (is_short and htf_score <= -12.0):
                conf_pts += 16.0
                positives.append(f"Üst zaman dilimi ana akıntısı ({htf_score:+.0f}/100) işlem yönüyle tam uyumlu.")
            elif abs(htf_score) < 12.0:
                conf_pts += 10.0
            else:
                conf_pts += 2.0
                warnings.append(f"Üst zaman dilimi ({htf_score:+.0f}) ters yönde; işlem karşı-trend riski taşıyor.")
                if abs(htf_score) >= 28.0 and ((is_long and cmf_val < -0.03) or (is_short and cmf_val > 0.03)):
                    veto_reasons.append(
                        f"Üst zaman dilimi ({htf_score:+.0f}) ve sıcak para akışı (CMF: {cmf_val:+.2f}) işlem yönüne sert karşı çıkıyor."
                    )
        elif cand_dir in ("LONG", "SHORT"):
            conf_pts += 12.0 if abs(t_score) >= 30.0 else 7.0

        # Pillar C: S/R Geometry & R:R Advantage (0 - 20 pts)
        if cand_dir in ("LONG", "SHORT"):
            if rr_ratio >= 2.0:
                conf_pts += 20.0
                positives.append(f"Destek/Direnç mesafesi çok avantajlı (Kazanç/Risk R:R = 1:{rr_ratio:.2f}).")
            elif rr_ratio >= 1.55:
                conf_pts += 16.0
                positives.append(f"Kazanç/Risk oranı vadeli işleme uygun (R:R = 1:{rr_ratio:.2f}).")
            elif rr_ratio >= 1.35:
                conf_pts += 11.5
            else:
                conf_pts += 3.0
                veto_reasons.append(
                    f"Kazanç/Risk oranı yetersiz (R:R = 1:{rr_ratio:.2f} < 1:1.35); hedef direnç/destek çok yakın, stop mesafesi ise geniş."
                )

        # Pillar D: Futures Microstructure (Open Interest, Funding Rate, Taker CVD, Order Book) (0 - 18 pts)
        fut_notes: List[str] = []
        if cand_dir in ("LONG", "SHORT"):
            # Spot + Taker Money Flow
            if (is_long and (cmf_val > 0.03 or whale_score >= 56.0)) or (is_short and (cmf_val < -0.03 or whale_score <= 44.0)):
                conf_pts += 7.5
                positives.append(f"Nakit akışı (CMF: {cmf_val:+.2f}) ve Balina İzi ({whale_score:.0f}/100) yönü onaylıyor.")
            elif (is_long and cmf_val < -0.05) or (is_short and cmf_val > 0.05):
                warnings.append(f"Spot nakit akışı (CMF: {cmf_val:+.2f}) henüz işlem yönünü desteklemiyor.")
            else:
                conf_pts += 4.0

            if order_flow is not None:
                # Futures Taker Buy/Sell Ratio
                t_ratio = order_flow.futures_taker_buy_sell_ratio
                if t_ratio is not None:
                    if (is_long and t_ratio >= 1.02) or (is_short and t_ratio <= 0.98):
                        conf_pts += 4.5
                        fut_notes.append(f"Vadeli Taker İştahı ({t_ratio:.2f}) yönle uyumlu")
                    else:
                        conf_pts += 1.5
                else:
                    conf_pts += 3.0

                # Open Interest (OI) Change & Funding Rate Crowd Filter (Real Data Only)
                if oi_1h_val is not None or oi_24h_val is not None:
                    oi_parts = []
                    if oi_1h_val is not None:
                        oi_parts.append(f"1S: {oi_1h_val:+.1f}%")
                    if oi_24h_val is not None:
                        oi_parts.append(f"24S: {oi_24h_val:+.1f}%")
                    fut_notes.append(f"OI Değişimi ({' | '.join(oi_parts)})")
                    conf_pts += 3.0 if (abs(oi_1h_val or 0.0) > 0.4 or abs(oi_24h_val or 0.0) > 1.5) else 2.0
                else:
                    conf_pts += 2.0

                # Crowd Squeeze Warning / Fuel on Funding
                if is_long and is_short_squeeze:
                    conf_pts += 4.5
                    positives.append(leverage_squeeze_status_tr)
                elif is_short and is_long_squeeze:
                    conf_pts += 4.5
                    positives.append(leverage_squeeze_status_tr)
                elif fr_val is not None and is_long and fr_val > 0.035:
                    warnings.append(f"Fonlama oranı yüksek (+%{fr_val:.4f}); aşırı kalabalık Long kaynaklı iğne riski var.")
                elif fr_val is not None and is_short and fr_val < -0.025:
                    warnings.append(f"Fonlama oranı negatif (%{fr_val:.4f}); Short Squeeze (yukarı patlatma) riskine dikkat.")
                elif fr_val is not None:
                    conf_pts += 3.0
                    fut_notes.append(f"Fonlama (%{fr_val:+.4f}) dengeli")
                else:
                    conf_pts += 2.5
            else:
                conf_pts += 7.5

        # Pillar E: Smart Money Structure (BOS / CHoCH / Sweep / OB / Breakout / Retest / SFP / Trendline Breakout) (0 - 14 pts)
        if cand_dir in ("LONG", "SHORT"):
            if (is_long and sr_action_type in ("BULL_SR_BREAKOUT", "BULL_SFP", "BULL_RETEST")) or (
                is_short and sr_action_type in ("BEAR_SR_BREAKDOWN", "BEAR_SFP", "BEAR_RETEST")
            ):
                conf_pts += 14.0 if "BREAK" in sr_action_type else 13.0
                positives.append(sr_action_status_tr)
            elif (is_long and tl_status == "BULL_BREAKOUT") or (is_short and tl_status == "BEAR_BREAKDOWN"):
                conf_pts += 12.5
                if trendlines is not None:
                    positives.append(trendlines.summary_tr)
            elif (is_long and ("BULL_BOS" in last_ev_type or "BULL_CHOCH" in last_ev_type or "BULL_SWEEP" in last_ev_type)) or (
                is_short and ("BEAR_BOS" in last_ev_type or "BEAR_CHOCH" in last_ev_type or "BEAR_SWEEP" in last_ev_type)
            ):
                conf_pts += 12.0
                positives.append("Kurumsal piyasa yapısı (BOS/CHoCH veya Stop Avı Dönüşü) işlemi teyit ediyor.")
            else:
                conf_pts += 6.5

        # Pillar F: Choppiness / Whipsaw Filter (0 - 10 pts)
        if chop_val >= 60.5 and squeeze_pct < 75.0:
            veto_reasons.append(
                f"Piyasa şiddetli yatay testere (CHOP: {chop_val:.1f} > 60) içinde; vadeli işlemlerde iki yönlü stop patlatma riski çok yüksek."
            )
        elif chop_val < 54.0 or hurst_val >= 0.53:
            if cand_dir in ("LONG", "SHORT"):
                conf_pts += 10.0
                positives.append(f"Piyasa testere sıkışmasında değil, trend akışı temiz (CHOP: {chop_val:.1f}).")
        else:
            if cand_dir in ("LONG", "SHORT"):
                conf_pts += 5.5

        confidence_score = float(np.clip(round(conf_pts, 1), 12.0, 98.0))
        if confidence_score < 62.0 and not veto_reasons:
            veto_reasons.append(
                f"Vadeli işlem güven notu ({confidence_score:.0f}/100), güvenli eşik olan 62/100'ün altında kaldı."
            )

        is_tradeable = (cand_dir in ("LONG", "SHORT")) and (len(veto_reasons) == 0) and (confidence_score >= 62.0)

        if confidence_score >= 84.0 and is_tradeable:
            confidence_grade = "A+"
            confidence_verdict_tr = f"🟢 A+ SINIFI ÇOK YÜKSEK GÜVEN ({confidence_score:.0f}/100 — Kurumsal Onaylı)"
        elif confidence_score >= 74.0 and is_tradeable:
            confidence_grade = "A"
            confidence_verdict_tr = f"🟢 A SINIFI GÜÇLÜ KURULUM ({confidence_score:.0f}/100 — Teknik Yapı Net)"
        elif confidence_score >= 62.0 and is_tradeable:
            confidence_grade = "B"
            confidence_verdict_tr = f"🟡 B SINIFI UYGUN KURULUM ({confidence_score:.0f}/100 — Kademeli / Kontrollü)"
        elif confidence_score >= 48.0:
            confidence_grade = "C"
            confidence_verdict_tr = f"🟠 C SINIFI ZAYIF / RİSKLİ YAPI ({confidence_score:.0f}/100 — İşlem Önerilmez)"
        else:
            confidence_grade = "D"
            confidence_verdict_tr = f"🔴 D SINIFI YÜKSEK RİSK / TESTERE ({confidence_score:.0f}/100 — Uzak Durulmalı)"

        # Compute Safe Isolated Leverage Cap so liquidation is >2.5x further than Stop-Loss
        if is_tradeable and stop_distance_pct > 0:
            raw_lev = int(min(10, max(2, round(12.0 / max(stop_distance_pct, 0.8)))))
            if confidence_score < 72.0:
                raw_lev = min(raw_lev, 5)
            max_safe_leverage = raw_lev
        else:
            max_safe_leverage = 1

        futures_tech_summary_tr = (
            " | ".join(fut_notes)
            if fut_notes
            else f"Mıknatıs POC: {format(poc_price, p_fmt)} | Dip Maliyet: {format(avwap_low_p, p_fmt)}"
        )

        wait_condition_tr = (
            f"Güvenli Long için {format(res_safe, p_fmt)} direncinin hacimli aşılması veya {format(sup_safe, p_fmt)} desteğinde alıcı teyidi; "
            f"Short için {format(sup_safe, p_fmt)} desteğinin kırılması beklenmelidir."
        )

        if not is_tradeable:
            all_warnings = veto_reasons + warnings
            return FuturesSetupReport(
                is_tradeable=False,
                direction="NO_TRADE",
                direction_label_tr="⛔ İŞLEM TAVSİYE EDİLMEZ (RİSK YÜKSEK / TEKNİK YAPI UYGUN DEĞİL)",
                confidence_score=confidence_score,
                confidence_grade=confidence_grade,
                confidence_verdict_tr=confidence_verdict_tr,
                entry_type_tr="Bekle-Gör (Giriş / TP / Stop Verilmedi)",
                entry_price=0.0,
                entry_zone_low=0.0,
                entry_zone_high=0.0,
                stop_price=0.0,
                stop_distance_pct=0.0,
                tp1_price=0.0,
                tp2_price=0.0,
                tp3_price=0.0,
                tp1_distance_pct=0.0,
                tp2_distance_pct=0.0,
                tp3_distance_pct=0.0,
                rr_ratio=rr_ratio,
                max_safe_leverage=1,
                sr_context_tr=(
                    f"Destek (Taban): {format(sup_safe, p_fmt)} USDT | Direnç (Tavan): {format(res_safe, p_fmt)} USDT"
                ),
                futures_tech_summary_tr=futures_tech_summary_tr,
                leverage_squeeze_status_tr=leverage_squeeze_status_tr,
                positive_factors_tr=positives,
                risk_warnings_tr=all_warnings if all_warnings else ["Teknik yapı vadeli işlem kriterlerini karşılamıyor."],
                wait_condition_tr=wait_condition_tr,
            )

        dir_lbl = (
            "🟢 VADELİ LONG (YÜKSELİŞ) KURULUMU"
            if cand_dir == "LONG"
            else "🔴 VADELİ SHORT (DÜŞÜŞ) KURULUMU"
        )
        return FuturesSetupReport(
            is_tradeable=True,
            direction=cand_dir,
            direction_label_tr=dir_lbl,
            confidence_score=confidence_score,
            confidence_grade=confidence_grade,
            confidence_verdict_tr=confidence_verdict_tr,
            entry_type_tr=entry_type_tr,
            entry_price=entry_price,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            stop_price=stop_price,
            stop_distance_pct=stop_distance_pct,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            tp3_price=tp3_price,
            tp1_distance_pct=tp1_distance_pct,
            tp2_distance_pct=tp2_distance_pct,
            tp3_distance_pct=tp3_distance_pct,
            rr_ratio=rr_ratio,
            max_safe_leverage=max_safe_leverage,
            sr_context_tr=sr_context_tr,
            futures_tech_summary_tr=futures_tech_summary_tr,
            leverage_squeeze_status_tr=leverage_squeeze_status_tr,
            positive_factors_tr=positives,
            risk_warnings_tr=warnings,
            wait_condition_tr=wait_condition_tr,
        )

    @staticmethod
    def summarize_signals(df: pd.DataFrame) -> pd.DataFrame:
        mask = df["signal_type"] != "NONE"
        cols = [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "rsi",
            "mfi",
            "cmf",
            "bb_pct_b",
            "primary_pattern",
            "pattern_tr_name",
            "pattern_meaning_tr",
            "signal_type",
            "signal_label",
        ]
        existing_cols = [c for c in cols if c in df.columns]
        return df.loc[mask, existing_cols].copy().reset_index(drop=True)
