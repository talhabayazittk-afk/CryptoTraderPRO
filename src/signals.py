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

        # 2. Pattern Groups (including new Morning Star, Evening Star, Inverted Hammer, Hanging Man)
        morning_star = out.get("pattern_morning_star", pd.Series(False, index=out.index))
        evening_star = out.get("pattern_evening_star", pd.Series(False, index=out.index))
        inv_hammer = out.get("pattern_inverted_hammer", pd.Series(False, index=out.index))
        hanging_man = out.get("pattern_hanging_man", pd.Series(False, index=out.index))

        bullish_patterns = (
            morning_star
            | out["pattern_bullish_engulfing"]
            | out["pattern_hammer"]
            | inv_hammer
            | out["pattern_dragonfly_doji"]
        )
        bearish_patterns = (
            evening_star
            | out["pattern_bearish_engulfing"]
            | out["pattern_shooting_star"]
            | hanging_man
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
            | ((out["pattern_hammer"] | out["pattern_dragonfly_doji"]) & (out["regime_oversold"] | (rsi <= 43.0)))
            | (inv_hammer & out["regime_oversold"])
            | (standard_doji & out["regime_oversold"] & (cmf >= -0.05))
        ).fillna(False)

        strong_bearish_reversal = (
            evening_star
            | (out["pattern_bearish_engulfing"] & near_overbought & vol_confirmed)
            | ((out["pattern_shooting_star"] | out["pattern_gravestone_doji"]) & (out["regime_overbought"] | (rsi >= 57.0)))
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
        window: int = 7,
        max_levels: int = 2,
    ) -> Tuple[List[SupportResistanceLevel], List[SupportResistanceLevel]]:
        """
        Institutional Support & Resistance Detector combining:
            1. Swing High / Swing Low Pivot Clusters
            2. Volume Profile (POC, VAH, VAL) High-Volume Nodes
            3. Golden Ratio Fibonacci (0.618 & 0.382) Retracement Zones
        """
        if len(df) < window * 2 + 1:
            return [], []

        highs = df["high"].values
        lows = df["low"].values
        current_price = float(df["close"].iloc[-1])
        atr_val = float(df["atr"].iloc[-1]) if "atr" in df.columns and pd.notna(df["atr"].iloc[-1]) else current_price * 0.008
        price_range = float(df["high"].max() - df["low"].min())
        cluster_tol = max(price_range * 0.015, current_price * 0.0045)
        zone_half_width = max(atr_val * 0.25, current_price * 0.0018)

        candidates: List[Tuple[float, str]] = []

        # 1. Pivot Highs & Lows
        for i in range(window, len(df) - window):
            if highs[i] == np.max(highs[i - window : i + window + 1]):
                candidates.append((float(highs[i]), "Pivot"))
            if lows[i] == np.min(lows[i - window : i + window + 1]):
                candidates.append((float(lows[i]), "Pivot"))

        candidates.append((float(df["high"].tail(65).max()), "Major Ekstrem"))
        candidates.append((float(df["low"].tail(65).min()), "Major Ekstrem"))

        # 2. Volume Profile Key Nodes (POC, VAH, VAL)
        if "vp_poc" in df.columns:
            poc = float(df["vp_poc"].iloc[-1])
            vah = float(df["vp_vah"].iloc[-1])
            val = float(df["vp_val"].iloc[-1])
            candidates.append((poc, "Hacim POC"))
            candidates.append((vah, "Hacim VAH"))
            candidates.append((val, "Hacim VAL"))

        # 3. Fibonacci 0.618 & 0.382 Retracements of recent 90 bars
        recent_high = float(df["high"].tail(90).max())
        recent_low = float(df["low"].tail(90).min())
        span_90 = recent_high - recent_low
        if span_90 > 0:
            fib_618 = recent_high - 0.618 * span_90
            fib_382 = recent_high - 0.382 * span_90
            candidates.append((fib_618, "Fib 0.618"))
            candidates.append((fib_382, "Fib 0.382"))

        # Cluster nearby levels and classify strictly relative to current_price (handles S/R Flip!)
        candidates.sort(key=lambda x: x[0])
        clusters: List[Tuple[List[float], List[str]]] = []
        for price_val, tag in candidates:
            placed = False
            for c_prices, c_tags in clusters:
                if abs(np.mean(c_prices) - price_val) <= cluster_tol:
                    c_prices.append(price_val)
                    if tag not in c_tags:
                        c_tags.append(tag)
                    placed = True
                    break
            if not placed:
                clusters.append(([price_val], [tag]))

        supports: List[SupportResistanceLevel] = []
        resistances: List[SupportResistanceLevel] = []

        for c_prices, c_tags in clusters:
            lvl_price = float(np.mean(c_prices))
            touches = len(c_prices)
            special_tags = [t for t in c_tags if t not in ("Pivot", "Major Ekstrem")]
            tag_suffix = f" + {'/'.join(special_tags)}" if special_tags else ""

            if lvl_price < current_price * 0.9985:
                strength = f"Güçlü Destek ({touches} Onay{tag_suffix})" if touches >= 2 or special_tags else "Yakın Destek"
                supports.append(
                    SupportResistanceLevel(
                        price=lvl_price,
                        band_low=lvl_price - zone_half_width,
                        band_high=lvl_price + zone_half_width,
                        level_type="DESTEK",
                        touches=touches,
                        strength_label=strength,
                    )
                )
            elif lvl_price > current_price * 1.0015:
                strength = f"Güçlü Direnç ({touches} Onay{tag_suffix})" if touches >= 2 or special_tags else "Yakın Direnç"
                resistances.append(
                    SupportResistanceLevel(
                        price=lvl_price,
                        band_low=lvl_price - zone_half_width,
                        band_high=lvl_price + zone_half_width,
                        level_type="DİRENÇ",
                        touches=touches,
                        strength_label=strength,
                    )
                )

        supports.sort(key=lambda x: abs(x.price - current_price))
        resistances.sort(key=lambda x: abs(x.price - current_price))
        return supports[:max_levels], resistances[:max_levels]

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
        # LAYER 1: TREND STRUCTURE & ZERO-LAG KALMAN FILTER (-100 to +100)
        # ==================================================================
        t_score = 0.0
        if live_close > ema20 > ema50:
            t_score += 50.0
            trend_name_tr = "Yükselen Trend (Fiyat > EMA20 > EMA50)"
        elif live_close < ema20 < ema50:
            t_score -= 50.0
            trend_name_tr = "Düşen Trend (Fiyat < EMA20 < EMA50)"
        elif live_close > ema20:
            t_score += 22.0
            trend_name_tr = "Kısa Vadeli Toparlanma (Fiyat > EMA20)"
        else:
            t_score -= 22.0
            trend_name_tr = "Kısa Vadeli Zayıflama (Fiyat < EMA20)"

        # Zero-Lag Kalman Filter confirmation
        if live_close >= kalman_price and kalman_slope >= 0:
            t_score += 12.0
        elif live_close < kalman_price and kalman_slope < 0:
            t_score -= 12.0

        t_score += 13.0 if live_close > ema200 else -13.0

        if st_dir == 1:
            t_score += 25.0
            supertrend_status_tr = "POZİTİF (SuperTrend Alım Yönünde)"
        else:
            t_score -= 25.0
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

        supports, resistances = self.detect_support_resistance(df)
        nearest_sup = supports[0].price if supports else (live_close - 2.0 * atr_val)
        nearest_res = resistances[0].price if resistances else (live_close + 2.0 * atr_val)

        dist_to_sup = max(live_close - nearest_sup, atr_val * 0.1)
        dist_to_res = max(nearest_res - live_close, atr_val * 0.1)
        rr_ratio = dist_to_res / dist_to_sup
        if rr_ratio >= 1.7:
            s_score += 18.0
        elif rr_ratio <= 0.58:
            s_score -= 18.0

        # Pre-compute SMC structure events for Layer 4 scoring
        smc_engine = SmartMoneyEngine()
        smc_events, _, _ = smc_engine.detect_structure_and_sweeps(df)
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

        composite = float(np.clip(composite, -100.0, 100.0))

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

        if composite >= 42.0:
            verdict_tr = "GÜÇLÜ POZİTİF EĞİLİM (YUKARI YÖNLÜ OLASILIK ÜSTÜNLÜĞÜ)"
        elif composite >= 15.0:
            verdict_tr = "POZİTİF / YUKARI YÖNLÜ TEKNİK GÖRÜNÜM"
        elif composite <= -42.0:
            verdict_tr = "GÜÇLÜ NEGATİF EĞİLİM (AŞAĞI YÖNLÜ BASKI ÜSTÜNLÜĞÜ)"
        elif composite <= -15.0:
            verdict_tr = "NEGATİF / ZAYIF TEKNİK GÖRÜNÜM (SATIŞ BASKILI)"
        else:
            verdict_tr = "YATAY / DENGE ARAYIŞI (KARARSIZ BÖLGE)"

        p_fmt = ",.4f" if live_close < 10.0 else ",.2f"
        sup_str = f"{format(nearest_sup, p_fmt)} USDT"
        res_str = f"{format(nearest_res, p_fmt)} USDT"
        poc_str = f"{format(poc_price, p_fmt)} USDT"

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

        active_rr = risk_plan.risk_reward_ratio if risk_plan else 1.0
        chk5_ok = active_rr >= 1.25
        chk5_desc = (
            f"Hedef kazanç mesafesi, Stop mesafesinin {active_rr:.2f} katı (Avantajlı R:R)."
            if chk5_ok
            else f"Hedef mesafesi Stop mesafesine göre dar ({active_rr:.2f}R < 1.25R)."
        )

        readiness_checks: List[Tuple[str, bool, str]] = [
            ("1. Yön & Trend Netliği", bool(chk1_ok), chk1_desc),
            ("2. Üst Zaman Dilimi (Ana Akıntı) Uyumu", bool(chk2_ok), chk2_desc),
            ("3. Gerçek Nakit & Balina Desteği", bool(chk3_ok), chk3_desc),
            ("4. Testere / Sıkışma Filtresi", bool(chk4_ok), chk4_desc),
            ("5. Kazanç / Risk Mesafesi (R:R)", bool(chk5_ok), chk5_desc),
        ]
        readiness_score_5 = sum(1 for _, ok, _ in readiness_checks if ok)
        if readiness_score_5 >= 4 and abs(composite) >= 18.0:
            readiness_verdict_tr = f"🟢 YÜKSEK KALİTELİ KURULUM ({readiness_score_5}/5 Kriter Onaylı — Şartlar Olgun)"
        elif readiness_score_5 == 3 and abs(composite) >= 15.0:
            readiness_verdict_tr = f"🟡 ORTA KALİTELİ KURULUM ({readiness_score_5}/5 Kriter Onaylı — Kademeli/Temkinli İzlenmeli)"
        else:
            readiness_verdict_tr = f"🔴 BEKLE-GÖR BÖLGESİ ({readiness_score_5}/5 Kriter Onaylı — İşlem İçin Erken / Riskli)"

        bullish_scenario_tr = (
            f"Fiyat {sup_str} destek bölgesi (Mıknatıs POC: {poc_str} | Dip Alıcı Maliyeti: {format(avwap_low_p, p_fmt)}) üzerinde tutunduğu sürece; "
            f"<b>1. Güvenli Kâr Hedefi (TP1): {format(bull_tp1, p_fmt)} USDT</b>, "
            f"<b>2. Ana Yükseliş Hedefi (TP2): {format(bull_target, p_fmt)} USDT</b> bölgesidir "
            f"(Hedefe Temas İhtimali: ~%{prob_bull_pct:.0f} | Stop'tan Önce Hedef Olasılığı: ~%{prob_win_first:.0f})."
        )
        bearish_scenario_tr = (
            f"Fiyat {sup_str} desteğini hacimli aşağı kırarsa (<b>Yükseliş Zarar-Kes / Stop Sınırı: {format(bear_invalidation, p_fmt)} USDT</b> | "
            f"Temas Riski: ~%{prob_bear_pct:.0f}), düşüşte <b>1. Hedef (TP1): {format(bear_tp1, p_fmt)} USDT</b> ve "
            f"<b>2. Ana Düşüş Hedefi (TP2): {format(bear_target, p_fmt)} USDT</b> talep bölgesidir (Düşüş Stop Eşiği: {format(short_stop, p_fmt)} USDT)."
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
        cand_dir = "NO_TRADE"
        if composite >= 15.0:
            cand_dir = "LONG"
        elif composite <= -15.0:
            cand_dir = "SHORT"
        elif composite >= 10.0 and ("BULL_SWEEP" in last_ev_type or "BULL_CHOCH" in last_ev_type) and mf_score > 10.0:
            cand_dir = "LONG"
        elif composite <= -10.0 and ("BEAR_SWEEP" in last_ev_type or "BEAR_CHOCH" in last_ev_type) and mf_score < -10.0:
            cand_dir = "SHORT"

        if cand_dir == "NO_TRADE":
            veto_reasons.append(
                f"Yön belirsizliği var (Genel Puan: {composite:+.0f}/100); alıcı ve satıcılar dengede olduğu için vadeli işlemde stop olma riski yüksek."
            )

        # 2. Support / Resistance Geometry, Entry Mode, Stop-Hunt Protected Stop & Staged TP1/TP2/TP3
        sup_safe = nearest_sup if (nearest_sup and nearest_sup < live_close) else (live_close - 1.3 * atr_safe)
        res_safe = nearest_res if (nearest_res and nearest_res > live_close) else (live_close + 1.3 * atr_safe)
        sup2_safe = supports[1].price if (len(supports) > 1 and supports[1].price < sup_safe) else (sup_safe - 1.4 * atr_safe)
        res2_safe = resistances[1].price if (len(resistances) > 1 and resistances[1].price > res_safe) else (res_safe + 1.4 * atr_safe)

        dist_to_sup_pct = max((live_close - sup_safe) / max(live_close, 1e-9) * 100.0, 0.05)
        dist_to_res_pct = max((res_safe - live_close) / max(live_close, 1e-9) * 100.0, 0.05)

        entry_price = live_close
        entry_zone_low = live_close
        entry_zone_high = live_close
        stop_price = 0.0
        tp1_price = 0.0
        tp2_price = 0.0
        tp3_price = 0.0
        entry_type_tr = "Bekle-Gör (İşlem Açılmaz)"
        sr_context_tr = (
            f"Fiyat ({format(live_close, p_fmt)}) şu an {format(sup_safe, p_fmt)} desteği ile "
            f"{format(res_safe, p_fmt)} direnci arasında kararsız bölgede."
        )

        if cand_dir == "LONG":
            # Check if price is jammed right under resistance ceiling without breakout momentum
            if dist_to_res_pct < 0.42 * atr_pct and composite < 38.0 and "BULL_BOS" not in last_ev_type:
                veto_reasons.append(
                    f"Fiyat {format(res_safe, p_fmt)} direnç tavanına çok yakın (mesafe sadece %{dist_to_res_pct:.2f}); direnç altında Long açmak tavan reddi riski taşır."
                )

            # Decide Market/Near Entry vs Pullback Limit Entry
            if dist_to_sup_pct <= 1.35 * atr_pct or "BULL_BOS" in last_ev_type or "BULL_SWEEP" in last_ev_type:
                entry_type_tr = "⚡ Piyasa / Yakın Bölge Girişi (Destek & Yapı Onaylı)"
                entry_price = live_close
                entry_zone_low = max(sup_safe, live_close - 0.25 * atr_safe)
                entry_zone_high = live_close * 1.0015
            else:
                # Price is somewhat extended above support -> recommend slight pullback entry toward EMA20/Kalman/Support
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

            # TP1, TP2, TP3 respecting Resistance & Short Liquidation Pool
            tp1_cand = res_safe if (res_safe >= entry_price + 0.95 * stop_dist) else (entry_price + 1.15 * stop_dist)
            tp1_price = min(tp1_cand, entry_price + 1.45 * stop_dist)
            tp2_cand = max(res_safe, poc_price if poc_price > entry_price else 0.0, vah_price if vah_price > entry_price else 0.0)
            if tp2_cand < entry_price + 1.45 * stop_dist:
                tp2_cand = max(res2_safe, entry_price + 1.85 * stop_dist)
            tp2_price = max(tp2_cand, tp1_price + 0.65 * atr_safe)
            tp3_cand = max(short_liq_price or 0.0, res2_safe, tp2_price + 1.10 * atr_safe)
            tp3_price = max(tp3_cand, tp2_price + 0.75 * atr_safe)

            sr_context_tr = (
                f"🟢 <b>{format(sup_safe, p_fmt)}</b> ana desteği baz alınarak Stop seviyesi iğne/tuzak avının "
                f"altına (<b>{format(stop_price, p_fmt)}</b>) korundu; yukarıda <b>{format(res_safe, p_fmt)}</b> direnci "
                f"ve <b>{format(tp2_price, p_fmt)}</b> hedefi gözetildi."
            )

        elif cand_dir == "SHORT":
            # Check if price is jammed right on top of major support floor without breakdown momentum
            if dist_to_sup_pct < 0.42 * atr_pct and composite > -38.0 and "BEAR_BOS" not in last_ev_type:
                veto_reasons.append(
                    f"Fiyat {format(sup_safe, p_fmt)} destek tabanına çok yakın (mesafe sadece %{dist_to_sup_pct:.2f}); destek üstünde Short açmak sert tepki riski taşır."
                )

            if dist_to_res_pct <= 1.35 * atr_pct or "BEAR_BOS" in last_ev_type or "BEAR_SWEEP" in last_ev_type:
                entry_type_tr = "⚡ Piyasa / Yakın Bölge Girişi (Direnç & Yapı Onaylı)"
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

            # TP1, TP2, TP3 respecting Support & Long Liquidation Pool
            tp1_cand = sup_safe if (sup_safe <= entry_price - 0.95 * stop_dist) else (entry_price - 1.15 * stop_dist)
            tp1_price = max(tp1_cand, entry_price - 1.45 * stop_dist)
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
                f"🔴 <b>{format(res_safe, p_fmt)}</b> ana direnci baz alınarak Stop seviyesi iğne/tuzak avının "
                f"üstüne (<b>{format(stop_price, p_fmt)}</b>) korundu; aşağıda <b>{format(sup_safe, p_fmt)}</b> desteği "
                f"ve <b>{format(tp2_price, p_fmt)}</b> hedefi gözetildi."
            )

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

                # Open Interest (OI) Change & Funding Rate Crowd Filter
                oi_1h = order_flow.oi_change_1h_pct or 0.0
                oi_24h = order_flow.oi_change_24h_pct or 0.0
                fr_pct = order_flow.funding_rate_pct or 0.0
                if abs(oi_1h) > 0.4 or abs(oi_24h) > 1.5:
                    fut_notes.append(f"OI Değişimi (1S: {oi_1h:+.1f}% | 24S: {oi_24h:+.1f}%)")
                    conf_pts += 3.0
                else:
                    conf_pts += 2.0

                # Crowd Squeeze Warning on Extreme Funding
                if is_long and fr_pct > 0.035:
                    warnings.append(f"Fonlama oranı yüksek (+%{fr_pct:.4f}); aşırı kalabalık Long kaynaklı iğne riski var.")
                elif is_short and fr_pct < -0.025:
                    warnings.append(f"Fonlama oranı negatif (%{fr_pct:.4f}); Short Squeeze (yukarı patlatma) riskine dikkat.")
                else:
                    conf_pts += 3.0
                    fut_notes.append(f"Fonlama (%{fr_pct:+.4f}) aşırı şişkin değil")
            else:
                conf_pts += 7.5

        # Pillar E: Smart Money Structure (BOS / CHoCH / Sweep / OB) (0 - 12 pts)
        if cand_dir in ("LONG", "SHORT"):
            if (is_long and ("BULL_BOS" in last_ev_type or "BULL_CHOCH" in last_ev_type or "BULL_SWEEP" in last_ev_type)) or (
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
