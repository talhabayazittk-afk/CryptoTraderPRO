"""
Interactive Touch-Button & Proactive Radar Telegram Bot for the Smart Crypto Platform (v7.0).
Run with:
    py -3.13 telegram_bot.py

Features:
  1. Full Touch-Button Navigation (Inline Keyboards + Persistent Bottom Reply Keyboard)
  2. Multi-Timeframe 4-Card Analysis (/analiz ONDO 1h or just ONDO) with 1-tap [15M | 1H | 4H | 1D] switching
  3. Instant Dark-Mode PNG Chart Snapshot (/grafik ONDO 1h or [🖼️ Grafik Gönder] button)
  4. Fast Parallel Multi-Coin Screener (/tara, /firsat) with clickable coin buttons
  5. Global Market & Cash Flow Overview (/piyasa, /nakit)
  6. Multi-Timeframe Magnet (POC) & Liquidation Map (/miknatis, /likidasyon)
  7. Position Sizing & Risk Calculator (/kasa ONDO 1000) with 1-tap capital buttons ($500 / $1000 / $2500 / $5000)
  8. Personal Price Alarms (/alarm ONDO 0.3620 or 1-tap Resistance/Support alarm buttons)
  9. 24/7 Proactive Breakout, Whale & Squeeze Radar + Automatic Session Bulletins (09:00 & 16:30)
  10. Single-instance PID lock & Authorized Chat ID security
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure UTF-8 console output on Windows so emojis never raise UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import pandas as pd

from src.config import AnalysisConfig, ExchangeConfig
from src.data_fetcher import CryptoDataFetcher
from src.indicators import TechnicalIndicators
from src.market_scanner import (
    MarketWideHunter,
    build_market_hunter_inline_keyboard,
    format_market_hunter_telegram_html,
)
from src.local_ai import (
    build_ai_summary_inline_keyboard,
    format_ai_summary_telegram_html,
    generate_ai_executive_summary,
)
from src.patterns import CandlestickPatternDetector
from src.pipeline import AnalysisPipeline
from src.signal_ledger import SignalLedger, format_ledger_telegram_html
from src.signals import MarketForecast, SignalEngine
import src.telegram_notifier as _tg_notifier
from src.telegram_notifier import (
    PID_FILE,
    POPULAR_QUICK_COINS,
    add_price_alarm,
    answer_callback_query,
    build_alarm_radar_inline_keyboard,
    build_analysis_inline_keyboard,
    build_coin_list_inline_keyboard,
    build_futures_radar_inline_keyboard,
    build_futures_setup_inline_keyboard,
    build_main_reply_keyboard,
    build_screener_inline_keyboard,
    build_watchlist_manage_inline_keyboard,
    edit_telegram_message,
    edit_telegram_photo_message,
    format_forecast_telegram_html,
    format_futures_radar_scan_telegram_html,
    format_futures_setup_telegram_html,
    format_liquidation_magnet_telegram_html,
    format_market_overview_telegram_html,
    format_position_size_telegram_html,
    format_screener_telegram_html,
    generate_telegram_chart_png,
    is_bot_running,
    load_telegram_config,
    load_telegram_state,
    remove_price_alarm,
    save_telegram_config,
    save_telegram_state,
    send_telegram_message,
    send_telegram_photo,
)
from src.x_publisher import (
    build_x_intent_url,
    format_breakout_radar_x_post,
    format_coin_analysis_x_post,
    format_futures_radar_x_post,
    format_futures_setup_x_post,
    format_ledger_scorecard_x_post,
    format_market_hunter_x_post,
    format_market_overview_x_post,
    format_radar_alert_x_post,
    format_screener_x_post,
    get_x_daily_post_count,
    is_x_configured,
    load_x_config,
    load_x_state,
    publish_x_content,
    save_x_state,
)


def _bot_fallback_build_breakout_radar_kb(entries: List[Dict[str, Any]], timeframe: str = "4H") -> Dict[str, Any]:
    tf_up = timeframe.upper()
    tf_row = [
        {"text": f"✅ {t}" if t == tf_up else f"🚨 {t}", "callback_data": f"brk_scan:{t}"}
        for t in ("15M", "1H", "4H", "1D")
    ]
    rows: List[List[Dict[str, str]]] = [tf_row]
    btn_row: List[Dict[str, str]] = []
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


def _bot_fallback_format_breakout_radar_html(entries: List[Dict[str, Any]], timeframe: str = "4H") -> str:
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
    _tg_notifier,
    "build_breakout_radar_inline_keyboard",
    _bot_fallback_build_breakout_radar_kb,
)
format_breakout_radar_scan_telegram_html = getattr(
    _tg_notifier,
    "format_breakout_radar_scan_telegram_html",
    _bot_fallback_format_breakout_radar_html,
)

LOG_FILE = Path(__file__).resolve().parent / "telegram_bot.log"
WATCHLIST_FILE = Path(__file__).resolve().parent / "watchlist.json"


def _log(msg: str) -> None:
    """Safe UTF-8 logger that writes to telegram_bot.log and console without crashing on Windows cp1254."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(line + "\n")
    except Exception:
        pass
DEFAULT_WATCHLIST = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "ONDO/USDT",
    "ENA/USDT",
    "XRP/USDT",
    "SUI/USDT",
    "AVAX/USDT",
]


def _load_shared_watchlist() -> List[str]:
    if WATCHLIST_FILE.exists():
        try:
            data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) > 0:
                return list(dict.fromkeys([str(x).upper() for x in data]))
        except Exception:
            pass
    return list(DEFAULT_WATCHLIST)


def _save_shared_watchlist(items: List[str]) -> None:
    try:
        clean = list(dict.fromkeys([str(x).strip().upper() for x in items if str(x).strip()]))
        WATCHLIST_FILE.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _normalize_symbol(raw: str) -> str:
    clean = raw.strip().upper().replace("-", "/")
    if "/" not in clean:
        if clean.endswith("USDT") and len(clean) > 4:
            clean = clean[:-4] + "/USDT"
        else:
            clean = f"{clean}/USDT"
    return clean


import threading

# Short-lived (45s) in-memory caches so timeframe/tab switching & button taps respond in <0.05s
_CACHE_LOCK = threading.Lock()
_BUNDLE_CACHE: Dict[str, Tuple[float, Dict[str, pd.DataFrame], Dict[str, MarketForecast], Dict[str, float], float]] = {}
_SCAN_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
CACHE_TTL_SEC = 45.0


def _invalidate_scan_cache() -> None:
    """Clears multi-coin scan cache whenever the user adds or removes a coin."""
    with _CACHE_LOCK:
        _SCAN_CACHE.clear()


def _validate_coin_on_exchange(sym: str) -> bool:
    """Verifies that a symbol exists on the live exchange before adding to watchlist."""
    sym_u = _normalize_symbol(sym)
    if sym_u in POPULAR_QUICK_COINS:
        return True
    ex_choice = str(load_telegram_state().get("primary_exchange", "binance")).lower()
    with _CACHE_LOCK:
        if f"{ex_choice}:{sym_u}" in _BUNDLE_CACHE:
            return True
    try:
        cfg = AnalysisConfig(exchange=ExchangeConfig(primary_exchange=ex_choice, symbol=sym_u, timeframe="15m", limit=5))
        df_v, _ = CryptoDataFetcher(cfg.exchange).fetch_ohlcv(allow_synthetic_fallback=False)
        return not df_v.empty
    except Exception:
        return False


def _compute_full_coin_bundle(
    symbol: str,
    timeframe: str = "4h",
    allow_synthetic_fallback: bool = False,
    force_refresh: bool = False,
    _is_btc_internal: bool = False,
) -> Tuple[pd.DataFrame, MarketForecast, Dict[str, MarketForecast], Dict[str, float], float]:
    """
    Fetches all 4 timeframes (15m, 1h, 4h, 1d) + OrderFlowIntel IN PARALLEL,
    incorporates BTC Macro Regime & Relative Strength (100% synchronized with app.py),
    evaluates from 1D -> 15M so HTF alignment is accurate, caches the 4-timeframe bundle
    for 45 seconds so button switches are instantaneous, and returns:
      (df_active, fc_active, tf_forecasts, mtf_scores, current_price)
    """
    tf = timeframe.lower() if timeframe.lower() in ("15m", "1h", "4h", "1d") else "4h"
    tf_key = tf.upper()
    sym_key = symbol.upper()
    ex_choice = str(load_telegram_state().get("primary_exchange", "binance")).lower()
    cache_key = f"{ex_choice}:{sym_key}"
    now_t = time.time()

    if not force_refresh:
        with _CACHE_LOCK:
            cached = _BUNDLE_CACHE.get(cache_key)
            if cached and (now_t - cached[0]) <= CACHE_TTL_SEC:
                _, tf_data_c, tf_forecasts_c, mtf_scores_c, curr_p_c = cached
                return tf_data_c[tf_key], tf_forecasts_c[tf_key], tf_forecasts_c, mtf_scores_c, curr_p_c

    # Fetch BTC macro regime & 4-timeframe reference first when analyzing altcoins (same as app.py)
    btc_tf_data_ref: Optional[Dict[str, pd.DataFrame]] = None
    btc_scores_ref: Optional[Dict[str, float]] = None
    if not sym_key.startswith("BTC/") and not _is_btc_internal:
        try:
            _, _, _, btc_scores_ref, _ = _compute_full_coin_bundle(
                "BTC/USDT",
                timeframe=tf,
                allow_synthetic_fallback=False,
                force_refresh=force_refresh,
                _is_btc_internal=True,
            )
            with _CACHE_LOCK:
                btc_cached = _BUNDLE_CACHE.get(f"{ex_choice}:BTC/USDT")
                if btc_cached:
                    btc_tf_data_ref = btc_cached[1]
        except Exception:
            btc_tf_data_ref = None
            btc_scores_ref = None

    bundle = AnalysisPipeline.run_coin_bundle(
        symbol=sym_key,
        exchange_id=ex_choice,
        timeframes=("15m", "1h", "4h", "1d"),
        limit=500,
        btc_regime_scores=btc_scores_ref,
        btc_tf_data=btc_tf_data_ref,
        allow_synthetic_fallback=allow_synthetic_fallback,
        enable_ledger=True,
    )
    tf_data = bundle.tf_data
    tf_forecasts = bundle.tf_forecasts
    mtf_scores = bundle.mtf_scores
    df_active = tf_data[tf_key]
    fc_active = tf_forecasts[tf_key]
    current_price = float(df_active["close"].iloc[-1])

    with _CACHE_LOCK:
        _BUNDLE_CACHE[cache_key] = (now_t, tf_data, tf_forecasts, mtf_scores, current_price)

    return df_active, fc_active, tf_forecasts, mtf_scores, current_price


def _analyze_single_coin(
    symbol: str,
    timeframe: str = "4h",
    force_refresh: bool = False,
) -> Tuple[str, Dict[str, Any], pd.DataFrame, MarketForecast, float]:
    """Returns (html_text, inline_keyboard, df_active, fc_active, current_price)."""
    tf = timeframe.lower() if timeframe.lower() in ("15m", "1h", "4h", "1d") else "4h"
    tf_key = tf.upper()
    df_active, fc_active, _, mtf_scores, current_price = _compute_full_coin_bundle(
        symbol,
        tf,
        force_refresh=force_refresh,
    )
    html_text = format_forecast_telegram_html(
        fc_active,
        symbol=symbol,
        timeframe=tf_key,
        current_price=current_price,
        mtf_scores=mtf_scores,
    )
    kb = build_analysis_inline_keyboard(symbol, tf_key)
    return html_text, kb, df_active, fc_active, current_price


def _send_or_update_analysis_with_chart(
    bot_token: str,
    chat_id: str,
    df_act: pd.DataFrame,
    fc_act: MarketForecast,
    symbol: str,
    timeframe: str,
    html_text: str,
    kb: Dict[str, Any],
    include_futures_levels: bool = False,
    msg_id: int = 0,
    is_photo_msg: bool = False,
) -> None:
    """
    Guarantees every Telegram analysis output (General or Futures) is delivered WITH its chart image.
    If triggered from an inline button on an existing photo message, updates the photo + caption in-place.
    """
    png_b = generate_telegram_chart_png(
        df_act,
        fc_act,
        symbol,
        timeframe.upper(),
        include_futures_levels=include_futures_levels,
    )
    if png_b:
        if is_photo_msg and msg_id:
            if edit_telegram_photo_message(bot_token, chat_id, msg_id, png_b, caption_html=html_text, reply_markup=kb):
                return
        send_telegram_photo(bot_token, chat_id, png_b, caption_html=html_text, reply_markup=kb)
    else:
        if not is_photo_msg and msg_id:
            if edit_telegram_message(bot_token, chat_id, msg_id, html_text, reply_markup=kb):
                return
        send_telegram_message(bot_token, chat_id, html_text, reply_markup=kb)


def _analyze_single_coin_for_scan(
    sym: str,
    tf: str,
    btc_df: Optional[pd.DataFrame] = None,
    btc_score: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Worker function for parallel multi-coin scanning (uses full 4-TF bundle so HTF + BTC alignment match 100%)."""
    try:
        df, fc, _, _, current_price = _compute_full_coin_bundle(
            sym,
            timeframe=tf,
            allow_synthetic_fallback=False,
            force_refresh=False,
        )
        p_fmt = ",.4f" if current_price < 10.0 else ",.2f"
        t_st = getattr(fc, "trend_state", "")
        if t_st == "UPTREND" or (not t_st and fc.score >= 15):
            trend_lbl = f"📈 Yükselen ({fc.score:+.0f})"
        elif t_st == "DOWNTREND" or (not t_st and fc.score <= -15):
            trend_lbl = f"📉 Düşen ({fc.score:+.0f})"
        else:
            trend_lbl = f"⚖️ Yatay ({fc.score:+.0f})"
        flow_lbl = (
            "🟢 Para Girişi"
            if fc.cmf_value > 0.04
            else ("🔴 Para Çıkışı" if fc.cmf_value < -0.04 else "⚪ Dengeli")
        )
        sup_s = format(fc.nearest_support, p_fmt) if fc.nearest_support else "N/A"
        res_s = format(fc.nearest_resistance, p_fmt) if fc.nearest_resistance else "N/A"
        net_d = fc.net_delta_20_usd
        if abs(net_d) >= 1_000_000:
            delta_s = f"{net_d / 1_000_000:+,.1f}M$"
        elif abs(net_d) >= 1_000:
            delta_s = f"{net_d / 1_000:+,.1f}K$"
        else:
            delta_s = f"{net_d:+,.0f}$"

        return {
            "_sort_ready": fc.readiness_score_5,
            "_sort_whale": abs(fc.whale_accumulation_score - 50.0),
            "_sort_bias": abs(fc.score),
            "Coin": sym,
            "symbol": sym,
            "price": current_price,
            "price_str": format(current_price, p_fmt),
            "Fiyat (USDT)": format(current_price, p_fmt),
            "1S Trend": trend_lbl,
            "Onay": f"{fc.readiness_score_5}/5",
            "ready": fc.readiness_score_5,
            "score": fc.score,
            "whale": fc.whale_accumulation_score,
            "cmf": fc.cmf_value,
            "delta_str": delta_s,
            "🐋 Balina İzi": f"{fc.whale_accumulation_score:.0f}/100",
            "Para Akışı (1S)": flow_lbl,
            "Destek / Direnç": f"{sup_s} / {res_s}",
            "fc": fc,
            "df": df,
        }
    except Exception:
        return None


def _scan_watchlist_parallel(
    timeframe: str = "4h",
    only_high_quality: bool = False,
    force_refresh: bool = False,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Scans up to 15 watchlist coins IN PARALLEL using ThreadPoolExecutor,
    incorporating BTC macro context, caches raw results for 45s so filter/market
    switches are instant, and returns (html_text, inline_keyboard, raw_results).
    """
    tf = timeframe.lower() if timeframe.lower() in ("15m", "1h", "4h", "1d") else "4h"
    now_t = time.time()
    results: Optional[List[Dict[str, Any]]] = None

    if not force_refresh:
        with _CACHE_LOCK:
            cached_s = _SCAN_CACHE.get(tf)
            if cached_s and (now_t - cached_s[0]) <= CACHE_TTL_SEC:
                results = list(cached_s[1])

    if results is None:
        symbols_to_scan = _load_shared_watchlist()[:15]
        if not symbols_to_scan:
            symbols_to_scan = list(DEFAULT_WATCHLIST)

        # Warm up 4-TF BTC reference bundle once before parallel coin workers run
        try:
            _compute_full_coin_bundle(
                "BTC/USDT",
                timeframe=tf,
                allow_synthetic_fallback=False,
                force_refresh=force_refresh,
                _is_btc_internal=True,
            )
        except Exception:
            pass

        results = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = {
                pool.submit(_analyze_single_coin_for_scan, sym, tf, None, None): sym
                for sym in symbols_to_scan
            }
            for fut in as_completed(futs):
                res = fut.result()
                if res is not None:
                    results.append(res)

        with _CACHE_LOCK:
            _SCAN_CACHE[tf] = (now_t, list(results))

    filtered: List[Dict[str, Any]] = []
    for r in results:
        if only_high_quality and r["ready"] < 3 and abs(r["whale"] - 50.0) < 12.0:
            continue
        filtered.append(r)

    filtered.sort(key=lambda r: (r["_sort_ready"], r["_sort_whale"], r["_sort_bias"]), reverse=True)
    kb = build_screener_inline_keyboard(filtered if filtered else results, tf, only_high_quality)
    if not filtered:
        msg = (
            f"ℹ️ <b>[{tf.upper()}]</b> Şu an yüksek hazırlık onaylı (3/5+) veya güçlü balina izi taşıyan "
            "fırsat bulunamadı. Tüm listeyi görmek için aşağıdaki butona dokunabilirsiniz:"
        )
        return msg, kb, results

    return format_screener_telegram_html(filtered, tf, only_high_quality), kb, results


def _build_alarm_radar_status_html(state: Dict[str, Any]) -> str:
    radar_on = bool(state.get("radar_enabled", True))
    sess_on = bool(state.get("auto_session_summary", True))
    alarms = state.get("alarms", [])
    x_st = load_x_state()
    x_radar_on = bool(x_st.get("x_auto_radar_enabled", True))
    x_cfg_ok = is_x_configured()
    x_daily_n = get_x_daily_post_count(x_st)
    x_max_n = int(x_st.get("x_max_daily_posts", 15))

    lines = [
        "⏰ <b>AKILLI ALARM &amp; 7/24 RADAR MERKEZİ (TELEGRAM + X)</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📡 <b>Telegram 7/24 Kırılım Radarı (4H):</b> {'🟢 <b>AÇIK</b> (Otomatik Tarama Aktif)' if radar_on else '🔴 <b>KAPALI</b>'}",
        f"🐦 <b>X (Twitter) 7/24 Otomatik Radar:</b> {'🟢 <b>AÇIK</b>' if (x_radar_on and x_cfg_ok) else ('⚠️ <b>AÇIK (API Anahtarı Eksik)</b>' if x_radar_on else '⚪ <b>KAPALI</b>')} <i>(Bugün: {x_daily_n}/{x_max_n})</i>",
        f"🌅 <b>Otomatik Seans Özeti (09:00 &amp; 16:30):</b> {'🟢 <b>AÇIK</b>' if sess_on else '⚪ <b>KAPALI</b>'}",
        "",
        f"🔔 <b>AKTİF FİYAT ALARMLARINIZ ({len(alarms)} Adet):</b>",
    ]
    if not alarms:
        lines.append("<i>• Henüz kurulu fiyat alarmınız yok.</i>")
        lines.append("<i>💡 Herhangi bir coin analizinin altındaki <b>[🔔 Direnç Alarmı]</b> / <b>[🔔 Destek Alarmı]</b> butonlarına dokunarak veya <code>/alarm ONDO 0.3620</code> yazarak alarm kurabilirsiniz.</i>")
    else:
        for idx, a in enumerate(alarms, start=1):
            sym = a.get("symbol", "")
            tp = float(a.get("target_price", 0.0))
            p_fmt = ",.4f" if tp < 10.0 else ",.2f"
            note = a.get("note", "")
            lines.append(f"{idx}. <b>{sym}</b> ➔ <code>{format(tp, p_fmt)} USDT</code> ({note})")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━\n<i>👇 Alttaki dokunmatik butonlarla Telegram &amp; X Radar ve Alarmlarınızı yönetebilirsiniz:</i>")
    return "\n".join(lines)


def _build_kasa_inline_keyboard(symbol: str, tf_up: str = "4H", active_cap: float = 1000.0) -> Dict[str, Any]:
    caps = [500, 1000, 2500, 5000]
    cap_row = []
    for c in caps:
        lbl = f"✅ {c}$" if abs(active_cap - c) < 1 else f"💼 {c}$"
        cap_row.append({"text": lbl, "callback_data": f"kasa:{symbol}:{tf_up}:{c}"})
    return {
        "inline_keyboard": [
            cap_row,
            [
                {"text": "📊 Özet Analize Dön", "callback_data": f"an:{symbol}:{tf_up}"},
                {"text": "🖼️ Grafik Gönder", "callback_data": f"chart:{symbol}:{tf_up}"},
            ],
        ]
    }


def _build_help_html(chat_id: str) -> str:
    return (
        "👋 <b>Akıllı Kripto Karar-Destek &amp; Kırılım Radarı Terminali (Varsayılan: 4H)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Artık yazı yazmanıza gerek kalmadan <b>ekranın altındaki sabit menüyü</b> veya mesajların altındaki <b>dokunmatik butonları</b> kullanabilirsiniz!\n\n"
        "🧠 <b>Lokal AI Yönetici Özeti &amp; Çelişki Yorumu (%100 Ücretsiz · Ollama):</b>\n"
        "• <code>/ai BTC 4h</code> veya <code>ai ONDO</code> — Çoklu zaman dilimi, para akışı ve tuzak çelişkilerini denetleyen AI Yönetici Özeti (Analiz kartlarındaki <b>🧠 AI Özeti</b> butonuyla da açılır)\n\n"
        "🚨 <b>Destek / Direnç Kırılım &amp; Tuzak (SFP) Radarı:</b>\n"
        "• <code>/kirilim 4h</code> — <b>Direnç Kırılımı Geldi</b>, <b>Destek Kırılımı Geldi</b>, <b>Sahte Kırılım (Tuzak)</b> ve <b>Retest</b> onaylarını listeler\n\n"
        "🐋 <b>Tüm Piyasa Spot Nakit Girişi &amp; Sıkışma Avcısı (Top 80):</b>\n"
        "• <code>/avci 1h</code> veya <code>/avci 4h</code> — Borsadaki en likit 80 USDT tahtasını gerçek Taker Spot nakit akışı, Z-Skor ve sıkışma filtresiyle tarar (<code>/xavci</code> ile X'te paylaşır)\n\n"
        "⚡ <b>Vadeli İşlemler (Futures) Kurulum &amp; Güven Radarı:</b>\n"
        "• <code>/vadeli ONDO 4h</code> — Vadeli Long/Short Giriş, TP1/TP2/TP3 ve Stop Planı + Vadeli Grafik\n"
        "• <code>/vadelitara 4h</code> — Tüm Coinleri Tarar, Güvenli Vadeli Kurulumları Ayırır\n\n"
        "📲 <b>Temel Sorgu &amp; Grafik Komutları (Varsayılan: 4H):</b>\n"
        "• <code>ONDO</code> veya <code>ONDO 4h</code> — Grafik + Kısa &amp; Öz Yapısal Analiz\n"
        "• <code>/grafik ONDO 4h</code> — Destek/Direnç Sınıflandırmalı Grafik Görseli\n"
        "• <code>/miknatis ONDO</code> — 15M/1H/4H/1D Mıknatıs (POC) &amp; Likidasyon Haritası\n"
        "• <code>/kasa ONDO 1000</code> — Stop Mesafesine Göre Kasa &amp; Risk Hesaplayıcı\n\n"
        "🪙 <b>Telegram Üzerinden Coin Ekleme &amp; Çıkarma:</b>\n"
        "• <code>/ekle PEPE RENDER</code> — Borsada doğrulayarak izleme listenize yeni coin(ler) ekler\n"
        "• <code>/sil ENA</code> veya <code>/cikar ENA</code> — Coini izleme listenizden çıkarır\n"
        "• <code>/liste</code> — Tıklanabilir Coin Seçim &amp; 1-Tıkla Coin Ekle/Çıkar Menüsü (4H)\n\n"
        "⏰ <b>Alarm &amp; 7/24 Otomatik Radar (Telegram + X):</b>\n"
        "• <code>/alarm ONDO 0.3620</code> — Hedef Fiyata Anlık Bildirim Alarmı Kurar\n"
        "• <code>/alarmlar</code> veya <code>/radar</code> — 7/24 Otomatik Kırılım Radarı &amp; Alarm Kontrol Paneli\n\n"
        "🐦 <b>X (Twitter) &amp; Şeffaf Sinyal Karnesi Komutları:</b>\n"
        "• <code>/karne</code> — SQLite Canlı Sinyal Karnesi &amp; Gerçek Başarı Oranı (%0.10 komisyon dahil)\n"
        "• <code>/x ONDO 4h</code> — Coinin analizini ve grafiğini X hesabınızda paylaşır\n"
        "• <code>/xvadeli ONDO 4h</code> | <code>/xkarne</code> — Vadeli Planı veya Sinyal Karnesini X'te paylaşır\n"
        "• <code>/xtara 4h</code> | <code>/xkirilim 4h</code> | <code>/xpiyasa 4h</code> — Tarama ve Piyasa raporunu X'te paylaşır\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Chat ID:</b> <code>{chat_id}</code> (Yatırım tavsiyesi değildir - YTD)"
    )


# ===========================================================================
# PROACTIVE BACKGROUND CHECKS (PRICE ALARMS, SMART RADAR & SESSION BULLETINS)
# ===========================================================================
def _check_price_alarms(bot_token: str, chat_id: str) -> None:
    """Checks user price alarms every 30s and fires instant Telegram notifications when crossed."""
    state = load_telegram_state()
    alarms = state.get("alarms", [])
    if not alarms:
        return

    symbols_needed = list(dict.fromkeys([str(a.get("symbol", "")).upper() for a in alarms if a.get("symbol")]))
    live_prices: Dict[str, float] = {}
    for sym in symbols_needed:
        try:
            cfg = AnalysisConfig(exchange=ExchangeConfig(symbol=sym, timeframe="15m", limit=5))
            df, _ = CryptoDataFetcher(cfg.exchange).fetch_ohlcv(allow_synthetic_fallback=False)
            live_prices[sym] = float(df["close"].iloc[-1])
        except Exception:
            continue

    remaining_alarms = []
    triggered_any = False
    for a in alarms:
        sym = str(a.get("symbol", "")).upper()
        if sym not in live_prices:
            remaining_alarms.append(a)
            continue
        curr_p = live_prices[sym]
        target_p = float(a.get("target_price", 0.0))
        direction = a.get("direction", "ABOVE")
        hit = (direction == "ABOVE" and curr_p >= target_p) or (direction == "BELOW" and curr_p <= target_p)
        if hit:
            triggered_any = True
            p_fmt = ",.4f" if curr_p < 10.0 else ",.2f"
            dir_txt = "ÜSTÜNE ÇIKTI 📈" if direction == "ABOVE" else "ALTINA İNDİ 📉"
            alert_html = (
                f"🚨 <b>FİYAT ALARMI TETİKLENDİ: {sym}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• 🎯 <b>Alarm Seviyesi:</b> <code>{format(target_p, p_fmt)} USDT</code> ({a.get('note', '')})\n"
                f"• 💰 <b>Anlık Fiyat:</b> <code>{format(curr_p, p_fmt)} USDT</code> (<b>{dir_txt}</b>)\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>👇 Güncel 4H grafik ve analizi görmek için dokunun:</i>"
            )
            kb = {
                "inline_keyboard": [
                    [
                        {"text": f"📊 {sym} (4H) Analiz", "callback_data": f"an:{sym}:4H"},
                        {"text": f"📊 {sym} (1H) Analiz", "callback_data": f"an:{sym}:1H"},
                    ],
                    [
                        {"text": f"🖼️ {sym} (4H) Grafik", "callback_data": f"chart:{sym}:4H"},
                    ],
                ]
            }
            target_cid = str(a.get("chat_id") or chat_id).strip()
            if target_cid:
                send_telegram_message(bot_token, target_cid, alert_html, reply_markup=kb)
        else:
            remaining_alarms.append(a)

    if triggered_any:
        state["alarms"] = remaining_alarms
        save_telegram_state(state)


def _run_proactive_radar_cycle(bot_token: str, chat_id: str, force: bool = False) -> int:
    """
    Scans watchlist in parallel on 4H default timeframe and alerts on high-conviction events
    with a mandatory chart PNG (without futures TP/Stop lines) to both Telegram and X (Twitter).
    """
    state = load_telegram_state()
    x_st = load_x_state()
    x_cfg = load_x_config()
    tg_active = bool(bot_token and chat_id and (force or state.get("radar_enabled", True)))
    x_active = bool(is_x_configured(x_cfg) and (force or x_st.get("x_auto_radar_enabled", True)))

    if not tg_active and not x_active:
        return 0

    _, _, results = _scan_watchlist_parallel("4h", only_high_quality=False)
    cooldowns: Dict[str, float] = state.get("radar_cooldowns", {})
    x_cooldowns: Dict[str, float] = x_st.get("x_cooldowns", {})
    x_cd_sec = float(x_st.get("x_coin_cooldown_sec", 14400))
    x_max_daily = int(x_st.get("x_max_daily_posts", 15))
    now_ts = time.time()
    alerts_sent = 0
    x_posts_sent = 0

    for r in results:
        sym = r["symbol"]
        fc: MarketForecast = r["fc"]
        last_sent_tg = float(cooldowns.get(sym, 0.0))
        last_sent_x = float(x_cooldowns.get(sym, 0.0))
        can_send_tg = tg_active and (force or (now_ts - last_sent_tg) >= 7200)
        can_send_x = (
            x_active
            and (force or (now_ts - last_sent_x) >= x_cd_sec)
            and (force or get_x_daily_post_count(x_st) < x_max_daily)
        )
        if not can_send_tg and not can_send_x:
            continue

        reasons: List[str] = []
        sr_act = getattr(fc, "sr_action_type", "NONE")
        sr_status_tr = getattr(fc, "sr_action_status_tr", "")
        tl_rep = getattr(fc, "trendlines", None)
        tl_brk = getattr(tl_rep, "breakout_status", "NONE") if tl_rep else "NONE"
        tl_sum = getattr(tl_rep, "summary_tr", "") if tl_rep else ""

        header_title = f"📡 <b>RADAR UYARISI: {sym} [4H]</b>"

        if sr_act == "BULL_SR_BREAKOUT":
            header_title = f"🚀 <b>DİRENÇ KIRILIMI GELDİ: {sym} [4H]</b>"
            reasons.append(f"🚀 <b>Kırılım Onayı:</b> {sr_status_tr}")
        elif sr_act == "BEAR_SR_BREAKDOWN":
            header_title = f"🩸 <b>DESTEK KIRILIMI GELDİ: {sym} [4H]</b>"
            reasons.append(f"🩸 <b>Kırılım Onayı:</b> {sr_status_tr}")
        elif sr_act in ("BULL_SFP", "BEAR_SFP"):
            header_title = f"🪤 <b>SAHTE KIRILIM (TUZAK / SFP): {sym} [4H]</b>"
            reasons.append(f"🪤 <b>Tuzak Tespit Edildi:</b> {sr_status_tr}")
        elif sr_act in ("BULL_RETEST", "BEAR_RETEST"):
            header_title = f"🔄 <b>KIRILIM SONRASI RETEST: {sym} [4H]</b>"
            reasons.append(f"🔄 <b>Retest Onayı:</b> {sr_status_tr}")

        if tl_brk in ("BULL_BREAKOUT", "BEAR_BREAKDOWN"):
            if sr_act == "NONE":
                header_title = (
                    f"📐 <b>DÜŞEN TREND KIRILIMI: {sym} [4H]</b>"
                    if tl_brk == "BULL_BREAKOUT"
                    else f"📐 <b>YÜKSELEN TREND KIRILIMI: {sym} [4H]</b>"
                )
            reasons.append(f"📐 <b>Trend Kırılımı:</b> {tl_sum}")

        if fc.readiness_score_5 >= 4 and abs(fc.score) >= 22:
            tr_txt = "YÜKSELİŞ" if fc.score > 0 else "DÜŞÜŞ"
            reasons.append(f"🚦 <b>Güçlü {tr_txt} Kurulumu:</b> Hazırlık <b>{fc.readiness_score_5}/5</b> ({fc.score:+.0f}/100)")
        if fc.whale_accumulation_score >= 70:
            reasons.append(f"🐋 <b>Balina Toplaması:</b> <b>{fc.whale_accumulation_score:.0f}/100</b> (Nakit: {r['delta_str']})")
        elif fc.whale_accumulation_score <= 30:
            reasons.append(f"🐋 <b>Balina Satışı:</b> <b>{fc.whale_accumulation_score:.0f}/100</b> (Nakit: {r['delta_str']})")
        if fc.squeeze_energy_pct >= 80:
            reasons.append(f"💥 <b>Yüksek Sıkışma:</b> <b>%{fc.squeeze_energy_pct:.0f}</b> (±%{fc.expected_breakout_move_pct:.1f} hareket yakın)")

        if reasons:
            p_fmt = ",.4f" if r["price"] < 10.0 else ",.2f"
            sup_s = format(fc.nearest_support, p_fmt) if fc.nearest_support else "N/A"
            res_s = format(fc.nearest_resistance, p_fmt) if fc.nearest_resistance else "N/A"
            sup_tier = getattr(fc, "nearest_support_tier_tr", "🟢 Sıradan Destek")
            res_tier = getattr(fc, "nearest_resistance_tier_tr", "🔴 Sıradan Direnç")
            sup_sc = getattr(fc, "nearest_support_score", 0.0)
            res_sc = getattr(fc, "nearest_resistance_score", 0.0)

            chart_png_bytes: Optional[bytes] = None
            if r.get("df") is not None:
                chart_png_bytes = generate_telegram_chart_png(
                    r["df"], fc, sym, "4H", include_futures_levels=False
                )

            x_post_url_note = ""
            if can_send_x and (x_posts_sent < 2 or force):
                x_tweets = format_radar_alert_x_post(
                    symbol=sym,
                    timeframe="4H",
                    current_price=r["price"],
                    fc=fc,
                    reasons=reasons,
                    header_title=header_title,
                )
                ok_x, msg_x, tid_x = publish_x_content(
                    tweets=x_tweets,
                    photo_bytes=chart_png_bytes,
                    title=f"Radar Uyarısı ({sym} 4H)",
                    symbol=sym,
                    cfg=x_cfg,
                )
                if ok_x and tid_x:
                    x_st = load_x_state()
                    x_cooldowns = x_st.get("x_cooldowns", {})
                    x_cooldowns[sym] = now_ts
                    x_st["x_cooldowns"] = x_cooldowns
                    save_x_state(x_st)
                    x_posts_sent += 1
                    alerts_sent += 1
                    x_url = f"https://x.com/i/web/status/{tid_x}"
                    x_post_url_note = f"\n• 🐦 <b>X'te Otomatik Paylaşıldı:</b> {x_url}"
                    _log(f"🐦 X Radar Paylaşıldı: {sym} -> {x_url}")
                else:
                    _log(f"⚠️ X Radar Paylaşım Uyarısı ({sym}): {msg_x}")

            if can_send_tg:
                radar_html = (
                    f"{header_title}\n"
                    f"💰 <b>Fiyat:</b> <code>{r['price_str']} USDT</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    + "\n".join([f"• {rs}" for rs in reasons[:3]])
                    + "\n"
                    + f"• <b>{sup_tier} ({sup_sc:.0f}p):</b> <code>{sup_s}</code>\n"
                    + f"• <b>{res_tier} ({res_sc:.0f}p):</b> <code>{res_s}</code>\n"
                    + f"• 🧲 <b>Mıknatıs (POC):</b> <code>{format(fc.poc_price, p_fmt)}</code>"
                    + x_post_url_note
                )
                kb = build_analysis_inline_keyboard(sym, "4H")
                if r.get("df") is not None:
                    _send_or_update_analysis_with_chart(
                        bot_token,
                        chat_id,
                        r["df"],
                        fc,
                        sym,
                        "4H",
                        radar_html,
                        kb,
                        include_futures_levels=False,
                    )
                else:
                    send_telegram_message(bot_token, chat_id, radar_html, reply_markup=kb)

                cooldowns[sym] = now_ts
                alerts_sent += 1

            if alerts_sent >= 3 and not force:
                break

    state["radar_cooldowns"] = cooldowns
    save_telegram_state(state)
    return alerts_sent


def _check_auto_session_bulletin(bot_token: str, chat_id: str) -> None:
    """Sends automatic market & cash flow summary at 09:00 and 16:30 local time to Telegram and X if enabled."""
    state = load_telegram_state()
    x_st = load_x_state()
    x_cfg = load_x_config()
    tg_sess_ok = bool(state.get("auto_session_summary", True) and bot_token and chat_id)
    x_sess_ok = bool(x_st.get("x_auto_session_bulletin", True) and is_x_configured(x_cfg))
    if not tg_sess_ok and not x_sess_ok:
        return

    lt = time.localtime()
    hm = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
    day_key = f"{lt.tm_year}-{lt.tm_yday}"

    session_tag = ""
    if hm in ("09:00", "09:01"):
        session_tag = f"{day_key}_MORNING"
    elif hm in ("16:30", "16:31"):
        session_tag = f"{day_key}_NY_OPEN"

    if not session_tag:
        return

    need_tg = tg_sess_ok and (state.get("last_session_tag") != session_tag)
    need_x = x_sess_ok and (x_st.get("x_last_session_tag") != session_tag)
    if not need_tg and not need_x:
        return

    _, _, results = _scan_watchlist_parallel("4h", only_high_quality=False)
    if not results:
        return

    sess_tr = results[0]["fc"].session_status_tr
    if need_x:
        x_st["x_last_session_tag"] = session_tag
        save_x_state(x_st)
        x_tweets = format_market_overview_x_post(results, sess_tr, "4H")
        top_chart = None
        if results[0].get("df") is not None:
            top_chart = generate_telegram_chart_png(
                results[0]["df"], results[0]["fc"], results[0]["symbol"], "4H", include_futures_levels=False
            )
        ok_x, msg_x, _ = publish_x_content(
            tweets=x_tweets,
            photo_bytes=top_chart,
            title="Seans Piyasa & Nakit Özeti (4H)",
            symbol="PİYASA",
            cfg=x_cfg,
        )
        _log(f"🌅 X Seans Özeti: {msg_x}")

    if need_tg:
        state["last_session_tag"] = session_tag
        save_telegram_state(state)
        html_mkt = format_market_overview_telegram_html(results, sess_tr, "4H")
        kb = build_screener_inline_keyboard(results, "4H", False)
        send_telegram_message(bot_token, chat_id, html_mkt, reply_markup=kb)


# ===========================================================================
# CALLBACK QUERY (INLINE TOUCH BUTTON) HANDLER
# ===========================================================================
def _handle_callback_query(bot_token: str, cq: Dict[str, Any]) -> None:
    cq_id = str(cq.get("id", ""))
    data = str(cq.get("data", "")).strip()
    msg = cq.get("message") or {}
    chat_id = str(msg.get("chat", {}).get("id", ""))
    msg_id = int(msg.get("message_id", 0))
    is_photo_msg = bool(msg.get("photo"))

    if not chat_id or not data:
        return

    parts = data.split(":")
    action = parts[0]

    # 1. Single-Coin Analysis, Timeframe Switch or Explicit Refresh: an:SYMBOL:TF or an_ref:SYMBOL:TF
    if action in ("an", "an_ref") and len(parts) >= 2:
        sym = parts[1]
        tf = parts[2] if len(parts) >= 3 else "4H"
        is_ref = action == "an_ref"
        answer_callback_query(
            bot_token,
            cq_id,
            f"🔄 {sym} ({tf}) grafik & analiz yenileniyor..." if is_ref else f"📊 {sym} ({tf}) grafik & analiz açılıyor...",
        )
        html_text, kb, df_act, fc_act, _ = _analyze_single_coin(sym, tf, force_refresh=is_ref)
        _send_or_update_analysis_with_chart(
            bot_token,
            chat_id,
            df_act,
            fc_act,
            sym,
            tf,
            html_text,
            kb,
            include_futures_levels=False,
            msg_id=msg_id,
            is_photo_msg=is_photo_msg,
        )

    # 2. Send PNG Chart Snapshot: chart:SYMBOL:TF (General Chart WITHOUT Futures Stop/TP) or fut_chart:SYMBOL:TF (Futures Chart WITH Stop/TP)
    elif action in ("chart", "fut_chart") and len(parts) >= 2:
        sym = parts[1]
        tf = parts[2] if len(parts) >= 3 else "4H"
        is_fut_chart = action == "fut_chart"
        answer_callback_query(
            bot_token,
            cq_id,
            f"🖼️ {sym} ({tf}) {'Vadeli ' if is_fut_chart else ''}grafiği hazırlanıyor...",
        )
        df_act, fc_act, _, _, curr_p = _compute_full_coin_bundle(sym, tf)
        png_bytes = generate_telegram_chart_png(df_act, fc_act, sym, tf, include_futures_levels=is_fut_chart)
        kb = build_futures_setup_inline_keyboard(sym, tf) if is_fut_chart else build_analysis_inline_keyboard(sym, tf)
        if png_bytes:
            p_fmt = ",.4f" if curr_p < 10.0 else ",.2f"
            sup_tier = getattr(fc_act, "nearest_support_tier_tr", "🟢 Sıradan Destek")
            res_tier = getattr(fc_act, "nearest_resistance_tier_tr", "🔴 Sıradan Direnç")
            sup_s = format(fc_act.nearest_support, p_fmt) if fc_act.nearest_support else "N/A"
            res_s = format(fc_act.nearest_resistance, p_fmt) if fc_act.nearest_resistance else "N/A"
            if is_fut_chart and fc_act.futures_setup and fc_act.futures_setup.is_tradeable:
                fs = fc_act.futures_setup
                caption = (
                    f"🖼️ <b>{sym} [{tf.upper()}] VADELİ İŞLEM GRAFİĞİ ({fs.direction})</b>\n"
                    f"• 💰 <b>Fiyat:</b> <code>{format(curr_p, p_fmt)} USDT</code> | 🎯 <b>Giriş:</b> <code>{format(fs.entry_price, p_fmt)}</code>\n"
                    f"• 🟢 <b>TP1:</b> <code>{format(fs.tp1_price, p_fmt)}</code> | <b>TP2:</b> <code>{format(fs.tp2_price, p_fmt)}</code> | 🛡️ <b>Stop:</b> <code>{format(fs.stop_price, p_fmt)}</code>"
                )
            else:
                tr_lbl = "📈 Yükselen" if fc_act.score >= 15 else ("📉 Düşen" if fc_act.score <= -15 else "⚖️ Yatay")
                caption = (
                    f"🖼️ <b>{sym} [{tf.upper()}] GRAFİK &amp; DESTEK/DİRENÇLER</b>\n"
                    f"• <b>Trend:</b> {tr_lbl} ({fc_act.score:+.0f}/100) | 💰 <b>Fiyat:</b> <code>{format(curr_p, p_fmt)} USDT</code>\n"
                    f"• <b>{sup_tier}:</b> <code>{sup_s}</code> | <b>{res_tier}:</b> <code>{res_s}</code>\n"
                    f"• 🧲 <b>Mıknatıs (POC):</b> <code>{format(fc_act.poc_price, p_fmt)}</code>"
                )
            send_telegram_photo(bot_token, chat_id, png_bytes, caption_html=caption, reply_markup=kb)
        else:
            send_telegram_message(bot_token, chat_id, "❌ Grafik görseli oluşturulamadı.", reply_markup=kb)

    # 3. Magnet (POC) & Liquidation Map: liq:SYMBOL:TF
    elif action == "liq" and len(parts) >= 2:
        sym = parts[1]
        tf = parts[2] if len(parts) >= 3 else "4H"
        answer_callback_query(bot_token, cq_id, f"🧲 {sym} Mıknatıs & Likidasyon haritası açılıyor...")
        _, _, tf_fcs, _, curr_p = _compute_full_coin_bundle(sym, tf)
        html_liq = format_liquidation_magnet_telegram_html(sym, tf_fcs, curr_p)
        kb = build_analysis_inline_keyboard(sym, tf)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_liq, reply_markup=kb):
                send_telegram_message(bot_token, chat_id, html_liq, reply_markup=kb)
        else:
            send_telegram_message(bot_token, chat_id, html_liq, reply_markup=kb)

    # 4. Position Sizing & Risk Plan: kasa:SYMBOL:TF[:CAPITAL]
    elif action == "kasa" and len(parts) >= 2:
        sym = parts[1]
        tf = parts[2] if len(parts) >= 3 else "4H"
        cap_val = float(parts[3]) if len(parts) >= 4 else 1000.0
        answer_callback_query(bot_token, cq_id, f"🧮 {sym} ({cap_val:,.0f}$) Kasa planı hesaplanıyor...")
        _, fc_act, _, _, curr_p = _compute_full_coin_bundle(sym, tf)
        html_kasa = format_position_size_telegram_html(fc_act, sym, tf, curr_p, capital_usd=cap_val)
        kb = _build_kasa_inline_keyboard(sym, tf.upper(), cap_val)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_kasa, reply_markup=kb):
                send_telegram_message(bot_token, chat_id, html_kasa, reply_markup=kb)
        else:
            send_telegram_message(bot_token, chat_id, html_kasa, reply_markup=kb)

    # 5. Quick 1-Tap Resistance / Support Price Alarm Setup: al_res:SYMBOL:TF or al_sup:SYMBOL:TF
    elif action in ("al_res", "al_sup") and len(parts) >= 2:
        sym = parts[1]
        tf = parts[2] if len(parts) >= 3 else "4H"
        answer_callback_query(bot_token, cq_id, f"🔔 {sym} ({tf}) alarm seviyesi kaydediliyor...")
        _, fc_act, _, _, curr_p = _compute_full_coin_bundle(sym, tf)
        if action == "al_res":
            res_cand = fc_act.nearest_resistance
            target_p = res_cand if (res_cand and res_cand > curr_p) else (curr_p * 1.015)
            note = f"{tf} Direnç Kırılımı 📈"
        else:
            sup_cand = fc_act.nearest_support
            target_p = sup_cand if (sup_cand and sup_cand < curr_p) else (curr_p * 0.985)
            note = f"{tf} Destek Kırılımı 📉"
        add_price_alarm(sym, target_p, curr_p, note=note, chat_id=chat_id)
        p_fmt = ",.4f" if target_p < 10.0 else ",.2f"
        st_a = load_telegram_state()
        confirm_html = (
            f"✅ <b>FİYAT ALARMI KURULDU: {sym}</b>\n"
            f"• 🎯 <b>Alarm Seviyesi:</b> <code>{format(target_p, p_fmt)} USDT</code> ({note})\n"
            f"• 💰 <b>Güncel Fiyat:</b> <code>{format(curr_p, p_fmt)} USDT</code>\n\n"
            + _build_alarm_radar_status_html(st_a)
        )
        send_telegram_message(
            bot_token,
            chat_id,
            confirm_html,
            reply_markup=build_alarm_radar_inline_keyboard(st_a),
        )

    # 6. Delete or Clear Alarms: al_del:ID or al_clear:all
    elif action == "al_del" and len(parts) >= 2:
        aid = parts[1]
        remove_price_alarm(aid)
        answer_callback_query(bot_token, cq_id, "🗑️ Alarm silindi.")
        state = load_telegram_state()
        html_al = _build_alarm_radar_status_html(state)
        kb_al = build_alarm_radar_inline_keyboard(state)
        if not edit_telegram_message(bot_token, chat_id, msg_id, html_al, reply_markup=kb_al):
            send_telegram_message(bot_token, chat_id, html_al, reply_markup=kb_al)

    elif action == "al_clear":
        state = load_telegram_state()
        state["alarms"] = []
        save_telegram_state(state)
        answer_callback_query(bot_token, cq_id, "🧹 Tüm alarmlar temizlendi.")
        html_al = _build_alarm_radar_status_html(state)
        kb_al = build_alarm_radar_inline_keyboard(state)
        if not edit_telegram_message(bot_token, chat_id, msg_id, html_al, reply_markup=kb_al):
            send_telegram_message(bot_token, chat_id, html_al, reply_markup=kb_al)

    # 7. Radar Toggles & Manual Scan: radar:toggle | radar:session_toggle | radar:scan_now
    elif action == "radar" and len(parts) >= 2:
        sub = parts[1]
        state = load_telegram_state()
        if sub == "toggle":
            state["radar_enabled"] = not bool(state.get("radar_enabled", True))
            save_telegram_state(state)
            status_txt = "🟢 Otomatik Radar AÇILDI!" if state["radar_enabled"] else "🔴 Otomatik Radar KAPATILDI."
            answer_callback_query(bot_token, cq_id, status_txt)
        elif sub == "session_toggle":
            state["auto_session_summary"] = not bool(state.get("auto_session_summary", True))
            save_telegram_state(state)
            status_txt = "🌅 Seans Özeti AÇILDI!" if state["auto_session_summary"] else "⚪ Seans Özeti KAPATILDI."
            answer_callback_query(bot_token, cq_id, status_txt)
        elif sub == "scan_now":
            answer_callback_query(bot_token, cq_id, "📡 Radar taraması başlatıldı, lütfen bekleyin...")
            sent_n = _run_proactive_radar_cycle(bot_token, chat_id, force=True)
            if sent_n == 0:
                send_telegram_message(
                    bot_token,
                    chat_id,
                    "ℹ️ <b>Radar Kontrolü Tamamlandı (4H):</b> Şu an izleme listenizde acil kırılım (4/5+), aşırı balina (>=70) veya patlama sıkışması (>=%80) kriterini tetikleyen coin bulunmuyor.",
                )
            return

        html_al = _build_alarm_radar_status_html(state)
        kb_al = build_alarm_radar_inline_keyboard(state)
        if not edit_telegram_message(bot_token, chat_id, msg_id, html_al, reply_markup=kb_al):
            send_telegram_message(bot_token, chat_id, html_al, reply_markup=kb_al)

    # 8. Coin Picker Menu: coins:TF
    elif action == "coins":
        tf = parts[1] if len(parts) >= 2 else "4H"
        answer_callback_query(bot_token, cq_id, f"🪙 Coin Seçim Menüsü ({tf})")
        wl = _load_shared_watchlist()
        now_hm = time.strftime("%H:%M:%S")
        html_c = (
            f"🪙 <b>AKTİF İZLEME LİSTENİZ ({tf.upper()} DİLİMİ)</b> <i>({now_hm})</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Grafikli özet analizini görmek istediğiniz coinin butonuna dokunun veya alttan zaman dilimini değiştirin:</i>"
        )
        kb_c = build_coin_list_inline_keyboard(wl, tf)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_c, reply_markup=kb_c):
                send_telegram_message(bot_token, chat_id, html_c, reply_markup=kb_c)
        else:
            send_telegram_message(bot_token, chat_id, html_c, reply_markup=kb_c)

    # 9. Parallel Multi-Coin Screener: scan:TF:ONLY_HQ
    elif action == "scan":
        tf = parts[1] if len(parts) >= 2 else "4H"
        only_hq = (parts[2] == "1") if len(parts) >= 3 else False
        answer_callback_query(bot_token, cq_id, f"🔍 [{tf}] Paralel tarama açılıyor...")
        with _CACHE_LOCK:
            cached_s = _SCAN_CACHE.get(tf.lower())
            is_cold_s = (cached_s is None) or ((time.time() - cached_s[0]) > CACHE_TTL_SEC)
        if is_cold_s and not is_photo_msg and msg_id:
            edit_telegram_message(
                bot_token,
                chat_id,
                msg_id,
                f"🔍 <b>[{tf.upper()}]</b> İzleme listesi borsadan paralel taranıyor, lütfen birkaç saniye bekleyin...",
            )
        scan_html, kb_s, _ = _scan_watchlist_parallel(tf, only_high_quality=only_hq)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, scan_html, reply_markup=kb_s):
                send_telegram_message(bot_token, chat_id, scan_html, reply_markup=kb_s)
        else:
            send_telegram_message(bot_token, chat_id, scan_html, reply_markup=kb_s)

    # 10. Global Market & Cash Flow Overview: market:TF
    elif action == "market":
        tf = parts[1] if len(parts) >= 2 else "4H"
        answer_callback_query(bot_token, cq_id, "🌍 Küresel piyasa & nakit akışı açılıyor...")
        with _CACHE_LOCK:
            cached_s = _SCAN_CACHE.get(tf.lower())
            is_cold_s = (cached_s is None) or ((time.time() - cached_s[0]) > CACHE_TTL_SEC)
        if is_cold_s and not is_photo_msg and msg_id:
            edit_telegram_message(
                bot_token,
                chat_id,
                msg_id,
                f"🌍 <b>[{tf.upper()}]</b> Küresel piyasa iklimi ve sıcak para akışı hesaplanıyor...",
            )
        _, _, results = _scan_watchlist_parallel(tf, only_high_quality=False)
        if results:
            sess_tr = results[0]["fc"].session_status_tr
            html_m = format_market_overview_telegram_html(results, sess_tr, tf)
            kb_m = build_screener_inline_keyboard(results, tf, False)
            if not is_photo_msg and msg_id:
                if not edit_telegram_message(bot_token, chat_id, msg_id, html_m, reply_markup=kb_m):
                    send_telegram_message(bot_token, chat_id, html_m, reply_markup=kb_m)
            else:
                send_telegram_message(bot_token, chat_id, html_m, reply_markup=kb_m)

    # 11. Dedicated Perpetual Futures (Vadeli İşlemler) Setup & Chart Report: fut:SYMBOL:TF or fut_ref:SYMBOL:TF
    elif action in ("fut", "fut_ref") and len(parts) >= 2:
        sym = parts[1]
        tf = parts[2] if len(parts) >= 3 else "4H"
        is_ref = action == "fut_ref"
        answer_callback_query(
            bot_token,
            cq_id,
            f"⚡ {sym} ({tf}) Vadeli İşlem Planı & Grafiği hazırlanıyor...",
        )
        df_act, fc_act, _, mtf_sc, curr_p = _compute_full_coin_bundle(sym, tf, force_refresh=is_ref)
        html_fut = format_futures_setup_telegram_html(fc_act, sym, tf, curr_p, mtf_scores=mtf_sc)
        kb_fut = build_futures_setup_inline_keyboard(sym, tf)
        _send_or_update_analysis_with_chart(
            bot_token,
            chat_id,
            df_act,
            fc_act,
            sym,
            tf,
            html_fut,
            kb_fut,
            include_futures_levels=True,
            msg_id=msg_id,
            is_photo_msg=is_photo_msg,
        )

    # 12. Multi-Coin Perpetual Futures Radar Scan: fut_scan:TF
    elif action == "fut_scan":
        tf = parts[1] if len(parts) >= 2 else "4H"
        answer_callback_query(bot_token, cq_id, f"📡 [{tf}] Vadeli İşlem Radarı taranıyor...")
        with _CACHE_LOCK:
            cached_s = _SCAN_CACHE.get(tf.lower())
            is_cold_s = (cached_s is None) or ((time.time() - cached_s[0]) > CACHE_TTL_SEC)
        if is_cold_s and not is_photo_msg and msg_id:
            edit_telegram_message(
                bot_token,
                chat_id,
                msg_id,
                f"📡 <b>[{tf.upper()}]</b> Vadeli İşlem Radarı tüm coinlerde güven notu ve R:R filtresiyle taranıyor...",
            )
        _, _, results = _scan_watchlist_parallel(tf, only_high_quality=False)
        html_fs = format_futures_radar_scan_telegram_html(results, tf)
        kb_fs = build_futures_radar_inline_keyboard(results, tf)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_fs, reply_markup=kb_fs):
                send_telegram_message(bot_token, chat_id, html_fs, reply_markup=kb_fs)
        else:
            send_telegram_message(bot_token, chat_id, html_fs, reply_markup=kb_fs)

    # 13. Support / Resistance Breakout & Trap Radar Scan: brk_scan:TF
    elif action == "brk_scan":
        tf = parts[1] if len(parts) >= 2 else "4H"
        answer_callback_query(bot_token, cq_id, f"🚨 [{tf}] Destek/Direnç Kırılım & Tuzak Radarı taranıyor...")
        with _CACHE_LOCK:
            cached_s = _SCAN_CACHE.get(tf.lower())
            is_cold_s = (cached_s is None) or ((time.time() - cached_s[0]) > CACHE_TTL_SEC)
        if is_cold_s and not is_photo_msg and msg_id:
            edit_telegram_message(
                bot_token,
                chat_id,
                msg_id,
                f"🚨 <b>[{tf.upper()}]</b> Destek/Direnç Kırılım, Tuzak (SFP) ve Retest Radarı tüm coinlerde taranıyor...",
            )
        _, _, results = _scan_watchlist_parallel(tf, only_high_quality=False)
        html_brk = format_breakout_radar_scan_telegram_html(results, tf)
        kb_brk = build_breakout_radar_inline_keyboard(results, tf)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_brk, reply_markup=kb_brk):
                send_telegram_message(bot_token, chat_id, html_brk, reply_markup=kb_brk)
        else:
            send_telegram_message(bot_token, chat_id, html_brk, reply_markup=kb_brk)

    # 14. Watchlist Add / Remove from Analysis Card: wl_add:SYMBOL:TF or wl_del:SYMBOL:TF
    elif action in ("wl_add", "wl_del") and len(parts) >= 2:
        sym = _normalize_symbol(parts[1])
        tf = parts[2] if len(parts) >= 3 else "4H"
        wl = _load_shared_watchlist()
        if action == "wl_add":
            if sym not in wl:
                wl.append(sym)
                _save_shared_watchlist(wl)
                _invalidate_scan_cache()
            answer_callback_query(bot_token, cq_id, f"✅ {sym} izleme listesine eklendi!")
            send_telegram_message(
                bot_token,
                chat_id,
                f"✅ <b>{sym}</b> aktif izleme listenize eklendi! Artık tüm taramalarda ve radarlarda takip edilecek.",
                reply_markup=build_coin_list_inline_keyboard(wl, tf),
            )
        else:
            if len(wl) <= 1 and sym in wl:
                answer_callback_query(bot_token, cq_id, "⚠️ Listede en az 1 coin kalmalıdır!")
                return
            wl = [x for x in wl if x != sym]
            _save_shared_watchlist(wl)
            _invalidate_scan_cache()
            answer_callback_query(bot_token, cq_id, f"🗑️ {sym} izleme listesinden çıkarıldı.")
            send_telegram_message(
                bot_token,
                chat_id,
                f"🗑️ <b>{sym}</b> izleme listenizden çıkarıldı.",
                reply_markup=build_coin_list_inline_keyboard(wl, tf),
            )

    # 15. Interactive Watchlist Management Menu: wl_menu:MODE:TF
    elif action == "wl_menu":
        mode = parts[1] if len(parts) >= 2 else "add"
        tf = parts[2] if len(parts) >= 3 else "4H"
        wl = _load_shared_watchlist()
        if mode == "add":
            answer_callback_query(bot_token, cq_id, "➕ Hızlı Coin Ekleme Menüsü")
            html_wm = (
                f"➕ <b>HIZLI COİN EKLEME PANELİ ({len(wl)} Aktif Coin)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "• Aşağıdaki popüler coinlerden birine dokunarak <b>tek tıkla</b> izleme listenize ekleyebilirsiniz.\n"
                "• Listede olmayan <b>herhangi bir coini</b> eklemek için sohbete doğrudan:\n"
                "<code>/ekle SEMBOL</code> (Örn: <code>/ekle PEPE</code> veya <code>/ekle RENDER FET</code>) yazmanız yeterlidir."
            )
        else:
            answer_callback_query(bot_token, cq_id, "➖ Coin Çıkarma Menüsü")
            html_wm = (
                f"➖ <b>COİN ÇIKARMA PANELİ ({len(wl)} Aktif Coin)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "• İzleme listenizden çıkarmak istediğiniz coinin üzerindeki <b>🗑️ butonuna</b> dokunun.\n"
                "• Komutla çıkarmak için: <code>/cikar SEMBOL</code> yazabilirsiniz."
            )
        kb_wm = build_watchlist_manage_inline_keyboard(wl, mode=mode, timeframe=tf)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_wm, reply_markup=kb_wm):
                send_telegram_message(bot_token, chat_id, html_wm, reply_markup=kb_wm)
        else:
            send_telegram_message(bot_token, chat_id, html_wm, reply_markup=kb_wm)

    # 16. Quick 1-Tap Add/Remove inside Watchlist Management Menu: wl_qadd:SYMBOL:TF or wl_qdel:SYMBOL:TF
    elif action in ("wl_qadd", "wl_qdel") and len(parts) >= 2:
        sym = _normalize_symbol(parts[1])
        tf = parts[2] if len(parts) >= 3 else "4H"
        wl = _load_shared_watchlist()
        if action == "wl_qadd":
            if sym not in wl:
                wl.append(sym)
                _save_shared_watchlist(wl)
                _invalidate_scan_cache()
            answer_callback_query(bot_token, cq_id, f"✅ {sym} listeye eklendi!")
            mode = "add"
            status_line = f"✅ <b>{sym}</b> başarıyla izleme listenize eklendi!"
        else:
            if len(wl) <= 1 and sym in wl:
                answer_callback_query(bot_token, cq_id, "⚠️ Listede en az 1 coin kalmalıdır!")
                return
            wl = [x for x in wl if x != sym]
            _save_shared_watchlist(wl)
            _invalidate_scan_cache()
            answer_callback_query(bot_token, cq_id, f"🗑️ {sym} listeden çıkarıldı!")
            mode = "del"
            status_line = f"🗑️ <b>{sym}</b> izleme listenizden çıkarıldı."

        wl_str = ", ".join(c.replace("/USDT", "") for c in wl)
        html_wm = (
            f"{status_line}\n"
            f"📋 <b>Güncel Liste ({len(wl)} Coin):</b> <code>{wl_str}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>İşleme devam edebilir veya 🔙 Coin Listesine Dön butonuna dokunabilirsiniz:</i>"
        )
        kb_wm = build_watchlist_manage_inline_keyboard(wl, mode=mode, timeframe=tf)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_wm, reply_markup=kb_wm):
                send_telegram_message(bot_token, chat_id, html_wm, reply_markup=kb_wm)
        else:
            send_telegram_message(bot_token, chat_id, html_wm, reply_markup=kb_wm)

    # 17. 1-Tap X (Twitter) Share from Telegram Inline Buttons:
    #     x_post:SYMBOL:TF | x_fut:SYMBOL:TF | x_scan:TF:ONLY_HQ | x_brk_scan:TF | x_fut_scan:TF | x_radar:toggle
    elif action == "x_radar" and len(parts) >= 2:
        sub = parts[1]
        x_st = load_x_state()
        if sub == "toggle":
            x_st["x_auto_radar_enabled"] = not bool(x_st.get("x_auto_radar_enabled", True))
            save_x_state(x_st)
            st_msg = "🐦 X Otomatik Radar AÇILDI!" if x_st["x_auto_radar_enabled"] else "⚪ X Otomatik Radar KAPATILDI."
            answer_callback_query(bot_token, cq_id, st_msg)
        state = load_telegram_state()
        html_al = _build_alarm_radar_status_html(state)
        kb_al = build_alarm_radar_inline_keyboard(state)
        if not edit_telegram_message(bot_token, chat_id, msg_id, html_al, reply_markup=kb_al):
            send_telegram_message(bot_token, chat_id, html_al, reply_markup=kb_al)

    elif action in ("x_post", "x_fut") and len(parts) >= 2:
        sym = _normalize_symbol(parts[1])
        tf = parts[2] if len(parts) >= 3 else "4H"
        is_fut = action == "x_fut"
        answer_callback_query(
            bot_token,
            cq_id,
            f"🐦 {sym} ({tf}) {'Vadeli Planı ' if is_fut else 'Analizi '}ve Grafiği X'te paylaşılıyor...",
        )
        df_act, fc_act, _, mtf_sc, curr_p = _compute_full_coin_bundle(sym, tf)
        png_b = generate_telegram_chart_png(df_act, fc_act, sym, tf, include_futures_levels=is_fut)
        if is_fut:
            tweets = format_futures_setup_x_post(fc_act, sym, tf, curr_p)
            title_s = f"{sym} ({tf}) Vadeli Planı"
        else:
            tweets = format_coin_analysis_x_post(fc_act, sym, tf, curr_p, mtf_scores=mtf_sc)
            title_s = f"{sym} ({tf}) Teknik Analiz"
        ok_x, msg_x, _ = publish_x_content(tweets, photo_bytes=png_b, title=title_s, symbol=sym)
        if ok_x:
            send_telegram_message(bot_token, chat_id, f"🐦 <b>X (Twitter) Paylaşım Durumu:</b>\n{msg_x}")
        else:
            intent_u = build_x_intent_url(tweets[0])
            kb_x_free = {"inline_keyboard": [[{"text": "🐦 Tek Dokunuşla X Uygulamasında Aç & Paylaş (Ücretsiz)", "url": intent_u}]]}
            send_telegram_message(
                bot_token,
                chat_id,
                f"🐦 <b>Ücretsiz X (Twitter) Hazır Gönderi Paketi:</b>\n<i>(X Resmi API Kredisi $0 olduğu için aşağıdaki butona dokunarak X uygulamanızda hazır metinle ücretsiz paylaşabilirsiniz):</i>\n\n<pre>{tweets[0]}</pre>",
                reply_markup=kb_x_free,
            )

    elif action in ("x_scan", "x_brk_scan", "x_fut_scan"):
        tf = parts[1] if len(parts) >= 2 else "4H"
        only_hq = (parts[2] == "1") if (action == "x_scan" and len(parts) >= 3) else False
        answer_callback_query(bot_token, cq_id, f"🐦 [{tf}] Rapor X hesabınızda paylaşılıyor...")
        _, _, results = _scan_watchlist_parallel(tf, only_high_quality=only_hq)
        if action == "x_brk_scan":
            tweets = format_breakout_radar_x_post(results, tf)
            title_s = f"Kırılım Radarı ({tf})"
        elif action == "x_fut_scan":
            tweets = format_futures_radar_x_post(results, tf)
            title_s = f"Vadeli İşlem Radarı ({tf})"
        else:
            tweets = format_screener_x_post(results, tf, only_high_quality=only_hq)
            title_s = f"Çoklu Coin Tarama ({tf})"
        top_png = None
        if results and results[0].get("df") is not None:
            top_png = generate_telegram_chart_png(
                results[0]["df"],
                results[0]["fc"],
                results[0]["symbol"],
                tf,
                include_futures_levels=(action == "x_fut_scan"),
            )
        ok_x, msg_x, _ = publish_x_content(tweets, photo_bytes=top_png, title=title_s, symbol="TARAMA")
        if ok_x:
            send_telegram_message(bot_token, chat_id, f"🐦 <b>X (Twitter) Paylaşım Durumu:</b>\n{msg_x}")
        else:
            intent_u = build_x_intent_url(tweets[0])
            kb_x_free = {"inline_keyboard": [[{"text": "🐦 Tek Dokunuşla X Uygulamasında Aç & Paylaş (Ücretsiz)", "url": intent_u}]]}
            send_telegram_message(
                bot_token,
                chat_id,
                f"🐦 <b>Ücretsiz X (Twitter) Hazır Rapor Paketi:</b>\n\n<pre>{tweets[0]}</pre>",
                reply_markup=kb_x_free,
            )

    elif action == "hunter":
        tf = parts[1] if len(parts) >= 2 else "1H"
        only_unlisted = (parts[2] == "1") if len(parts) >= 3 else False
        force_ref = (parts[3] == "1") if len(parts) >= 4 else False
        answer_callback_query(bot_token, cq_id, f"🐋 Top 80 Piyasa Avcısı [{tf}] taranıyor...")
        if force_ref and not is_photo_msg and msg_id:
            edit_telegram_message(
                bot_token,
                chat_id,
                msg_id,
                f"🐋 <b>[{tf.upper()}]</b> Borsadaki en likit 80 USDT tahtasının gerçek Spot Taker nakit girişleri ve sıkışma enerjileri canlı taranıyor...",
            )
        wl = _load_shared_watchlist()
        rep = MarketWideHunter.scan_market(
            timeframe=tf.lower(),
            universe_size=80,
            min_quote_vol_usd=2_500_000.0,
            top_n=10,
            watchlist=wl,
            force_refresh=force_ref,
        )
        html_h = format_market_hunter_telegram_html(rep, only_unlisted=only_unlisted)
        kb_h = build_market_hunter_inline_keyboard(rep, only_unlisted=only_unlisted)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_h, reply_markup=kb_h):
                send_telegram_message(bot_token, chat_id, html_h, reply_markup=kb_h)
        else:
            send_telegram_message(bot_token, chat_id, html_h, reply_markup=kb_h)

    elif action == "x_hunter":
        tf = parts[1] if len(parts) >= 2 else "1H"
        answer_callback_query(bot_token, cq_id, f"🐦 Top 80 Piyasa Avcısı [{tf}] X'te paylaşılıyor...")
        wl = _load_shared_watchlist()
        rep = MarketWideHunter.scan_market(timeframe=tf.lower(), universe_size=80, watchlist=wl)
        tweets = format_market_hunter_x_post(rep)
        top_png = None
        if rep.top_picks:
            try:
                top_sym = rep.top_picks[0].symbol
                df_top, fc_top, _, _, _ = _compute_full_coin_bundle(top_sym, tf.lower())
                top_png = generate_telegram_chart_png(df_top, fc_top, top_sym, tf.upper(), include_futures_levels=False)
            except Exception:
                top_png = None
        ok_x, msg_x, _ = publish_x_content(tweets, photo_bytes=top_png, title=f"Top 80 Piyasa Avcısı ({tf.upper()})", symbol="AVCI")
        if ok_x:
            send_telegram_message(bot_token, chat_id, f"🐦 <b>X (Twitter) Paylaşım Durumu:</b>\n{msg_x}")
        else:
            intent_u = build_x_intent_url(tweets[0])
            kb_x_free = {"inline_keyboard": [[{"text": "🐦 Tek Dokunuşla X Uygulamasında Aç & Paylaş (Ücretsiz)", "url": intent_u}]]}
            send_telegram_message(
                bot_token,
                chat_id,
                f"🐦 <b>Ücretsiz X Piyasa Avcısı Paketi:</b>\n\n<pre>{tweets[0]}</pre>",
                reply_markup=kb_x_free,
            )

    elif action in ("ai_sum", "ai_ref") and len(parts) >= 2:
        sym = _normalize_symbol(parts[1])
        tf = parts[2] if len(parts) >= 3 else "4H"
        is_ref = action == "ai_ref"
        answer_callback_query(
            bot_token,
            cq_id,
            f"🧠 {sym} ({tf.upper()}) Lokal AI Yönetici & Çelişki Yorumu hazırlanıyor...",
        )
        if not is_photo_msg and msg_id:
            edit_telegram_message(
                bot_token,
                chat_id,
                msg_id,
                f"🧠 <b>{sym} [{tf.upper()}]</b> için Lokal Yapay Zeka (Ollama) yönetici özeti ve çelişki denetimi üretiliyor...",
            )
        _, fc_act, _, mtf_sc, curr_p = _compute_full_coin_bundle(sym, tf.lower(), force_refresh=is_ref)
        rep_ai = generate_ai_executive_summary(
            symbol=sym,
            timeframe=tf.upper(),
            current_price=curr_p,
            fc=fc_act,
            mtf_scores=mtf_sc,
            force_refresh=is_ref,
        )
        html_ai = format_ai_summary_telegram_html(rep_ai, current_price=curr_p)
        kb_ai = build_ai_summary_inline_keyboard(sym, tf.upper())
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_ai, reply_markup=kb_ai):
                send_telegram_message(bot_token, chat_id, html_ai, reply_markup=kb_ai)
        else:
            send_telegram_message(bot_token, chat_id, html_ai, reply_markup=kb_ai)

    else:
        answer_callback_query(bot_token, cq_id, "✅ İşlem alındı.")


def _map_reply_keyboard_text(raw_text: str) -> str:
    """
    Maps persistent bottom Reply Keyboard button texts to slash commands reliably,
    defaulting all scans and radars to 4H.
    """
    t = raw_text.strip()
    t_low = t.lower()
    if "coin seç" in t_low or "coin listesi" in t_low or t.startswith("🪙"):
        return "/liste"
    if "ai yönetici" in t_low or "ai özet" in t_low or t.startswith("🧠"):
        return "/ai"
    if "avcı" in t_low or "avci" in t_low or "top 80" in t_low or t.startswith("🐋"):
        return "/avci 1h"
    if "sinyal karnesi" in t_low or t.startswith("📊"):
        return "/karne"
    if "kırılım" in t_low or "kirilim" in t_low or t.startswith("🚨"):
        return "/kirilim 4h"
    if "vadeli" in t_low or t.startswith("⚡"):
        return "/vadelitara 4h"
    if "tümünü tara" in t_low or t.startswith("🚀"):
        return "/tara 4h"
    if "fırsatlar" in t_low or "firsatlar" in t_low or t.startswith("🎯"):
        return "/firsat 4h"
    if "piyasa" in t_low or "nakit özeti" in t_low or t.startswith("🌍"):
        return "/piyasa 4h"
    if "alarmlarım" in t_low or "alarmlarim" in t_low or t.startswith("⏰"):
        return "/alarmlar"
    if "komutlar" in t_low or "yardım" in t_low or "yardim" in t_low or t.startswith("📋"):
        return "/yardim"
    # Support natural slashless AI requests like: "ai BTC", "ai analiz ONDO 1h", "BTC ai", "ONDO ai analiz"
    tokens = t.split()
    low_tokens = [tok.lower() for tok in tokens]
    if low_tokens and low_tokens[0] in ("ai", "yapayzeka", "ozet", "özet"):
        rest = [tok for tok in tokens[1:] if tok.lower() not in ("analiz", "analizi", "yorum", "yorumu", "özet", "ozet")]
        return ("/ai " + " ".join(rest)).strip()
    if len(low_tokens) >= 2 and ("ai" in low_tokens[1:] or "yapay" in low_tokens[1:]):
        coin_tok = tokens[0]
        tf_tok = next((tok for tok in low_tokens[1:] if tok in ("15m", "1h", "4h", "1d")), "4h")
        return f"/ai {coin_tok} {tf_tok}"
    return t


def _handle_message_command(bot_token: str, chat_id: str, raw_text: str) -> None:
    text = _map_reply_keyboard_text(raw_text)
    parts = text.split()
    if not parts:
        return
    cmd = parts[0].lower().split("@")[0]

    try:
        if cmd in ("/start", "/yardim", "/help", "/komutlar", "/menu"):
            send_telegram_message(
                bot_token,
                chat_id,
                _build_help_html(chat_id),
                reply_markup=build_main_reply_keyboard(),
            )
            wl = _load_shared_watchlist()
            send_telegram_message(
                bot_token,
                chat_id,
                "👇 <b>Hızlı Başlangıç (Varsayılan: 4H):</b> Analiz etmek istediğiniz coine dokunun:",
                reply_markup=build_coin_list_inline_keyboard(wl, "4H"),
            )

        elif cmd in ("/ai", "/aiyorum", "/ozet", "ai"):
            if len(parts) < 2:
                wl = _load_shared_watchlist()
                ai_rows: List[List[Dict[str, str]]] = []
                row_buf: List[Dict[str, str]] = []
                for sym_w in wl[:12]:
                    row_buf.append({"text": f"🧠 {sym_w.split('/')[0]}", "callback_data": f"ai_sum:{sym_w}:4H"})
                    if len(row_buf) == 3:
                        ai_rows.append(row_buf)
                        row_buf = []
                if row_buf:
                    ai_rows.append(row_buf)
                send_telegram_message(
                    bot_token,
                    chat_id,
                    "🧠 <b>LOKAL AI YÖNETİCİ ÖZETİ &amp; ÇELİŞKİ DENETİMİ (4H)</b>\n"
                    "<i>AI yorumunu görmek istediğiniz coine dokunun veya doğrudan <code>/ai BTC 4h</code> / <code>ai ONDO</code> yazın:</i>",
                    reply_markup={"inline_keyboard": ai_rows},
                )
            else:
                sym = _normalize_symbol(parts[1])
                tf = parts[2].lower() if (len(parts) >= 3 and parts[2].lower() in ("15m", "1h", "4h", "1d")) else "4h"
                send_telegram_message(
                    bot_token,
                    chat_id,
                    f"🧠 <b>{sym} [{tf.upper()}]</b> için Lokal AI Yönetici Özeti &amp; Çelişki Yorumu hazırlanıyor...",
                )
                _, fc_act, _, mtf_sc, curr_p = _compute_full_coin_bundle(sym, tf)
                rep_ai = generate_ai_executive_summary(
                    symbol=sym,
                    timeframe=tf.upper(),
                    current_price=curr_p,
                    fc=fc_act,
                    mtf_scores=mtf_sc,
                )
                send_telegram_message(
                    bot_token,
                    chat_id,
                    format_ai_summary_telegram_html(rep_ai, current_price=curr_p),
                    reply_markup=build_ai_summary_inline_keyboard(sym, tf.upper()),
                )

        elif cmd == "/analiz":
            sym = _normalize_symbol(parts[1]) if len(parts) >= 2 else "ONDO/USDT"
            tf = parts[2].lower() if len(parts) >= 3 else "4h"
            report_html, kb, df_act, fc_act, _ = _analyze_single_coin(sym, tf)
            _send_or_update_analysis_with_chart(
                bot_token,
                chat_id,
                df_act,
                fc_act,
                sym,
                tf,
                report_html,
                kb,
                include_futures_levels=False,
            )

        elif cmd in ("/grafik", "/chart"):
            sym = _normalize_symbol(parts[1]) if len(parts) >= 2 else "ONDO/USDT"
            tf = parts[2].lower() if len(parts) >= 3 else "4h"
            df_act, fc_act, _, _, curr_p = _compute_full_coin_bundle(sym, tf)
            png_b = generate_telegram_chart_png(df_act, fc_act, sym, tf, include_futures_levels=False)
            kb = build_analysis_inline_keyboard(sym, tf.upper())
            if png_b:
                p_fmt = ",.4f" if curr_p < 10.0 else ",.2f"
                sup_tier = getattr(fc_act, "nearest_support_tier_tr", "🟢 Sıradan Destek")
                res_tier = getattr(fc_act, "nearest_resistance_tier_tr", "🔴 Sıradan Direnç")
                sup_s = format(fc_act.nearest_support, p_fmt) if fc_act.nearest_support else "N/A"
                res_s = format(fc_act.nearest_resistance, p_fmt) if fc_act.nearest_resistance else "N/A"
                cap = (
                    f"🖼️ <b>{sym} [{tf.upper()}] GRAFİK &amp; DESTEK/DİRENÇLER</b>\n"
                    f"💰 <b>Fiyat:</b> <code>{format(curr_p, p_fmt)} USDT</code> | 🚦 <b>Hazırlık:</b> {fc_act.readiness_score_5}/5\n"
                    f"• <b>{sup_tier}:</b> <code>{sup_s}</code> | <b>{res_tier}:</b> <code>{res_s}</code>\n"
                    f"• 🧲 <b>Mıknatıs (POC):</b> <code>{format(fc_act.poc_price, p_fmt)}</code>"
                )
                send_telegram_photo(bot_token, chat_id, png_b, caption_html=cap, reply_markup=kb)
            else:
                send_telegram_message(bot_token, chat_id, "❌ Grafik oluşturulamadı.", reply_markup=kb)

        elif cmd in ("/miknatis", "/likidasyon", "/poc"):
            sym = _normalize_symbol(parts[1]) if len(parts) >= 2 else "ONDO/USDT"
            _, _, tf_fcs, _, curr_p = _compute_full_coin_bundle(sym, "4h")
            html_liq = format_liquidation_magnet_telegram_html(sym, tf_fcs, curr_p)
            send_telegram_message(
                bot_token,
                chat_id,
                html_liq,
                reply_markup=build_analysis_inline_keyboard(sym, "4H"),
            )

        elif cmd in ("/kasa", "/risk", "/pozisyon"):
            sym = _normalize_symbol(parts[1]) if len(parts) >= 2 else "ONDO/USDT"
            cap_val = 1000.0
            risk_p = 1.0
            if len(parts) >= 3:
                try:
                    cap_val = float(parts[2])
                except Exception:
                    cap_val = 1000.0
            if len(parts) >= 4:
                try:
                    risk_p = float(parts[3])
                except Exception:
                    risk_p = 1.0
            _, fc_act, _, _, curr_p = _compute_full_coin_bundle(sym, "4h")
            html_kasa = format_position_size_telegram_html(fc_act, sym, "4H", curr_p, capital_usd=cap_val, risk_pct=risk_p)
            send_telegram_message(
                bot_token,
                chat_id,
                html_kasa,
                reply_markup=_build_kasa_inline_keyboard(sym, "4H", cap_val),
            )

        elif cmd in ("/vadeli", "/futures"):
            if len(parts) < 2 or parts[1].lower() in ("15m", "1h", "4h", "1d", "tara"):
                tf = parts[1].lower() if (len(parts) >= 2 and parts[1].lower() in ("15m", "1h", "4h", "1d")) else "4h"
                send_telegram_message(
                    bot_token,
                    chat_id,
                    f"📡 <b>[{tf.upper()}]</b> Vadeli İşlem (Futures) Radarı tüm coinleri güven notu ve R:R filtresiyle tarıyor...",
                )
                _, _, results = _scan_watchlist_parallel(tf, only_high_quality=False)
                html_fs = format_futures_radar_scan_telegram_html(results, tf)
                kb_fs = build_futures_radar_inline_keyboard(results, tf)
                send_telegram_message(bot_token, chat_id, html_fs, reply_markup=kb_fs)
            else:
                sym = _normalize_symbol(parts[1])
                tf = parts[2].lower() if len(parts) >= 3 else "4h"
                df_act, fc_act, _, mtf_sc, curr_p = _compute_full_coin_bundle(sym, tf)
                html_fut = format_futures_setup_telegram_html(fc_act, sym, tf, curr_p, mtf_scores=mtf_sc)
                kb_fut = build_futures_setup_inline_keyboard(sym, tf)
                _send_or_update_analysis_with_chart(
                    bot_token,
                    chat_id,
                    df_act,
                    fc_act,
                    sym,
                    tf,
                    html_fut,
                    kb_fut,
                    include_futures_levels=True,
                )

        elif cmd in ("/vadelitara", "/vadeliradar"):
            tf = parts[1].lower() if len(parts) >= 2 else "4h"
            send_telegram_message(
                bot_token,
                chat_id,
                f"📡 <b>[{tf.upper()}]</b> Vadeli İşlem (Futures) Radarı tüm coinleri güven notu ve R:R filtresiyle tarıyor...",
            )
            _, _, results = _scan_watchlist_parallel(tf, only_high_quality=False)
            html_fs = format_futures_radar_scan_telegram_html(results, tf)
            kb_fs = build_futures_radar_inline_keyboard(results, tf)
            send_telegram_message(bot_token, chat_id, html_fs, reply_markup=kb_fs)

        elif cmd in ("/kirilim", "/kirilimtara", "/breakout"):
            tf = parts[1].lower() if (len(parts) >= 2 and parts[1].lower() in ("15m", "1h", "4h", "1d")) else "4h"
            send_telegram_message(
                bot_token,
                chat_id,
                f"🚨 <b>[{tf.upper()}]</b> Destek/Direnç Kırılım, Tuzak (SFP) ve Retest Radarı taranıyor...",
            )
            _, _, results = _scan_watchlist_parallel(tf, only_high_quality=False)
            html_brk = format_breakout_radar_scan_telegram_html(results, tf)
            kb_brk = build_breakout_radar_inline_keyboard(results, tf)
            send_telegram_message(bot_token, chat_id, html_brk, reply_markup=kb_brk)

        elif cmd == "/tara":
            tf = parts[1].lower() if len(parts) >= 2 else "4h"
            send_telegram_message(
                bot_token,
                chat_id,
                f"🔍 <b>[{tf.upper()}]</b> Paralel çoklu coin taraması yapılıyor...",
            )
            scan_html, kb_s, _ = _scan_watchlist_parallel(tf, only_high_quality=False)
            send_telegram_message(bot_token, chat_id, scan_html, reply_markup=kb_s)

        elif cmd == "/firsat":
            tf = parts[1].lower() if len(parts) >= 2 else "4h"
            send_telegram_message(
                bot_token,
                chat_id,
                f"🎯 <b>[{tf.upper()}]</b> En güçlü hazırlık onaylı ve balina izli fırsatlar filtreleniyor...",
            )
            scan_html, kb_s, _ = _scan_watchlist_parallel(tf, only_high_quality=True)
            send_telegram_message(bot_token, chat_id, scan_html, reply_markup=kb_s)

        elif cmd in ("/piyasa", "/nakit", "/makro"):
            tf = parts[1].lower() if len(parts) >= 2 else "4h"
            send_telegram_message(bot_token, chat_id, "🌍 Küresel piyasa iklimi ve sıcak para akışı hesaplanıyor...")
            _, _, results = _scan_watchlist_parallel(tf, only_high_quality=False)
            if results:
                sess_tr = results[0]["fc"].session_status_tr
                html_m = format_market_overview_telegram_html(results, sess_tr, tf)
                kb_m = build_screener_inline_keyboard(results, tf, False)
                send_telegram_message(bot_token, chat_id, html_m, reply_markup=kb_m)

        elif cmd == "/alarm":
            if len(parts) < 3:
                st_a = load_telegram_state()
                send_telegram_message(
                    bot_token,
                    chat_id,
                    _build_alarm_radar_status_html(st_a),
                    reply_markup=build_alarm_radar_inline_keyboard(st_a),
                )
            else:
                sym = _normalize_symbol(parts[1])
                try:
                    target_p = float(parts[2].replace(",", "."))
                    cfg_a = AnalysisConfig(exchange=ExchangeConfig(symbol=sym, timeframe="15m", limit=5))
                    df_a, _ = CryptoDataFetcher(cfg_a.exchange).fetch_ohlcv(allow_synthetic_fallback=False)
                    curr_p = float(df_a["close"].iloc[-1])
                    entry = add_price_alarm(sym, target_p, curr_p, chat_id=chat_id)
                    p_fmt = ",.4f" if target_p < 10.0 else ",.2f"
                    st_a = load_telegram_state()
                    send_telegram_message(
                        bot_token,
                        chat_id,
                        f"✅ <b>Fiyat Alarmı Kuruldu!</b>\n• Coin: <b>{sym}</b>\n• Hedef: <code>{format(target_p, p_fmt)} USDT</code> ({entry['note']})\n\n"
                        + _build_alarm_radar_status_html(st_a),
                        reply_markup=build_alarm_radar_inline_keyboard(st_a),
                    )
                except Exception:
                    send_telegram_message(bot_token, chat_id, "⚠️ Geçerli bir sembol ve fiyat girin. Örnek: <code>/alarm ONDO 0.3620</code>")

        elif cmd in ("/alarmlar", "/radar"):
            st_a = load_telegram_state()
            if len(parts) >= 2:
                arg = parts[1].lower()
                if arg in ("ac", "on", "aktif"):
                    st_a["radar_enabled"] = True
                    save_telegram_state(st_a)
                elif arg in ("kapat", "off", "pasif"):
                    st_a["radar_enabled"] = False
                    save_telegram_state(st_a)
            send_telegram_message(
                bot_token,
                chat_id,
                _build_alarm_radar_status_html(st_a),
                reply_markup=build_alarm_radar_inline_keyboard(st_a),
            )

        elif cmd in ("/liste", "/sec", "/coinler"):
            wl = _load_shared_watchlist()
            send_telegram_message(
                bot_token,
                chat_id,
                "🪙 <b>AKTİF İZLEME LİSTENİZ (4H)</b>\n<i>Grafikli özet analizini açmak istediğiniz coinin butonuna dokunun veya alttan coin ekleyip çıkarın:</i>",
                reply_markup=build_coin_list_inline_keyboard(wl, "4H"),
            )

        elif cmd in ("/ekle", "/add", "ekle"):
            wl = _load_shared_watchlist()
            if len(parts) < 2:
                html_wm = (
                    f"➕ <b>HIZLI COİN EKLEME PANELİ ({len(wl)} Aktif Coin)</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "• Aşağıdaki popüler coinlerden birine dokunarak <b>tek tıkla</b> izleme listenize ekleyebilirsiniz.\n"
                    "• Listede olmayan <b>herhangi bir coini</b> eklemek için sohbete doğrudan:\n"
                    "<code>/ekle SEMBOL</code> (Örn: <code>/ekle PEPE</code> veya <code>/ekle RENDER FET</code>) yazmanız yeterlidir."
                )
                send_telegram_message(
                    bot_token,
                    chat_id,
                    html_wm,
                    reply_markup=build_watchlist_manage_inline_keyboard(wl, mode="add", timeframe="4H"),
                )
            else:
                added_syms = []
                already_syms = []
                invalid_syms = []
                raw_coins = [c.strip() for p in parts[1:] for c in p.split(",") if c.strip()]
                for raw_c in raw_coins:
                    sym = _normalize_symbol(raw_c)
                    if sym in wl:
                        already_syms.append(sym)
                    elif _validate_coin_on_exchange(sym):
                        wl.append(sym)
                        added_syms.append(sym)
                    else:
                        invalid_syms.append(sym)

                if added_syms:
                    _save_shared_watchlist(wl)
                    _invalidate_scan_cache()

                msg_lines = []
                if added_syms:
                    msg_lines.append(f"✅ <b>Eklendi:</b> {', '.join(added_syms)} artık tüm tarama ve radarlarda takip edilecek!")
                if already_syms:
                    msg_lines.append(f"ℹ️ <b>Zaten Listede:</b> {', '.join(already_syms)}")
                if invalid_syms:
                    msg_lines.append(f"⚠️ <b>Borsada Doğrulanamadı:</b> {', '.join(invalid_syms)} (Sembol adını kontrol edin)")

                send_telegram_message(
                    bot_token,
                    chat_id,
                    "\n".join(msg_lines) if msg_lines else "ℹ️ Eklenecek sembol belirtilmedi.",
                    reply_markup=build_coin_list_inline_keyboard(wl, "4H"),
                )

        elif cmd in ("/cikar", "/çıkar", "/sil", "cikar", "çıkar", "sil"):
            wl = _load_shared_watchlist()
            if len(parts) < 2:
                html_wm = (
                    f"➖ <b>COİN ÇIKARMA PANELİ ({len(wl)} Aktif Coin)</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "• İzleme listenizden çıkarmak istediğiniz coinin üzerindeki <b>🗑️ butonuna</b> dokunun.\n"
                    "• Komutla çıkarmak için: <code>/cikar SEMBOL</code> yazabilirsiniz."
                )
                send_telegram_message(
                    bot_token,
                    chat_id,
                    html_wm,
                    reply_markup=build_watchlist_manage_inline_keyboard(wl, mode="del", timeframe="4H"),
                )
            else:
                raw_coins = [c.strip() for p in parts[1:] for c in p.split(",") if c.strip()]
                removed_syms = []
                for raw_c in raw_coins:
                    sym = _normalize_symbol(raw_c)
                    if sym in wl and len(wl) > 1:
                        wl = [x for x in wl if x != sym]
                        removed_syms.append(sym)
                if removed_syms:
                    _save_shared_watchlist(wl)
                    _invalidate_scan_cache()
                    msg_txt = f"🗑️ <b>Çıkarıldı:</b> {', '.join(removed_syms)} izleme listenizden kaldırıldı."
                else:
                    msg_txt = "ℹ️ Belirtilen coin listede bulunamadı veya listede en az 1 coin kalmalıdır."
                send_telegram_message(
                    bot_token,
                    chat_id,
                    msg_txt,
                    reply_markup=build_coin_list_inline_keyboard(wl, "4H"),
                )

        elif cmd in ("/x", "/tweet", "/xpaylas"):
            sym = _normalize_symbol(parts[1]) if len(parts) >= 2 else "ONDO/USDT"
            tf = parts[2].lower() if len(parts) >= 3 else "4h"
            send_telegram_message(bot_token, chat_id, f"🐦 <b>{sym} [{tf.upper()}]</b> analizi ve grafiği X (Twitter) hesabınızda paylaşılıyor...")
            df_act, fc_act, _, mtf_sc, curr_p = _compute_full_coin_bundle(sym, tf)
            png_b = generate_telegram_chart_png(df_act, fc_act, sym, tf, include_futures_levels=False)
            tweets = format_coin_analysis_x_post(fc_act, sym, tf, curr_p, mtf_scores=mtf_sc)
            ok_x, msg_x, _ = publish_x_content(tweets, photo_bytes=png_b, title=f"{sym} ({tf.upper()}) Analiz", symbol=sym)
            send_telegram_message(
                bot_token,
                chat_id,
                f"🐦 <b>X Paylaşım Sonucu:</b>\n{msg_x}",
                reply_markup=build_analysis_inline_keyboard(sym, tf.upper()),
            )

        elif cmd in ("/xvadeli", "/xfutures"):
            sym = _normalize_symbol(parts[1]) if len(parts) >= 2 else "ONDO/USDT"
            tf = parts[2].lower() if len(parts) >= 3 else "4h"
            send_telegram_message(bot_token, chat_id, f"🐦 <b>{sym} [{tf.upper()}]</b> Vadeli İşlem Planı ve grafiği X'te paylaşılıyor...")
            df_act, fc_act, _, _, curr_p = _compute_full_coin_bundle(sym, tf)
            png_b = generate_telegram_chart_png(df_act, fc_act, sym, tf, include_futures_levels=True)
            tweets = format_futures_setup_x_post(fc_act, sym, tf, curr_p)
            ok_x, msg_x, _ = publish_x_content(tweets, photo_bytes=png_b, title=f"{sym} ({tf.upper()}) Vadeli Plan", symbol=sym)
            send_telegram_message(
                bot_token,
                chat_id,
                f"🐦 <b>X Vadeli Paylaşım Sonucu:</b>\n{msg_x}",
                reply_markup=build_futures_setup_inline_keyboard(sym, tf.upper()),
            )

        elif cmd in ("/xtara", "/xkirilim", "/xpiyasa"):
            tf = parts[1].lower() if len(parts) >= 2 else "4h"
            send_telegram_message(bot_token, chat_id, f"🐦 <b>[{tf.upper()}]</b> Rapor hazırlanıp X hesabınızda paylaşılıyor...")
            _, _, results = _scan_watchlist_parallel(tf, only_high_quality=False)
            if cmd == "/xkirilim":
                tweets = format_breakout_radar_x_post(results, tf)
                title_s = f"Kırılım Radarı ({tf.upper()})"
            elif cmd == "/xpiyasa" and results:
                tweets = format_market_overview_x_post(results, results[0]["fc"].session_status_tr, tf)
                title_s = f"Piyasa Özeti ({tf.upper()})"
            else:
                tweets = format_screener_x_post(results, tf, False)
                title_s = f"Tarama Özeti ({tf.upper()})"
            top_png = None
            if results and results[0].get("df") is not None:
                top_png = generate_telegram_chart_png(results[0]["df"], results[0]["fc"], results[0]["symbol"], tf, include_futures_levels=False)
            ok_x, msg_x, _ = publish_x_content(tweets, photo_bytes=top_png, title=title_s, symbol="RAPOR")
            send_telegram_message(bot_token, chat_id, f"🐦 <b>X Paylaşım Sonucu:</b>\n{msg_x}")

        elif cmd in ("/avci", "/hunter", "/tara80"):
            tf = "1h"
            only_unlisted = False
            for arg in parts[1:]:
                a_low = arg.lower()
                if a_low in ("1h", "4h"):
                    tf = a_low
                elif a_low in ("yeni", "kesif", "keşif", "new"):
                    only_unlisted = True
            send_telegram_message(
                bot_token,
                chat_id,
                f"🐋 <b>[{tf.upper()}]</b> Borsadaki en likit 80 USDT tahtasının gerçek Spot Taker nakit girişleri, Z-Skorları ve sıkışma enerjileri taranıyor...",
            )
            wl = _load_shared_watchlist()
            rep = MarketWideHunter.scan_market(
                timeframe=tf,
                universe_size=80,
                min_quote_vol_usd=2_500_000.0,
                top_n=10,
                watchlist=wl,
            )
            html_h = format_market_hunter_telegram_html(rep, only_unlisted=only_unlisted)
            kb_h = build_market_hunter_inline_keyboard(rep, only_unlisted=only_unlisted)
            send_telegram_message(bot_token, chat_id, html_h, reply_markup=kb_h)

        elif cmd == "/xavci":
            tf = parts[1].lower() if (len(parts) >= 2 and parts[1].lower() in ("1h", "4h")) else "1h"
            send_telegram_message(bot_token, chat_id, f"🐦 <b>[{tf.upper()}]</b> Top 80 Piyasa Avcısı raporu hazırlanıp X'te paylaşılıyor...")
            wl = _load_shared_watchlist()
            rep = MarketWideHunter.scan_market(timeframe=tf, universe_size=80, watchlist=wl)
            tweets = format_market_hunter_x_post(rep)
            top_png = None
            if rep.top_picks:
                try:
                    top_sym = rep.top_picks[0].symbol
                    df_top, fc_top, _, _, _ = _compute_full_coin_bundle(top_sym, tf)
                    top_png = generate_telegram_chart_png(df_top, fc_top, top_sym, tf.upper(), include_futures_levels=False)
                except Exception:
                    top_png = None
            ok_x, msg_x, _ = publish_x_content(tweets, photo_bytes=top_png, title=f"Top 80 Piyasa Avcısı ({tf.upper()})", symbol="AVCI")
            if ok_x:
                send_telegram_message(bot_token, chat_id, f"🐦 <b>X Paylaşım Sonucu:</b>\n{msg_x}")
            else:
                intent_u = build_x_intent_url(tweets[0])
                kb_x_free = {"inline_keyboard": [[{"text": "🐦 Piyasa Avcısı Raporunu X'te Aç & Paylaş", "url": intent_u}]]}
                send_telegram_message(
                    bot_token,
                    chat_id,
                    f"🐦 <b>Ücretsiz X Piyasa Avcısı Paketi:</b>\n\n<pre>{tweets[0]}</pre>",
                    reply_markup=kb_x_free,
                )

        elif cmd in ("/karne", "/performans", "/ledger"):
            # Refresh open signals against current watchlist before showing scorecard
            try:
                _scan_watchlist_parallel("4h", only_high_quality=False)
            except Exception:
                pass
            sc = SignalLedger().get_scorecard(days=30)
            html_sc = format_ledger_telegram_html(sc)
            send_telegram_message(bot_token, chat_id, html_sc)

        elif cmd == "/xkarne":
            sc = SignalLedger().get_scorecard(days=30)
            tweets = format_ledger_scorecard_x_post(sc)
            ok_x, msg_x, _ = publish_x_content(tweets, photo_bytes=None, title="Canlı Sinyal Karnesi (30G)", symbol="KARNE")
            if ok_x:
                send_telegram_message(bot_token, chat_id, f"🐦 <b>X Paylaşım Sonucu:</b>\n{msg_x}")
            else:
                intent_u = build_x_intent_url(tweets[0])
                kb_x_free = {"inline_keyboard": [[{"text": "🐦 Sinyal Karnesini X Uygulamasında Aç & Paylaş", "url": intent_u}]]}
                send_telegram_message(
                    bot_token,
                    chat_id,
                    f"🐦 <b>Ücretsiz X Sinyal Karnesi Paketi:</b>\n\n<pre>{tweets[0]}</pre>",
                    reply_markup=kb_x_free,
                )

        elif not cmd.startswith("/") and 2 <= len(parts[0]) <= 12:
            sym = _normalize_symbol(parts[0])
            tf = parts[1].lower() if len(parts) >= 2 else "4h"
            report_html, kb, df_act, fc_act, _ = _analyze_single_coin(sym, tf)
            _send_or_update_analysis_with_chart(
                bot_token,
                chat_id,
                df_act,
                fc_act,
                sym,
                tf,
                report_html,
                kb,
                include_futures_levels=False,
            )

    except Exception as cmd_err:
        _log(f"Komut işleme hatası ({text}): {cmd_err}")
        wl = _load_shared_watchlist()
        send_telegram_message(
            bot_token,
            chat_id,
            "⚠️ <b>Sembol Borsada Bulunamadı veya Veri Alınamadı:</b>\n"
            f"Girilen komut/coin (<code>{text}</code>) borsada doğrulanamadı. Lütfen yazımı kontrol edin veya aşağıdaki listeden dokunarak seçin:",
            reply_markup=build_coin_list_inline_keyboard(wl, "4H"),
        )


def _safe_callback_worker(bot_token: str, cq: Dict[str, Any], cq_chat_id: str) -> None:
    try:
        _handle_callback_query(bot_token, cq)
    except Exception as cq_err:
        import traceback
        _log(f"Callback hatası ({cq.get('data')}): {cq_err}\n{traceback.format_exc()}")
        if cq_chat_id:
            send_telegram_message(
                bot_token,
                cq_chat_id,
                f"⚠️ İstek işlenirken geçici bir borsa/veri hatası oluştu ({cq_err}). Lütfen tekrar dokunun.",
            )


# ===========================================================================
# MAIN 24/7 POLLING & PROACTIVE RADAR LOOP
# ===========================================================================
def run_polling_bot(bot_token: str) -> None:
    # Ensure no older duplicate instance is polling at the same time
    running, old_pid = is_bot_running()
    if running and old_pid and old_pid != os.getpid():
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(old_pid), "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        except Exception:
            pass

    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass

    _log(f"🤖 Akıllı Kripto İnteraktif Telegram Botu & Radar Başlatıldı (PID: {os.getpid()})!")
    offset = 0
    last_alarm_check = 0.0
    last_radar_check = time.time()
    worker_pool = ThreadPoolExecutor(max_workers=6)

    while True:
        try:
            now_t = time.time()
            saved_cfg = load_telegram_config()
            latest_tok = saved_cfg.get("bot_token", "").strip()
            if latest_tok and latest_tok != bot_token:
                _log("🔄 Yeni Telegram Bot Token algılandı, canlı olarak güncellendi!")
                bot_token = latest_tok
            auth_chat_id = saved_cfg.get("chat_id", "").strip()

            # 1. Background Price Alarm & Session Bulletin Check (every 30s)
            if (now_t - last_alarm_check) >= 30.0:
                last_alarm_check = now_t
                if bot_token:
                    worker_pool.submit(_check_price_alarms, bot_token, auth_chat_id)
                if auth_chat_id or is_x_configured():
                    worker_pool.submit(_check_auto_session_bulletin, bot_token, auth_chat_id)

            # 2. Background 24/7 Smart Breakout/Whale/Squeeze Radar (Telegram + X Auto-Publisher)
            state_curr = load_telegram_state()
            x_state_curr = load_x_state()
            radar_int = float(state_curr.get("radar_interval_sec", 600))
            tg_radar_ready = bool(bot_token and auth_chat_id and state_curr.get("radar_enabled", True))
            x_radar_ready = bool(is_x_configured() and x_state_curr.get("x_auto_radar_enabled", True))
            if (tg_radar_ready or x_radar_ready) and (now_t - last_radar_check) >= radar_int:
                last_radar_check = now_t
                worker_pool.submit(_run_proactive_radar_cycle, bot_token, auth_chat_id, False)

            if not bot_token:
                # X-only mode (no Telegram Bot Token configured): sleep 10s between background radar checks
                time.sleep(10)
                continue

            # 3. Poll Telegram Updates (messages + callback_query touch buttons) — Open to ALL users
            url = (
                f"https://api.telegram.org/bot{bot_token}/getUpdates"
                f"?timeout=12&offset={offset}&allowed_updates=%5B%22message%22,%22callback_query%22%5D"
            )
            with urllib.request.urlopen(url, timeout=18) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok"):
                time.sleep(2)
                continue

            for upd in data.get("result", []):
                offset = upd["update_id"] + 1

                # Handle Inline Touch Button Taps concurrently (Open to everyone)
                if "callback_query" in upd:
                    cq = upd["callback_query"]
                    cq_chat_id = str((cq.get("message") or {}).get("chat", {}).get("id", ""))
                    worker_pool.submit(_safe_callback_worker, bot_token, cq, cq_chat_id)
                    continue

                msg = upd.get("message") or upd.get("edited_message") or {}
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = str(msg.get("text", "")).strip()
                if not chat_id or not text:
                    continue

                if not auth_chat_id:
                    auth_chat_id = chat_id
                    save_telegram_config(bot_token, chat_id)

                worker_pool.submit(_handle_message_command, bot_token, chat_id, text)

        except KeyboardInterrupt:
            _log("👋 Telegram Botu durduruldu.")
            break
        except Exception as e:
            err_s = str(e)
            _log(f"⚠️ Geçici bağlantı uyarısı: {err_s}")
            if "401" in err_s or "409" in err_s:
                time.sleep(10)
            else:
                time.sleep(3)


if __name__ == "__main__":
    cfg = load_telegram_config()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("bot_token", "")
    if not token and not is_x_configured():
        print("❗ Telegram Bot Token veya X (Twitter) API Anahtarı bulunamadı.")
        print("Lütfen Streamlit arayüzünün sol menüsünden Telegram Bot Token veya X API Anahtarlarınızı kaydedin.")
        sys.exit(1)
    run_polling_bot(token)
