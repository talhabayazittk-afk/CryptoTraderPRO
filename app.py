"""
Interactive Streamlit Web Dashboard (v2.0):
Kurumsal Kripto Kantitatif Yön, Gerçek Taker Para Akışı (CVD), Hacim Profili (POC),
Derin Emir Defteri, Backtest Doğrulama & Çoklu Zaman Dilimi (15M, 1H, 4H, 1D) Terminali.

Çalıştırmak için:
    py -3.13 -m streamlit run app.py
"""
import html
import importlib
import inspect
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import src
import src.config
import src.data_fetcher
import src.indicators
import src.market_scanner
import src.patterns
import src.smart_money
import src.signals
import src.signal_ledger
import src.pipeline
import src.visualizer
import src.telegram_notifier
import src.x_publisher
import src.local_ai

# Hot-reload submodules automatically if an older module is still cached in a running Streamlit process
if (
    "symbol" not in inspect.signature(src.signals.SignalEngine.generate_forecast).parameters
    or "show_kalman_avwap" not in inspect.signature(src.visualizer.InteractiveChartVisualizer.create_multi_timeframe_figure).parameters
    or not getattr(src.visualizer, "_V6_0_READY", False)
    or not hasattr(src.telegram_notifier, "build_analysis_inline_keyboard")
    or not hasattr(src.telegram_notifier, "build_futures_radar_inline_keyboard")
    or not hasattr(src.telegram_notifier, "build_breakout_radar_inline_keyboard")
    or not hasattr(src.telegram_notifier, "build_watchlist_manage_inline_keyboard")
    or not hasattr(src.telegram_notifier, "format_breakout_radar_scan_telegram_html")
    or not hasattr(src.signals, "FuturesSetupReport")
    or not hasattr(src.signals.MarketForecast, "sr_breakout_guide_tr")
    or not hasattr(src.signals.MarketForecast, "plain_guidance_tr")
    or not hasattr(src.signals.MarketForecast, "contradiction_veto_tr")
    or not hasattr(src.signals.MarketForecast, "ai_report")
    or not hasattr(src.x_publisher, "publish_x_content")
    or not hasattr(src.x_publisher, "format_ledger_scorecard_x_post")
    or not hasattr(src.x_publisher, "format_market_hunter_x_post")
    or not hasattr(src.pipeline, "AnalysisPipeline")
    or not hasattr(src.pipeline.AnalysisPipeline, "attach_ai_summary")
    or not hasattr(src.signal_ledger, "SignalLedger")
    or not hasattr(src.market_scanner, "MarketWideHunter")
    or not hasattr(src.local_ai, "generate_ai_executive_summary")
    or not hasattr(src.local_ai, "build_unified_coin_analysis")
    or not hasattr(src.data_fetcher, "LiquidationMapIntel")
):
    for _mod in (
        src.config,
        src.data_fetcher,
        src.indicators,
        src.market_scanner,
        src.patterns,
        src.smart_money,
        src.signals,
        src.local_ai,
        src.signal_ledger,
        src.pipeline,
        src.visualizer,
        src.telegram_notifier,
        src.x_publisher,
        src,
    ):
        try:
            importlib.reload(_mod)
        except Exception:
            pass
    st.cache_data.clear()

from src.config import AnalysisConfig, ChartConfig, ExchangeConfig, IndicatorConfig, PatternConfig
from src.data_fetcher import CryptoDataFetcher, OrderFlowIntel
from src.indicators import TechnicalIndicators
from src.market_scanner import (
    MarketWideHunter,
    build_market_hunter_inline_keyboard,
    fmt_usd_compact,
    format_market_hunter_telegram_html,
)
from src.patterns import CandlestickPatternDetector, PATTERN_INFO_TR
from src.pipeline import AnalysisPipeline
from src.local_ai import (
    DEFAULT_OLLAMA_MODEL,
    build_ai_summary_inline_keyboard,
    build_unified_coin_analysis,
    check_ollama_status,
    format_ai_summary_telegram_html,
    format_unified_analysis_telegram_html,
    generate_ai_executive_summary,
)
from src.signal_ledger import SignalLedger, format_ledger_telegram_html
from src.signals import MarketForecast, SignalEngine
from src.telegram_notifier import (
    build_analysis_inline_keyboard,
    build_coin_list_inline_keyboard,
    build_futures_radar_inline_keyboard,
    build_futures_setup_inline_keyboard,
    build_main_reply_keyboard,
    build_screener_inline_keyboard,
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
from src.x_publisher import (
    build_x_intent_url,
    copy_chart_png_to_windows_clipboard,
    format_breakout_radar_x_post,
    format_coin_analysis_x_post,
    format_futures_radar_x_post,
    format_futures_setup_x_post,
    format_ledger_scorecard_x_post,
    format_market_hunter_x_post,
    format_market_overview_x_post,
    format_screener_x_post,
    get_x_daily_post_count,
    is_x_configured,
    load_x_config,
    load_x_state,
    post_x_tweet,
    publish_x_content,
    save_x_config,
    save_x_state,
    x_weighted_length,
)


def _fallback_build_breakout_radar_inline_keyboard(entries: list, timeframe: str = "1H") -> dict:
    tf_up = timeframe.upper()
    tf_row = [
        {"text": f"✅ {t}" if t == tf_up else f"🚨 {t}", "callback_data": f"brk_scan:{t}"}
        for t in ("15M", "1H", "4H", "1D")
    ]
    rows = [tf_row]
    btn_row = []
    for r in entries[:8]:
        sym = str(r.get("symbol", "")).upper()
        if not sym:
            continue
        btn_row.append({"text": f"📊 {sym.replace('/USDT', '')}", "callback_data": f"an:{sym}:{tf_up}"})
        if len(btn_row) == 2:
            rows.append(btn_row)
            btn_row = []
    if btn_row:
        rows.append(btn_row)
    return {"inline_keyboard": rows}


def _fallback_format_breakout_radar_scan_telegram_html(entries: list, timeframe: str = "1H") -> str:
    tf_up = timeframe.upper()
    lines = [
        f"🚨 <b>DESTEK / DİRENÇ KIRILIM RADARI [{tf_up}]</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for r in entries[:10]:
        sym = str(r.get("symbol", ""))
        price = float(r.get("price", 0.0))
        fc = r.get("fc")
        p_fmt = ",.4f" if price < 10.0 else ",.2f"
        sr_status = getattr(fc, "sr_action_status_tr", "") or "Kırılım Bekleniyor"
        guide = getattr(fc, "sr_breakout_guide_tr", "")
        lines.append(f"• <b>{sym}</b> (<code>{format(price, p_fmt)} USDT</code>) — {sr_status}")
        if guide:
            lines.append(f"  ↳ <i>{guide}</i>")
    return "\n".join(lines)


build_breakout_radar_inline_keyboard = getattr(
    src.telegram_notifier,
    "build_breakout_radar_inline_keyboard",
    _fallback_build_breakout_radar_inline_keyboard,
)
format_breakout_radar_scan_telegram_html = getattr(
    src.telegram_notifier,
    "format_breakout_radar_scan_telegram_html",
    _fallback_format_breakout_radar_scan_telegram_html,
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
        .roadmap-banner {
            background: linear-gradient(95deg, rgba(15, 23, 42, 0.96) 0%, rgba(17, 24, 39, 0.92) 100%);
            border: 1px solid #334155;
            border-left: 5px solid #38BDF8;
            border-radius: 10px;
            padding: 12px 16px;
            margin-bottom: 14px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
            font-size: 13.5px;
            line-height: 1.55;
            color: #E2E8F0;
        }
        @media (max-width: 768px) {
            .block-container {
                padding-top: 0.6rem;
                padding-left: 0.45rem;
                padding-right: 0.45rem;
                max-width: 100%;
            }
            .kpi-value {
                font-size: 16.5px;
            }
            .kpi-card {
                padding: 10px 12px;
                margin-bottom: 8px;
                border-radius: 9px;
            }
            .roadmap-banner {
                padding: 10px 12px;
                font-size: 12.8px;
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
    _engine_version: str = "v13.0_phase3",
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, MarketForecast], OrderFlowIntel, str, Dict[str, float]]:
    """
    Canonical Phase 3 Single-Source-of-Truth Pipeline:
    Delegates directly to `AnalysisPipeline.run_coin_bundle` so Web UI, Telegram Bot, and X
    produce 100% identical indicators, cash-flow metrics, contradiction locks, and SQLite Ledger logs.
    """
    bundle = AnalysisPipeline.run_coin_bundle(
        symbol=symbol,
        exchange_id=exchange_id,
        timeframes=list(timeframes),
        limit=limit,
        btc_regime_scores=btc_regime_scores,
        btc_tf_data=btc_tf_data,
        sample_capital_usd=sample_capital_usd,
        risk_pct=risk_pct,
        allow_synthetic_fallback=False,
        enable_ledger=True,
    )
    return bundle.tf_data, bundle.tf_forecasts, bundle.order_flow, bundle.source_used, bundle.mtf_scores


# ---------------------------------------------------------------------------
# PERSISTENT SESSION STATE FOR DYNAMIC COIN WATCHLIST (SYNCED WITH TELEGRAM)
# ---------------------------------------------------------------------------
_disk_wl = load_watchlist()
if "watchlist" not in st.session_state or st.session_state.get("_last_disk_wl") != _disk_wl:
    st.session_state.watchlist = list(_disk_wl)
    st.session_state["_last_disk_wl"] = list(_disk_wl)

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
        "Analiz Edilecek Mum Sayısı (EMA 200 & İndikatör Isınması)",
        min_value=250,
        max_value=1000,
        value=500,
        step=50,
        help="EMA 200, Wilder RSI(14), ADX(14) ve SuperTrend değerlerinin TradingView ile birebir örtüşmesi için en az 500 mum önerilir.",
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
    st.markdown("### 🧠 Hibrit Yön & Lokal Yapay Zeka Motoru")
    ollama_online, ollama_models, resolved_ollama_model = check_ollama_status()
    enable_local_ai_chk = st.checkbox(
        "🧠 Lokal AI Desteğini Aktif Et (Kapalıysa Bağımsız Kantitatif Motor v10 Çalışır)",
        value=True,
        help="Açıkken lokal Ollama modeli ile Hibrit Yön & Çelişki kalibrasyonu yapar. Kapalıyken veya Ollama yokken kendi v10.0 Bağımsız Kantitatif Motoru tam kapasite analiz üretir.",
    )
    if ollama_online and enable_local_ai_chk:
        model_opts = ollama_models if ollama_models else [resolved_ollama_model]
        sel_idx = model_opts.index(resolved_ollama_model) if resolved_ollama_model in model_opts else 0
        selected_ollama_model = st.selectbox(
            "Aktif Lokal Ollama Modeli",
            options=model_opts,
            index=sel_idx,
        )
        st.caption(f"🟢 **Motor Modu:** Hibrit (`Kantitatif v10 + {selected_ollama_model}` — %100 Lokal & Ücretsiz)")
    else:
        selected_ollama_model = DEFAULT_OLLAMA_MODEL
        st.caption("⚙️ **Motor Modu:** Bağımsız Kantitatif Motor v10 (AI Olmadan Kendi Tam Kapasite Analizi)")

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
        value=bool(tg_state.get("send_chart_with_analysis", True)),
        help="Telegram analiz çıktıları grafik görseliyle birlikte gönderilir.",
    )
    radar_chk = st.checkbox(
        "📡 7/24 Otomatik Kırılım & Balina Radarı",
        value=bool(tg_state.get("radar_enabled", True)),
        help="Bot çalışırken izleme listenizdeki güçlü kırılım, balina girişi ve sıkışmaları otomatik bildirir.",
    )
    if (
        send_chart_chk != bool(tg_state.get("send_chart_with_analysis", True))
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
                "Akıllı Kripto Karar-Destek &amp; Radar Terminali (Varsayılan: 4H) bağlı.\n\n"
                "👇 <i>Alt menüdeki dokunmatik butonlardan veya aşağıdaki coin listesinden tek dokunuşla grafikli analiz başlatabilirsiniz:</i>",
                reply_markup=build_main_reply_keyboard(),
            )
            send_telegram_message(
                tg_token_input,
                tg_chat_input,
                "🪙 <b>Hızlı Coin Seçim Menüsü (4H):</b>",
                reply_markup=build_coin_list_inline_keyboard(st.session_state.watchlist, "4H"),
            )
            if ok_t:
                st.success("✅ Dokunmatik menü gitti!")
            else:
                st.warning(msg_t)

    st.markdown("---")
    st.markdown("### 🐦 X (Twitter) Otomatik Paylaşım Merkezi")
    x_cfg = load_x_config()
    x_state = load_x_state()

    with st.expander("ℹ️ X API Anahtarları Nasıl Alınır? (Ücretsiz)", expanded=False):
        st.markdown(
            """
            1. **[developer.x.com](https://developer.x.com/en/portal/dashboard)** adresinden ücretsiz bir Developer hesabı ve Proje/Uygulama açın.
            2. **User authentication settings** kısmından uygulama iznini **Read and Write** (Okuma ve Yazma) yapın.
            3. **Keys and tokens** sekmesinden:
               - **API Key and Secret** (Consumer Keys)
               - **Access Token and Secret** (Read & Write yetkili)
               kodlarını alıp aşağıdaki 4 kutuya yapıştırıp **💾 X Ayarlarını Kaydet** butonuna basın.
            """
        )

    x_api_key_in = st.text_input(
        "X API Key (Consumer Key)",
        value=x_cfg.get("api_key", ""),
        type="password",
        placeholder="Örn: aBcDeFg123...",
    )
    x_api_secret_in = st.text_input(
        "X API Secret (Consumer Secret)",
        value=x_cfg.get("api_secret", ""),
        type="password",
        placeholder="Örn: xYz987...",
    )
    x_acc_token_in = st.text_input(
        "X Access Token",
        value=x_cfg.get("access_token", ""),
        type="password",
        placeholder="Örn: 12345678-AbCd...",
    )
    x_acc_secret_in = st.text_input(
        "X Access Token Secret",
        value=x_cfg.get("access_token_secret", ""),
        type="password",
        placeholder="Örn: sEcReT123...",
    )

    x_mode_options = {
        "SHORT_280": "🐦 Tek Gönderi (≤280 Karakter + Grafik) [Ücretsiz/Standart X]",
        "THREAD": "🧵 2 Tweetlik Zincir / Flood (+ Grafik) [Standart X Detaylı]",
        "LONG_PREMIUM": "💎 X Premium Uzun Gönderi (+ Grafik)",
    }
    curr_x_mode = str(x_state.get("x_post_mode", "SHORT_280")).upper()
    if curr_x_mode not in x_mode_options:
        curr_x_mode = "SHORT_280"
    x_mode_sel = st.selectbox(
        "📝 X Paylaşım Formatı",
        options=list(x_mode_options.keys()),
        format_func=lambda k: x_mode_options[k],
        index=list(x_mode_options.keys()).index(curr_x_mode),
    )

    x_chart_chk = st.checkbox(
        "🖼️ X Gönderilerine Otomatik Grafik Görseli (PNG) Ekle",
        value=bool(x_state.get("x_attach_chart", True)),
        help="Telegram'da olduğu gibi X paylaşımlarına da koyu tema teknik analiz grafiğini otomatik yükler.",
    )
    x_radar_chk = st.checkbox(
        "📡 7/24 Otomatik X Kırılım & Balina Radarı Paylaşımı",
        value=bool(x_state.get("x_auto_radar_enabled", True)),
        help="Arka plan botu çalışırken tespit edilen güçlü direnç/destek kırılımlarını, tuzakları (SFP) ve balina hareketlerini grafikle birlikte otomatik olarak X hesabınızda paylaşır.",
    )
    x_sess_chk = st.checkbox(
        "🌅 Otomatik Seans Özeti X Paylaşımı (09:00 & 16:30)",
        value=bool(x_state.get("x_auto_session_bulletin", True)),
        help="Her gün 09:00 ve ABD açılışı 16:30'da küresel piyasa ve sıcak para akışı özetini X'te otomatik paylaşır.",
    )
    x_max_daily_in = st.slider(
        "Günlük Maksimum Otomatik X Gönderi Limiti",
        min_value=1,
        max_value=17,
        value=int(x_state.get("x_max_daily_posts", 15)),
        help="X Ücretsiz API katmanı 24 saatte ~17 gönderiye izin verir. Bu limit kotanızın dolmasını engeller.",
    )
    x_tags_in = st.text_input(
        "🏷️ Varsayılan X Etiketleri (Hashtag)",
        value=str(x_state.get("x_custom_hashtags", "#Kripto #Bitcoin")),
    )

    if (
        x_mode_sel != x_state.get("x_post_mode")
        or x_chart_chk != bool(x_state.get("x_attach_chart", True))
        or x_radar_chk != bool(x_state.get("x_auto_radar_enabled", True))
        or x_sess_chk != bool(x_state.get("x_auto_session_bulletin", True))
        or x_max_daily_in != int(x_state.get("x_max_daily_posts", 15))
        or x_tags_in != str(x_state.get("x_custom_hashtags", "#Kripto #Bitcoin"))
    ):
        x_state["x_post_mode"] = x_mode_sel
        x_state["x_attach_chart"] = x_chart_chk
        x_state["x_auto_radar_enabled"] = x_radar_chk
        x_state["x_auto_session_bulletin"] = x_sess_chk
        x_state["x_max_daily_posts"] = x_max_daily_in
        x_state["x_custom_hashtags"] = x_tags_in
        save_x_state(x_state)

    xb1, xb2 = st.columns(2)
    with xb1:
        if st.button("💾 X Ayarlarını Kaydet", use_container_width=True):
            if save_x_config(x_api_key_in, x_api_secret_in, x_acc_token_in, x_acc_secret_in):
                st.success("✅ X API Anahtarları kaydedildi!")
            else:
                st.error("X ayarları kaydedilemedi.")
    with xb2:
        if st.button("🧪 X Test Paylaşımı", use_container_width=True):
            save_x_config(x_api_key_in, x_api_secret_in, x_acc_token_in, x_acc_secret_in)
            test_cfg = {
                "api_key": x_api_key_in,
                "api_secret": x_api_secret_in,
                "access_token": x_acc_token_in,
                "access_token_secret": x_acc_secret_in,
            }
            now_hm_s = pd.Timestamp.now().strftime("%H:%M")
            test_tw = (
                f"🤖 Akıllı Kripto Karar-Destek & Kırılım Radarı Terminali X Bağlantısı Aktif! ({now_hm_s})\n"
                "📊 7/24 Otomatik Destek/Direnç Kırılım, Balina & Likidasyon Analizleri\n"
                "⚖️ YTD #Kripto #Bitcoin"
            )
            ok_xt, msg_xt, _ = post_x_tweet(test_tw, cfg=test_cfg)
            if ok_xt:
                st.success(msg_xt)
            else:
                st.markdown(msg_xt)

    x_ready_now = is_x_configured(
        {
            "api_key": x_api_key_in,
            "api_secret": x_api_secret_in,
            "access_token": x_acc_token_in,
            "access_token_secret": x_acc_secret_in,
        }
    )
    x_daily_used = get_x_daily_post_count(x_state)
    if x_ready_now:
        st.caption(
            f"🟢 **X API Durumu:** Bağlı / Hazır | **Bugün Paylaşılan:** `{x_daily_used}/{x_max_daily_in}` | **Otomatik Radar:** `{'AÇIK' if x_radar_chk else 'KAPALI'}`"
        )
    else:
        st.caption("⚪ **X API Durumu:** Anahtarlar henüz girilmedi.")

    x_hist = x_state.get("x_post_history", [])
    if x_hist:
        with st.expander(f"📜 Son Paylaşılan X Gönderileri ({len(x_hist)})", expanded=False):
            for h_item in x_hist[:8]:
                st.markdown(
                    f"- `{h_item.get('time', '')}` **{h_item.get('title', '')}** — [🔗 X'te Gör]({h_item.get('url', '#')})"
                )

    st.markdown("---")
    bot_alive, bot_pid = is_bot_running()
    if (
        not bot_alive
        and (tg_token_input.strip() or x_ready_now)
        and not st.session_state.get("bot_manually_stopped", False)
    ):
        save_telegram_config(tg_token_input, tg_chat_input)
        save_x_config(x_api_key_in, x_api_secret_in, x_acc_token_in, x_acc_secret_in)
        start_bot_background()
        bot_alive, bot_pid = is_bot_running()

    if bot_alive:
        st.caption(f"🟢 **7/24 Arka Plan Botu (Telegram + X Radar):** Çalışıyor (PID: `{bot_pid}`) | Aktif Alarm: `{len(tg_state.get('alarms', []))}`")
    else:
        st.caption("🔴 **7/24 Arka Plan Botu:** Şu An Kapalı (Otomatik Telegram & X Radarı için başlatın)")

    bot_c1, bot_c2 = st.columns(2)
    with bot_c1:
        if st.button("▶️ Botu Başlat", use_container_width=True):
            if not tg_token_input.strip() and not x_ready_now:
                st.warning("Önce Telegram Bot Token veya X API Anahtarlarınızı girip kaydedin.")
            else:
                st.session_state["bot_manually_stopped"] = False
                save_telegram_config(tg_token_input, tg_chat_input)
                save_x_config(x_api_key_in, x_api_secret_in, x_acc_token_in, x_acc_secret_in)
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

            df_4h = tf_data["4H"]
            fc_15m = tf_forecasts["15M"]
            fc_1h = tf_forecasts["1H"]
            fc_4h = tf_forecasts["4H"]
            fc_1d = tf_forecasts["1D"]

            last_close = float(df_4h["close"].iloc[-1])
            cmf_4h = float(df_4h["cmf"].iloc[-1])
            mtf_master = 0.15 * fc_15m.score + 0.25 * fc_1h.score + 0.35 * fc_4h.score + 0.25 * fc_1d.score

            def badge(score: float) -> str:
                if score >= 15:
                    return f"🟢 Yükselen ({score:+.0f})"
                if score <= -15:
                    return f"🔴 Düşen ({score:+.0f})"
                return f"🟡 Yatay ({score:+.0f})"

            flow_tag = (
                "🟢 Para Girişi"
                if cmf_4h > 0.04
                else ("🔴 Para Çıkışı" if cmf_4h < -0.04 else "⚪ Dengeli")
            )

            fut_4h = getattr(fc_4h, "futures_setup", None)
            if fut_4h and fut_4h.is_tradeable:
                fut_dir_icon = "🟢 LONG" if fut_4h.direction == "LONG" else "🔴 SHORT"
                fut_radar_tag = (
                    f"{fut_dir_icon} ({fut_4h.confidence_score:.0f}/100 - {fut_4h.confidence_grade}) | "
                    f"Giriş:{price_fmt(fut_4h.entry_price)} TP1:{price_fmt(fut_4h.tp1_price)} Stop:{price_fmt(fut_4h.stop_price)}"
                )
            elif fut_4h:
                fut_radar_tag = f"⛔ Girilmez (Riskli - Güven:{fut_4h.confidence_score:.0f}/100 {fut_4h.confidence_grade})"
            else:
                fut_radar_tag = "⛔ Hesaplanmadı"

            sup_tier_4h = getattr(fc_4h, "nearest_support_tier_tr", "🟢 Sıradan Destek")
            res_tier_4h = getattr(fc_4h, "nearest_resistance_tier_tr", "🔴 Sıradan Direnç")
            screener_rows.append({
                "_sort_ready": fc_4h.readiness_score_5,
                "_sort_whale": abs(fc_4h.whale_accumulation_score - 50.0),
                "_sort_master": abs(mtf_master),
                "_fut_tradeable": bool(fut_4h and fut_4h.is_tradeable),
                "_fut_conf": float(fut_4h.confidence_score) if fut_4h else 0.0,
                "_raw_price": last_close,
                "_fc_4h": fc_4h,
                "Coin": sym,
                "Fiyat (USDT)": f"{price_fmt(last_close)}",
                "24s Değişim": f"{order_flow.price_change_24h_pct:+.2f}%",
                "⚡ Vadeli İşlem Radarı (4S)": fut_radar_tag,
                "Onay": f"{fc_4h.readiness_score_5}/5",
                "15D Trend": badge(fc_15m.score),
                "1S Trend": badge(fc_1h.score),
                "4S Trend": badge(fc_4h.score),
                "1G Trend": badge(fc_1d.score),
                "Para Akışı (4S)": flow_tag,
                "🐋 Balina İzi": f"{fc_4h.whale_accumulation_score:.0f}/100",
                "Destek / Direnç": f"{sup_tier_4h}: {price_fmt(fc_4h.nearest_support)} / {res_tier_4h}: {price_fmt(fc_4h.nearest_resistance)}",
            })
        except Exception as exc:
            st.error(f"{sym} verisi alınırken hata oluştu: {exc}")

with st.expander("🌐 Çoklu Coin Tarama Tablosu & ⚡ Vadeli İşlem Radarı Özeti (4H — Açmak İçin Tıklayın)", expanded=False):
    if all_coin_results:
        magnet_sym, magnet_cmf = None, -999.0
        outflow_sym, outflow_cmf = None, 999.0
        bull_4h_count = 0
        tradeable_fut_count = 0
        for sym_g, (tfd_g, tffc_g, _, _) in all_coin_results.items():
            cmf_g = float(tfd_g["4H"]["cmf"].iloc[-1]) if "4H" in tfd_g else 0.0
            if cmf_g > magnet_cmf:
                magnet_cmf, magnet_sym = cmf_g, sym_g
            if cmf_g < outflow_cmf:
                outflow_cmf, outflow_sym = cmf_g, sym_g
            if "4H" in tffc_g and tffc_g["4H"].score >= 15.0:
                bull_4h_count += 1
            if "4H" in tffc_g and getattr(tffc_g["4H"], "futures_setup", None) and tffc_g["4H"].futures_setup.is_tradeable:
                tradeable_fut_count += 1

        st.markdown(
            f"**🌍 Piyasa Özeti (4H):** 4 Saatlikte **{bull_4h_count}/{len(all_coin_results)}** coin yükselişte &nbsp;|&nbsp; "
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
                msg_html = format_screener_telegram_html(screener_rows, "4H")
                kb_sc = build_screener_inline_keyboard(screener_rows, "4H", False)
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
                        "fc": r["_fc_4h"],
                    }
                    for r in screener_rows
                ]
                msg_brk_radar = format_breakout_radar_scan_telegram_html(brk_entries, "4H")
                kb_brk_radar = build_breakout_radar_inline_keyboard(brk_entries, "4H")
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
                        "fc": r["_fc_4h"],
                    }
                    for r in screener_rows
                ]
                msg_fut_radar = format_futures_radar_scan_telegram_html(radar_entries, "4H")
                kb_fut_radar = build_futures_radar_inline_keyboard(radar_entries, "4H")
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

        x_sc1, x_sc2, x_sc3 = st.columns([1, 1, 1])
        with x_sc1:
            if st.button("🐦 Tarama Raporunu X'te Paylaş", use_container_width=True):
                tweets_sc = format_screener_x_post(screener_rows, "4H", False)
                top_sym = screener_rows[0]["Coin"]
                top_df, top_fcs, _, _ = all_coin_results[top_sym]
                top_png = generate_telegram_chart_png(top_df["4H"], top_fcs["4H"], top_sym, "4H", include_futures_levels=False)
                ok_xs, msg_xs, _ = publish_x_content(tweets_sc, photo_bytes=top_png, title="Çoklu Coin Tarama (4H)", symbol="TARAMA")
                if ok_xs:
                    st.success(msg_xs)
                else:
                    st.warning(msg_xs)
        with x_sc2:
            if st.button("🐦 Kırılım Radarını X'te Paylaş", use_container_width=True):
                brk_entries_x = [
                    {"symbol": r["Coin"], "price": r["_raw_price"], "fc": r["_fc_4h"]}
                    for r in screener_rows
                ]
                tweets_brk = format_breakout_radar_x_post(brk_entries_x, "4H")
                top_sym = screener_rows[0]["Coin"]
                top_df, top_fcs, _, _ = all_coin_results[top_sym]
                top_png = generate_telegram_chart_png(top_df["4H"], top_fcs["4H"], top_sym, "4H", include_futures_levels=False)
                ok_xb, msg_xb, _ = publish_x_content(tweets_brk, photo_bytes=top_png, title="Kırılım Radarı (4H)", symbol="KIRILIM")
                if ok_xb:
                    st.success(msg_xb)
                else:
                    st.warning(msg_xb)
        with x_sc3:
            if st.button("🐦 Vadeli İşlem Radarını X'te Paylaş", use_container_width=True):
                fut_entries_x = [
                    {"symbol": r["Coin"], "price": r["_raw_price"], "fc": r["_fc_4h"]}
                    for r in screener_rows
                ]
                tweets_fut_r = format_futures_radar_x_post(fut_entries_x, "4H")
                top_sym = screener_rows[0]["Coin"]
                top_df, top_fcs, _, _ = all_coin_results[top_sym]
                top_png = generate_telegram_chart_png(top_df["4H"], top_fcs["4H"], top_sym, "4H", include_futures_levels=True)
                ok_xf, msg_xf, _ = publish_x_content(tweets_fut_r, photo_bytes=top_png, title="Vadeli İşlem Radarı (4H)", symbol="VADELİ")
                if ok_xf:
                    st.success(msg_xf)
                else:
                    st.warning(msg_xf)

# ---------------------------------------------------------------------------
# MARKET-WIDE TOP 80 REAL SPOT CASH-FLOW & SQUEEZE HUNTER
# ---------------------------------------------------------------------------
with st.expander("🌐 Tüm Piyasayı Tarayan 'Balina Girişi & Sıkışma Avcısı' (Top 80 Likit Coin — %100 Gerçek Spot Taker Verisi)", expanded=False):
    st.caption(
        "İzleme listenizde olmasa bile borsadaki en likit **USDT** paritelerinin kapanmış 12-sütunlu **Spot + USD-M Vadeli** mumlarını tarar; "
        "**gerçek agresif Spot nakit girişi (`Taker Buy - Sell $`)**, **Z-Skor anomalisi**, **volatilite sıkışması (Squeeze)** ve **kaldıraç köpüğü filtresini** geçen fırsatları yakalar."
    )
    hc1, hc2, hc3, hc4 = st.columns([1.1, 1.1, 1.3, 1.8])
    with hc1:
        hunter_tf = st.selectbox("Periyot", options=["1H", "4H"], index=0, key="hunter_tf_sel")
    with hc2:
        hunter_uni = st.selectbox("Taranacak Evren", options=[60, 80, 100], index=1, format_func=lambda x: f"Top {x} Likit Coin", key="hunter_uni_sel")
    with hc3:
        hunter_min_vol_m = st.selectbox("Min. 24S Hacim", options=[2.5, 5.0, 10.0, 25.0], index=0, format_func=lambda x: f">= ${x:g}M (24S)", key="hunter_vol_sel")
    with hc4:
        hunter_view_mode = st.selectbox(
            "Görünüm Filtresi",
            options=["Doğrulanmış En Güçlü Adaylar", "Sadece Liste Dışı Yeni Keşifler (🆕)", "Taranan Tüm Piyasa Tablosu"],
            index=0,
            key="hunter_view_sel",
        )

    h_act1, h_act2 = st.columns([2, 3])
    with h_act1:
        run_hunter_btn = st.button(f"🔎 Top {hunter_uni} Piyasayı Şimdi Canlı Tara (~4 sn)", type="primary", use_container_width=True)
    with h_act2:
        st.caption("💡 Stabilcoinler, kaldıraçlı tokenlar ve sığ tahtalar otomatik elenir; yalnızca kapanmış mum verisi kullanılır.")

    if run_hunter_btn:
        with st.spinner(f"Borsadaki en likit {hunter_uni} USDT tahtasının gerçek Spot + Vadeli Taker para akışları taranıyor..."):
            try:
                st.session_state["market_hunter_report"] = MarketWideHunter.scan_market(
                    timeframe=hunter_tf.lower(),
                    universe_size=int(hunter_uni),
                    min_quote_vol_usd=float(hunter_min_vol_m) * 1_000_000.0,
                    top_n=15,
                    watchlist=st.session_state.watchlist,
                    force_refresh=True,
                )
            except Exception as h_err:
                st.error(f"Piyasa Avcısı taraması sırasında bağlantı hatası oluştu: {h_err}")

    hunter_rep = st.session_state.get("market_hunter_report")
    if hunter_rep is not None:
        # Refresh watchlist membership dynamically
        wl_curr_set = {s.upper() for s in st.session_state.watchlist}
        for c_item in hunter_rep.all_ranked:
            c_item.in_watchlist = c_item.symbol.upper() in wl_curr_set

        tf_win_lbl = "Son 4 Saat" if hunter_rep.timeframe == "1H" else "Son 16 Saat"
        hk1, hk2, hk3, hk4 = st.columns(4)
        breadth_p = (hunter_rep.inflow_positive_count / max(1, hunter_rep.universe_scanned)) * 100.0
        hk1.metric(
            f"Top {hunter_rep.universe_scanned} Net Spot ({tf_win_lbl})",
            fmt_usd_compact(hunter_rep.total_top_spot_net_4bar_usd),
            f"24S: {fmt_usd_compact(hunter_rep.total_top_spot_net_24h_usd)}",
        )
        hk2.metric(
            "Pozitif Spot Giriş Genişliği",
            f"{hunter_rep.inflow_positive_count} / {hunter_rep.universe_scanned} Coin",
            f"%{breadth_p:.0f} Alıcılı Tahta",
        )
        hk3.metric(
            "Volatilite Sıkışması (Squeeze)",
            f"{hunter_rep.squeezing_count} Coin",
            f"{hunter_rep.timeframe} Periyotta Sıkışan",
        )
        hk4.metric(
            "Köpüksüz Nitelikli Aday",
            f"{len(hunter_rep.top_picks)} Coin",
            f"Kaynak: {hunter_rep.exchange_source}",
        )

        if hunter_view_mode == "Doğrulanmış En Güçlü Adaylar":
            display_cands = list(hunter_rep.top_picks)
        elif hunter_view_mode == "Sadece Liste Dışı Yeni Keşifler (🆕)":
            display_cands = [c for c in hunter_rep.top_picks if not c.in_watchlist]
        else:
            display_cands = list(hunter_rep.all_ranked)

        if not display_cands:
            st.warning(
                "🛑 Seçili filtrede (Gerçek Spot Nakit Girişi + Köpüksüz Vadeli + Sağlıklı Yapı) tüm şartları aynı anda sağlayan aday bulunamadı. "
                "Piyasa genelini görmek için yukarıdan **'Taranan Tüm Piyasa Tablosu'** görünümünü seçebilirsiniz."
            )
        else:
            hunter_df_rows = []
            for c in display_cands:
                best_z = max(c.delta_zscore, c.flow_impulse_z)
                hunter_df_rows.append(
                    {
                        "Liste": "📌 Listede" if c.in_watchlist else "🆕 Yeni Keşif",
                        "Coin": c.symbol,
                        "Avcı Skoru": f"{c.hunter_score:.0f}/100",
                        "Sinyal Sınıfı": c.signal_badge_tr,
                        "Fiyat": price_fmt(c.price),
                        "24S Değişim": f"{c.change_24h_pct:+.2f}%",
                        f"Gerçek Spot ({tf_win_lbl})": fmt_usd_compact(c.spot_delta_4bar_usd),
                        "24S Net Spot": fmt_usd_compact(c.spot_delta_24h_usd),
                        "Nakit Z-Skor": f"{best_z:+.2f}σ",
                        "Taker Alıcı %": f"%{c.spot_buy_ratio_4bar_pct:.1f}",
                        "Göreli Hacim": f"{c.rvol:.2f}x",
                        "Sıkışma": f"%{c.squeeze_energy_pct:.0f}" + (" 🔥" if c.is_squeezing else ""),
                        "Fonlama": f"{c.funding_rate_pct:+.4f}%" if c.funding_rate_pct is not None else "Spot",
                        "Spot vs Vadeli": c.spot_perp_quality_tr,
                        "Kırılım Direnci": price_fmt(c.breakout_trigger_price),
                        "Destek / İptal": price_fmt(c.support_invalid_price),
                    }
                )
            st.dataframe(pd.DataFrame(hunter_df_rows), use_container_width=True, hide_index=True)

            # 1-Click Add Unlisted Discoveries to Watchlist
            unlisted_options = [c.symbol for c in display_cands if not c.in_watchlist]
            if unlisted_options:
                add_col1, add_col2 = st.columns([3, 1.4])
                with add_col1:
                    picked_to_add = st.multiselect(
                        "🆕 Keşfedilen coinlerden izleme listenize (`watchlist.json`) eklemek istediklerinizi seçin:",
                        options=unlisted_options,
                        default=unlisted_options[: min(2, len(unlisted_options))],
                        key="hunter_add_ms",
                    )
                with add_col2:
                    st.markdown("<div style='height:26px;'></div>", unsafe_allow_html=True)
                    if st.button("➕ Seçilenleri İzleme Listeme Ekle", use_container_width=True):
                        added_now = []
                        for s_new in picked_to_add:
                            if s_new not in st.session_state.watchlist:
                                st.session_state.watchlist.append(s_new)
                                added_now.append(s_new)
                        if added_now:
                            save_watchlist(st.session_state.watchlist)
                            st.session_state["_last_disk_wl"] = list(st.session_state.watchlist)
                            st.success(f"✅ {', '.join(added_now)} izleme listenize eklendi! Sayfa yenilendiğinde grafik inceleyicide görünecektir.")
                            st.rerun()

        hsh1, hsh2 = st.columns(2)
        with hsh1:
            if st.button("📲 Top 80 Piyasa Avcısı Raporunu Telegram'a Gönder", use_container_width=True):
                only_un_flag = hunter_view_mode == "Sadece Liste Dışı Yeni Keşifler (🆕)"
                html_h_tg = format_market_hunter_telegram_html(hunter_rep, only_unlisted=only_un_flag)
                kb_h_tg = build_market_hunter_inline_keyboard(hunter_rep, only_unlisted=only_un_flag)
                ok_htg, msg_htg = send_telegram_message(tg_token_input, tg_chat_input, html_h_tg, reply_markup=kb_h_tg)
                if ok_htg:
                    st.success(msg_htg)
                else:
                    st.warning(msg_htg)
        with hsh2:
            if st.button("🐦 Top 80 Piyasa Avcısı Raporunu X'te Paylaş", use_container_width=True):
                tweets_hx = format_market_hunter_x_post(hunter_rep)
                png_hx = b""
                if hunter_rep.top_picks:
                    top_pick_sym = hunter_rep.top_picks[0].symbol
                    if top_pick_sym in all_coin_results:
                        t_df, t_fcs, _, _ = all_coin_results[top_pick_sym]
                        tf_k = hunter_rep.timeframe if hunter_rep.timeframe in t_df else "4H"
                        png_hx = generate_telegram_chart_png(t_df[tf_k], t_fcs[tf_k], top_pick_sym, tf_k, include_futures_levels=False)
                ok_hx, msg_hx, _ = publish_x_content(
                    tweets_hx,
                    photo_bytes=png_hx,
                    title=f"Top {hunter_rep.universe_scanned} Piyasa Avcısı ({hunter_rep.timeframe})",
                    symbol="AVCI",
                )
                if ok_hx:
                    st.success(msg_hx)
                else:
                    st.markdown(msg_hx)

# ---------------------------------------------------------------------------
# PHASE 3: LIVE SQLITE SIGNAL SCORECARD & SELF-VERIFICATION LEDGER
# ---------------------------------------------------------------------------
with st.expander("📊 Canlı Sinyal Karnesi & Şeffaf Öz-Doğrulama Defteri (SQLite — %0.10 Komisyon & Kayma Dahil)", expanded=False):
    ledger_inst = SignalLedger()
    sc_live = ledger_inst.get_scorecard(days=30, limit_recent=20)
    st.caption(
        "Sistem tarafından üretilen gerçek zamanlı kurulumlar (`1H`, `4H`, `1D`) SQLite (`signal_ledger.db`) defterine işlenir "
        "ve takip eden borsa mumlarının iğnelerine göre (%0.10 toplam komisyon/kayma düşülerek) otomatik doğrulanır."
    )
    lc1, lc2, lc3, lc4, lc5 = st.columns(5)
    lc1.metric("Toplam Takip (30G)", f"{sc_live.total_tracked}", f"Açık: {sc_live.open_count}")
    lc2.metric(
        "Gerçek Başarı Oranı",
        f"%{sc_live.win_rate_pct:.1f}" if sc_live.closed_count > 0 else "Bekleniyor",
        f"{sc_live.wins_count}K / {sc_live.losses_count}Z",
    )
    lc3.metric(
        "Toplam Net Getiri (R)",
        f"{sc_live.cumulative_net_r:+.2f}R" if sc_live.closed_count > 0 else "0.00R",
        f"Ort: {sc_live.avg_r_per_trade:+.2f}R",
    )
    lc4.metric("Profit Factor", f"{sc_live.profit_factor:.2f}" if sc_live.closed_count > 0 else "—")
    lc5.metric("Maks. Düşüş (DD)", f"-{sc_live.max_drawdown_r:.2f}R" if sc_live.closed_count > 0 else "0.00R")

    if sc_live.recent_signals:
        ledger_rows_ui = []
        for s_row in sc_live.recent_signals:
            st_raw = str(s_row.get("status", "OPEN"))
            st_badge = (
                "🚀 TP2 KAZANÇ"
                if st_raw == "TP2_WIN"
                else (
                    "✅ TP1 + Başabaş"
                    if st_raw == "TP1_PARTIAL_WIN"
                    else ("🛑 STOP" if st_raw == "STOP_LOSS" else ("⏳ AÇIK TAKİPTE" if st_raw == "OPEN" else "⌛ SÜRE DOLDU"))
                )
            )
            ledger_rows_ui.append(
                {
                    "Tarih (UTC)": s_row.get("created_at_utc", ""),
                    "Coin": s_row.get("symbol", ""),
                    "Periyot": s_row.get("timeframe", ""),
                    "Yön": s_row.get("direction", ""),
                    "Giriş": price_fmt(float(s_row.get("entry_price", 0.0))),
                    "TP1": price_fmt(float(s_row.get("tp1_price", 0.0))),
                    "TP2": price_fmt(float(s_row.get("tp2_price", 0.0))),
                    "Stop": price_fmt(float(s_row.get("stop_price", 0.0))),
                    "Güven": f"{float(s_row.get('confidence_score', 0.0)):.0f}/100",
                    "Durum": st_badge,
                    "Net R (Komisyon Dahil)": (
                        f"{float(s_row.get('net_r_multiple', 0.0)):+.2f}R"
                        if st_raw != "OPEN"
                        else ("TP1 Alındı 🔒" if int(s_row.get("tp1_hit", 0)) == 1 else "Devam Ediyor")
                    ),
                }
            )
        st.dataframe(pd.DataFrame(ledger_rows_ui), use_container_width=True, hide_index=True)
    else:
        st.info("ℹ️ Henüz SQLite öz-doğrulama defterine kaydedilmiş kurulum bulunmuyor; kriterleri karşılayan ilk canlı kurulumda otomatik başlar.")

    lbtn1, lbtn2 = st.columns(2)
    with lbtn1:
        if st.button("📲 Canlı Sinyal Karnesini Telegram'a Gönder", use_container_width=True):
            ok_lg, msg_lg = send_telegram_message(
                tg_token_input,
                tg_chat_input,
                format_ledger_telegram_html(sc_live),
                reply_markup=build_main_reply_keyboard(),
            )
            if ok_lg:
                st.success(msg_lg)
            else:
                st.warning(msg_lg)
    with lbtn2:
        if st.button("🐦 Şeffaf Performans Karnesini X'te Paylaş", use_container_width=True):
            tweets_lg = format_ledger_scorecard_x_post(sc_live)
            ok_xlg, msg_xlg, _ = publish_x_content(tweets_lg, photo_bytes=b"", title="Canlı Sinyal Karnesi", symbol="KARNE")
            if ok_xlg:
                st.success(msg_xlg)
            else:
                st.markdown(msg_xlg)

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
        index=2,
        horizontal=True,
        help="Varsayılan: 4H (4 Saat) | 15M: 15 Dakika | 1H: 1 Saat | 1D: 1 Gün",
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
            df=df_active,
            order_flow=order_flow,
        )
        kb_an = build_analysis_inline_keyboard(active_symbol, active_tf)
        png_bytes = generate_telegram_chart_png(
            df_active,
            fc_active,
            active_symbol,
            active_tf,
            include_futures_levels=False,
        )
        if png_bytes:
            ok_c, msg_c = send_telegram_photo(
                tg_token_input,
                tg_chat_input,
                png_bytes,
                caption_html=coin_html,
                reply_markup=kb_an,
            )
        else:
            ok_c, msg_c = send_telegram_message(
                tg_token_input,
                tg_chat_input,
                coin_html,
                reply_markup=kb_an,
            )
        if ok_c:
            st.success(msg_c)
        else:
            st.warning(msg_c)
    if st.button(f"🐦 {active_symbol} ({active_tf}) X'te Paylaş (Grafikli)", use_container_width=True):
        mtf_sc_x = {k: tf_forecasts[k].score for k in ("15M", "1H", "4H", "1D") if k in tf_forecasts}
        tweets_coin = format_coin_analysis_x_post(
            fc=fc_active,
            symbol=active_symbol,
            timeframe=active_tf,
            current_price=last_price,
            mtf_scores=mtf_sc_x,
        )
        png_bytes_x = generate_telegram_chart_png(
            df_active,
            fc_active,
            active_symbol,
            active_tf,
            include_futures_levels=False,
        )
        ok_xc, msg_xc, _ = publish_x_content(
            tweets=tweets_coin,
            photo_bytes=png_bytes_x,
            title=f"{active_symbol} ({active_tf}) Teknik Analiz",
            symbol=active_symbol,
        )
        if ok_xc:
            st.success(msg_xc)
        else:
            st.markdown(msg_xc)

with st.expander(f"🐦 {active_symbol} ({active_tf}) X (Twitter) Gönderi Önizlemesi & Özelleştirerek Paylaş", expanded=False):
    mtf_sc_prev = {k: tf_forecasts[k].score for k in ("15M", "1H", "4H", "1D") if k in tf_forecasts}
    preview_tweets = format_coin_analysis_x_post(
        fc=fc_active,
        symbol=active_symbol,
        timeframe=active_tf,
        current_price=last_price,
        mtf_scores=mtf_sc_prev,
    )
    default_tw_text = "\n\n---\n\n".join(preview_tweets) if len(preview_tweets) > 1 else preview_tweets[0]
    custom_tw_text = st.text_area(
        "Paylaşılacak X Metni (İsterseniz düzenleyebilirsiniz; '---' ile ayrılan bölümler Zincir/Flood modunda ayrı tweet olarak atılır):",
        value=default_tw_text,
        height=175,
        key=f"x_custom_tw_{active_symbol}_{active_tf}",
    )
    first_part = custom_tw_text.split("---")[0].strip()
    w_len = x_weighted_length(first_part)
    st.caption(
        f"📏 **1. Tweet Karakter Ağırlığı:** `{w_len} / 280` "
        f"({'🟢 Standart X Limitine Uygun' if w_len <= 280 else '⚠️ 280 Karakteri Aşıyor (Otomatik Kısaltılır veya X Premium Gerekir)'})"
    )
    x_pcol1, x_pcol2 = st.columns(2)
    with x_pcol1:
        if st.button(f"🚀 API ile {active_symbol} ({active_tf}) Şimdi X'te Paylaş", use_container_width=True):
            parts_custom = [p.strip() for p in custom_tw_text.split("---") if p.strip()]
            png_custom = generate_telegram_chart_png(
                df_active,
                fc_active,
                active_symbol,
                active_tf,
                include_futures_levels=False,
            )
            ok_cust, msg_cust, _ = publish_x_content(
                tweets=parts_custom,
                photo_bytes=png_custom,
                title=f"{active_symbol} ({active_tf}) Özel Analiz",
                symbol=active_symbol,
            )
            if ok_cust:
                st.success(msg_cust)
            else:
                st.info(msg_cust)
    with x_pcol2:
        if st.button(f"🆓 Ücretsiz X'te Hazırla + Grafiği Panoya Kopyala (Ctrl+V)", use_container_width=True):
            png_free = generate_telegram_chart_png(
                df_active,
                fc_active,
                active_symbol,
                active_tf,
                include_futures_levels=False,
            )
            clip_ok = copy_chart_png_to_windows_clipboard(png_free)
            intent_u = build_x_intent_url(first_part)
            st.success(
                f"✅ {'Grafik görseli Windows panonuza (Ctrl+V) kopyalandı! ' if clip_ok else ''}"
                f"Şimdi 👉 **[🐦 Buraya Tıklayarak X Gönderi Ekranını Hazır Metinle Açın]({intent_u})** ve **`Ctrl+V`** tuşuna basıp grafiği yapıştırarak ücretsiz paylaşın!"
            )

# ---------------------------------------------------------------------------
# 1. COMPACT STATUS & MULTI-TIMEFRAME ALIGNMENT BAR
# ---------------------------------------------------------------------------
data_health_lbl = getattr(fc_active, "data_health_status_tr", "✅ Doğrulanmış Canlı Borsa Verisi")
spot_src_lbl = getattr(order_flow, "spot_source", "") or source_used
fut_src_lbl = getattr(order_flow, "futures_source", "") or "Yok"
macro_liq_lbl = getattr(fc_active, "macro_liquidity_tr", "")
st.caption(
    f"🛡️ **Veri Sağlığı & Kaynak Denetimi:** `{data_health_lbl}` &nbsp;|&nbsp; "
    f"**Spot:** `{spot_src_lbl}` &nbsp;|&nbsp; **Küresel Vadeli:** `{fut_src_lbl}`"
    + (f" &nbsp;|&nbsp; **🌍 Makro Pusula:** {macro_liq_lbl}" if macro_liq_lbl and macro_liq_lbl != "Makro Likidite Dengeli" else "")
)
contradiction_veto_act = getattr(fc_active, "contradiction_veto_tr", "")
if contradiction_veto_act:
    st.warning(f"**Çoklu Zaman Dilimi & Para Akışı Çelişki Kilidi Devrede:** {contradiction_veto_act}")

trend_state_act = getattr(fc_active, "trend_state", "")
swing_struct_act = getattr(fc_active, "swing_structure_tr", "Yatay Kanal")
candle_anat_act = getattr(fc_active, "candle_anatomy_tr", "")
plain_guide_act = getattr(fc_active, "plain_guidance_tr", "")

if trend_state_act == "UPTREND" or (not trend_state_act and fc_active.score >= 15):
    score_col = "#00E676"
    main_trend_title = "📈 YÜKSELEN TREND"
    main_trend_desc = f"{swing_struct_act} — Alıcılar baskın"
elif trend_state_act == "DOWNTREND" or (not trend_state_act and fc_active.score <= -15):
    score_col = "#FF5252"
    main_trend_title = "📉 DÜŞEN TREND"
    main_trend_desc = f"{swing_struct_act} — Satıcılar baskın"
else:
    score_col = "#FACC15"
    main_trend_title = "⚖️ YATAY / KARARSIZ TREND"
    main_trend_desc = f"{swing_struct_act} — Kırılım yönü bekleniyor"

mtf_badges_html = []
for tf_k in ("15M", "1H", "4H", "1D"):
    fc_tf_k = tf_forecasts[tf_k]
    sc_k = fc_tf_k.score
    t_st_k = getattr(fc_tf_k, "trend_state", "")
    if t_st_k == "UPTREND" or (not t_st_k and sc_k >= 15):
        c_k, lbl_k = "#00E676", "📈 Yükselen"
    elif t_st_k == "DOWNTREND" or (not t_st_k and sc_k <= -15):
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
    <div style="background:#111827; border:1px solid #1E293B; border-left:5px solid {score_col}; border-radius:10px; padding:10px 16px; margin-bottom:10px; display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:10px;">
        <div style="font-size:14px;">
            <b style="color:#F8FAFC; font-size:15px;">{active_symbol} ({active_tf}) <span style="color:#64748B; font-size:12px;">[{source_used}]</span></b>
            <span style="color:#E2E8F0; font-weight:700; margin-left:8px;">Fiyat: {price_fmt(last_price)} USDT</span>
            &nbsp;|&nbsp;
            <span style="color:{score_col}; font-weight:800;">{main_trend_title} ({fc_active.score:+.0f}/100)</span>
        </div>
        <div>
            {"".join(mtf_badges_html)}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 1b. UNIFIED HARMONIZED TECHNICAL, CASH-FLOW & REAL LIQUIDATION ANALYSIS
#     (Single clean output — strictly chart & real exchange data, zero clutter)
# ---------------------------------------------------------------------------
mtf_scores_act = {k: tf_forecasts[k].score for k in ("15M", "1H", "4H", "1D") if k in tf_forecasts}
unified_active = build_unified_coin_analysis(
    symbol=active_symbol,
    timeframe=active_tf,
    df=df_active,
    fc=fc_active,
    mtf_scores=mtf_scores_act,
    order_flow=order_flow,
)

u_col = unified_active.accent_color
u_liq_col = (
    "#FF5252"
    if unified_active.expected_first_liq_side == "LONG_LIQ"
    else ("#00E676" if unified_active.expected_first_liq_side == "SHORT_LIQ" else "#FACC15")
)

st.markdown(
    f"""
    <div style="background:linear-gradient(180deg, #111827 0%, #0B1220 100%); border:1px solid #1E293B; border-left:5px solid {u_col}; border-radius:12px; padding:16px 20px; margin-bottom:10px; box-shadow:0 4px 16px rgba(0,0,0,0.35);">
        <div style="font-size:16.5px; font-weight:800; color:{u_col}; margin-bottom:10px;">
            {html.escape(unified_active.trend_headline_tr)}
        </div>
        <div style="font-size:13.6px; color:#E2E8F0; line-height:1.78;">
            <div><span style="color:#94A3B8;">{html.escape(unified_active.trend_breakout_label_tr)} =</span> <b style="color:#38BDF8;">{html.escape(unified_active.trend_breakout_value_tr)}</b></div>
            <div><span style="color:#94A3B8;">Destek =</span> <b style="color:#34D399;">{html.escape(unified_active.support_tr)}</b></div>
            <div><span style="color:#94A3B8;">Güçlü destek =</span> <b style="color:#00E676;">{html.escape(unified_active.strong_support_tr)}</b></div>
            <div><span style="color:#94A3B8;">Direnç =</span> <b style="color:#FB7185;">{html.escape(unified_active.resistance_tr)}</b></div>
            <div><span style="color:#94A3B8;">Güçlü Direnç =</span> <b style="color:#FF5252;">{html.escape(unified_active.strong_resistance_tr)}</b></div>
        </div>
        <div style="border-top:1px solid #1E293B; margin:10px 0; padding-top:10px; font-size:13.5px; color:#E2E8F0; line-height:1.78;">
            <div><span style="color:#94A3B8;">Coinin para giriş çıkış seviyeleri =</span> <b>{html.escape(unified_active.money_flow_tr)}</b></div>
            <div><span style="color:#94A3B8;">Likiditasyon seviyeleri =</span> <b>{html.escape(unified_active.liquidation_levels_tr)}</b></div>
            <div><span style="color:#94A3B8;">Önce almasını beklediğin likiditasyon seviyesi/olasılık =</span> <b style="color:{u_liq_col};">{html.escape(unified_active.expected_first_liq_tr)}</b></div>
        </div>
        <div style="border-top:1px solid #1E293B; margin-top:10px; padding-top:10px; font-size:13.6px; color:#F1F5F9; line-height:1.68;">
            <div><b style="color:#38BDF8;">Teknik ne diyor ?</b> <b>{html.escape(unified_active.technical_verdict_tr)}</b></div>
            <div style="margin-top:4px; color:#CBD5E1;"><b style="color:#94A3B8;">Açıklama:</b> {html.escape(unified_active.explanation_tr)}</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

ua_b1, ua_b2, _ = st.columns([1.4, 1.4, 3.2])
with ua_b1:
    if st.button("📲 Analizi Telegram'a Gönder", key=f"btn_ua_tg_{active_symbol}_{active_tf}", use_container_width=True):
        ok_utg, msg_utg = send_telegram_message(
            tg_token_input,
            tg_chat_input,
            format_unified_analysis_telegram_html(unified_active),
            reply_markup=build_analysis_inline_keyboard(active_symbol, active_tf),
        )
        if ok_utg:
            st.success(msg_utg)
        else:
            st.warning(msg_utg)
with ua_b2:
    with st.popover("📋 Düz Metin (Kopyala)", use_container_width=True):
        st.code(unified_active.plain_text_tr, language=None)

fut_active = getattr(fc_active, "futures_setup", None)
st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 3. CLEAN CHART PRESET BAR + OPTIONAL EXPANDER FOR ADVANCED SETTINGS/DETAILS
# ---------------------------------------------------------------------------
preset_mode = st.radio(
    "🎛️ Grafik Görünümü Seçin:",
    options=[
        "✨ Sade Trend & Destek/Direnç (Önerilen)",
        "🧱 Destek, Direnç & Maliyet Odaklı",
        "🧲 Mıknatıs & Likidasyon Odaklı",
        "🔬 Tüm Katmanlar & Vadeli Hedef Kutusu",
    ],
    index=0,
    horizontal=True,
)

is_clean = preset_mode.startswith("✨")
is_sr_focus = preset_mode.startswith("🧱")
is_smc_focus = preset_mode.startswith("🧲")
is_all = preset_mode.startswith("🔬")
default_proj_box = bool(is_all)

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
        show_liq_pools = st.checkbox("🧲 Likidasyon Seviyeleri (Canlı Veri)", value=(is_clean or is_smc_focus or is_all), key=f"liq_{preset_mode}")
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
        if fut_active is not None:
            if fut_active.is_tradeable:
                st.markdown(
                    f"**⚡ Vadeli İşlem Planı ({fut_active.direction} · Güven {fut_active.confidence_score:.0f}/100):** "
                    f"Giriş `{price_fmt(fut_active.entry_price)}` | Stop `{price_fmt(fut_active.stop_price)}` | "
                    f"TP1 `{price_fmt(fut_active.tp1_price)}` | TP2 `{price_fmt(fut_active.tp2_price)}` | R:R `1:{fut_active.rr_ratio:.2f}`"
                )
            else:
                st.markdown(
                    f"**⚡ Vadeli İşlem Durumu:** İşlem önerilmiyor ({fut_active.confidence_score:.0f}/100) — {fut_active.wait_condition_tr}"
                )
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
