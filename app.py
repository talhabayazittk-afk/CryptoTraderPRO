"""
Interactive Streamlit Web Dashboard (v2.0):
Kurumsal Kripto Kantitatif Yön, Gerçek Taker Para Akışı (CVD), Hacim Profili (POC),
Derin Emir Defteri, Backtest Doğrulama & Çoklu Zaman Dilimi (15M, 1H, 4H, 1D) Terminali.

Çalıştırmak için:
    py -3.13 -m streamlit run app.py
"""
import importlib
import inspect
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import src
import src.config
import src.data_fetcher
import src.indicators
import src.patterns
import src.smart_money
import src.signals
import src.visualizer
import src.telegram_notifier

# Hot-reload submodules automatically if an older module is still cached in a running Streamlit process
if (
    "symbol" not in inspect.signature(src.signals.SignalEngine.generate_forecast).parameters
    or "show_kalman_avwap" not in inspect.signature(src.visualizer.InteractiveChartVisualizer.create_multi_timeframe_figure).parameters
    or not getattr(src.visualizer, "_V6_0_READY", False)
    or not hasattr(src.telegram_notifier, "build_analysis_inline_keyboard")
    or not hasattr(src.telegram_notifier, "build_futures_radar_inline_keyboard")
    or not hasattr(src.signals, "FuturesSetupReport")
):
    for _mod in (
        src.config,
        src.data_fetcher,
        src.indicators,
        src.patterns,
        src.smart_money,
        src.signals,
        src.visualizer,
        src.telegram_notifier,
        src,
    ):
        importlib.reload(_mod)
    st.cache_data.clear()

from src.config import AnalysisConfig, ChartConfig, ExchangeConfig, IndicatorConfig, PatternConfig
from src.data_fetcher import CryptoDataFetcher, OrderFlowIntel
from src.indicators import TechnicalIndicators
from src.patterns import CandlestickPatternDetector, PATTERN_INFO_TR
from src.signals import MarketForecast, SignalEngine
from src.telegram_notifier import (
    build_analysis_inline_keyboard,
    build_breakout_radar_inline_keyboard,
    build_coin_list_inline_keyboard,
    build_futures_radar_inline_keyboard,
    build_futures_setup_inline_keyboard,
    build_main_reply_keyboard,
    build_screener_inline_keyboard,
    format_breakout_radar_scan_telegram_html,
    format_forecast_telegram_html,
    format_futures_radar_scan_telegram_html,
    format_futures_setup_telegram_html,
    format_screener_telegram_html,
    generate_telegram_chart_png,
    is_bot_running,
    load_telegram_config,
    load_telegram_state,
    save_telegram_config,
    save_telegram_state,
    send_telegram_message,
    send_telegram_photo,
    start_bot_background,
    stop_bot_background,
)
from src.visualizer import InteractiveChartVisualizer

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"
DEFAULT_WATCHLIST = ["ETH/USDT", "ONDO/USDT", "BTC/USDT", "ENA/USDT"]


def load_watchlist() -> List[str]:
    if WATCHLIST_FILE.exists():
        try:
            data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) > 0:
                return [str(x) for x in data]
        except Exception:
            pass
    return list(DEFAULT_WATCHLIST)


def save_watchlist(items: List[str]) -> None:
    try:
        WATCHLIST_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# PAGE CONFIG & CUSTOM DARK INSTITUTIONAL STYLING
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Kurumsal Kripto Kantitatif Yön & Para Akışı Terminali (v2.0)",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .stApp {
            background-color: #0B0F19;
            color: #F8FAFC;
        }
        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2rem;
            max-width: 97%;
        }
        .kpi-card {
            background: #111827;
            border: 1px solid #1E293B;
            border-radius: 10px;
            padding: 14px 16px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.35);
            height: 100%;
        }
        .kpi-title {
            font-size: 12px;
            color: #94A3B8;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
        }
        .kpi-value {
            font-size: 20px;
            font-weight: 700;
            color: #F8FAFC;
            margin-top: 4px;
        }
        .kpi-sub {
            font-size: 12px;
            color: #CBD5E1;
            margin-top: 4px;
        }
        .scenario-box {
            background: #111827;
            border-radius: 8px;
            padding: 13px 16px;
            border: 1px solid #1E293B;
            margin-bottom: 10px;
        }
        .disclaimer-banner {
            background: rgba(30, 41, 59, 0.75);
            border: 1px solid #334155;
            border-left: 4px solid #38BDF8;
            border-radius: 8px;
            padding: 10px 14px;
            font-size: 12.5px;
            color: #CBD5E1;
            margin-bottom: 16px;
        }
        .beginner-box {
            background: linear-gradient(90deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 41, 59, 0.90) 100%);
            border: 1px solid #38BDF8;
            border-left: 5px solid #38BDF8;
            border-radius: 10px;
            padding: 14px 18px;
            margin-bottom: 16px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
        }
        .help-tip {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 17px;
            height: 17px;
            border-radius: 50%;
            background: rgba(56, 189, 248, 0.18);
            color: #38BDF8;
            border: 1px solid rgba(56, 189, 248, 0.55);
            font-size: 11px;
            font-weight: 700;
            cursor: pointer;
            position: relative;
            margin-left: 4px;
            vertical-align: middle;
        }
        .help-tip:hover {
            background: #38BDF8;
            color: #0B0F19;
        }
        .help-tip::after {
            content: attr(data-tip);
            position: absolute;
            bottom: 135%;
            left: 50%;
            transform: translateX(-50%);
            width: 280px;
            background: #0F172A;
            color: #F8FAFC;
            border: 1px solid #38BDF8;
            border-radius: 8px;
            padding: 9px 11px;
            font-size: 12px;
            font-weight: 400;
            line-height: 1.45;
            text-transform: none;
            letter-spacing: 0;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.65);
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.18s ease;
            z-index: 9999;
            pointer-events: none;
        }
        .help-tip:hover::after {
            opacity: 1;
            visibility: visible;
        }
        @media (max-width: 768px) {
            .block-container {
                padding-top: 0.7rem;
                padding-left: 0.5rem;
                padding-right: 0.5rem;
                max-width: 100%;
            }
            .kpi-value {
                font-size: 17px;
            }
            .kpi-card {
                padding: 10px 12px;
                margin-bottom: 8px;
            }
            .help-tip::after {
                width: 220px;
                left: auto;
                right: 0;
                transform: none;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def normalize_symbol(coin: str) -> str:
    cleaned = coin.strip().upper().replace("-", "/")
    if not cleaned:
        return ""
    if "/" not in cleaned:
        if cleaned.endswith("USDT") and len(cleaned) > 4:
            return f"{cleaned[:-4]}/USDT"
        return f"{cleaned}/USDT"
    return cleaned


def price_fmt(val: Optional[float]) -> str:
    if val is None or pd.isna(val):
        return "N/A"
    return f"{val:,.4f}" if abs(val) < 10.0 else f"{val:,.2f}"


@st.cache_data(ttl=90, show_spinner=False)
def load_coin_intelligence(
    symbol: str,
    exchange_id: str,
    timeframes: Tuple[str, ...],
    limit: int,
    btc_regime_scores: Optional[Dict[str, float]] = None,
    btc_tf_data: Optional[Dict[str, pd.DataFrame]] = None,
    sample_capital_usd: float = 1000.0,
    risk_pct: float = 1.0,
    _engine_version: str = "v9.4",
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, MarketForecast], OrderFlowIntel, str, Dict[str, float]]:
    """
    Parallel cached pipeline (v3.0):
    Fetches multi-timeframe OHLCV (with Real Taker Buy/Sell CVD) + Deep Spot OrderBook
    + Futures Funding/OI/Long-Short/Taker/Basis, and computes HTF + BTC Macro + SMC + Probability Cone
    + Position Sizing and path-dependent backtest win-rates.
    """
    base_cfg = AnalysisConfig(
        exchange=ExchangeConfig(primary_exchange=exchange_id, symbol=symbol, limit=limit),
        indicators=IndicatorConfig(),
        patterns=PatternConfig(),
        chart=ChartConfig(),
    )
    fetcher = CryptoDataFetcher(base_cfg.exchange)
    indicators = TechnicalIndicators(base_cfg.indicators)
    detector = CandlestickPatternDetector(base_cfg.patterns)
    signal_engine = SignalEngine(base_cfg.indicators)

    raw_tf_dict, source_used = fetcher.fetch_multi_timeframe_parallel(
        symbol=symbol,
        timeframes=list(timeframes),
        limit=limit,
        exchange_id=exchange_id,
        allow_synthetic_fallback=False,
    )
    order_flow = fetcher.fetch_order_flow_intel(symbol=symbol, exchange_id=exchange_id)

    tf_data: Dict[str, pd.DataFrame] = {}
    tf_forecasts: Dict[str, MarketForecast] = {}
    coin_scores: Dict[str, float] = {}

    ordered_tfs = [tf.upper() for tf in timeframes]
    for tf_key in ordered_tfs:
        df_ind = indicators.enrich(raw_tf_dict[tf_key])
        df_pat = detector.detect_all(df_ind)
        tf_data[tf_key] = signal_engine.evaluate(df_pat)

    # Evaluate from highest timeframe (1D -> 4H -> 1H -> 15M) so HTF feeds into LTF
    htf_prev_score: Optional[float] = None
    htf_sr_pool: List[Any] = []
    for tf_key in reversed(ordered_tfs):
        df_final = tf_data[tf_key]
        btc_score = (
            btc_regime_scores.get(tf_key)
            if (btc_regime_scores and not symbol.startswith("BTC/"))
            else None
        )
        btc_df = btc_tf_data.get(tf_key) if btc_tf_data else None
        forecast = signal_engine.generate_forecast(
            df_final,
            order_flow=order_flow,
            htf_score=htf_prev_score,
            btc_regime_score=btc_score,
            symbol=symbol,
            btc_df=btc_df,
            sample_capital_usd=sample_capital_usd,
            risk_pct=risk_pct,
            htf_sr_levels=list(htf_sr_pool) if htf_sr_pool else None,
        )
        tf_forecasts[tf_key] = forecast
        coin_scores[tf_key] = forecast.score
        htf_prev_score = forecast.score
        if tf_key in ("1D", "4H"):
            htf_sr_pool.extend(forecast.support_levels[:2])
            htf_sr_pool.extend(forecast.resistance_levels[:2])

    tf_forecasts = {k: tf_forecasts[k] for k in ordered_tfs}
    return tf_data, tf_forecasts, order_flow, source_used, coin_scores


# ---------------------------------------------------------------------------
# PERSISTENT SESSION STATE FOR DYNAMIC COIN WATCHLIST
# ---------------------------------------------------------------------------
if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

# ---------------------------------------------------------------------------
# SIDEBAR: WATCHLIST MANAGEMENT & CHART SETTINGS
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Terminal Kontrol Paneli (v2.0)")
    st.caption("İzleme listeniz `watchlist.json` dosyasına otomatik kaydedilir.")

    exchange_choice = st.selectbox(
        "Birincil Kripto Borsası",
        options=["binance", "gate", "kucoin", "kraken", "coinbase", "okx", "bybit"],
        index=0,
        help="Binance (Global Vision), Gate.io, KuCoin, Kraken ve Coinbase üzerinde canlı Spot/Vadeli veriler çekilir.",
    )

    candle_limit = st.slider(
        "Analiz Edilecek Mum Sayısı",
        min_value=100,
        max_value=400,
        value=200,
        step=50,
    )

    st.markdown("---")
    st.markdown("### 🪙 İzleme Listesi (Coin Ekle / Çıkar)")

    col_in, col_btn = st.columns([3, 2])
    with col_in:
        new_coin_input = st.text_input(
            "Yeni Coin Sembolü",
            placeholder="Örn: SOL, SUI, AVAX",
            label_visibility="collapsed",
        )
    with col_btn:
        if st.button("➕ Ekle", use_container_width=True):
            norm = normalize_symbol(new_coin_input)
            if norm and norm not in st.session_state.watchlist:
                st.session_state.watchlist.append(norm)
                save_watchlist(st.session_state.watchlist)
                st.rerun()

    popular_options = [
        "ETH/USDT", "ONDO/USDT", "BTC/USDT", "ENA/USDT",
        "SOL/USDT", "SUI/USDT", "AVAX/USDT", "XRP/USDT",
        "RENDER/USDT", "FET/USDT", "ARB/USDT", "LINK/USDT",
    ]
    all_available = list(dict.fromkeys(st.session_state.watchlist + popular_options))

    selected_watchlist = st.multiselect(
        "Aktif Analiz Edilen Coinler",
        options=all_available,
        default=st.session_state.watchlist,
        help="Çarpı (x) işaretine basarak istediğiniz coini listeden çıkarabilirsiniz.",
    )
    if selected_watchlist != st.session_state.watchlist:
        st.session_state.watchlist = selected_watchlist
        save_watchlist(st.session_state.watchlist)
        st.rerun()

    st.markdown("---")
    st.markdown("### 🧮 Kasa & Risk Yönetimi Hesaplayıcı")
    sample_capital_usd = st.number_input(
        "Örnek Kasa Büyüklüğü (USDT)",
        min_value=100.0,
        max_value=1000000.0,
        value=1000.0,
        step=250.0,
        help="Geçersizlik (Stop) seviyesine olan mesafeye göre matematiksel pozisyon büyüklüğünü hesaplar (YTD değildir).",
    )
    risk_pct_input = st.slider(
        "İşlem Başı Maksimum Risk (%)",
        min_value=0.25,
        max_value=5.0,
        value=1.0,
        step=0.25,
    )

    st.markdown("---")
    st.markdown("### 📲 Mobil & Telegram Bildirim Merkezi")
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as _s:
            _s.connect(("8.8.8.8", 80))
            _real_lan_ip = _s.getsockname()[0]
    except Exception:
        _real_lan_ip = "192.168.1.12"
    st.caption(f"📱 **Gerçek Wi-Fi Telefon Adresi:** `http://{_real_lan_ip}:8501`")

    tg_cfg = load_telegram_config()
    tg_state = load_telegram_state()
    tg_token_input = st.text_input(
        "Telegram Bot Token",
        value=tg_cfg.get("bot_token", ""),
        type="password",
        placeholder="Örn: 7123456:AAH...",
        help="Telegram'da @BotFather üzerinden ücretsiz oluşturduğunuz botun Token kodu.",
    )
    tg_chat_input = st.text_input(
        "Telegram Chat ID",
        value=tg_cfg.get("chat_id", ""),
        placeholder="Örn: 123456789",
        help="Mesajların geleceği kendi Telegram ID'niz veya grup ID'niz (@userinfobot ile öğrenebilirsiniz).",
    )

    send_chart_chk = st.checkbox(
        "🖼️ Analizle Birlikte Grafik Görseli de Gönder",
        value=bool(tg_state.get("send_chart_with_analysis", False)),
        help="İşaretlenirse Telegram'a analiz gönderirken Destek/Direnç/POC çizgili grafik görselini de otomatik gönderir.",
    )
    radar_chk = st.checkbox(
        "📡 7/24 Otomatik Kırılım & Balina Radarı",
        value=bool(tg_state.get("radar_enabled", True)),
        help="Bot çalışırken izleme listenizdeki güçlü kırılım, balina girişi ve sıkışmaları otomatik bildirir.",
    )
    if (
        send_chart_chk != bool(tg_state.get("send_chart_with_analysis", False))
        or radar_chk != bool(tg_state.get("radar_enabled", True))
        or exchange_choice != str(tg_state.get("primary_exchange", "binance"))
    ):
        tg_state["send_chart_with_analysis"] = send_chart_chk
        tg_state["radar_enabled"] = radar_chk
        tg_state["primary_exchange"] = exchange_choice
        save_telegram_state(tg_state)

    tg_b1, tg_b2 = st.columns(2)
    with tg_b1:
        if st.button("💾 Kaydet", use_container_width=True):
            if save_telegram_config(tg_token_input, tg_chat_input):
                st.success("✅ Kaydedildi!")
            else:
                st.error("Kaydedilemedi.")
    with tg_b2:
        if st.button("🧪 Menü Gönder", use_container_width=True):
            save_telegram_config(tg_token_input, tg_chat_input)
            ok_t, msg_t = send_telegram_message(
                tg_token_input,
                tg_chat_input,
                "✅ <b>Bağlantı &amp; Dokunmatik Menü Aktif!</b>\n"
                "Akıllı Kripto Karar-Destek &amp; Radar Terminali (v7.0) bağlı.\n\n"
                "👇 <i>Alt menüdeki dokunmatik butonlardan veya aşağıdaki coin listesinden tek dokunuşla analiz başlatabilirsiniz:</i>",
                reply_markup=build_main_reply_keyboard(),
            )
            send_telegram_message(
                tg_token_input,
                tg_chat_input,
                "🪙 <b>Hızlı Coin Seçim Menüsü (1H):</b>",
                reply_markup=build_coin_list_inline_keyboard(st.session_state.watchlist, "1H"),
            )
            if ok_t:
                st.success("✅ Dokunmatik menü gitti!")
            else:
                st.warning(msg_t)

    bot_alive, bot_pid = is_bot_running()
    if not bot_alive and tg_token_input.strip() and not st.session_state.get("bot_manually_stopped", False):
        save_telegram_config(tg_token_input, tg_chat_input)
        start_bot_background()
        bot_alive, bot_pid = is_bot_running()

    if bot_alive:
        st.caption(f"🟢 **Bot Durumu:** Arka Planda Çalışıyor (PID: `{bot_pid}`) | Aktif Alarm: `{len(tg_state.get('alarms', []))}`")
    else:
        st.caption("🔴 **Bot Durumu:** Şu An Kapalı (Dokunmatik butonların çalışması için başlatın)")

    bot_c1, bot_c2 = st.columns(2)
    with bot_c1:
        if st.button("▶️ Botu Başlat", use_container_width=True):
            if not tg_token_input.strip():
                st.warning("Önce Telegram Bot Token girip kaydedin.")
            else:
                st.session_state["bot_manually_stopped"] = False
                save_telegram_config(tg_token_input, tg_chat_input)
                ok_b, msg_b = start_bot_background()
                if ok_b:
                    st.success(msg_b)
                    st.rerun()
                else:
                    st.error(msg_b)
    with bot_c2:
        if st.button("⏹️ Botu Durdur", use_container_width=True):
            st.session_state["bot_manually_stopped"] = True
            ok_s, msg_s = stop_bot_background()
            st.info(msg_s)
            st.rerun()

    st.markdown("---")
    if st.button("🔄 Tüm Verileri Şimdi Yenile", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# HEADER & COMPACT NON-FINANCIAL ADVICE CAPTION
# ---------------------------------------------------------------------------
st.markdown("## 📊 Akıllı Kripto Trend, Destek/Direnç, Para Akışı & Likidasyon Terminali")
st.caption("⚖️ **Bilgilendirme:** Bu ekran borsa verilerini sadeleştirerek sunan bir karar-destek aracıdır; yatırım tavsiyesi (YTD) değildir.")

if not st.session_state.watchlist:
    st.warning("Lütfen sol menüden en az bir coin seçin veya ekleyin (Örn: ETH, ONDO, BTC, ENA).")
    st.stop()

TIMEFRAMES = ("15m", "1h", "4h", "1d")

# ---------------------------------------------------------------------------
# LOAD BTC MACRO REGIME FIRST, THEN ALL WATCHLIST COINS
# ---------------------------------------------------------------------------
all_coin_results: Dict[str, Tuple[Dict[str, pd.DataFrame], Dict[str, MarketForecast], OrderFlowIntel, str]] = {}
screener_rows = []

with st.spinner("Canlı borsa verileri, trend, para giriş/çıkışı ve likidasyon seviyeleri hesaplanıyor..."):
    btc_regime_scores: Optional[Dict[str, float]] = None
    btc_tf_data_ref: Optional[Dict[str, pd.DataFrame]] = None
    try:
        btc_tf_data, btc_tf_fc, btc_flow, btc_src, btc_regime_scores = load_coin_intelligence(
            symbol="BTC/USDT",
            exchange_id=exchange_choice,
            timeframes=TIMEFRAMES,
            limit=candle_limit,
            btc_regime_scores=None,
            btc_tf_data=None,
            sample_capital_usd=sample_capital_usd,
            risk_pct=risk_pct_input,
        )
        btc_tf_data_ref = btc_tf_data
        if "BTC/USDT" in st.session_state.watchlist:
            all_coin_results["BTC/USDT"] = (btc_tf_data, btc_tf_fc, btc_flow, btc_src)
    except Exception:
        btc_regime_scores = None
        btc_tf_data_ref = None

    for sym in st.session_state.watchlist:
        try:
            if sym not in all_coin_results:
                tf_data, tf_forecasts, order_flow, src, _ = load_coin_intelligence(
                    symbol=sym,
                    exchange_id=exchange_choice,
                    timeframes=TIMEFRAMES,
                    limit=candle_limit,
                    btc_regime_scores=btc_regime_scores,
                    btc_tf_data=btc_tf_data_ref,
                    sample_capital_usd=sample_capital_usd,
                    risk_pct=risk_pct_input,
                )
                all_coin_results[sym] = (tf_data, tf_forecasts, order_flow, src)
            else:
                tf_data, tf_forecasts, order_flow, src = all_coin_results[sym]

            df_1h = tf_data["1H"]
            fc_15m = tf_forecasts["15M"]
            fc_1h = tf_forecasts["1H"]
            fc_4h = tf_forecasts["4H"]
            fc_1d = tf_forecasts["1D"]

            last_close = float(df_1h["close"].iloc[-1])
            cmf_1h = float(df_1h["cmf"].iloc[-1])
            mtf_master = 0.15 * fc_15m.score + 0.30 * fc_1h.score + 0.30 * fc_4h.score + 0.25 * fc_1d.score

            def badge(score: float) -> str:
                if score >= 15:
                    return f"🟢 Yükselen ({score:+.0f})"
                if score <= -15:
                    return f"🔴 Düşen ({score:+.0f})"
                return f"🟡 Yatay ({score:+.0f})"

            flow_tag = (
                "🟢 Para Girişi"
                if cmf_1h > 0.04
                else ("🔴 Para Çıkışı" if cmf_1h < -0.04 else "⚪ Dengeli")
            )

            fut_1h = getattr(fc_1h, "futures_setup", None)
            if fut_1h and fut_1h.is_tradeable:
                fut_dir_icon = "🟢 LONG" if fut_1h.direction == "LONG" else "🔴 SHORT"
                fut_radar_tag = (
                    f"{fut_dir_icon} ({fut_1h.confidence_score:.0f}/100 - {fut_1h.confidence_grade}) | "
                    f"Giriş:{price_fmt(fut_1h.entry_price)} TP1:{price_fmt(fut_1h.tp1_price)} Stop:{price_fmt(fut_1h.stop_price)}"
                )
            elif fut_1h:
                fut_radar_tag = f"⛔ Girilmez (Riskli - Güven:{fut_1h.confidence_score:.0f}/100 {fut_1h.confidence_grade})"
            else:
                fut_radar_tag = "⛔ Hesaplanmadı"

            sup_icon_1h = "🛡️" if getattr(fc_1h, "nearest_support_score", 0.0) >= 58.0 else "🟢"
            res_icon_1h = "🧱" if getattr(fc_1h, "nearest_resistance_score", 0.0) >= 58.0 else "🔴"
            screener_rows.append({
                "_sort_ready": fc_1h.readiness_score_5,
                "_sort_whale": abs(fc_1h.whale_accumulation_score - 50.0),
                "_sort_master": abs(mtf_master),
                "_fut_tradeable": bool(fut_1h and fut_1h.is_tradeable),
                "_fut_conf": float(fut_1h.confidence_score) if fut_1h else 0.0,
                "_raw_price": last_close,
                "_fc_1h": fc_1h,
                "Coin": sym,
                "Fiyat (USDT)": f"{price_fmt(last_close)}",
                "24s Değişim": f"{order_flow.price_change_24h_pct:+.2f}%",
                "⚡ Vadeli İşlem Radarı (1S)": fut_radar_tag,
                "Onay": f"{fc_1h.readiness_score_5}/5",
                "15D Trend": badge(fc_15m.score),
                "1S Trend": badge(fc_1h.score),
                "4S Trend": badge(fc_4h.score),
                "1G Trend": badge(fc_1d.score),
                "Para Akışı (1S)": flow_tag,
                "🐋 Balina İzi": f"{fc_1h.whale_accumulation_score:.0f}/100",
                "Destek / Direnç": f"{sup_icon_1h} {price_fmt(fc_1h.nearest_support)} / {res_icon_1h} {price_fmt(fc_1h.nearest_resistance)}",
            })
        except Exception as exc:
            st.error(f"{sym} verisi alınırken hata oluştu: {exc}")

with st.expander("🌐 Çoklu Coin Tarama Tablosu & ⚡ Vadeli İşlem Radarı Özeti (Açmak İçin Tıklayın)", expanded=False):
    if all_coin_results:
        magnet_sym, magnet_cmf = None, -999.0
        outflow_sym, outflow_cmf = None, 999.0
        bull_1h_count = 0
        tradeable_fut_count = 0
        for sym_g, (tfd_g, tffc_g, _, _) in all_coin_results.items():
            cmf_g = float(tfd_g["1H"]["cmf"].iloc[-1]) if "1H" in tfd_g else 0.0
            if cmf_g > magnet_cmf:
                magnet_cmf, magnet_sym = cmf_g, sym_g
            if cmf_g < outflow_cmf:
                outflow_cmf, outflow_sym = cmf_g, sym_g
            if "1H" in tffc_g and tffc_g["1H"].score >= 15.0:
                bull_1h_count += 1
            if "1H" in tffc_g and getattr(tffc_g["1H"], "futures_setup", None) and tffc_g["1H"].futures_setup.is_tradeable:
                tradeable_fut_count += 1

        st.markdown(
            f"**🌍 Piyasa Özeti:** Saatlikte **{bull_1h_count}/{len(all_coin_results)}** coin yükselişte &nbsp;|&nbsp; "
            f"**⚡ Vadeli İşleme Uygun Coin:** `{tradeable_fut_count}/{len(all_coin_results)}` &nbsp;|&nbsp; "
            f"**🧲 En Güçlü Para Girişi:** `{magnet_sym}` &nbsp;|&nbsp; **📤 En Çok Para Çıkışı:** `{outflow_sym}`"
        )

    if screener_rows:
        screener_rows.sort(
            key=lambda r: (r["_fut_tradeable"], r["_fut_conf"], r["_sort_ready"], r["_sort_whale"], r["_sort_master"]),
            reverse=True,
        )
        drop_internal_cols = [c for c in screener_rows[0].keys() if c.startswith("_")]
        display_screener_df = pd.DataFrame(screener_rows).drop(
            columns=drop_internal_cols,
            errors="ignore",
        )
        st.dataframe(display_screener_df, use_container_width=True, hide_index=True)

        sc_btn1, sc_btn2, sc_btn3, sc_btn4 = st.columns([1, 1, 1, 1])
        with sc_btn1:
            csv_bytes = display_screener_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 Tarama Tablosunu İndir (CSV)",
                data=csv_bytes,
                file_name="kripto_tarama_ozeti.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with sc_btn2:
            if st.button("📲 Tarama Raporunu Telegram'a Gönder", use_container_width=True):
                msg_html = format_screener_telegram_html(screener_rows, "1H")
                kb_sc = build_screener_inline_keyboard(screener_rows, "1H", False)
                ok_tg, status_tg = send_telegram_message(
                    tg_token_input,
                    tg_chat_input,
                    msg_html,
                    reply_markup=kb_sc,
                )
                if ok_tg:
                    st.success(status_tg)
                else:
                    st.warning(status_tg)
        with sc_btn3:
            if st.button("🚨 Kırılım Radarını Telegram'a Gönder", use_container_width=True):
                brk_entries = [
                    {
                        "symbol": r["Coin"],
                        "price": r["_raw_price"],
                        "fc": r["_fc_1h"],
                    }
                    for r in screener_rows
                ]
                msg_brk_radar = format_breakout_radar_scan_telegram_html(brk_entries, "1H")
                kb_brk_radar = build_breakout_radar_inline_keyboard(brk_entries, "1H")
                ok_br, status_br = send_telegram_message(
                    tg_token_input,
                    tg_chat_input,
                    msg_brk_radar,
                    reply_markup=kb_brk_radar,
                )
                if ok_br:
                    st.success(status_br)
                else:
                    st.warning(status_br)
        with sc_btn4:
            if st.button("⚡ Vadeli İşlem Radarını Telegram'a Gönder", use_container_width=True):
                radar_entries = [
                    {
                        "symbol": r["Coin"],
                        "price": r["_raw_price"],
                        "fc": r["_fc_1h"],
                    }
                    for r in screener_rows
                ]
                msg_fut_radar = format_futures_radar_scan_telegram_html(radar_entries, "1H")
                kb_fut_radar = build_futures_radar_inline_keyboard(radar_entries, "1H")
                ok_fr, status_fr = send_telegram_message(
                    tg_token_input,
                    tg_chat_input,
                    msg_fut_radar,
                    reply_markup=kb_fut_radar,
                )
                if ok_fr:
                    st.success(status_fr)
                else:
                    st.warning(status_fr)

# ---------------------------------------------------------------------------
# DETAILED SINGLE-COIN INSPECTOR (CLEAN, CONCISE & JARGON-FREE LAYOUT)
# ---------------------------------------------------------------------------
available_symbols = [s for s in st.session_state.watchlist if s in all_coin_results]
if not available_symbols:
    st.warning("Seçili coinler için veri yüklenemedi. Lütfen sol menüden '🔄 Tüm Verileri Şimdi Yenile' butonuna tıklayın.")
    st.stop()

col_sel1, col_sel2, col_sel3 = st.columns([2, 2, 1.3])
with col_sel1:
    active_symbol = st.selectbox(
        "🔍 İncelenecek Coini Seçin",
        options=available_symbols,
        index=0,
    )
with col_sel2:
    active_tf = st.radio(
        "⏱️ Zaman Dilimi Seçin",
        options=["15M", "1H", "4H", "1D"],
        index=1,
        horizontal=True,
        help="15M: 15 Dakika | 1H: 1 Saat | 4H: 4 Saat | 1D: 1 Gün",
    )

tf_data, tf_forecasts, order_flow, source_used = all_coin_results[active_symbol]
df_active = tf_data[active_tf]
fc_active = tf_forecasts[active_tf]
last_row = df_active.iloc[-1]
last_price = float(last_row["close"])

with col_sel3:
    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
    if st.button(f"📲 {active_symbol} ({active_tf}) Telegram'a Gönder", use_container_width=True):
        coin_html = format_forecast_telegram_html(
            fc=fc_active,
            symbol=active_symbol,
            timeframe=active_tf,
            current_price=last_price,
            mtf_scores={k: tf_forecasts[k].score for k in ("15M", "1H", "4H", "1D") if k in tf_forecasts},
        )
        kb_an = build_analysis_inline_keyboard(active_symbol, active_tf)
        ok_c, msg_c = send_telegram_message(
            tg_token_input,
            tg_chat_input,
            coin_html,
            reply_markup=kb_an,
        )
        if send_chart_chk:
            png_bytes = generate_telegram_chart_png(df_active, fc_active, active_symbol, active_tf)
            if png_bytes:
                send_telegram_photo(
                    tg_token_input,
                    tg_chat_input,
                    png_bytes,
                    caption_html=f"🖼️ <b>{active_symbol} [{active_tf}] Kritik Seviyeler &amp; Grafik Görünümü</b>",
                )
        if ok_c:
            st.success(msg_c)
        else:
            st.warning(msg_c)

# ---------------------------------------------------------------------------
# 1. COMPACT STATUS & MULTI-TIMEFRAME ALIGNMENT BAR
# ---------------------------------------------------------------------------
score_col = "#00E676" if fc_active.score >= 15 else ("#FF5252" if fc_active.score <= -15 else "#FACC15")
if fc_active.score >= 15:
    main_trend_title = "📈 YÜKSELEN TREND"
    main_trend_desc = "Alıcılar baskın, yön yukarı"
elif fc_active.score <= -15:
    main_trend_title = "📉 DÜŞEN TREND"
    main_trend_desc = "Satıcılar baskın, yön aşağı"
else:
    main_trend_title = "⚖️ YATAY / KARARSIZ TREND"
    main_trend_desc = "Alıcı ve satıcılar dengede, kırılım bekleniyor"

mtf_badges_html = []
for tf_k in ("15M", "1H", "4H", "1D"):
    sc_k = tf_forecasts[tf_k].score
    if sc_k >= 15:
        c_k, lbl_k = "#00E676", "📈 Yükselen"
    elif sc_k <= -15:
        c_k, lbl_k = "#FF5252", "📉 Düşen"
    else:
        c_k, lbl_k = "#FACC15", "⚖️ Yatay"
    active_border = "2px solid #38BDF8" if tf_k == active_tf else "1px solid #334155"
    mtf_badges_html.append(
        f"<span style='display:inline-block; background:#0F172A; border:{active_border}; border-radius:6px; padding:3px 9px; margin-left:5px; font-size:12px;'>"
        f"<b>{tf_k}:</b> <span style='color:{c_k}; font-weight:700;'>{lbl_k} ({sc_k:+.0f})</span></span>"
    )

rd_fut = getattr(fc_active, "futures_setup", None)
if rd_fut and rd_fut.is_tradeable and fc_active.readiness_score_5 >= 4:
    rd_col = "#00E676"
    rd_short = f"Güçlü Kurulum ({rd_fut.direction})"
elif rd_fut and rd_fut.is_tradeable:
    rd_col = "#38BDF8"
    rd_short = f"İşleme Uygun ({rd_fut.direction})"
elif fc_active.readiness_score_5 >= 3:
    rd_col = "#FACC15"
    rd_short = "Kırılım / Onay Bekleniyor"
else:
    rd_col = "#FF5252"
    rd_short = "Bekle-Gör (Riskli)"

st.markdown(
    f"""
    <div style="background:#111827; border:1px solid #1E293B; border-left:5px solid {score_col}; border-radius:10px; padding:11px 16px; margin-bottom:14px; display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:10px;">
        <div style="font-size:14px;">
            <b style="color:#F8FAFC; font-size:15px;">{active_symbol} ({active_tf}) <span style="color:#64748B; font-size:12px;">[{source_used}]</span>:</b>
            <span style="color:{score_col}; font-weight:800; font-size:15px; margin-left:6px;">{main_trend_title} ({fc_active.score:+.0f}/100)</span>
            <span style="color:#94A3B8; font-size:13px; margin-left:6px;">— {main_trend_desc}</span>
            &nbsp;|&nbsp;
            <span style="color:{rd_col}; font-weight:700; font-size:13px;">🚦 Hazırlık: {fc_active.readiness_score_5}/5 ({rd_short})</span>
        </div>
        <div>
            {"".join(mtf_badges_html)}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 2. 4 CONCISE, READABLE & JARGON-FREE CARDS (TREND, S/R, MONEY FLOW, MAGNETS)
# ---------------------------------------------------------------------------
ema20_val = float(last_row.get("ema_20", last_price))
ema50_val = float(last_row.get("ema_50", last_price))
sup_val = fc_active.nearest_support
res_val = fc_active.nearest_resistance
sup2_val = fc_active.support_levels[1].price if len(fc_active.support_levels) > 1 else None
res2_val = fc_active.resistance_levels[1].price if len(fc_active.resistance_levels) > 1 else None

tp1_disp = fc_active.tp1_price if fc_active.tp1_price > 0 else fc_active.bullish_target_price
tp2_disp = fc_active.tp2_price if fc_active.tp2_price > 0 else fc_active.bullish_target_price
stop_disp = fc_active.stop_price if fc_active.stop_price > 0 else fc_active.bearish_invalidation_price
is_bear_target = (tp2_disp < last_price) or (fc_active.score < 0)
dir_label_tr = "Düşüş Hedefi" if is_bear_target else "Yükseliş Hedefi"

# Plain-language breakout & structure summary
smc_act = fc_active.smc
if smc_act and smc_act.structure_events:
    last_ev = smc_act.structure_events[-1]
    if "BULL_BOS" in last_ev.event_type or "BULL_CHOCH" in last_ev.event_type:
        breakout_text = f"🟢 Yukarı Trend Kırılımı ({price_fmt(last_ev.price)} aşımı)"
    elif "BEAR_BOS" in last_ev.event_type or "BEAR_CHOCH" in last_ev.event_type:
        breakout_text = f"🔴 Aşağı Trend Kırılımı ({price_fmt(last_ev.price)} kırılımı)"
    elif "BULL_SWEEP" in last_ev.event_type:
        breakout_text = f"🟢 Dip Tuzak / Stop Avı ({price_fmt(last_ev.price)} — Dönüş İzi)"
    elif "BEAR_SWEEP" in last_ev.event_type:
        breakout_text = f"⚠️ Tepe Tuzak / Stop Avı ({price_fmt(last_ev.price)} — Satış İzi)"
    else:
        breakout_text = "Belirgin kırılım yok"
else:
    breakout_text = "Henüz yeni kırılım yok"

sq_pct = fc_active.squeeze_energy_pct
if sq_pct >= 68:
    squeeze_short = f"💥 Yüksek Sıkışma (%{sq_pct:.0f}) — ±%{fc_active.expected_breakout_move_pct:.1f} sert kırılım yakın!"
elif fc_active.choppiness_index >= 60:
    squeeze_short = f"⚖️ Yatay Sıkışma (%{sq_pct:.0f}) — Kırılım yönü beklenmeli"
else:
    squeeze_short = f"🌊 Akıcı Hareket (Beklenen Dalga: ±%{fc_active.expected_breakout_move_pct:.1f})"

if res_val and res_val > last_price:
    up_break_price = res_val
elif ema20_val > last_price:
    up_break_price = ema20_val
else:
    up_break_price = last_price * 1.008

if sup_val and sup_val < last_price:
    down_break_price = sup_val
elif ema20_val < last_price:
    down_break_price = ema20_val
else:
    down_break_price = last_price * 0.992

# Money flow plain summary
cmf_v = float(last_row.get("cmf", 0.0))
net_delta_20 = float(df_active["net_money_delta_usd"].tail(20).sum())
wh_score = fc_active.whale_accumulation_score

if abs(net_delta_20) >= 1_000_000:
    delta_fmt_str = f"{net_delta_20 / 1_000_000:+,.1f} Milyon USDT"
elif abs(net_delta_20) >= 1_000:
    delta_fmt_str = f"{net_delta_20 / 1_000:+,.1f} Bin USDT"
else:
    delta_fmt_str = f"{net_delta_20:+,.0f} USDT"

if cmf_v > 0.04:
    mf_col = "#00E676"
    mf_headline = "🟢 Net Para Girişi Var"
elif cmf_v < -0.04:
    mf_col = "#FF5252"
    mf_headline = "🔴 Net Para Çıkışı Var"
else:
    mf_col = "#FACC15"
    mf_headline = "⚪ Para Akışı Dengeli"

if wh_score >= 60:
    whale_short = f"🟢 Balinalar Topluyor ({wh_score:.0f}/100)"
elif wh_score <= 40:
    whale_short = f"🔴 Balinalar Satıyor ({wh_score:.0f}/100)"
else:
    whale_short = f"⚪ Balinalar Dengede ({wh_score:.0f}/100)"

# Liquidation levels plain summary
short_liq_str = "Yok"
long_liq_str = "Yok"
if smc_act and smc_act.liquidation_pools:
    for p in smc_act.liquidation_pools:
        if p.pool_type == "SHORT_LIQ":
            short_liq_str = f"<b style='color:#C084FC;'>{price_fmt(p.price)}</b> <span style='color:#94A3B8;'>(+%{p.distance_pct:.1f})</span>"
        elif p.pool_type == "LONG_LIQ":
            long_liq_str = f"<b style='color:#FB923C;'>{price_fmt(p.price)}</b> <span style='color:#94A3B8;'>(-%{p.distance_pct:.1f})</span>"

c1, c2, c3, c4 = st.columns(4)

with c1:
    tl_rep = getattr(fc_active, "trendlines", None)
    tl_summary = getattr(tl_rep, "summary_tr", "") if tl_rep else ""
    sr_act_type = getattr(fc_active, "sr_action_type", "NONE")
    sr_act_str = getattr(fc_active, "sr_action_status_tr", "")
    sr_guide_str = getattr(fc_active, "sr_breakout_guide_tr", "")
    if sr_act_type in ("BULL_SR_BREAKOUT", "BEAR_SR_BREAKDOWN") and sr_act_str:
        brk_color = "#10B981" if sr_act_type == "BULL_SR_BREAKOUT" else "#EF4444"
        breakout_line_html = f"• <b>Kırılım Durumu:</b> <b style='color:{brk_color};'>{sr_act_str}</b>"
    elif sr_act_type != "NONE" and sr_act_str:
        breakout_line_html = f"• <b>Seviye Onayı / Tuzak:</b> <b style='color:#38BDF8;'>{sr_act_str}</b>"
    else:
        breakout_line_html = f"• <b>Kırılım İzi:</b> {breakout_text}"
    tl_line_html = f"• <b>Dinamik Kanal:</b> {tl_summary}<br>" if tl_summary else ""
    guide_line_html = (
        f"• <b>📐 Kırılım Nasıl Olur?:</b> <span style='color:#E2E8F0;'>{sr_guide_str}</span>"
        if sr_guide_str
        else f"• <b>Yukarı / Aşağı Eşik:</b> <b style='color:#00E676;'>{price_fmt(up_break_price)}</b> üstü / <b style='color:#FF5252;'>{price_fmt(down_break_price)}</b> altı"
    )
    st.markdown(
        f"""
        <div class="kpi-card" style="border-top: 4px solid {score_col};">
            <div class="kpi-title">1️⃣ MEVCUT TREND & KIRILIMLAR ({active_tf})</div>
            <div class="kpi-value" style="color:{score_col};">{main_trend_title}</div>
            <div class="kpi-sub" style="line-height:1.65; margin-top:8px;">
                {breakout_line_html}<br>
                {tl_line_html}• <b>Sıkışma Durumu:</b> {squeeze_short}<br>
                {guide_line_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c2:
    sup1_tier = getattr(fc_active, "nearest_support_tier_tr", "🟢 Destek")
    sup1_score = getattr(fc_active, "nearest_support_score", 0.0)
    sup1_reason = getattr(fc_active, "nearest_support_reason_tr", "")
    res1_tier = getattr(fc_active, "nearest_resistance_tier_tr", "🔴 Direnç")
    res1_score = getattr(fc_active, "nearest_resistance_score", 0.0)
    res1_reason = getattr(fc_active, "nearest_resistance_reason_tr", "")

    s1_stats = getattr(fc_active.support_levels[0], "stats_summary_tr", "") if fc_active.support_levels else ""
    r1_stats = getattr(fc_active.resistance_levels[0], "stats_summary_tr", "") if fc_active.resistance_levels else ""
    s1_htf = " · 🏛️ Üst Periyot Duvarı" if (fc_active.support_levels and getattr(fc_active.support_levels[0], "htf_confirmed", False) and "Üst Periyot" not in sup1_reason) else ""
    r1_htf = " · 🏛️ Üst Periyot Duvarı" if (fc_active.resistance_levels and getattr(fc_active.resistance_levels[0], "htf_confirmed", False) and "Üst Periyot" not in res1_reason) else ""

    sup1_badge = f" <span style='color:#94A3B8; font-size:11px;'>({sup1_score:.0f}/100{f' · {sup1_reason}' if sup1_reason else ''}{s1_htf}{f' · {s1_stats}' if s1_stats else ''})</span>" if sup1_score > 0 else ""
    res1_badge = f" <span style='color:#94A3B8; font-size:11px;'>({res1_score:.0f}/100{f' · {res1_reason}' if res1_reason else ''}{r1_htf}{f' · {r1_stats}' if r1_stats else ''})</span>" if res1_score > 0 else ""

    if len(fc_active.support_levels) > 1:
        s2_obj = fc_active.support_levels[1]
        s2_tier = getattr(s2_obj, "tier_tr", "🟢 Destek")
        s2_sc = getattr(s2_obj, "strength_score", 0.0)
        s2_st = getattr(s2_obj, "stats_summary_tr", "")
        sup2_html = f"<br>• <span style='color:#94A3B8;'>2. {s2_tier}:</span> <b style='color:#34D399;'>{price_fmt(s2_obj.price)}</b> <span style='color:#64748B; font-size:11px;'>({s2_sc:.0f}/100{f' · {s2_st}' if s2_st else ''})</span>"
    else:
        sup2_html = ""

    if len(fc_active.resistance_levels) > 1:
        r2_obj = fc_active.resistance_levels[1]
        r2_tier = getattr(r2_obj, "tier_tr", "🔴 Direnç")
        r2_sc = getattr(r2_obj, "strength_score", 0.0)
        r2_st = getattr(r2_obj, "stats_summary_tr", "")
        res2_html = f"<br>• <span style='color:#94A3B8;'>2. {r2_tier}:</span> <b style='color:#FB7185;'>{price_fmt(r2_obj.price)}</b> <span style='color:#64748B; font-size:11px;'>({r2_sc:.0f}/100{f' · {r2_st}' if r2_st else ''})</span>"
    else:
        res2_html = ""

    fut_c2 = getattr(fc_active, "futures_setup", None)
    if fut_c2 and fut_c2.is_tradeable:
        c2_target_line = (
            f"• 🎯 <b>Onaylı Hedef ({fut_c2.direction}):</b> <b style='color:#38BDF8;'>{price_fmt(fut_c2.tp1_price)}</b> ➔ <b style='color:#00E676;'>{price_fmt(fut_c2.tp2_price)}</b> "
            f"| <b>Stop:</b> <b style='color:#FF5252;'>{price_fmt(fut_c2.stop_price)}</b>"
        )
    else:
        channel_pct = abs((res_val or last_price) - (sup_val or last_price)) / max(last_price, 1e-9) * 100.0
        c2_target_line = (
            f"• 📐 <b>Kanal Genişliği:</b> <b>%{channel_pct:.2f}</b> "
            f"<span style='color:#F59E0B; font-size:11.5px;'>(Risk Kalkanı Aktif: Kırılım Öncesi İşlem/TP Önerilmez)</span>"
        )

    st.markdown(
        f"""
        <div class="kpi-card" style="border-top: 4px solid #38BDF8;">
            <div class="kpi-title">2️⃣ DESTEK & DİRENÇ MİMARİSİ</div>
            <div class="kpi-value" style="color:#F8FAFC;">Fiyat: {price_fmt(last_price)} <span style="font-size:13px; color:#94A3B8;">USDT</span></div>
            <div class="kpi-sub" style="line-height:1.62; margin-top:8px;">
                • <b>{sup1_tier}:</b> <b style="color:#00E676;">{price_fmt(sup_val)}</b>{sup1_badge}{sup2_html}<br>
                • <b>{res1_tier}:</b> <b style="color:#FF5252;">{price_fmt(res_val)}</b>{res1_badge}{res2_html}<br>
                {c2_target_line}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c3:
    has_real_taker_col = bool(last_row.get("has_real_taker_flow", False))
    delta_label_tr = "Son 20 Mum Nakit (Gerçek Taker)" if has_real_taker_col else "Son 20 Mum Nakit (Hacim Tahmini)"
    st.markdown(
        f"""
        <div class="kpi-card" style="border-top: 4px solid {mf_col};">
            <div class="kpi-title">3️⃣ PARA GİRİŞ / ÇIKIŞI & BALİNALAR</div>
            <div class="kpi-value" style="color:{mf_col};">{mf_headline}</div>
            <div class="kpi-sub" style="line-height:1.65; margin-top:8px;">
                • 💵 <b>{delta_label_tr}:</b> <b>{delta_fmt_str}</b><br>
                • 🐋 <b>Balina Durumu:</b> {whale_short}<br>
                • 📘 <b>Bekleyen Emirler:</b> <b>%{order_flow.imbalance_pct:.0f} Alıcı</b> / %{100 - order_flow.imbalance_pct:.0f} Satıcı<br>
                • 🧱 <b>Duvarlar:</b> Alış <b style="color:#00E676;">{price_fmt(order_flow.strongest_bid_wall)}</b> | Satış <b style="color:#FF5252;">{price_fmt(order_flow.strongest_ask_wall)}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c4:
    poc_dist_pct = abs(fc_active.poc_price - last_price) / max(last_price, 1e-9) * 100.0
    if last_price >= fc_active.poc_price:
        poc_relation = f"🟢 Fiyat, mıknatısın üstünde (+%{poc_dist_pct:.1f} — Destek)"
    else:
        poc_relation = f"🟡 Mıknatıs yukarıda (+%{poc_dist_pct:.1f} çekim bölgesi)"
    st.markdown(
        f"""
        <div class="kpi-card" style="border-top: 4px solid #A855F7;">
            <div class="kpi-title">4️⃣ MIKNATIS (POC) & TASFİYE BÖLGELERİ</div>
            <div class="kpi-value" style="color:#FACC15;">🧲 Mıknatıs: {price_fmt(fc_active.poc_price)}</div>
            <div class="kpi-sub" style="line-height:1.65; margin-top:8px;">
                • 🟡 <b>En Yoğun Fiyat (POC):</b> {poc_relation}<br>
                • ⚓ <b>Dip Alıcı Maliyeti (AVWAP):</b> <b>{price_fmt(fc_active.avwap_low_price)}</b><br>
                • ⬆️ <b>Tahmini Short Tasfiye (25x-50x):</b> {short_liq_str}<br>
                • ⬇️ <b>Tahmini Long Tasfiye (25x-50x):</b> {long_liq_str}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 2.5 DEDICATED PERPETUAL FUTURES (VADELİ İŞLEMLER) RADAR & SETUP ENGINE
# ---------------------------------------------------------------------------
fut_active = getattr(fc_active, "futures_setup", None)
if fut_active is not None:
    fut_hdr_col1, fut_hdr_col2 = st.columns([3.7, 1.3])
    with fut_hdr_col1:
        if fut_active.is_tradeable:
            fut_badge_col = "#00E676" if fut_active.direction == "LONG" else "#FF5252"
            fut_badge_bg = "rgba(0, 230, 118, 0.10)" if fut_active.direction == "LONG" else "rgba(255, 82, 82, 0.10)"
            fut_icon = "🟢 LONG (YÜKSELİŞ İŞLEMİ)" if fut_active.direction == "LONG" else "🔴 SHORT (DÜŞÜŞ İŞLEMİ)"
            st.markdown(
                f"""
                <div style="background:{fut_badge_bg}; border:1px solid {fut_badge_col}; border-left:5px solid {fut_badge_col}; border-radius:10px; padding:10px 16px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                    <div>
                        <span style="font-size:0.82rem; color:#94A3B8; font-weight:700; letter-spacing:0.04em;">⚡ VADELİ İŞLEMLER (FUTURES) YÖN TAHMİN & SEVİYE RADARI ({active_symbol} - {active_tf})</span><br>
                        <span style="font-size:1.15rem; font-weight:800; color:{fut_badge_col};">{fut_icon}</span>
                        <span style="font-size:0.92rem; color:#E2E8F0; margin-left:8px;">— {fut_active.confidence_verdict_tr}</span>
                    </div>
                    <div style="background:#0F172A; border:1px solid {fut_badge_col}; border-radius:8px; padding:6px 14px; text-align:right;">
                        <span style="font-size:0.76rem; color:#94A3B8; display:block;">VADELİ GÜVEN NOTU</span>
                        <span style="font-size:1.1rem; font-weight:800; color:{fut_badge_col};">{fut_active.confidence_score:.0f}/100 ({fut_active.confidence_grade} Kalite)</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
                <div style="background:rgba(245, 158, 11, 0.10); border:1px solid #F59E0B; border-left:5px solid #EF4444; border-radius:10px; padding:10px 16px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                    <div>
                        <span style="font-size:0.82rem; color:#FCD34D; font-weight:700; letter-spacing:0.04em;">⚡ VADELİ İŞLEMLER (FUTURES) RİSK KALKANI & GÜVEN RADARI ({active_symbol} - {active_tf})</span><br>
                        <span style="font-size:1.12rem; font-weight:800; color:#EF4444;">⛔ VADELİ İŞLEM TAVSİYE EDİLMEZ (RİSK YÜKSEK / TEKNİK YAPI UYGUN DEĞİL)</span>
                    </div>
                    <div style="background:#0F172A; border:1px solid #EF4444; border-radius:8px; padding:6px 14px; text-align:right;">
                        <span style="font-size:0.76rem; color:#94A3B8; display:block;">VADELİ GÜVEN NOTU</span>
                        <span style="font-size:1.1rem; font-weight:800; color:#F59E0B;">{fut_active.confidence_score:.0f}/100 ({fut_active.confidence_grade} — Riskli)</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    with fut_hdr_col2:
        if st.button(f"⚡ {active_symbol} ({active_tf}) Vadeli Planı Telegram'a Gönder", use_container_width=True):
            mtf_scores_fut = {k: tf_forecasts[k].score for k in ("15M", "1H", "4H", "1D") if k in tf_forecasts}
            fut_msg_html = format_futures_setup_telegram_html(
                fc=fc_active,
                symbol=active_symbol,
                timeframe=active_tf,
                current_price=last_price,
                mtf_scores=mtf_scores_fut,
            )
            fut_kb = build_futures_setup_inline_keyboard(active_symbol, active_tf)
            ok_ftg, msg_ftg = send_telegram_message(
                tg_token_input,
                tg_chat_input,
                fut_msg_html,
                reply_markup=fut_kb,
            )
            if ok_ftg:
                st.success("✅ Vadeli İşlem Planı Telegram'a gönderildi!")
            else:
                st.warning(msg_ftg)

    if fut_active.is_tradeable:
        fc_f1, fc_f2, fc_f3 = st.columns(3)
        dir_color = "#00E676" if fut_active.direction == "LONG" else "#FF5252"
        dir_title = "🟢 LONG (YÜKSELİŞ)" if fut_active.direction == "LONG" else "🔴 SHORT (DÜŞÜŞ)"
        with fc_f1:
            st.markdown(
                f"""
                <div class="kpi-card" style="border-top: 3px solid {dir_color};">
                    <div class="kpi-title">🎯 1. İŞLEM YÖNÜ, GİRİŞ YERİ & KALDIRAÇ</div>
                    <div class="kpi-value" style="color:{dir_color}; font-size:1.18rem;">{dir_title} | Giriş: {price_fmt(fut_active.entry_price)}</div>
                    <div class="kpi-sub" style="line-height:1.68; margin-top:8px;">
                        • 🧭 <b>Giriş Stratejisi:</b> <b>{fut_active.entry_type_tr}</b><br>
                        • 📍 <b>Kademeli Giriş Bölgesi:</b> <b>{price_fmt(fut_active.entry_zone_low)} – {price_fmt(fut_active.entry_zone_high)} USDT</b><br>
                        • 🛡️ <b>Vadeli Güven Notu:</b> <b style="color:{dir_color};">{fut_active.confidence_score:.0f}/100 ({fut_active.confidence_grade})</b><br>
                        • ⚙️ <b>Önerilen Maks. Kaldıraç:</b> <b>{fut_active.max_safe_leverage}x (İzole)</b><br>
                        • 🧱 <b>Destek/Direnç Gözetimi:</b> {fut_active.sr_context_tr}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with fc_f2:
            st.markdown(
                f"""
                <div class="kpi-card" style="border-top: 3px solid #38BDF8;">
                    <div class="kpi-title">🏁 2. KAR AL (TP1 / TP2 / TP3) & STOP YERİ</div>
                    <div class="kpi-value" style="color:#38BDF8; font-size:1.18rem;">⚖️ R:R Oranı: 1 : {fut_active.rr_ratio:.2f}</div>
                    <div class="kpi-sub" style="line-height:1.68; margin-top:8px;">
                        • 🎯 <b>1. Kâr Al (TP1 - %40 Kapat):</b> <b style="color:#00E676;">{price_fmt(fut_active.tp1_price)} USDT</b> (%{fut_active.tp1_distance_pct:.2f} — <i>Stop'u Girişe Çek</i>)<br>
                        • 🎯 <b>2. Ana Hedef (TP2 - %40 Kapat):</b> <b style="color:#00E676;">{price_fmt(fut_active.tp2_price)} USDT</b> (%{fut_active.tp2_distance_pct:.2f})<br>
                        • 🚀 <b>3. Uzatılmış Hedef (TP3 - %20):</b> <b style="color:#38BDF8;">{price_fmt(fut_active.tp3_price)} USDT</b> (%{fut_active.tp3_distance_pct:.2f})<br>
                        • 🛑 <b>Zarar-Kes (Stop-Loss Yeri):</b> <b style="color:#FF5252;">{price_fmt(fut_active.stop_price)} USDT</b> (%{fut_active.stop_distance_pct:.2f} — <i>İğne Korumalı</i>)<br>
                        • ⏳ <b>Takip Notu:</b> {fut_active.wait_condition_tr}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with fc_f3:
            lev_sq_str = getattr(fut_active, "leverage_squeeze_status_tr", "") or getattr(fc_active, "leverage_squeeze_status_tr", "")
            lev_sq_html = f"• ⚡ <b>Kaldıraç Sıkıştırma:</b> <b style='color:#38BDF8;'>{lev_sq_str}</b><br>" if lev_sq_str else ""
            fluences_html = "<br>".join([f"• ✅ {item}" for item in fut_active.positive_factors_tr[:4]])
            warnings_html = (
                "<br>".join([f"• ⚠️ {w}" for w in fut_active.risk_warnings_tr[:2]])
                if fut_active.risk_warnings_tr
                else "• ✅ Kritik bir mikro-yapı veya sıkışma engeli tespit edilmedi."
            )
            st.markdown(
                f"""
                <div class="kpi-card" style="border-top: 3px solid #A855F7;">
                    <div class="kpi-title">🔬 3. VADELİ TEKNİK ONAYLAR & FONLAMA/OI</div>
                    <div class="kpi-value" style="color:#FACC15; font-size:1.05rem;">📊 {fut_active.futures_tech_summary_tr.split('|')[0]}</div>
                    <div class="kpi-sub" style="line-height:1.62; margin-top:8px;">
                        {lev_sq_html}{fluences_html}<br>
                        {warnings_html}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        reasons_html = "<br>".join([f"• ❌ <b>{w}</b>" for w in fut_active.risk_warnings_tr[:5]])
        pos_notes_html = (
            "<br>".join([f"• 🔹 {f_item}" for f_item in fut_active.positive_factors_tr[:3]])
            if fut_active.positive_factors_tr
            else "• 🔹 Henüz yeterli vadeli işlem onayı oluşmadı."
        )
        st.markdown(
            f"""
            <div class="kpi-card" style="border-top: 3px solid #EF4444; background: linear-gradient(180deg, rgba(239,68,68,0.07) 0%, rgba(17,24,39,0.95) 100%);">
                <div style="display:flex; flex-wrap:wrap; gap:20px; justify-content:space-between;">
                    <div style="flex:1.4; min-width:280px;">
                        <div class="kpi-title" style="color:#FCA5A5;">🚨 NEDEN ŞU AN VADELİ İŞLEM ÖNERİLMİYOR? (RİSK ANALİZİ)</div>
                        <div class="kpi-sub" style="line-height:1.72; margin-top:6px; color:#E2E8F0;">
                            <i>Vadeli İşlem Radarı; destek/direnç sıkışması, testere piyasası veya yetersiz kazanç/risk (R:R) gördüğünde sermayenizi korumak için <b>Giriş, TP ve Stop seviyesi vermez</b>:</i><br>
                            {reasons_html}<br>
                            • 🧱 <b>Destek/Direnç Durumu:</b> {fut_active.sr_context_tr}
                        </div>
                    </div>
                    <div style="flex:1; min-width:260px; border-left:1px solid #334155; padding-left:16px;">
                        <div class="kpi-title" style="color:#FCD34D;">⏳ NE ZAMAN İŞLEME GİRİLEBİLİR? (RADAR BEKLEME ŞARTI)</div>
                        <div class="kpi-sub" style="line-height:1.72; margin-top:6px;">
                            • 🎯 <b>Beklenen Kırılım / Onay:</b> <b style="color:#38BDF8;">{fut_active.wait_condition_tr}</b><br>
                            • 📊 <b>Vadeli Mikro-Yapı:</b> {fut_active.futures_tech_summary_tr}<br>
                            {pos_notes_html}
                        </div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 3. CLEAN CHART PRESET BAR + OPTIONAL EXPANDER FOR ADVANCED SETTINGS/DETAILS
# ---------------------------------------------------------------------------
preset_mode = st.radio(
    "🎛️ Grafik Görünümü Seçin:",
    options=[
        "✨ Sade Trend & Hedefler (Önerilen)",
        "🧱 Destek, Direnç & Maliyet Odaklı",
        "🧲 Mıknatıs & Likidasyon Odaklı",
        "🔬 Tüm Katmanları Göster",
    ],
    index=0,
    horizontal=True,
)

is_clean = preset_mode.startswith("✨")
is_sr_focus = preset_mode.startswith("🧱")
is_smc_focus = preset_mode.startswith("🧲")
is_all = preset_mode.startswith("🔬")
default_proj_box = bool((fut_active and fut_active.is_tradeable) or is_all)

with st.expander("➕ Gelişmiş Detaylar: Tekil Çizgi Ayarları, 5 Kriterli Onay Listesi, Kasa Planı & Faktör Grafiği", expanded=False):
    chk_c1, chk_c2, chk_c3, chk_c4 = st.columns(4)
    with chk_c1:
        show_ema_ribbon = st.checkbox("🌊 Ana Trend Çizgileri (EMA 20 & 50)", value=True, key=f"ema_{preset_mode}")
        show_projection_box = st.checkbox("🎯 Hedef & Zarar-Kes (Stop) Kutusu", value=default_proj_box, key=f"proj_{preset_mode}")
        show_reversal_markers = st.checkbox("🔺 Dönüş Sinyali Üçgenleri (▲/▼)", value=True, key=f"rev_{preset_mode}")
    with chk_c2:
        show_sr_zones = st.checkbox("🟢🔴 Destek & Direnç Bölgeleri", value=(is_clean or is_sr_focus or is_all), key=f"sr_{preset_mode}")
        show_poc = st.checkbox("🟡 Mıknatıs Fiyat (POC)", value=(is_clean or is_sr_focus or is_smc_focus or is_all), key=f"poc_{preset_mode}")
        show_kalman_avwap = st.checkbox("⚓ Dip/Tepe Maliyet & Erken Trend", value=(is_sr_focus or is_all), key=f"kav_{preset_mode}")
        show_vpvr = st.checkbox("📊 Yatay Hacim Barları (VPVR)", value=(is_sr_focus or is_all), key=f"vpvr_{preset_mode}")
    with chk_c3:
        show_liq_pools = st.checkbox("🧲 Tahmini Tasfiye Mıknatısları", value=(is_smc_focus or is_all), key=f"liq_{preset_mode}")
        show_smc = st.checkbox("🏦 Balina Emir Kutuları (OB/FVG)", value=(is_smc_focus or is_all), key=f"smc_{preset_mode}")
        show_prob_cone = st.checkbox("🔮 Olasılık Yelpazesi (%68)", value=(is_smc_focus or is_all), key=f"cone_{preset_mode}")
    with chk_c4:
        show_supertrend = st.checkbox("🛡️ SuperTrend Çizgisi", value=is_all, key=f"st_{preset_mode}")
        show_bollinger = st.checkbox("📏 Bollinger Bantları", value=is_all, key=f"bb_{preset_mode}")
        show_divergences = st.checkbox("📐 RSI Uyumsuzluk Çizgileri", value=(is_sr_focus or is_all), key=f"div_{preset_mode}")
        show_text_labels = st.checkbox("🏷️ Mum Üzeri Yazı Etiketleri", value=False, key=f"txt_{preset_mode}")

    st.markdown("---")
    adv_col1, adv_col2 = st.columns([3, 2])
    with adv_col1:
        st.markdown(f"**🚦 5 Kriterli İşlem Hazırlık Kontrolü ({fc_active.readiness_score_5}/5 Onay):**")
        for c_title, c_ok, c_desc in fc_active.readiness_checks:
            st.markdown(f"{'✅' if c_ok else '❌'} **{c_title}:** {c_desc}")
        if fc_active.risk_plan:
            st.markdown(f"**🧮 Örnek Kasa & Risk Planı:** {fc_active.risk_plan.summary_tr}")
    with adv_col2:
        factor_names = [
            "1. Trend Yönü",
            "2. Para Giriş / Çıkışı",
            "3. Alım İştahı (Momentum)",
            "4. Destek & Direnç Yapısı",
            "5. Mum Formasyonu",
            "6. Bitcoin & Üst Zaman Uyumu",
        ]
        factor_vals = [
            fc_active.trend_score,
            fc_active.money_flow_score,
            fc_active.momentum_score,
            fc_active.structure_score,
            fc_active.pattern_score,
            fc_active.macro_htf_score,
        ]
        bar_colors = ["#00E676" if v >= 10 else ("#FF5252" if v <= -10 else "#FACC15") for v in factor_vals]
        fig_factors = go.Figure(
            go.Bar(
                x=factor_vals,
                y=factor_names[::-1],
                orientation="h",
                marker_color=bar_colors[::-1],
                text=[f"{v:+.0f}" for v in factor_vals[::-1]],
                textposition="auto",
            )
        )
        fig_factors.update_layout(
            template="plotly_dark",
            height=230,
            margin=dict(l=10, r=15, t=10, b=20),
            xaxis=dict(range=[-105, 105], zeroline=True, zerolinecolor="#94A3B8"),
            paper_bgcolor="#111827",
            plot_bgcolor="#111827",
        )
        st.plotly_chart(fig_factors, use_container_width=True)

# ---------------------------------------------------------------------------
# MAIN INTERACTIVE PLOTLY CHART
# ---------------------------------------------------------------------------
visualizer = InteractiveChartVisualizer(
    AnalysisConfig(
        exchange=ExchangeConfig(primary_exchange=exchange_choice, symbol=active_symbol, timeframe=active_tf.lower()),
        chart=ChartConfig(height=860),
    )
)

main_fig = visualizer.create_figure(
    df=df_active,
    exchange_source=source_used,
    forecast=fc_active,
    show_bollinger=show_bollinger,
    show_ema_ribbon=show_ema_ribbon,
    show_supertrend=show_supertrend,
    show_sr_zones=show_sr_zones,
    show_poc=show_poc,
    show_reversal_markers=show_reversal_markers,
    show_divergences=show_divergences,
    show_projection_box=show_projection_box,
    show_smc=show_smc,
    show_liq_pools=show_liq_pools,
    show_prob_cone=show_prob_cone,
    show_text_labels=show_text_labels,
    show_kalman_avwap=show_kalman_avwap,
    show_vpvr=show_vpvr,
)

st.plotly_chart(main_fig, use_container_width=True)

# ---------------------------------------------------------------------------
# BOTTOM TABS (3 CLEAN, NON-REDUNDANT PROFESSIONAL TABS)
# ---------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs([
    "⏱️ Tüm Zaman Dilimleri (15M / 1H / 4H / 1D) & Vadeli Kurulum Karşılaştırması",
    f"📋 {active_symbol} ({active_tf}) Kapanmış Mum Formasyon & Sinyal Geçmişi",
    "🧭 Piyasa Genişliği (ETH/BTC Rotasyon) & Portföy Korelasyon Matrisi",
])

with tab1:
    mtf_rows = []
    for tf_k, fc_k in tf_forecasts.items():
        bt_k = fc_k.backtest_stats
        fs_k = getattr(fc_k, "futures_setup", None)
        if fs_k and fs_k.is_tradeable:
            fut_col_str = f"{'🟢 LONG' if fs_k.direction == 'LONG' else '🔴 SHORT'} ({fs_k.confidence_score:.0f}/100 · 1:{fs_k.rr_ratio:.2f})"
            tp_col_str = f"{price_fmt(fs_k.tp1_price)} / {price_fmt(fs_k.tp2_price)} USDT"
            stop_col_str = f"{price_fmt(fs_k.stop_price)} USDT"
        else:
            sc_f = fs_k.confidence_score if fs_k else 0.0
            fut_col_str = f"⛔ İşlem Önerilmez (Güven: {sc_f:.0f}/100)"
            tp_col_str = "Kırılım Bekleniyor"
            stop_col_str = "—"

        s_tier_k = getattr(fc_k, "nearest_support_tier_tr", "🟢 Destek")
        r_tier_k = getattr(fc_k, "nearest_resistance_tier_tr", "🔴 Direnç")
        mtf_rows.append({
            "Zaman Dilimi": tf_k,
            "Yön Skoru": f"{fc_k.score:+.1f} / 100",
            "Hazırlık": f"{fc_k.readiness_score_5}/5",
            "⚡ Vadeli İşlem Radarı": fut_col_str,
            "Destek / Direnç (Güç Sınıfı)": f"{s_tier_k}: {price_fmt(fc_k.nearest_support)} | {r_tier_k}: {price_fmt(fc_k.nearest_resistance)}",
            "Onaylı TP1 / TP2": tp_col_str,
            "Onaylı Stop": stop_col_str,
            "Para Akışı & CVD": f"{fc_k.money_flow_status_tr}",
            "Dönüş Sinyali Backtest": f"%{bt_k.win_rate_pct:.1f} (TP1: %{bt_k.tp1_hit_rate_pct:.0f} | PF:{bt_k.profit_factor:.2f})",
        })
    st.dataframe(pd.DataFrame(mtf_rows), use_container_width=True, hide_index=True)

    bt_act = fc_active.backtest_stats
    if bt_act.equity_curve_r and len(bt_act.equity_curve_r) >= 2:
        st.markdown(f"#### 📈 {active_symbol} ({active_tf}) — Geçmiş Dönüş Sinyallerinin Kümülatif Performans Eğrisi (Net R Birimi)")
        st.caption(
            "Bu grafik, seçili zaman diliminde geçmişte oluşan onaylı mum dönüş sinyallerinin kademeli kâr alma (TP1 + Başabaş Stop + TP2) "
            "ve borsa komisyonu düşüldükten sonra kümülatif olarak nasıl sonuç verdiğini gösterir (+1R = 1 birim risk kazancı)."
        )
        eq_fig = go.Figure()
        eq_fig.add_trace(
            go.Scatter(
                x=bt_act.equity_timestamps,
                y=bt_act.equity_curve_r,
                mode="lines+markers",
                name="Kümülatif Net R Getirisi",
                line=dict(color="#00E676" if bt_act.equity_curve_r[-1] >= 0 else "#FF5252", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(0, 230, 118, 0.10)" if bt_act.equity_curve_r[-1] >= 0 else "rgba(255, 82, 82, 0.10)",
                hovertemplate="<b>Sinyal Tarihi:</b> %{x}<br><b>Kümülatif Net Kazanç:</b> %{y:+.2f}R<extra></extra>",
            )
        )
        eq_fig.update_layout(
            template="plotly_dark",
            height=270,
            margin=dict(l=40, r=25, t=20, b=30),
            paper_bgcolor="#111827",
            plot_bgcolor="#111827",
            yaxis_title="Kümülatif Net Getiri (R)",
            xaxis_title="Geçmiş Sinyal Zamanı",
        )
        st.plotly_chart(eq_fig, use_container_width=True)

with tab2:
    sig_engine = SignalEngine()
    summary_df = sig_engine.summarize_signals(df_active)
    if not summary_df.empty:
        recent_sigs = summary_df.tail(25).iloc[::-1].copy()
        recent_sigs["Tarih / Saat (UTC)"] = recent_sigs["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        recent_sigs["Fiyat (USDT)"] = recent_sigs["close"].map(price_fmt)
        recent_sigs["RSI (14)"] = recent_sigs["rsi"].map(lambda x: f"{x:.1f}" if pd.notna(x) else "N/A")
        recent_sigs["Para Akışı (CMF)"] = recent_sigs["cmf"].map(lambda x: f"{x:+.2f}" if pd.notna(x) else "0.00")
        recent_sigs["Türkçe Formasyon Adı"] = recent_sigs["pattern_tr_name"]
        recent_sigs["Sinyal Özeti"] = recent_sigs["signal_label"]
        recent_sigs["Ne Anlama Gelir? (Yatırımcı Açıklaması)"] = recent_sigs["pattern_meaning_tr"]

        cols_to_show = [
            "Tarih / Saat (UTC)",
            "Fiyat (USDT)",
            "RSI (14)",
            "Para Akışı (CMF)",
            "Türkçe Formasyon Adı",
            "Sinyal Özeti",
            "Ne Anlama Gelir? (Yatırımcı Açıklaması)",
        ]
        st.dataframe(recent_sigs[cols_to_show], use_container_width=True, hide_index=True)
    else:
        st.info("Bu zaman diliminde filtre kriterlerini geçen sinyal bulunamadı.")

    with st.expander("📘 Türkçe Mum Formasyonları Rehberi (Açmak İçin Tıklayın)", expanded=False):
        dict_rows = []
        for eng, info in PATTERN_INFO_TR.items():
            dict_rows.append({
                "Türkçe Formasyon Adı": info["tr_name"],
                "Uluslararası Adı": eng,
                "Beklenen Yön Etkisi": info["direction"],
                "Detaylı Yatırımcı Açıklaması": info["meaning"],
            })
        st.dataframe(pd.DataFrame(dict_rows), use_container_width=True, hide_index=True)

with tab3:
    st.markdown(f"#### 🧭 Portföy Getiri Korelasyon Matrisi ({active_tf}) & Altcoin Rotasyon Analizi")
    ret_dict = {}
    bull_breadth = 0
    for sym_k, (tfd_k, tffc_k, _, _) in all_coin_results.items():
        if active_tf in tfd_k and len(tfd_k[active_tf]) > 20:
            s_close = tfd_k[active_tf]["close"].tail(60).pct_change().dropna().reset_index(drop=True)
            ret_dict[sym_k] = s_close
        if active_tf in tffc_k and tffc_k[active_tf].score >= 15.0:
            bull_breadth += 1

    total_coins = max(len(all_coin_results), 1)
    breadth_pct = (bull_breadth / total_coins) * 100.0
    eth_rs_str = "Hesaplanmadı"
    if "ETH/USDT" in all_coin_results:
        eth_fc = all_coin_results["ETH/USDT"][1].get(active_tf)
        if eth_fc:
            eth_rs_str = eth_fc.smc.relative_strength.status_tr

    st.info(
        f"📊 **Piyasa Genişliği (Market Breadth - {active_tf}):** İzlenen {total_coins} coinin **{bull_breadth} tanesi (%{breadth_pct:.0f})** pozitif yön bölgesinde.  \n"
        f"🔄 **ETH/BTC Altcoin Rotasyon Göstergesi:** {eth_rs_str}"
    )

    if len(ret_dict) >= 2:
        corr_df = pd.DataFrame(ret_dict).corr().round(2)
        high_corr_pairs = []
        cols_c = list(corr_df.columns)
        for i in range(len(cols_c)):
            for j in range(i + 1, len(cols_c)):
                c_val = float(corr_df.iloc[i, j])
                if c_val >= 0.80:
                    high_corr_pairs.append(f"**{cols_c[i]} – {cols_c[j]}** (r = {c_val:.2f})")
        if high_corr_pairs:
            st.warning(
                "⚠️ **Yüksek Portföy Korelasyon Uyarısı (Gizli Kaldıraç Riski):** "
                + ", ".join(high_corr_pairs)
                + " çiftleri birbirleriyle %80 üzeri korelasyonla hareket ediyor. Aynı anda aynı yönde işlem açmak kasa riskinizi katlayabilir (YTD)."
            )
        st.dataframe(corr_df, use_container_width=True)
    else:
        st.caption("Korelasyon matrisi için izleme listenizde en az 2 coin bulunmalıdır.")
