"""
Professional Multi-Timeframe (15M, 1H, 4H, 1D) Interactive Plotly Dashboard & Turkish
Quantitative Decision-Support Report (v2.0).
Features:
    - Future Scenario Projection Box (Boğa Hedef Alanı & Ayı Risk/Geçersizlik Alanı) drawn to the right of the latest candle
    - Volume Profile POC (Point of Control - En Yoğun Hacim Seviyesi) horizontal reference line
    - Real Taker Buy/Sell CVD & Chaikin Money Flow (CMF-20) visualization
    - Historical Signal Win-Rate (Backtest Doğrulama) cards
"""
from datetime import timedelta
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .config import AnalysisConfig
from .data_fetcher import OrderFlowIntel
from .patterns import PATTERN_INFO_TR
from .signals import MarketForecast, SignalEngine

_V4_1_UI_CLEAN = True
_V5_0_READY = True
_V6_0_READY = True


class InteractiveChartVisualizer:
    """
    Builds an institutional-grade, ultra-readable Turkish Crypto Decision-Support Chart (v2.0):
        - Row 1 (58%): Candlesticks + EMA 20/50 Trend Ribbon + SuperTrend + Bollinger Bands
                       + Volume Profile POC Line + Shaded Support/Resistance Zones
                       + Future Scenario Target/Invalidation Projection Box (Risk/Reward)
                       + Confirmed A+ Reversal Markers & RSI Divergence Lines
        - Row 2 (20%): Money Flow & Real Taker Delta (Chaikin Money Flow CMF-20 + Net USDT Delta)
        - Row 3 (22%): Wilder's RSI (14) + Money Flow Index (MFI 14) + Divergence Connectors
    """

    def __init__(self, config: Optional[AnalysisConfig] = None):
        self.config = config or AnalysisConfig()
        self.signal_engine = SignalEngine(self.config.indicators)

    @staticmethod
    def _price_format(max_price: float) -> str:
        return ",.4f" if max_price < 10.0 else ",.2f"

    def create_figure(
        self,
        df: pd.DataFrame,
        exchange_source: str = "BINANCE",
        forecast: Optional[MarketForecast] = None,
        show_bollinger: bool = False,
        show_ema_ribbon: bool = True,
        show_supertrend: bool = False,
        show_sr_zones: bool = True,
        show_poc: bool = True,
        show_divergences: bool = False,
        show_projection_box: bool = True,
        show_smc: bool = False,
        show_liq_pools: bool = False,
        show_prob_cone: bool = False,
        show_reversal_markers: bool = True,
        show_text_labels: bool = False,
        show_kalman_avwap: bool = False,
        show_vpvr: bool = False,
    ) -> go.Figure:
        tf_label = self.config.exchange.timeframe.upper()
        return self.create_multi_timeframe_figure(
            tf_data={tf_label: df},
            tf_forecasts={tf_label: forecast or self.signal_engine.generate_forecast(df, symbol=self.config.exchange.symbol)},
            exchange_source=exchange_source,
            default_tf=tf_label,
            show_bollinger=show_bollinger,
            show_ema_ribbon=show_ema_ribbon,
            show_supertrend=show_supertrend,
            show_sr_zones=show_sr_zones,
            show_poc=show_poc,
            show_divergences=show_divergences,
            show_projection_box=show_projection_box,
            show_smc=show_smc,
            show_liq_pools=show_liq_pools,
            show_prob_cone=show_prob_cone,
            show_reversal_markers=show_reversal_markers,
            show_text_labels=show_text_labels,
            show_kalman_avwap=show_kalman_avwap,
            show_vpvr=show_vpvr,
        )

    def create_multi_timeframe_figure(
        self,
        tf_data: Dict[str, pd.DataFrame],
        tf_forecasts: Dict[str, MarketForecast],
        exchange_source: str = "BINANCE",
        default_tf: str = "1H",
        show_bollinger: bool = False,
        show_ema_ribbon: bool = True,
        show_supertrend: bool = False,
        show_sr_zones: bool = True,
        show_poc: bool = True,
        show_divergences: bool = False,
        show_projection_box: bool = True,
        show_smc: bool = False,
        show_liq_pools: bool = False,
        show_prob_cone: bool = False,
        show_reversal_markers: bool = True,
        show_text_labels: bool = False,
        show_kalman_avwap: bool = False,
        show_vpvr: bool = False,
    ) -> go.Figure:
        c_cfg = self.config.chart
        i_cfg = self.config.indicators
        e_cfg = self.config.exchange

        timeframes = list(tf_data.keys())
        if default_tf not in timeframes:
            default_tf = timeframes[0]

        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.045,
            row_heights=[0.58, 0.19, 0.23],
            subplot_titles=(
                f"<b>1. {e_cfg.symbol} Fiyat Grafiği, Trend Yönü & Gelecek Hedef / Stop Alanı</b>",
                "<b>2. Para Giriş / Çıkış Barları (Yeşil Bar = Para Girişi, Kırmızı Bar = Para Çıkışı)</b>",
                "<b>3. Alım / Satım Gücü (70 Üstü = Pahalı / Kâr Satışı Riski, 30 Altı = Ucuz / Tepki Bölgesi)</b>",
            ),
        )

        tf_trace_indices: Dict[str, list] = {}
        tf_shapes: Dict[str, list] = {}
        tf_annotations: Dict[str, list] = {}

        base_annotations = [a.to_plotly_json() for a in fig.layout.annotations]

        for tf in timeframes:
            df = tf_data[tf]
            fc = tf_forecasts[tf]
            is_visible = tf == default_tf
            start_idx = len(fig.data)

            max_price = float(df["close"].max())
            p_fmt = self._price_format(max_price)
            price_span = float(df["high"].max() - df["low"].min())
            offset = price_span * 0.024 if price_span > 0 else float(df["close"].iloc[-1]) * 0.006

            # ------------------------------------------------------------------
            # 1. TREND RIBBON: EMA 20 & EMA 50 (Row 1)
            # ------------------------------------------------------------------
            if show_ema_ribbon:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df["ema_20"],
                        name="Kısa Vadeli Trend (EMA 20)",
                        visible=is_visible,
                        line=dict(color="#38BDF8", width=1.9),
                        hovertemplate=(
                            f"<b>🌊 Kısa Vadeli Trend Çizgisi (EMA 20):</b> %{{y:{p_fmt}}} USDT<br>"
                            "💬 <b>Ne İşe Yarar?:</b> Son 20 mumun ortalama yönüdür. Fiyat bu mavi çizginin "
                            "üzerindeyse kısa vadede alıcılar güçlüdür.<extra></extra>"
                        ),
                    ),
                    row=1,
                    col=1,
                )

                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df["ema_50"],
                        name="Ana Trend Çizgisi (EMA 50)",
                        visible=is_visible,
                        line=dict(color="#F59E0B", width=2.1),
                        fill="tonexty",
                        fillcolor="rgba(56, 189, 248, 0.06)",
                        hovertemplate=(
                            f"<b>🌊 Ana Trend Çizgisi (EMA 50):</b> %{{y:{p_fmt}}} USDT<br>"
                            "💬 <b>Ne İşe Yarar?:</b> Orta vadeli ana yön çizgisidir. Mavi çizgi (EMA 20) bu turuncu "
                            "çizginin üzerindeyse yükseliş trendi, altındaysa düşüş trendi hakimdir.<extra></extra>"
                        ),
                    ),
                    row=1,
                    col=1,
                )

            # ------------------------------------------------------------------
            # 2. SUPERTREND INDICATOR (Row 1)
            # ------------------------------------------------------------------
            if show_supertrend and "supertrend" in df.columns:
                st_bull = df["supertrend"].where(df["supertrend_dir"] == 1, np.nan)
                st_bear = df["supertrend"].where(df["supertrend_dir"] == -1, np.nan)

                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=st_bull,
                        name="SuperTrend (Yükseliş Koruma Çizgisi)",
                        visible=is_visible,
                        line=dict(color="rgba(0, 230, 118, 0.85)", width=1.6, dash="dash"),
                        hovertemplate=(
                            f"<b>🛡️ SuperTrend Yükseliş Desteği:</b> %{{y:{p_fmt}}} USDT<br>"
                            "💬 <b>Ne İşe Yarar?:</b> Fiyat bu yeşil kesikli çizginin üzerinde kaldıkça yükseliş "
                            "korunur; altına kırılırsa trend negatife döner.<extra></extra>"
                        ),
                    ),
                    row=1,
                    col=1,
                )
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=st_bear,
                        name="SuperTrend (Düşüş Baskı Çizgisi)",
                        visible=is_visible,
                        line=dict(color="rgba(255, 82, 82, 0.85)", width=1.6, dash="dash"),
                        hovertemplate=(
                            f"<b>🛡️ SuperTrend Düşüş Direnci:</b> %{{y:{p_fmt}}} USDT<br>"
                            "💬 <b>Ne İşe Yarar?:</b> Fiyat bu kırmızı kesikli çizginin altında kaldıkça düşüş "
                            "baskısı sürer; üzerine çıkarsa yükseliş başlar.<extra></extra>"
                        ),
                    ),
                    row=1,
                    col=1,
                )

            # ------------------------------------------------------------------
            # 3. BOLLINGER BANDS (Row 1)
            # ------------------------------------------------------------------
            if show_bollinger:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df["bb_upper"],
                        name="Bollinger Üst Sınır (Pahalı Bölge)",
                        visible=is_visible,
                        line=dict(color="rgba(148, 163, 184, 0.45)", width=1.0, dash="dot"),
                        hovertemplate=(
                            f"<b>📏 Bollinger Üst Sınırı:</b> %{{y:{p_fmt}}} USDT<br>"
                            "💬 <b>Ne İşe Yarar?:</b> Fiyatın normal dalgalanma tavanıdır. Buraya değdiğinde fiyat "
                            "kısa vadede 'pahalı/aşırı şişkin' kabul edilir.<extra></extra>"
                        ),
                    ),
                    row=1,
                    col=1,
                )

                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df["bb_lower"],
                        name="Bollinger Alt Sınır (Ucuz Bölge)",
                        visible=is_visible,
                        line=dict(color="rgba(148, 163, 184, 0.45)", width=1.0, dash="dot"),
                        fill="tonexty",
                        fillcolor="rgba(148, 163, 184, 0.03)",
                        hovertemplate=(
                            f"<b>📏 Bollinger Alt Sınırı:</b> %{{y:{p_fmt}}} USDT<br>"
                            "💬 <b>Ne İşe Yarar?:</b> Fiyatın normal dalgalanma tabanıdır. Buraya değdiğinde fiyat "
                            "kısa vadede 'ucuz' kabul edilir ve tepki alımı gelebilir.<extra></extra>"
                        ),
                    ),
                    row=1,
                    col=1,
                )

            # ------------------------------------------------------------------
            # 3b. ZERO-LAG KALMAN FILTER & ANCHORED VWAP (High/Low) (Row 1)
            # ------------------------------------------------------------------
            if show_kalman_avwap:
                if "kalman_trend" in df.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=df["timestamp"],
                            y=df["kalman_trend"],
                            name="⚡ Erken Trend İzi (Kalman)",
                            visible=is_visible,
                            line=dict(color="#EC4899", width=1.8),
                            hovertemplate=(
                                f"<b>⚡ Erken Trend İzi (Kalman Filtresi):</b> %{{y:{p_fmt}}} USDT<br>"
                                "💬 <b>Ne İşe Yarar?:</b> Normal ortalamalar geç kalırken bu pembe çizgi fiyatın "
                                "dönüşünü gecikmesiz yakalar. Fiyat pembe çizginin üstündeyse anlık yön yukarıdır.<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )
                if "avwap_low" in df.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=df["timestamp"],
                            y=df["avwap_low"],
                            name="⚓ Dip Alıcılarının Ortalama Maliyeti (Dip AVWAP)",
                            visible=is_visible,
                            line=dict(color="#10B981", width=1.6, dash="dashdot"),
                            hovertemplate=(
                                f"<b>⚓ Dip Alıcılarının Ortalama Maliyeti (Dip AVWAP):</b> %{{y:{p_fmt}}} USDT<br>"
                                "💬 <b>Ne İşe Yarar?:</b> Son büyük dipten beri alım yapan balina ve yatırımcıların "
                                "ortalama alış fiyatıdır. Fiyat bunun üzerindeyse alıcılar kârdadır ve burayı destek yaparlar.<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )
                if "avwap_high" in df.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=df["timestamp"],
                            y=df["avwap_high"],
                            name="⚓ Tepe Satıcılarının Ortalama Maliyeti (Tepe AVWAP)",
                            visible=is_visible,
                            line=dict(color="#F43F5E", width=1.6, dash="dashdot"),
                            hovertemplate=(
                                f"<b>⚓ Tepe Satıcılarının Ortalama Maliyeti (Tepe AVWAP):</b> %{{y:{p_fmt}}} USDT<br>"
                                "💬 <b>Ne İşe Yarar?:</b> Son büyük tepeden beri içeride kalanların ve düşüşe oynayanların "
                                "ortalama maliyetidir. Fiyat bu kırmızı çizgiyi yukarı aşarsa düşüş biter, yükseliş hızlanır.<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )

            # ------------------------------------------------------------------
            # 4. CANDLESTICK CHART (Row 1)
            # ------------------------------------------------------------------
            fig.add_trace(
                go.Candlestick(
                    x=df["timestamp"],
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                    name=f"{e_cfg.symbol} Mum ({tf})",
                    visible=is_visible,
                    increasing_line_color=c_cfg.up_color,
                    decreasing_line_color=c_cfg.down_color,
                    increasing_fillcolor=c_cfg.up_color,
                    decreasing_fillcolor=c_cfg.down_color,
                ),
                row=1,
                col=1,
            )

            # ------------------------------------------------------------------
            # 5. PROBABILITY CONE (1σ 68% VOLATILITY FAN) & FUTURE SCENARIO PROJECTION (Row 1)
            # ------------------------------------------------------------------
            if len(df) >= 3:
                last_ts = df["timestamp"].iloc[-1]
                prev_ts = df["timestamp"].iloc[-2]
                bar_delta = last_ts - prev_ts
                future_ts = last_ts + (bar_delta * 7)
                curr_p = float(df["close"].iloc[-1])
                cone = fc.smc.probability_cone if fc.smc else None

                # Statistical Probability Cone (1-Sigma 68% Volatility Fan) — Independent toggle
                if show_prob_cone and cone and len(cone.timestamps) >= 2:
                    fig.add_trace(
                        go.Scatter(
                            x=cone.timestamps,
                            y=cone.upper_1sigma,
                            mode="lines",
                            name="Olasılık Konisi Üst Sınır (%68)",
                            visible=is_visible,
                            showlegend=False,
                            line=dict(color="rgba(56, 189, 248, 0.35)", width=1.0, dash="dot"),
                            hovertemplate=(
                                f"<b>🔮 Olasılık Yelpazesi Üst Sınırı:</b> %{{y:{p_fmt}}} USDT<br>"
                                "💬 <b>Ne İşe Yarar?:</b> İstatistiksel olarak fiyatın önümüzdeki mumlarda %68 ihtimalle "
                                "bu mavi koridorun içinde kalması beklenir.<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=cone.timestamps,
                            y=cone.lower_1sigma,
                            mode="lines",
                            name="🔮 Olasılık Yelpazesi (%68 Beklenen Koridor)",
                            visible=is_visible,
                            fill="tonexty",
                            fillcolor="rgba(56, 189, 248, 0.08)",
                            line=dict(color="rgba(56, 189, 248, 0.35)", width=1.0, dash="dot"),
                            hovertemplate=(
                                f"<b>🔮 Olasılık Yelpazesi Alt Sınırı:</b> %{{y:{p_fmt}}} USDT<br>"
                                "💬 <b>Ne İşe Yarar?:</b> İstatistiksel olarak fiyatın önümüzdeki mumlarda %68 ihtimalle "
                                "bu mavi koridorun içinde kalması beklenir.<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=cone.timestamps,
                            y=cone.expected_path,
                            mode="lines",
                            name="🧭 İstatistiksel Ortalama Rota",
                            visible=is_visible,
                            line=dict(color="#38BDF8", width=1.6, dash="dashdot"),
                            hovertemplate=(
                                f"<b>🧭 İstatistiksel Ortalama Rota:</b> %{{y:{p_fmt}}} USDT<br>"
                                "💬 <b>Ne İşe Yarar?:</b> Mevcut hız ve oynaklığa göre fiyatın en olası merkez rotasıdır.<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )

                if show_projection_box:
                    tp1_val = fc.tp1_price if fc.tp1_price > 0 else fc.bullish_target_price
                    tp2_val = fc.tp2_price if fc.tp2_price > 0 else fc.bullish_target_price
                    stp_val = fc.stop_price if fc.stop_price > 0 else fc.bearish_invalidation_price
                    is_bear_setup = (tp2_val < curr_p) or (fc.score < 0)

                    prob_win_tag = f" (~%{cone.prob_win_before_stop_pct:.0f})" if (cone and not is_bear_setup) else (
                        f" (~%{100.0 - cone.prob_win_before_stop_pct:.0f})" if cone else ""
                    )
                    dir_word = "Düşüş" if is_bear_setup else "Yükseliş"

                    # 1st Safe Partial Target (TP1)
                    fig.add_trace(
                        go.Scatter(
                            x=[last_ts, future_ts],
                            y=[curr_p, tp1_val],
                            mode="lines+markers+text",
                            name=f"🎯 1. Güvenli Hedef ({dir_word} TP1)",
                            visible=is_visible,
                            text=["", f"<b> 🎯 TP1 (İlk Kâr): {format(tp1_val, p_fmt)}</b>"],
                            textposition="middle right",
                            textfont=dict(color="#38BDF8", size=10.5),
                            line=dict(color="#38BDF8", width=1.6, dash="dashdot"),
                            marker=dict(symbol="circle", size=7, color="#38BDF8"),
                            hovertemplate=(
                                f"<b>🎯 1. Güvenli Kâr Hedefi ({dir_word} TP1):</b> {format(tp1_val, p_fmt)} USDT<br>"
                                "💬 <b>Ne İşe Yarar?:</b> Fiyatın ilk ulaşması beklenen yakın kâr alma bölgesidir. "
                                "Kurumsal yatırımcılar burada işlemin yarısını kapatıp stopu giriş fiyatına çekerler.<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )

                    # 2nd Main Target Trajectory (TP2)
                    fig.add_trace(
                        go.Scatter(
                            x=[last_ts, future_ts],
                            y=[curr_p, tp2_val],
                            mode="lines+markers+text",
                            name=f"🎯 2. Ana Hedef ({dir_word} TP2)",
                            visible=is_visible,
                            text=["", f"<b> 🎯 TP2 (Ana Hedef): {format(tp2_val, p_fmt)}{prob_win_tag}</b>"],
                            textposition="middle right",
                            textfont=dict(color="#00E676", size=11),
                            line=dict(color="#00E676", width=2.0, dash="dot"),
                            marker=dict(symbol="diamond", size=8, color="#00E676"),
                            hovertemplate=(
                                f"<b>🎯 2. Ana Kâr Hedefi ({dir_word} TP2):</b> {format(tp2_val, p_fmt)} USDT<br>"
                                "💬 <b>Ne İşe Yarar?:</b> Hareketin devamında ulaşılması beklenen ana hedef seviyesidir.<br>"
                                f"{fc.bearish_scenario_tr if is_bear_setup else fc.bullish_scenario_tr}<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )

                    # Direction-Aware Invalidation / Stop-Loss Trajectory
                    fig.add_trace(
                        go.Scatter(
                            x=[last_ts, future_ts],
                            y=[curr_p, stp_val],
                            mode="lines+markers+text",
                            name="🛡️ Zarar Kes (Stop / Risk Sınırı)",
                            visible=is_visible,
                            text=["", f"<b> 🛡️ Stop (Tehlike Sınırı): {format(stp_val, p_fmt)}</b>"],
                            textposition="middle right",
                            textfont=dict(color="#FF5252", size=11),
                            line=dict(color="#FF5252", width=2.0, dash="dot"),
                            marker=dict(symbol="x", size=8, color="#FF5252"),
                            hovertemplate=(
                                f"<b>🛡️ Zarar Kes / Tehlike Sınırı (Stop):</b> {format(stp_val, p_fmt)} USDT<br>"
                                "💬 <b>Ne İşe Yarar?:</b> Fiyat bu kırmızı çizgiye değerse mevcut yön beklentisi iptal olur; "
                                "zararın büyümemesi için koruma sınırıdır.<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )

            # ------------------------------------------------------------------
            # 5B. SMART MONEY CONCEPTS (SMC): BOS / CHoCH & LIQUIDITY SWEEPS (Row 1)
            # ------------------------------------------------------------------
            if show_smc and fc.smc and fc.smc.structure_events:
                recent_evs = fc.smc.structure_events[-2:]
                for idx_ev, ev in enumerate(recent_evs):
                    is_bull_ev = "BULL" in ev.event_type
                    ev_color = "#00E676" if is_bull_ev else "#FF5252"
                    ev_sym = "star" if "SWEEP" in ev.event_type else "diamond-open"
                    # Show text only on the latest event if show_text_labels is enabled
                    show_ev_txt = show_text_labels and (idx_ev == len(recent_evs) - 1)
                    fig.add_trace(
                        go.Scatter(
                            x=[ev.timestamp],
                            y=[ev.price],
                            mode="markers+text" if show_ev_txt else "markers",
                            name=ev.label_tr,
                            visible=is_visible,
                            showlegend=False,
                            text=[f"<b>{ev.label_tr}</b>"] if show_ev_txt else None,
                            textposition="bottom center" if is_bull_ev else "top center",
                            textfont=dict(color=ev_color, size=10),
                            marker=dict(symbol=ev_sym, size=11, color=ev_color, line=dict(color="#FFFFFF", width=1)),
                            hovertemplate=f"<b>{ev.label_tr}</b><br>Seviye: {format(ev.price, p_fmt)} USDT<br>{ev.explanation_tr}<extra></extra>",
                        ),
                        row=1,
                        col=1,
                    )

            # ------------------------------------------------------------------
            # 6. CONFIRMED REVERSAL SIGNALS & TURKISH EXPLANATIONS (Row 1)
            # ------------------------------------------------------------------
            if show_reversal_markers:
                bull_rev = df[df["signal_type"] == "BULLISH_REVERSAL"].copy()
                if not bull_rev.empty:
                    texts = [""] * len(bull_rev)
                    if show_text_labels:
                        texts[-1] = bull_rev.iloc[-1]["chart_tag_tr"]

                    fig.add_trace(
                        go.Scatter(
                            x=bull_rev["timestamp"],
                            y=bull_rev["low"] - offset * 1.05,
                            mode="markers+text" if show_text_labels else "markers",
                            name="Onaylı Yükseliş Dönüşü (▲)",
                            visible=is_visible,
                            text=texts if show_text_labels else None,
                            textposition="bottom center",
                            textfont=dict(color="#00E676", size=10.5, family="Segoe UI, Arial, sans-serif"),
                            marker=dict(
                                symbol="triangle-up",
                                size=12,
                                color="#00E676",
                                line=dict(color="#FFFFFF", width=1.2),
                            ),
                            customdata=np.stack(
                                [
                                    bull_rev["pattern_tr_name"],
                                    bull_rev["pattern_meaning_tr"],
                                    bull_rev["close"],
                                    bull_rev["rsi"].fillna(50.0),
                                    bull_rev["cmf"].fillna(0.0),
                                ],
                                axis=-1,
                            ),
                            hovertemplate=(
                                "<b>🟢 ONAYLI YÜKSELİŞ DÖNÜŞ SİNYALİ (Kapanmış Mum)</b><br>"
                                "<b>Formasyon:</b> %{customdata[0]}<br>"
                                f"<b>Kapanış:</b> %{{customdata[2]:{p_fmt}}} USDT | <b>RSI:</b> %{{customdata[3]:.1f}} | <b>CMF:</b> %{{customdata[4]:+.2f}}<br>"
                                "<b>Ne Anlama Gelir?:</b> %{customdata[1]}<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )

                bear_rev = df[df["signal_type"] == "BEARISH_REVERSAL"].copy()
                if not bear_rev.empty:
                    texts = [""] * len(bear_rev)
                    if show_text_labels:
                        texts[-1] = bear_rev.iloc[-1]["chart_tag_tr"]

                    fig.add_trace(
                        go.Scatter(
                            x=bear_rev["timestamp"],
                            y=bear_rev["high"] + offset * 1.05,
                            mode="markers+text" if show_text_labels else "markers",
                            name="Onaylı Düşüş Dönüşü (▼)",
                            visible=is_visible,
                            text=texts if show_text_labels else None,
                            textposition="top center",
                            textfont=dict(color="#FF5252", size=10.5, family="Segoe UI, Arial, sans-serif"),
                            marker=dict(
                                symbol="triangle-down",
                                size=12,
                                color="#FF5252",
                                line=dict(color="#FFFFFF", width=1.2),
                            ),
                            customdata=np.stack(
                                [
                                    bear_rev["pattern_tr_name"],
                                    bear_rev["pattern_meaning_tr"],
                                    bear_rev["close"],
                                    bear_rev["rsi"].fillna(50.0),
                                    bear_rev["cmf"].fillna(0.0),
                                ],
                                axis=-1,
                            ),
                            hovertemplate=(
                                "<b>🔴 ONAYLI DÜŞÜŞ DÖNÜŞ SİNYALİ (Kapanmış Mum)</b><br>"
                                "<b>Formasyon:</b> %{customdata[0]}<br>"
                                f"<b>Kapanış:</b> %{{customdata[2]:{p_fmt}}} USDT | <b>RSI:</b> %{{customdata[3]:.1f}} | <b>CMF:</b> %{{customdata[4]:+.2f}}<br>"
                                "<b>Ne Anlama Gelir?:</b> %{customdata[1]}<extra></extra>"
                            ),
                        ),
                        row=1,
                        col=1,
                    )

            other_bull = df[df["signal_type"] == "BULLISH_PATTERN"]
            if not other_bull.empty:
                fig.add_trace(
                    go.Scatter(
                        x=other_bull["timestamp"],
                        y=other_bull["low"] - offset * 0.65,
                        mode="markers",
                        name="Diğer Boğa Mumları (Detay)",
                        visible="legendonly" if is_visible else False,
                        marker=dict(symbol="circle", size=7, color="#00E676"),
                        customdata=np.stack(
                            [other_bull["pattern_tr_name"], other_bull["pattern_meaning_tr"], other_bull["close"]],
                            axis=-1,
                        ),
                        hovertemplate=(
                            "<b>🟢 %{customdata[0]}</b><br>"
                            f"<b>Fiyat:</b> %{{customdata[2]:{p_fmt}}} USDT<br>"
                            "<b>Açıklama:</b> %{customdata[1]}<extra></extra>"
                        ),
                    ),
                    row=1,
                    col=1,
                )

            other_bear = df[df["signal_type"] == "BEARISH_PATTERN"]
            if not other_bear.empty:
                fig.add_trace(
                    go.Scatter(
                        x=other_bear["timestamp"],
                        y=other_bear["high"] + offset * 0.65,
                        mode="markers",
                        name="Diğer Ayı Mumları (Detay)",
                        visible="legendonly" if is_visible else False,
                        marker=dict(symbol="circle", size=7, color="#FF5252"),
                        customdata=np.stack(
                            [other_bear["pattern_tr_name"], other_bear["pattern_meaning_tr"], other_bear["close"]],
                            axis=-1,
                        ),
                        hovertemplate=(
                            "<b>🔴 %{customdata[0]}</b><br>"
                            f"<b>Fiyat:</b> %{{customdata[2]:{p_fmt}}} USDT<br>"
                            "<b>Açıklama:</b> %{customdata[1]}<extra></extra>"
                        ),
                    ),
                    row=1,
                    col=1,
                )

            # ------------------------------------------------------------------
            # 7. RSI DIVERGENCE LINES ON PRICE & RSI (Row 1 & Row 3)
            # ------------------------------------------------------------------
            if show_divergences and fc.divergences:
                for div in fc.divergences:
                    div_color = "#00E676" if div.div_type == "BULLISH_DIV" else "#FF5252"
                    fig.add_trace(
                        go.Scatter(
                            x=[div.time_start, div.time_end],
                            y=[div.price_start, div.price_end],
                            mode="lines+markers+text",
                            name=div.label_tr,
                            visible=is_visible,
                            text=["", f"<b>{div.label_tr}</b>"],
                            textposition="bottom center" if div.div_type == "BULLISH_DIV" else "top center",
                            textfont=dict(color=div_color, size=11),
                            line=dict(color=div_color, width=2.4, dash="solid"),
                            marker=dict(size=8, color=div_color),
                            hovertemplate=f"<b>{div.label_tr}</b><br>{div.explanation_tr}<extra></extra>",
                        ),
                        row=1,
                        col=1,
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=[div.time_start, div.time_end],
                            y=[div.rsi_start, div.rsi_end],
                            mode="lines+markers",
                            name=f"{div.label_tr} (RSI)",
                            visible=is_visible,
                            showlegend=False,
                            line=dict(color=div_color, width=2.2, dash="solid"),
                            marker=dict(size=7, color=div_color),
                            hovertemplate=f"<b>{div.label_tr}</b><br>RSI: {div.rsi_start:.1f} -> {div.rsi_end:.1f}<extra></extra>",
                        ),
                        row=3,
                        col=1,
                    )

            # ------------------------------------------------------------------
            # 8. MONEY FLOW: CHAIKIN MONEY FLOW (CMF 20) & REAL TAKER DELTA (Row 2)
            # ------------------------------------------------------------------
            cmf_vals = df.get("cmf", pd.Series(0.0, index=df.index)).fillna(0.0)
            cmf_colors = np.where(cmf_vals >= 0.0, "rgba(0, 230, 118, 0.78)", "rgba(255, 82, 82, 0.78)")
            fig.add_trace(
                go.Bar(
                    x=df["timestamp"],
                    y=cmf_vals,
                    name="💸 Para Giriş / Çıkışı (CMF)",
                    visible=is_visible,
                    marker_color=cmf_colors,
                    customdata=np.stack(
                        [
                            df.get("net_money_delta_usd", pd.Series(0.0, index=df.index)).fillna(0.0),
                            df.get("rvol", pd.Series(1.0, index=df.index)).fillna(1.0),
                        ],
                        axis=-1,
                    ),
                    hovertemplate=(
                        "<b>💸 Para Giriş / Çıkış Gücü (CMF 20):</b> %{y:+.3f}<br>"
                        "<b>Net Alıcı / Satıcı Nakit Farkı:</b> %{customdata[0]:+,.0f} USDT<br>"
                        "<b>İşlem Hacmi Katı (RVOL):</b> %{customdata[1]:.2f}x<br>"
                        "💬 <b>Ne İşe Yarar?:</b> Barlar yeşil (0 üstü) ise coine gerçek nakit para giriyor demektir. "
                        "Barlar kırmızı (0 altı) ise yatırımcılar mal satıp çıkıyor demektir.<extra></extra>"
                    ),
                ),
                row=2,
                col=1,
            )

            # ------------------------------------------------------------------
            # 9. RSI (14) & MONEY FLOW INDEX (MFI 14) (Row 3)
            # ------------------------------------------------------------------
            fig.add_trace(
                go.Scatter(
                    x=df["timestamp"],
                    y=df["rsi"],
                    name=f"⚡ Alım/Satım Gücü (RSI {i_cfg.rsi_period})",
                    visible=is_visible,
                    line=dict(color=c_cfg.rsi_color, width=2.2),
                    hovertemplate=(
                        "<b>⚡ Alım/Satım Gücü (RSI 14):</b> %{y:.1f}<br>"
                        "💬 <b>Ne İşe Yarar?:</b> 0 ile 100 arasında değişir. 70'in üstü fiyatın çok şiştiğini (kâr satışı gelebileceğini), "
                        "30'un altı ise çok düştüğünü (ucuzlayıp tepki alımı gelebileceğini) gösterir.<extra></extra>"
                    ),
                ),
                row=3,
                col=1,
            )

            if "mfi" in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df["mfi"],
                        name=f"💧 Hacimli Para Endeksi (MFI {i_cfg.mfi_period})",
                        visible=is_visible,
                        line=dict(color="#38BDF8", width=1.5, dash="dot"),
                        hovertemplate=(
                            "<b>💧 Hacimli Para Endeksi (MFI 14):</b> %{y:.1f}<br>"
                            "💬 <b>Ne İşe Yarar?:</b> RSI'ın işlem hacmiyle birleştirilmiş halidir. 80 üstü aşırı doygunluk, "
                            "20 altı ise aşırı satış sonrası dip toplama bölgesidir.<extra></extra>"
                        ),
                    ),
                    row=3,
                    col=1,
                )

            end_idx = len(fig.data)
            tf_trace_indices[tf] = list(range(start_idx, end_idx))

            # ------------------------------------------------------------------
            # 10. SHAPES: POC LINE, S/R SHADED ZONES & FUTURE RISK/REWARD BOX
            # ------------------------------------------------------------------
            shapes_for_tf = [
                dict(
                    type="line",
                    xref="paper",
                    yref="y2",
                    x0=0,
                    x1=1,
                    y0=0.0,
                    y1=0.0,
                    line=dict(color="rgba(255, 255, 255, 0.35)", width=1.0),
                ),
                dict(
                    type="line",
                    xref="paper",
                    yref="y3",
                    x0=0,
                    x1=1,
                    y0=i_cfg.rsi_overbought,
                    y1=i_cfg.rsi_overbought,
                    line=dict(color="rgba(255, 82, 82, 0.7)", width=1.2, dash="dash"),
                ),
                dict(
                    type="line",
                    xref="paper",
                    yref="y3",
                    x0=0,
                    x1=1,
                    y0=50.0,
                    y1=50.0,
                    line=dict(color="rgba(255, 255, 255, 0.22)", width=1.0, dash="dot"),
                ),
                dict(
                    type="line",
                    xref="paper",
                    yref="y3",
                    x0=0,
                    x1=1,
                    y0=i_cfg.rsi_oversold,
                    y1=i_cfg.rsi_oversold,
                    line=dict(color="rgba(0, 230, 118, 0.7)", width=1.2, dash="dash"),
                ),
                dict(
                    type="rect",
                    xref="paper",
                    yref="y3",
                    x0=0,
                    x1=1,
                    y0=i_cfg.rsi_oversold,
                    y1=i_cfg.rsi_overbought,
                    fillcolor="rgba(192, 132, 252, 0.05)",
                    line=dict(width=0),
                ),
            ]

            ann_for_tf = list(base_annotations)

            # Horizontal Volume Profile (VPVR) Histogram Bars on Left Side (v6.0)
            if show_vpvr and getattr(fc, "vp_bin_centers", None) and getattr(fc, "vp_bin_volumes", None):
                centers = fc.vp_bin_centers
                vols = fc.vp_bin_volumes
                max_v = max(vols) if vols else 0.0
                if max_v > 0 and len(centers) >= 2:
                    half_h = abs(centers[1] - centers[0]) * 0.42
                    for c_val, v_val in zip(centers, vols):
                        bar_w = 0.14 * (v_val / max_v)
                        if bar_w <= 0.002:
                            continue
                        is_poc_bin = abs(c_val - fc.poc_price) <= half_h * 1.35
                        in_va = fc.val_price <= c_val <= fc.vah_price
                        if is_poc_bin:
                            fill_c = "rgba(250, 204, 21, 0.34)"
                            line_c = "rgba(250, 204, 21, 0.75)"
                        elif in_va:
                            fill_c = "rgba(56, 189, 248, 0.18)"
                            line_c = "rgba(56, 189, 248, 0.42)"
                        else:
                            fill_c = "rgba(148, 163, 184, 0.10)"
                            line_c = "rgba(148, 163, 184, 0.25)"
                        shapes_for_tf.append(
                            dict(
                                type="rect",
                                xref="paper",
                                yref="y",
                                x0=0.0,
                                x1=bar_w,
                                y0=c_val - half_h,
                                y1=c_val + half_h,
                                fillcolor=fill_c,
                                line=dict(color=line_c, width=0.8),
                            )
                        )

            # Volume Profile POC (Point of Control) Golden Horizontal Line
            if show_poc and fc.poc_price > 0:
                shapes_for_tf.append(
                    dict(
                        type="line",
                        xref="paper",
                        yref="y",
                        x0=0,
                        x1=1,
                        y0=fc.poc_price,
                        y1=fc.poc_price,
                        line=dict(color="rgba(250, 204, 21, 0.78)", width=1.6, dash="longdash"),
                    )
                )
                ann_for_tf.append(
                    dict(
                        xref="paper",
                        yref="y",
                        x=0.008,
                        y=fc.poc_price,
                        xanchor="left",
                        yanchor="bottom",
                        text=f"<b>🟡 En Yoğun İşlem Fiyatı (POC): {format(fc.poc_price, p_fmt)}</b>",
                        showarrow=False,
                        font=dict(size=10, color="#FACC15"),
                        bgcolor="rgba(11, 15, 25, 0.85)",
                        bordercolor="rgba(250, 204, 21, 0.45)",
                        borderwidth=1,
                        borderpad=2,
                    )
                )

            if show_sr_zones:
                for idx_s, sup in enumerate(fc.support_levels[:2], start=1):
                    is_str_s = bool(getattr(sup, "is_strong", False))
                    s_score_v = float(getattr(sup, "strength_score", 45.0))
                    s_tier = f"{idx_s}. 🛡️ Güçlü Destek" if is_str_s else f"{idx_s}. 🟢 Sıradan Destek"
                    s_reasons = getattr(sup, "confluence_tags", []) or []
                    s_reason_short = f" • {s_reasons[0]}" if s_reasons else ""
                    s_stats_tr = getattr(sup, "stats_summary_tr", "")
                    s_stats_short = f" • {s_stats_tr.split('•')[0].strip()}" if s_stats_tr else ""
                    shapes_for_tf.append(
                        dict(
                            type="rect",
                            xref="paper",
                            yref="y",
                            x0=0,
                            x1=0.84,
                            y0=sup.band_low,
                            y1=sup.band_high,
                            fillcolor="rgba(0, 230, 118, 0.105)" if is_str_s else "rgba(0, 230, 118, 0.048)",
                            line=dict(
                                color="rgba(0, 230, 118, 0.45)" if is_str_s else "rgba(0, 230, 118, 0.25)",
                                width=1.0,
                                dash="solid" if is_str_s else "dot",
                            ),
                        )
                    )
                    # Crisp center line anchored directly to the candle pivot price
                    shapes_for_tf.append(
                        dict(
                            type="line",
                            xref="paper",
                            yref="y",
                            x0=0,
                            x1=0.84,
                            y0=sup.price,
                            y1=sup.price,
                            line=dict(
                                color="rgba(0, 230, 118, 0.85)" if is_str_s else "rgba(0, 230, 118, 0.55)",
                                width=1.6 if is_str_s else 1.1,
                                dash="solid" if is_str_s else "dash",
                            ),
                        )
                    )
                    ann_for_tf.append(
                        dict(
                            xref="paper",
                            yref="y",
                            x=0.008,
                            y=sup.price,
                            xanchor="left",
                            yanchor="middle",
                            text=f"<b>{s_tier} ({s_score_v:.0f}/100{s_reason_short}{s_stats_short}): {format(sup.price, p_fmt)}</b>",
                            showarrow=False,
                            font=dict(size=10.5, color="#00E676"),
                            bgcolor="rgba(11, 15, 25, 0.92)",
                            bordercolor="rgba(0, 230, 118, 0.72)" if is_str_s else "rgba(0, 230, 118, 0.42)",
                            borderwidth=1,
                            borderpad=2,
                        )
                    )

                for idx_r, res in enumerate(fc.resistance_levels[:2], start=1):
                    is_str_r = bool(getattr(res, "is_strong", False))
                    r_score_v = float(getattr(res, "strength_score", 45.0))
                    r_tier = f"{idx_r}. 🧱 Güçlü Direnç" if is_str_r else f"{idx_r}. 🔴 Sıradan Direnç"
                    r_reasons = getattr(res, "confluence_tags", []) or []
                    r_reason_short = f" • {r_reasons[0]}" if r_reasons else ""
                    r_stats_tr = getattr(res, "stats_summary_tr", "")
                    r_stats_short = f" • {r_stats_tr.split('•')[0].strip()}" if r_stats_tr else ""
                    shapes_for_tf.append(
                        dict(
                            type="rect",
                            xref="paper",
                            yref="y",
                            x0=0,
                            x1=0.84,
                            y0=res.band_low,
                            y1=res.band_high,
                            fillcolor="rgba(255, 82, 82, 0.105)" if is_str_r else "rgba(255, 82, 82, 0.048)",
                            line=dict(
                                color="rgba(255, 82, 82, 0.45)" if is_str_r else "rgba(255, 82, 82, 0.25)",
                                width=1.0,
                                dash="solid" if is_str_r else "dot",
                            ),
                        )
                    )
                    # Crisp center line anchored directly to the candle pivot price
                    shapes_for_tf.append(
                        dict(
                            type="line",
                            xref="paper",
                            yref="y",
                            x0=0,
                            x1=0.84,
                            y0=res.price,
                            y1=res.price,
                            line=dict(
                                color="rgba(255, 82, 82, 0.85)" if is_str_r else "rgba(255, 82, 82, 0.55)",
                                width=1.6 if is_str_r else 1.1,
                                dash="solid" if is_str_r else "dash",
                            ),
                        )
                    )
                    ann_for_tf.append(
                        dict(
                            xref="paper",
                            yref="y",
                            x=0.008,
                            y=res.price,
                            xanchor="left",
                            yanchor="middle",
                            text=f"<b>{r_tier} ({r_score_v:.0f}/100{r_reason_short}{r_stats_short}): {format(res.price, p_fmt)}</b>",
                            showarrow=False,
                            font=dict(size=10.5, color="#FF5252"),
                            bgcolor="rgba(11, 15, 25, 0.92)",
                            bordercolor="rgba(255, 82, 82, 0.72)" if is_str_r else "rgba(255, 82, 82, 0.42)",
                            borderwidth=1,
                            borderpad=2,
                        )
                    )

                # Dynamic Trendlines (Ascending Support & Descending Resistance) + Retest/SFP Marker
                tl_obj = getattr(fc, "trendlines", None)
                if tl_obj is not None and len(df) >= 5:
                    if getattr(tl_obj, "has_support_line", False) and tl_obj.sup_x0 is not None and tl_obj.sup_x1 is not None and tl_obj.sup_y1 > 0:
                        shapes_for_tf.append(
                            dict(
                                type="line",
                                xref="x",
                                yref="y",
                                x0=tl_obj.sup_x0,
                                y0=tl_obj.sup_y0,
                                x1=tl_obj.sup_x1,
                                y1=tl_obj.sup_y1,
                                line=dict(color="rgba(16, 185, 129, 0.85)", width=1.8, dash="dashdot"),
                            )
                        )
                    if getattr(tl_obj, "has_resistance_line", False) and tl_obj.res_x0 is not None and tl_obj.res_x1 is not None and tl_obj.res_y1 > 0:
                        shapes_for_tf.append(
                            dict(
                                type="line",
                                xref="x",
                                yref="y",
                                x0=tl_obj.res_x0,
                                y0=tl_obj.res_y0,
                                x1=tl_obj.res_x1,
                                y1=tl_obj.res_y1,
                                line=dict(color="rgba(244, 63, 94, 0.85)", width=1.8, dash="dashdot"),
                            )
                        )
                sr_act_t = getattr(fc, "sr_action_type", "NONE")
                sr_act_p = float(getattr(fc, "sr_action_price", 0.0) or 0.0)
                if sr_act_t != "NONE" and sr_act_p > 0:
                    is_bull_act = "BULL" in sr_act_t
                    if sr_act_t == "BULL_SR_BREAKOUT":
                        act_lbl = "🚀 DİRENÇ KIRILIMI GELDİ! (Yeni Destek)"
                        act_col = "#00E676"
                    elif sr_act_t == "BEAR_SR_BREAKDOWN":
                        act_lbl = "🩸 DESTEK KIRILIMI GELDİ! (Yeni Direnç)"
                        act_col = "#FF5252"
                    elif sr_act_t == "BULL_SFP":
                        act_lbl = "🪤 Sahte Destek Kırılımı / Dip SFP (Tuzak)"
                        act_col = "#38BDF8"
                    elif sr_act_t == "BEAR_SFP":
                        act_lbl = "🪤 Sahte Direnç Kırılımı / Tepe SFP (Tuzak)"
                        act_col = "#F59E0B"
                    elif sr_act_t == "BULL_RETEST":
                        act_lbl = "🔄 Yukarı Kırılım / Destek Retest Onayı"
                        act_col = "#34D399"
                    else:
                        act_lbl = "🔄 Direnç Reddi / Aşağı Retest Onayı"
                        act_col = "#FB7185"
                    ann_for_tf.append(
                        dict(
                            xref="paper",
                            yref="y",
                            x=0.48,
                            y=sr_act_p,
                            xanchor="center",
                            yanchor="bottom" if is_bull_act else "top",
                            text=f"<b>{act_lbl}: {format(sr_act_p, p_fmt)}</b>",
                            showarrow=False,
                            font=dict(size=11, color=act_col),
                            bgcolor="rgba(11, 15, 25, 0.95)",
                            bordercolor=act_col,
                            borderwidth=1.4,
                            borderpad=3,
                        )
                    )
                elif tl_obj is not None and getattr(tl_obj, "breakout_status", "NONE") in ("BULL_BREAKOUT", "BEAR_BREAKDOWN"):
                    is_bull_tl = tl_obj.breakout_status == "BULL_BREAKOUT"
                    tl_p = tl_obj.res_current_price if is_bull_tl else tl_obj.sup_current_price
                    tl_lbl = "📐 🟢 DÜŞEN TREND KIRILIMI GELDİ!" if is_bull_tl else "📐 🔴 YÜKSELEN TREND KIRILIMI GELDİ!"
                    tl_col = "#00E676" if is_bull_tl else "#FF5252"
                    if tl_p > 0:
                        ann_for_tf.append(
                            dict(
                                xref="paper",
                                yref="y",
                                x=0.48,
                                y=tl_p,
                                xanchor="center",
                                yanchor="bottom" if is_bull_tl else "top",
                                text=f"<b>{tl_lbl}: {format(tl_p, p_fmt)}</b>",
                                showarrow=False,
                                font=dict(size=11, color=tl_col),
                                bgcolor="rgba(11, 15, 25, 0.95)",
                                bordercolor=tl_col,
                                borderwidth=1.4,
                                borderpad=3,
                            )
                        )

            # Smart Money Concepts (SMC): Unfilled FVG & Order Block Boxes
            if show_smc and fc.smc and len(df) >= 3:
                last_ts = df["timestamp"].iloc[-1]
                for fvg in fc.smc.fvgs:
                    is_bull_fvg = fvg.fvg_type == "BULLISH_FVG"
                    fvg_fill = "rgba(56, 189, 248, 0.09)" if is_bull_fvg else "rgba(244, 63, 94, 0.09)"
                    fvg_line = "rgba(56, 189, 248, 0.40)" if is_bull_fvg else "rgba(244, 63, 94, 0.40)"
                    shapes_for_tf.append(
                        dict(
                            type="rect",
                            xref="x",
                            yref="y",
                            x0=fvg.created_at,
                            x1=last_ts,
                            y0=fvg.bottom,
                            y1=fvg.top,
                            fillcolor=fvg_fill,
                            line=dict(color=fvg_line, width=1.0, dash="dot"),
                        )
                    )
                for ob in fc.smc.order_blocks:
                    is_bull_ob = ob.ob_type == "BULLISH_OB"
                    ob_fill = "rgba(16, 185, 129, 0.11)" if is_bull_ob else "rgba(239, 68, 68, 0.11)"
                    ob_line = "rgba(16, 185, 129, 0.55)" if is_bull_ob else "rgba(239, 68, 68, 0.55)"
                    shapes_for_tf.append(
                        dict(
                            type="rect",
                            xref="x",
                            yref="y",
                            x0=ob.created_at,
                            x1=last_ts,
                            y0=ob.bottom,
                            y1=ob.top,
                            fillcolor=ob_fill,
                            line=dict(color=ob_line, width=1.2),
                        )
                    )

            # Leveraged Liquidation Magnet Lines (25x-50x) — Independent toggle
            if show_liq_pools and fc.smc and len(df) >= 3:
                for pool in fc.smc.liquidation_pools:
                    is_short_liq = pool.pool_type == "SHORT_LIQ"
                    liq_col = "#A855F7" if is_short_liq else "#F97316"
                    short_lbl = "🧲 Short Likidasyon" if is_short_liq else "🧲 Long Likidasyon"
                    shapes_for_tf.append(
                        dict(
                            type="line",
                            xref="paper",
                            yref="y",
                            x0=0.55,
                            x1=0.84,
                            y0=pool.price,
                            y1=pool.price,
                            line=dict(color=liq_col, width=1.3, dash="dashdot"),
                        )
                    )
                    ann_for_tf.append(
                        dict(
                            xref="paper",
                            yref="y",
                            x=0.55,
                            y=pool.price,
                            xanchor="left",
                            yanchor="bottom" if is_short_liq else "top",
                            text=f"<b>{short_lbl}: {format(pool.price, p_fmt)}</b>",
                            showarrow=False,
                            font=dict(size=9.5, color=liq_col),
                            bgcolor="rgba(11, 15, 25, 0.85)",
                            bordercolor=liq_col,
                            borderwidth=1,
                            borderpad=2,
                        )
                    )

            # Future Risk/Reward Target & Invalidation Shaded Projection Box (Direction-Aware)
            if show_projection_box and len(df) >= 3:
                last_ts = df["timestamp"].iloc[-1]
                prev_ts = df["timestamp"].iloc[-2]
                bar_delta = last_ts - prev_ts
                future_ts = last_ts + (bar_delta * 7)
                curr_p = float(df["close"].iloc[-1])
                tp2_val = fc.tp2_price if fc.tp2_price > 0 else fc.bullish_target_price
                stp_val = fc.stop_price if fc.stop_price > 0 else fc.bearish_invalidation_price

                # Green Target Zone Box (above curr_p in Bullish/Neutral, below curr_p in Bearish)
                shapes_for_tf.append(
                    dict(
                        type="rect",
                        xref="x",
                        yref="y",
                        x0=last_ts,
                        x1=future_ts,
                        y0=min(curr_p, tp2_val),
                        y1=max(curr_p, tp2_val),
                        fillcolor="rgba(0, 230, 118, 0.09)",
                        line=dict(color="rgba(0, 230, 118, 0.55)", width=1.1, dash="dot"),
                    )
                )
                # Red Risk/Invalidation Zone Box
                shapes_for_tf.append(
                    dict(
                        type="rect",
                        xref="x",
                        yref="y",
                        x0=last_ts,
                        x1=future_ts,
                        y0=min(curr_p, stp_val),
                        y1=max(curr_p, stp_val),
                        fillcolor="rgba(255, 82, 82, 0.09)",
                        line=dict(color="rgba(255, 82, 82, 0.55)", width=1.1, dash="dot"),
                    )
                )

            # Compact Top-Left Quantitative Status Pill
            badge_color = "#00E676" if fc.score >= 15 else ("#FF5252" if fc.score <= -15 else "#FACC15")
            bt = fc.backtest_stats
            bt_badge = (
                f"Geçmiş Sinyal Başarısı: %{bt.win_rate_pct:.0f} (Kazanç/Kayıp Oranı: {bt.profit_factor:.2f})"
                if bt.total_signals > 0
                else "Geçmiş Sinyal Testi: Veri Yok"
            )

            ann_for_tf.append(
                dict(
                    xref="paper",
                    yref="paper",
                    x=0.008,
                    y=0.985,
                    xanchor="left",
                    yanchor="top",
                    text=(
                        f"<b>[{tf}]</b> <span style='color:{badge_color};'><b>{fc.verdict_tr} (Puan: {fc.score:+.0f}/100 | Gösterge Uyumu: %{fc.confidence_pct:.0f})</b></span> "
                        f"| <b>🎯 {bt_badge}</b>"
                    ),
                    align="left",
                    showarrow=False,
                    font=dict(size=11, color="#F8FAFC"),
                    bgcolor="rgba(15, 23, 42, 0.88)",
                    bordercolor=badge_color,
                    borderwidth=1.2,
                    borderpad=4,
                )
            )

            tf_shapes[tf] = shapes_for_tf
            tf_annotations[tf] = ann_for_tf

        # ------------------------------------------------------------------
        # 11. INTERACTIVE TIMEFRAME BUTTONS (15M / 1H / 4H / 1D)
        # ------------------------------------------------------------------
        updatemenus = []
        if len(timeframes) > 1:
            buttons = []
            total_traces = len(fig.data)
            for tf in timeframes:
                vis_mask = [False] * total_traces
                for idx in tf_trace_indices[tf]:
                    t_name = fig.data[idx].name or ""
                    if "Diğer " in t_name:
                        vis_mask[idx] = "legendonly"
                    else:
                        vis_mask[idx] = True

                fc = tf_forecasts[tf]
                df_tf = tf_data[tf]
                last_close = float(df_tf["close"].iloc[-1])
                p_fmt = self._price_format(last_close)

                tf_tr_names = {
                    "15M": "15 Dakika (15M)",
                    "1H": "1 Saatlik (1H)",
                    "4H": "4 Saatlik (4H)",
                    "1D": "Günlük (1D)",
                }
                btn_label = tf_tr_names.get(tf, f"{tf} Grafiği")

                buttons.append(
                    dict(
                        label=f"⏱️ {btn_label}",
                        method="update",
                        args=[
                            {"visible": vis_mask},
                            {
                                "shapes": tf_shapes[tf],
                                "annotations": tf_annotations[tf],
                                "title.text": (
                                    f"<b>{e_cfg.symbol} Kurumsal Yön, Gerçek Taker Para Akışı & Senaryo Analizi [{tf}]</b> "
                                    f"<span style='font-size:13px;color:#94A3B8;'>"
                                    f"| Fiyat: <b>{format(last_close, p_fmt)} USDT</b> "
                                    f"| Görünüm: <b>{fc.verdict_tr}</b> "
                                    f"| Kaynak: <b>{exchange_source}</b></span>"
                                ),
                            },
                        ],
                    )
                )

            updatemenus = [
                dict(
                    type="buttons",
                    direction="right",
                    active=timeframes.index(default_tf),
                    x=0.99,
                    xanchor="right",
                    y=1.07,
                    yanchor="bottom",
                    bgcolor="#1E293B",
                    bordercolor="#38BDF8",
                    borderwidth=1.5,
                    font=dict(color="#F8FAFC", size=12),
                    buttons=buttons,
                )
            ]

        default_df = tf_data[default_tf]
        default_fc = tf_forecasts[default_tf]
        last_close = float(default_df["close"].iloc[-1])
        p_fmt = self._price_format(last_close)

        has_multi_tf = len(timeframes) > 1
        layout_title = (
            dict(
                text=(
                    f"<b>{e_cfg.symbol} Kurumsal Yön, Gerçek Taker Para Akışı & Senaryo Analizi [{default_tf}]</b> "
                    f"<span style='font-size:13px;color:#94A3B8;'>"
                    f"| Fiyat: <b>{format(last_close, p_fmt)} USDT</b> "
                    f"| Görünüm: <b>{default_fc.verdict_tr}</b> "
                    f"| Kaynak: <b>{exchange_source}</b></span>"
                ),
                x=0.01,
                xanchor="left",
                y=0.985,
                yanchor="top",
                font=dict(size=15),
            )
            if has_multi_tf
            else None
        )

        fig.update_layout(
            template=c_cfg.theme,
            height=c_cfg.height,
            shapes=tf_shapes[default_tf],
            annotations=tf_annotations[default_tf],
            updatemenus=updatemenus,
            title=layout_title,
            hovermode="closest",
            xaxis_rangeslider_visible=False,
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.055,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(15, 23, 42, 0.90)",
                bordercolor="rgba(148, 163, 184, 0.25)",
                borderwidth=1,
                font=dict(size=11.5),
            ),
            margin=dict(l=55, r=45, t=105 if has_multi_tf else 48, b=110),
            paper_bgcolor="#0B0F19",
            plot_bgcolor="#111827",
        )

        # Add right-side breathing margin on X-axis so target/stop labels never sit on top of candles
        if (show_projection_box or show_prob_cone) and len(default_df) >= 3:
            first_ts = default_df["timestamp"].iloc[0]
            last_ts = default_df["timestamp"].iloc[-1]
            bar_delta = last_ts - default_df["timestamp"].iloc[-2]
            x_end = last_ts + (bar_delta * 24)
            fig.update_xaxes(range=[first_ts, x_end])

        fig.update_yaxes(title_text="Fiyat (USDT)", gridcolor="rgba(255,255,255,0.06)", row=1, col=1)
        fig.update_yaxes(title_text="Para Akışı (CMF)", gridcolor="rgba(255,255,255,0.06)", row=2, col=1)
        fig.update_yaxes(
            title_text="RSI / MFI",
            range=[0, 100],
            gridcolor="rgba(255,255,255,0.06)",
            row=3,
            col=1,
        )
        fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)", row=3, col=1)

        return fig

    def _build_investor_dashboard_html(
        self,
        symbol: str,
        exchange_source: str,
        tf_data: Dict[str, pd.DataFrame],
        tf_forecasts: Dict[str, MarketForecast],
        order_flow: Optional[OrderFlowIntel] = None,
    ) -> str:
        order_flow_html = ""
        if order_flow is not None:
            last_close = float(next(iter(tf_data.values()))["close"].iloc[-1])
            p_fmt = self._price_format(last_close)
            imb_color = "#00E676" if order_flow.imbalance_pct >= 52 else ("#FF5252" if order_flow.imbalance_pct <= 48 else "#FACC15")
            oi_str = f"${order_flow.open_interest_usd:,.0f}" if order_flow.open_interest_usd else "Veri Yok"
            vol24_str = f"${order_flow.quote_volume_24h_usd:,.0f}" if order_flow.quote_volume_24h_usd else "Veri Yok"

            order_flow_html = f"""
            <div style="background:#111827; border:1px solid #1E293B; border-left:4px solid {imb_color}; border-radius:10px; padding:14px 18px; margin-bottom:16px; display:flex; flex-wrap:wrap; gap:20px; justify-content:space-between; align-items:center;">
                <div>
                    <div style="font-size:12px; color:#94A3B8;">📊 DERİN EMİR DEFTERİ LİKİDİTESİ (±%2.5 FİLTRELİ)</div>
                    <div style="font-size:15px; font-weight:700; color:{imb_color}; margin-top:2px;">{order_flow.orderbook_status_tr}</div>
                    <div style="font-size:12px; color:#CBD5E1; margin-top:2px;">
                        En Güçlü Alım Duvarı: <b style="color:#00E676;">{format(order_flow.strongest_bid_wall, p_fmt)} USDT</b> |
                        En Güçlü Satış Duvarı: <b style="color:#FF5252;">{format(order_flow.strongest_ask_wall, p_fmt)} USDT</b>
                    </div>
                </div>
                <div>
                    <div style="font-size:12px; color:#94A3B8;">💰 24 SAATLİK SPOT İŞLEM HACMİ & DEĞİŞİM</div>
                    <div style="font-size:15px; font-weight:700; color:#F8FAFC; margin-top:2px;">
                        {vol24_str} <span style="color:{'#00E676' if order_flow.price_change_24h_pct >= 0 else '#FF5252'};">({order_flow.price_change_24h_pct:+.2f}%)</span>
                    </div>
                    <div style="font-size:12px; color:#CBD5E1; margin-top:2px;">
                        24s En Yüksek: <b>{format(order_flow.high_24h, p_fmt)}</b> | 24s En Düşük: <b>{format(order_flow.low_24h, p_fmt)}</b>
                    </div>
                </div>
                <div>
                    <div style="font-size:12px; color:#94A3B8;">⚡ VADELİ İŞLEMLER (FONLAMA, AÇIK POZİSYON DEĞİŞİMİ & LONG/SHORT)</div>
                    <div style="font-size:14px; font-weight:700; color:#38BDF8; margin-top:2px;">{order_flow.futures_sentiment_tr}</div>
                    <div style="font-size:12px; color:#CBD5E1; margin-top:2px;">
                        Toplam Açık Pozisyon (OI): <b>{oi_str}</b>
                    </div>
                </div>
            </div>
            """

        tf_cards_html = ""
        for tf, fc in tf_forecasts.items():
            df = tf_data[tf]
            close = float(df["close"].iloc[-1])
            p_fmt = self._price_format(close)

            if fc.score >= 15:
                border_col = "#00E676"
                bg_badge = "rgba(0, 230, 118, 0.14)"
                icon = "📈 POZİTİF / BOĞA"
            elif fc.score <= -15:
                border_col = "#FF5252"
                bg_badge = "rgba(255, 82, 82, 0.14)"
                icon = "📉 NEGATİF / AYI"
            else:
                border_col = "#FACC15"
                bg_badge = "rgba(250, 204, 21, 0.14)"
                icon = "⚖️ YATAY / DENGE"

            sup_str = (
                " / ".join([f"{format(s.price, p_fmt)} USDT" for s in fc.support_levels])
                if fc.support_levels
                else "Belirgin değil"
            )
            res_str = (
                " / ".join([f"{format(r.price, p_fmt)} USDT" for r in fc.resistance_levels])
                if fc.resistance_levels
                else "Belirgin değil"
            )

            tf_titles = {
                "15M": "15 Dakikalık (Kısa Vade / Scalping)",
                "1H": "1 Saatlik (Gün İçi / Kısa Vade)",
                "4H": "4 Saatlik (Orta Vade / Swing)",
                "1D": "Günlük (Ana Trend / Makro)",
            }
            tf_title = tf_titles.get(tf, f"{tf} Periyodu")
            bt = fc.backtest_stats
            smc = fc.smc
            rp = fc.risk_plan

            fvg_str = (
                " / ".join([f"{g.label_tr}: {format(g.bottom, p_fmt)}-{format(g.top, p_fmt)}" for g in smc.fvgs[:2]])
                if smc and smc.fvgs
                else "Açık FVG boşluğu yok"
            )
            ob_str = (
                " / ".join([f"{o.label_tr}: {format(o.bottom, p_fmt)}-{format(o.top, p_fmt)}" for o in smc.order_blocks[:2]])
                if smc and smc.order_blocks
                else "Yakın Order Block yok"
            )
            liq_str = (
                " | ".join([f"{p.leverage_tag}: {format(p.price, p_fmt)} USDT" for p in smc.liquidation_pools])
                if smc and smc.liquidation_pools
                else "Hesaplanmadı"
            )
            risk_html = ""
            if rp is not None:
                risk_html = f"""
                    <div style="margin-top:6px; padding:6px 8px; background:rgba(168, 85, 247, 0.08); border-left:3px solid #A855F7; border-radius:4px; color:#E9D5FF; font-size:11.8px;">
                        🧮 <b>Kasa & Risk Yönetimi Planı (YTD Değildir):</b> {rp.summary_tr}
                    </div>
                """

            tf_cards_html += f"""
            <div style="flex:1; min-width:315px; background:#111827; border:1px solid #1F2937; border-top:4px solid {border_col}; border-radius:10px; padding:16px; box-shadow:0 4px 12px rgba(0,0,0,0.35);">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="font-size:15px; font-weight:700; color:#F8FAFC;">⏱️ {tf_title}</span>
                    <span style="background:{bg_badge}; color:{border_col}; font-weight:700; font-size:12px; padding:4px 10px; border-radius:20px; border:1px solid {border_col};">
                        {icon} ({fc.score:+.0f}/100 | Uyum: %{fc.confidence_pct:.0f})
                    </span>
                </div>
                <div style="font-size:13px; color:#E2E8F0; font-weight:700; margin-bottom:8px;">
                    {fc.verdict_tr} <br><span style="font-weight:400; font-size:12px; color:#94A3B8;">{fc.regime_tr}</span>
                </div>
                <div style="font-size:12.5px; color:#CBD5E1; line-height:1.62;">
                    <div>🔹 <b>Trend & SuperTrend:</b> {fc.trend_name_tr} ({fc.supertrend_status_tr})</div>
                    <div>🔹 <b>Gerçek Para Akışı:</b> {fc.money_flow_status_tr}</div>
                    <div>🔹 <b>Momentum & Uyumsuzluk:</b> {fc.momentum_tr} | {fc.divergence_status_tr}</div>
                    <div>🔹 <b>Hacim POC & Fib 0.618:</b> <span style="color:#FACC15;">POC: {format(fc.poc_price, p_fmt)} USDT</span> | Fib 0.618: {format(fc.fib_618_price, p_fmt)} USDT</div>
                    <div>🔹 <b>Smart Money (SMC) Yapı & Tuzak:</b> {smc.structure_summary_tr} | {smc.liquidity_summary_tr}</div>
                    <div>🔹 <b>Kurumsal FVG & Order Block:</b> {fvg_str} | {ob_str}</div>
                    <div>🔹 <b>Kaldıraçlı Likidasyon Mıknatısları:</b> <span style="color:#C084FC;">{liq_str}</span></div>
                    <div>🔹 <b>BTC Göreceli Güç (RS) & Makro:</b> {smc.relative_strength.status_tr} | {fc.macro_context_tr}</div>
                    <div style="margin-top:6px; padding-top:6px; border-top:1px dashed #334155;">
                        🟢 <b>Destek Bölgeleri (Talep):</b> <span style="color:#00E676; font-weight:600;">{sup_str}</span>
                    </div>
                    <div>
                        🔴 <b>Direnç Bölgeleri (Arz):</b> <span style="color:#FF5252; font-weight:600;">{res_str}</span>
                    </div>
                    <div style="margin-top:6px; padding:6px 8px; background:rgba(56, 189, 248, 0.08); border-radius:4px; color:#38BDF8; font-size:12px;">
                        🎯 <b>Gerçekçi Sinyal Doğrulaması (Backtest):</b> {bt.summary_tr}
                    </div>
                    {risk_html}
                    <div style="margin-top:8px; padding:8px; background:#0B0F19; border-left:3px solid #00E676; border-radius:4px; color:#CBD5E1; font-size:12px;">
                        📈 <b>Boğa (Yükseliş) Senaryosu:</b> {fc.bullish_scenario_tr}
                    </div>
                    <div style="margin-top:6px; padding:8px; background:#0B0F19; border-left:3px solid #FF5252; border-radius:4px; color:#CBD5E1; font-size:12px;">
                        📉 <b>Ayı (Risk / İptal) Senaryosu:</b> {fc.bearish_scenario_tr}
                    </div>
                </div>
            </div>
            """

        pattern_rows_html = ""
        for eng_name, info in PATTERN_INFO_TR.items():
            dir_color = (
                "#00E676"
                if "YUKARI" in info["direction"]
                else ("#FF5252" if "AŞAĞI" in info["direction"] else "#FACC15")
            )
            pattern_rows_html += f"""
            <div style="background:#111827; border:1px solid #1E293B; border-radius:8px; padding:10px 12px; flex:1; min-width:260px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                    <span style="font-weight:700; color:#F8FAFC; font-size:13px;">{info['tr_name']} <span style="color:#64748B; font-weight:400;">({eng_name})</span></span>
                    <span style="color:{dir_color}; font-size:11px; font-weight:700;">{info['direction']}</span>
                </div>
                <div style="font-size:12px; color:#94A3B8; line-height:1.45;">{info['meaning']}</div>
            </div>
            """

        return f"""
        <div style="font-family:'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background:#0B0F19; color:#F8FAFC; padding:20px 28px 10px 28px;">
            <div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; border-bottom:1px solid #1E293B; padding-bottom:12px; margin-bottom:14px;">
                <div>
                    <h1 style="margin:0; font-size:21px; color:#F8FAFC;">
                        📊 {symbol} — Kurumsal Yön, Gerçek Taker Para Akışı, Hacim POC & Backtest Doğrulamalı Senaryo Raporu (v2.0)
                    </h1>
                    <p style="margin:4px 0 0 0; font-size:12.5px; color:#94A3B8;">
                        Veri Kaynağı: <b>{exchange_source}</b> | Kapanmış Mum Garantisi Aktif | ⚠️ <i>Bu rapor istatistiksel ve matematiksel bir karar destek aracıdır; yatırım tavsiyesi (YTD) değildir.</i>
                    </p>
                </div>
            </div>

            {order_flow_html}

            <div style="display:flex; flex-wrap:wrap; gap:16px; margin-bottom:16px;">
                {tf_cards_html}
            </div>

            <details style="background:#0F172A; border:1px solid #1E293B; border-radius:10px; padding:12px 16px; margin-bottom:8px;">
                <summary style="cursor:pointer; font-weight:700; font-size:14px; color:#38BDF8; outline:none;">
                    📘 Mum Formasyonları (Sabah/Akşam Yıldızı, Kayan Yıldız, Çekiç, Boğa/Ayı Yutan), Hacim POC ve Para Akışı Rehberi (Tıklayın)
                </summary>
                <div style="display:flex; flex-wrap:wrap; gap:10px; margin-top:12px;">
                    {pattern_rows_html}
                </div>
            </details>
        </div>
        """

    def save_html(
        self,
        fig: go.Figure,
        output_path: Optional[str] = None,
        tf_data: Optional[Dict[str, pd.DataFrame]] = None,
        tf_forecasts: Optional[Dict[str, MarketForecast]] = None,
        order_flow: Optional[OrderFlowIntel] = None,
        exchange_source: str = "BINANCE",
    ) -> Path:
        target = Path(output_path or self.config.chart.output_html).resolve()

        plot_div = fig.to_html(
            include_plotlyjs="cdn",
            full_html=False,
            config={
                "scrollZoom": True,
                "displaylogo": False,
                "toImageButtonOptions": {
                    "format": "png",
                    "filename": f"{self.config.exchange.symbol.replace('/', '_').lower()}_analiz",
                    "height": 1080,
                    "width": 1920,
                    "scale": 2,
                },
            },
        )

        dashboard_header = ""
        if tf_data and tf_forecasts:
            dashboard_header = self._build_investor_dashboard_html(
                symbol=self.config.exchange.symbol,
                exchange_source=exchange_source,
                tf_data=tf_data,
                tf_forecasts=tf_forecasts,
                order_flow=order_flow,
            )

        full_html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{self.config.exchange.symbol} — Kurumsal Yön, Para Akışı & Backtest Raporu</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            background-color: #0B0F19;
            color: #F8FAFC;
        }}
    </style>
</head>
<body>
    {dashboard_header}
    {plot_div}
</body>
</html>
"""
        target.write_text(full_html, encoding="utf-8")
        return target
