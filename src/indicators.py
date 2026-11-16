"""
Vectorized Mathematical Calculation of Technical, Trend, Volatility, Volume Profile (POC),
and Real Taker Money Flow / CVD Indicators (v2.0):
    - Wilder's RSI (14)
    - Bollinger Bands (Upper, Middle, Lower, %B, Bandwidth, Squeeze)
    - EMA Ribbon (EMA 20, EMA 50, EMA 200)
    - SuperTrend (10, 3.0)
    - ADX / +DI / -DI (Average Directional Index - Trend Gücü)
    - MACD (12, 26, 9)
    - ATR (14 - Average True Range)
    - VWAP (Rolling Volume Weighted Average Price)
    - Money Flow Index (MFI 14 - Hacim Ağırlıklı Para Giriş/Çıkış Endeksi)
    - Chaikin Money Flow (CMF 20 - Kurumsal Akümülasyon / Distribüsyon)
    - True Taker Buy/Sell Delta & Cumulative Volume Delta (CVD)
    - Volume Profile (POC - Point of Control, VAH - Value Area High, VAL - Value Area Low)
"""
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .config import IndicatorConfig


class TechnicalIndicators:
    """
    Computes multi-dimensional technical, money-flow, and volume-profile indicators
    using pure vectorized Pandas/NumPy operations.
    """

    def __init__(self, config: Optional[IndicatorConfig] = None):
        self.config = config or IndicatorConfig()

    def compute_rsi(self, df: pd.DataFrame, price_col: str = "close") -> pd.Series:
        period = self.config.rsi_period
        delta = df[price_col].diff()

        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)

        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi = np.where((avg_loss == 0.0) & (avg_gain > 0.0), 100.0, rsi)
        rsi = np.where((avg_loss == 0.0) & (avg_gain == 0.0), 50.0, rsi)

        return pd.Series(rsi, index=df.index, name="rsi")

    def compute_bollinger_bands(self, df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame:
        period = self.config.bb_period
        std_mult = self.config.bb_std_dev

        close = df[price_col]
        bb_mid = close.rolling(window=period, min_periods=period).mean()
        rolling_std = close.rolling(window=period, min_periods=period).std(ddof=0)

        bb_upper = bb_mid + (std_mult * rolling_std)
        bb_lower = bb_mid - (std_mult * rolling_std)

        band_range = (bb_upper - bb_lower).replace(0.0, np.nan)
        bb_pct_b = (close - bb_lower) / band_range
        bb_width = ((bb_upper - bb_lower) / bb_mid.replace(0.0, np.nan)) * 100.0

        bb_width_min = bb_width.rolling(window=50, min_periods=20).quantile(0.20)
        bb_squeeze = (bb_width <= bb_width_min).fillna(False)

        return pd.DataFrame({
            "bb_mid": bb_mid,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "bb_pct_b": bb_pct_b,
            "bb_width": bb_width,
            "bb_squeeze": bb_squeeze,
        }, index=df.index)

    def compute_atr(self, df: pd.DataFrame, period: Optional[int] = None) -> pd.Series:
        p = period or self.config.atr_period
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = true_range.ewm(alpha=1.0 / p, min_periods=p, adjust=False).mean()
        return pd.Series(atr, index=df.index, name="atr")

    def compute_adx(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.config.adx_period
        high = df["high"]
        low = df["low"]

        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        atr = self.compute_atr(df, period=p).replace(0.0, np.nan)
        plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / p, adjust=False).mean() / atr
        minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / p, adjust=False).mean() / atr

        di_sum = (plus_di + minus_di).replace(0.0, np.nan)
        dx = 100.0 * (plus_di - minus_di).abs() / di_sum
        adx = dx.ewm(alpha=1.0 / p, min_periods=p, adjust=False).mean()

        return pd.DataFrame({
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
        }, index=df.index)

    def compute_supertrend(self, df: pd.DataFrame) -> pd.DataFrame:
        period = self.config.supertrend_period
        mult = self.config.supertrend_multiplier

        atr = self.compute_atr(df, period=period).bfill().fillna(0.0).values
        hl2 = ((df["high"] + df["low"]) / 2.0).values
        close = df["close"].values
        n = len(df)

        basic_upper = hl2 + mult * atr
        basic_lower = hl2 - mult * atr

        final_upper = np.copy(basic_upper)
        final_lower = np.copy(basic_lower)
        supertrend = np.zeros(n)
        direction = np.ones(n, dtype=int)

        for i in range(1, n):
            if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
                final_upper[i] = basic_upper[i]
            else:
                final_upper[i] = final_upper[i - 1]

            if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
                final_lower[i] = basic_lower[i]
            else:
                final_lower[i] = final_lower[i - 1]

            if direction[i - 1] == 1:
                if close[i] < final_lower[i]:
                    direction[i] = -1
                    supertrend[i] = final_upper[i]
                else:
                    direction[i] = 1
                    supertrend[i] = final_lower[i]
            else:
                if close[i] > final_upper[i]:
                    direction[i] = 1
                    supertrend[i] = final_lower[i]
                else:
                    direction[i] = -1
                    supertrend[i] = final_upper[i]

        supertrend[0] = final_lower[0]
        return pd.DataFrame({
            "supertrend": supertrend,
            "supertrend_dir": direction,
        }, index=df.index)

    def compute_macd(self, df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame:
        close = df[price_col]
        ema_fast = close.ewm(span=self.config.macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.config.macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        macd_sig = macd_line.ewm(span=self.config.macd_signal, adjust=False).mean()
        macd_hist = macd_line - macd_sig
        return pd.DataFrame({
            "macd": macd_line,
            "macd_signal": macd_sig,
            "macd_hist": macd_hist,
        }, index=df.index)

    def compute_money_flow(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute Institutional & Volume Money Flow Metrics:
            1. MFI (Money Flow Index, 14): Volume-weighted RSI (0 to 100)
            2. CMF (Chaikin Money Flow, 20): Buying/Selling pressure (-1.0 to +1.0)
            3. True Net Money Delta (USDT): Uses exact exchange `real_net_delta_usd` (Taker Buy - Taker Sell)
               if available from Binance klines, otherwise falls back to candle geometry estimation.
            4. CVD (Cumulative Volume Delta) & CVD EMA(20)
            5. OBV (On-Balance Volume) & Relative Volume (RVOL)
        """
        high = df["high"]
        low = df["low"]
        close = df["close"]
        vol = df["volume"]

        typical_price = (high + low + close) / 3.0
        raw_money_flow = typical_price * vol

        # 1. Money Flow Index (MFI 14)
        tp_diff = typical_price.diff()
        pos_flow = pd.Series(np.where(tp_diff > 0, raw_money_flow, 0.0), index=df.index)
        neg_flow = pd.Series(np.where(tp_diff < 0, raw_money_flow, 0.0), index=df.index)

        p_mfi = self.config.mfi_period
        pos_sum = pos_flow.rolling(window=p_mfi, min_periods=p_mfi).sum()
        neg_sum = neg_flow.rolling(window=p_mfi, min_periods=p_mfi).sum().replace(0.0, np.nan)
        mfr = pos_sum / neg_sum
        mfi = (100.0 - (100.0 / (1.0 + mfr))).fillna(50.0)

        # 2. Chaikin Money Flow (CMF 20)
        hl_range = (high - low).replace(0.0, np.nan)
        mf_multiplier = (((close - low) - (high - close)) / hl_range).fillna(0.0)
        mf_volume = mf_multiplier * vol

        p_cmf = self.config.cmf_period
        cmf = (
            mf_volume.rolling(window=p_cmf, min_periods=p_cmf).sum()
            / vol.rolling(window=p_cmf, min_periods=p_cmf).sum().replace(0.0, np.nan)
        ).fillna(0.0)

        # 3. Real Taker Buy/Sell Volume Delta (USDT) & Cumulative Volume Delta (CVD)
        if "real_net_delta_usd" in df.columns and df["real_net_delta_usd"].notna().any():
            net_money_delta_usd = df["real_net_delta_usd"].fillna(0.0)
            has_real_taker = True
        else:
            buy_fraction = ((close - low) / hl_range).fillna(0.5).clip(0.0, 1.0)
            net_delta_fraction = (2.0 * buy_fraction) - 1.0
            net_money_delta_usd = net_delta_fraction * vol * typical_price
            has_real_taker = False

        cvd = net_money_delta_usd.cumsum()
        cvd_ema20 = cvd.ewm(span=20, adjust=False).mean()

        # 3b. Phase 2 Statistical Cash-Flow Anomaly Z-Scores (Coin-Normalized Whale Footprint)
        delta_mean_50 = net_money_delta_usd.rolling(window=50, min_periods=12).mean()
        delta_std_50 = net_money_delta_usd.rolling(window=50, min_periods=12).std(ddof=0).replace(0.0, np.nan)
        delta_zscore = ((net_money_delta_usd - delta_mean_50) / delta_std_50).fillna(0.0).clip(-5.0, 5.0)

        delta_3bar = net_money_delta_usd.rolling(window=3, min_periods=1).sum()
        d3_mean_50 = delta_3bar.rolling(window=50, min_periods=12).mean()
        d3_std_50 = delta_3bar.rolling(window=50, min_periods=12).std(ddof=0).replace(0.0, np.nan)
        flow_impulse_z = ((delta_3bar - d3_mean_50) / d3_std_50).fillna(0.0).clip(-5.0, 5.0)

        # 4. On-Balance Volume (OBV)
        direction = np.sign(close.diff()).fillna(0.0)
        obv = (direction * vol).cumsum()
        obv_ema20 = obv.ewm(span=20, adjust=False).mean()

        # 5. Relative Volume (RVOL) & Rolling VWAP (20)
        vol_sma = vol.rolling(window=self.config.vol_sma_period, min_periods=5).mean().replace(0.0, np.nan)
        rvol = (vol / vol_sma).fillna(1.0)

        vwap_20 = (
            raw_money_flow.rolling(window=20, min_periods=5).sum()
            / vol.rolling(window=20, min_periods=5).sum().replace(0.0, np.nan)
        ).fillna(close)

        # 6. Institutional Limit Order Absorption (Pasif Limit Duvarı Emilimi)
        open_p = df["open"]
        close_pos_in_bar = ((close - low) / hl_range).fillna(0.5)
        lower_wick_ratio = ((np.minimum(open_p, close) - low) / hl_range).fillna(0.0)
        upper_wick_ratio = ((high - np.maximum(open_p, close)) / hl_range).fillna(0.0)

        # Bullish Absorption: High volume + heavy selling / lower wick sweep, yet price closes strong
        bull_abs = (
            (rvol >= 1.20)
            & (
                ((net_money_delta_usd < 0) & (close >= open_p))
                | ((lower_wick_ratio >= 0.45) & (close_pos_in_bar >= 0.55))
            )
        )
        # Bearish Absorption: High volume + heavy buying / upper wick sweep, yet price closes weak
        bear_abs = (
            (rvol >= 1.20)
            & (
                ((net_money_delta_usd > 0) & (close <= open_p))
                | ((upper_wick_ratio >= 0.45) & (close_pos_in_bar <= 0.45))
            )
        )
        absorption_sig = np.select(
            [bull_abs, bear_abs],
            ["BULL_ABSORPTION", "BEAR_ABSORPTION"],
            default="NONE",
        )

        return pd.DataFrame({
            "mfi": mfi,
            "cmf": cmf,
            "net_money_delta_usd": net_money_delta_usd,
            "has_real_taker_flow": has_real_taker,
            "cvd": cvd,
            "cvd_ema20": cvd_ema20,
            "obv": obv,
            "obv_ema20": obv_ema20,
            "rvol": rvol,
            "vwap_20": vwap_20,
            "absorption_signal": absorption_sig,
            "delta_zscore": delta_zscore,
            "flow_impulse_z": flow_impulse_z,
        }, index=df.index)

    @staticmethod
    def compute_kalman_filter(df: pd.DataFrame, q_process: float = 0.015, r_meas: float = 0.12) -> pd.DataFrame:
        """
        Adaptive Volatility-Regime Zero-Lag 1D State-Space Kalman Filter tracking dynamic price
        equilibrium (`kalman_trend`) and instantaneous velocity (`kalman_slope`).
        """
        closes = df["close"].values
        highs = df["high"].values if "high" in df.columns else closes
        lows = df["low"].values if "low" in df.columns else closes
        vols = df["volume"].values if "volume" in df.columns else np.ones(len(closes))
        n = len(closes)
        if n == 0:
            return pd.DataFrame({"kalman_trend": [], "kalman_slope": []}, index=df.index)

        hl_span = np.maximum(highs - lows, closes * 0.0005)
        avg_span = pd.Series(hl_span).rolling(20, min_periods=1).mean().values
        avg_vol = pd.Series(vols).rolling(20, min_periods=1).mean().replace(0.0, 1.0).values

        x_est = float(closes[0])
        v_est = 0.0
        p_cov = 1.0
        kalman_trend = np.zeros(n, dtype=float)
        kalman_slope = np.zeros(n, dtype=float)

        for i in range(n):
            vol_ratio = float(np.clip(vols[i] / max(avg_vol[i], 1e-9), 0.4, 2.5))
            range_ratio = float(np.clip(hl_span[i] / max(avg_span[i], 1e-9), 0.5, 2.2))
            impulse_factor = float(np.clip(0.55 * vol_ratio + 0.45 * range_ratio, 0.45, 2.2))
            r_eff = r_meas / impulse_factor

            # Prediction step
            x_pred = x_est + v_est
            p_pred = p_cov + q_process * impulse_factor

            # Update step
            k_gain = p_pred / (p_pred + r_eff)
            innovation = float(closes[i]) - x_pred
            x_est = x_pred + k_gain * innovation
            v_est = 0.82 * v_est + 0.18 * (k_gain * innovation)
            p_cov = (1.0 - k_gain) * p_pred

            kalman_trend[i] = x_est
            kalman_slope[i] = v_est

        return pd.DataFrame({
            "kalman_trend": kalman_trend,
            "kalman_slope": kalman_slope,
        }, index=df.index)

    def compute_hurst_and_chop(self, df: pd.DataFrame, chop_period: int = 14, hurst_window: int = 96) -> pd.DataFrame:
        """
        Compute Mathematical Regime Metrics:
            1. Choppiness Index (CHOP 14): 0..100 (< 38.2 = Strong Directional Trend, > 61.8 = Sideways Chop)
            2. Multi-Scale Rolling Hurst Exponent (H in 0.15..0.85 over up to 96 bars, lags [1, 2, 4, 8, 16]):
               - H > 0.55: Persistent Trend Regime (Momentum works best)
               - H < 0.45: Anti-Persistent / Mean-Reverting Regime (Support/Resistance & Oscillators work best)
               - 0.45 <= H <= 0.55: Geometric Random Walk / High Noise (Reduce signal confidence)
        """
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # 1. Choppiness Index (14)
        atr_1 = self.compute_atr(df, period=1)
        atr_sum = atr_1.rolling(window=chop_period, min_periods=5).sum()
        hh = high.rolling(window=chop_period, min_periods=5).max()
        ll = low.rolling(window=chop_period, min_periods=5).min()
        hl_span = (hh - ll).replace(0.0, np.nan)
        chop = (100.0 * np.log10((atr_sum / hl_span).clip(lower=1.0)) / np.log10(chop_period)).fillna(50.0).clip(0.0, 100.0)

        # 2. Multi-Scale Log-Dispersion Hurst Exponent (strictly causal)
        closes = close.values
        n = len(closes)
        hurst_arr = np.full(n, 0.5, dtype=float)
        log_p = np.log(np.maximum(closes, 1e-9))

        for i in range(min(24, n), n):
            start = max(0, i - hurst_window + 1)
            seg = log_p[start : i + 1]
            m_seg = len(seg)
            if m_seg < 16:
                continue
            lags = [1, 2, 4, 8, 16] if m_seg >= 40 else [1, 2, 4, 8]
            valid_x = []
            valid_y = []
            for lg in lags:
                if m_seg > lg + 3:
                    diffs = seg[lg:] - seg[:-lg]
                    sd = float(np.std(diffs))
                    if sd > 1e-10:
                        valid_x.append(np.log(float(lg)))
                        valid_y.append(np.log(sd))
            if len(valid_x) >= 3:
                h_est = float(np.polyfit(valid_x, valid_y, 1)[0])
                hurst_arr[i] = float(np.clip(h_est, 0.15, 0.85))

        return pd.DataFrame({
            "choppiness_index": chop,
            "hurst_exponent": hurst_arr,
        }, index=df.index)

    @staticmethod
    def compute_anchored_vwap(df: pd.DataFrame, lookback: int = 90) -> pd.DataFrame:
        """
        Compute Institutional Anchored VWAPs (AVWAP) anchored strictly on CLOSED candles (Zero Repainting)
        and WITHOUT backward-filling pre-anchor bars (Zero Look-Ahead Bias):
            - `avwap_high`: Major Swing High of the last `lookback` closed bars (Seller/Short cost basis)
            - `avwap_low`: Major Swing Low of the last `lookback` closed bars (Institutional Dip-Buyer cost basis)
        """
        n = len(df)
        if n == 0:
            return pd.DataFrame({"avwap_high": [], "avwap_low": []}, index=df.index)

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        vols = np.maximum(df["volume"].values, 1e-9)
        typ = (highs + lows + closes) / 3.0

        # Lock anchor selection to closed candles only so unclosed forming wicks never shift historical anchors
        end_closed = n - 1 if (n >= 2 and "is_closed" in df.columns and not bool(df["is_closed"].iloc[-1])) else n
        start_win = max(0, end_closed - lookback)
        idx_high = start_win + int(np.argmax(highs[start_win:end_closed]))
        idx_low = start_win + int(np.argmin(lows[start_win:end_closed]))

        avwap_high = np.full(n, np.nan, dtype=float)
        avwap_low = np.full(n, np.nan, dtype=float)

        # Compute cumulative VWAP strictly forward from idx_high / idx_low (no .bfill() look-ahead leak)
        cum_pv_h = np.cumsum(typ[idx_high:] * vols[idx_high:])
        cum_v_h = np.cumsum(vols[idx_high:])
        avwap_high[idx_high:] = cum_pv_h / cum_v_h

        cum_pv_l = np.cumsum(typ[idx_low:] * vols[idx_low:])
        cum_v_l = np.cumsum(vols[idx_low:])
        avwap_low[idx_low:] = cum_pv_l / cum_v_l

        return pd.DataFrame({
            "avwap_high": pd.Series(avwap_high, index=df.index),
            "avwap_low": pd.Series(avwap_low, index=df.index),
        }, index=df.index)

    @staticmethod
    def compute_volume_profile(df: pd.DataFrame, bins: int = 36, time_decay: bool = True) -> Dict[str, object]:
        """
        Compute Time-Decayed Institutional Intrabar Volume Profile strictly on CLOSED candles:
            - Locks to closed candles (`is_closed == True`) so forming candles never repaint POC/VAH/VAL
            - Distributes each candle's volume across its `[low, high]` price bins (65% body, 35% full range)
              rather than dumping 100% into a single point
            - POC (Point of Control), VAH & VAL (70% Value Area)
        """
        if df.empty or len(df) < 5:
            last_p = float(df["close"].iloc[-1]) if not df.empty else 0.0
            return {
                "poc": last_p,
                "vah": last_p,
                "val": last_p,
                "bin_centers": np.array([last_p]),
                "bin_volumes": np.array([0.0]),
            }

        work_df = (
            df.iloc[:-1]
            if (len(df) >= 6 and "is_closed" in df.columns and not bool(df["is_closed"].iloc[-1]))
            else df
        )
        # Focus Volume Profile on recent 180 closed bars so ancient macro regimes don't dilute active trading range
        if len(work_df) > 180:
            work_df = work_df.tail(180)

        low_min = float(work_df["low"].min())
        high_max = float(work_df["high"].max())
        if high_max <= low_min:
            return {
                "poc": low_min,
                "vah": low_min,
                "val": low_min,
                "bin_centers": np.array([low_min]),
                "bin_volumes": np.array([float(work_df["volume"].sum())]),
            }

        edges = np.linspace(low_min, high_max, bins + 1)
        centers = 0.5 * (edges[:-1] + edges[1:])
        opens = work_df["open"].values if "open" in work_df.columns else work_df["close"].values
        highs = work_df["high"].values
        lows = work_df["low"].values
        closes = work_df["close"].values
        volumes = work_df["volume"].values
        n = len(volumes)

        if time_decay and n > 10:
            ages = np.arange(n - 1, -1, -1, dtype=float)
            decay_weights = np.exp(-0.0065 * ages)
            eff_volumes = volumes * decay_weights
        else:
            eff_volumes = volumes

        hist_vol = np.zeros(bins, dtype=float)
        b_low_idx = np.clip(np.searchsorted(edges, lows, side="right") - 1, 0, bins - 1)
        b_high_idx = np.clip(np.searchsorted(edges, highs, side="right") - 1, 0, bins - 1)
        body_lo = np.minimum(opens, closes)
        body_hi = np.maximum(opens, closes)
        b_blo_idx = np.clip(np.searchsorted(edges, body_lo, side="right") - 1, 0, bins - 1)
        b_bhi_idx = np.clip(np.searchsorted(edges, body_hi, side="right") - 1, 0, bins - 1)

        for k in range(n):
            v = float(eff_volumes[k])
            if v <= 0.0:
                continue
            i0, i1 = int(b_low_idx[k]), int(b_high_idx[k])
            if i0 >= i1:
                hist_vol[i0] += v
            else:
                # 35% distributed across full [low, high] span, 65% across candle body [body_lo, body_hi]
                span_cnt = i1 - i0 + 1
                hist_vol[i0 : i1 + 1] += (0.35 * v) / span_cnt
                bi0, bi1 = int(b_blo_idx[k]), int(b_bhi_idx[k])
                body_cnt = max(bi1 - bi0 + 1, 1)
                hist_vol[bi0 : bi1 + 1] += (0.65 * v) / body_cnt

        poc_idx = int(np.argmax(hist_vol))
        poc_price = float(centers[poc_idx])

        # Compute 70% Value Area around POC
        total_vol = float(np.sum(hist_vol))
        target_vol = 0.70 * total_vol
        accum_vol = float(hist_vol[poc_idx])
        left_idx = poc_idx
        right_idx = poc_idx

        while accum_vol < target_vol and (left_idx > 0 or right_idx < bins - 1):
            next_left_vol = hist_vol[left_idx - 1] if left_idx > 0 else -1.0
            next_right_vol = hist_vol[right_idx + 1] if right_idx < bins - 1 else -1.0
            if next_left_vol >= next_right_vol and left_idx > 0:
                left_idx -= 1
                accum_vol += float(hist_vol[left_idx])
            elif right_idx < bins - 1:
                right_idx += 1
                accum_vol += float(hist_vol[right_idx])
            else:
                break

        val_price = float(centers[left_idx])
        vah_price = float(centers[right_idx])

        return {
            "poc": poc_price,
            "vah": vah_price,
            "val": val_price,
            "bin_centers": centers,
            "bin_volumes": hist_vol,
        }

    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all technical, trend, volatility, Kalman, Hurst/CHOP, Anchored VWAP, and money flow indicators."""
        enriched = df.copy()
        enriched["rsi"] = self.compute_rsi(enriched)

        for sub_df in [
            self.compute_bollinger_bands(enriched),
            self.compute_adx(enriched),
            self.compute_supertrend(enriched),
            self.compute_macd(enriched),
            self.compute_money_flow(enriched),
            self.compute_kalman_filter(enriched),
            self.compute_hurst_and_chop(enriched),
            self.compute_anchored_vwap(enriched),
        ]:
            for col in sub_df.columns:
                enriched[col] = sub_df[col]

        enriched["atr"] = self.compute_atr(enriched)
        enriched["ema_20"] = enriched["close"].ewm(span=self.config.ema_fast, adjust=False).mean()
        enriched["ema_50"] = enriched["close"].ewm(span=self.config.ema_slow, adjust=False).mean()
        enriched["ema_200"] = enriched["close"].ewm(span=self.config.ema_macro, adjust=False).mean()

        vp = self.compute_volume_profile(enriched)
        enriched["vp_poc"] = vp["poc"]
        enriched["vp_vah"] = vp["vah"]
        enriched["vp_val"] = vp["val"]
        return enriched
