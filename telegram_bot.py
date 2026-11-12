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
  10. Single-instance PID lock & Open access for all users and groups
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
from src.patterns import CandlestickPatternDetector
from src.signals import MarketForecast, SignalEngine
from src.telegram_notifier import (
    PID_FILE,
    add_price_alarm,
    answer_callback_query,
    build_alarm_radar_inline_keyboard,
    build_analysis_inline_keyboard,
    build_coin_list_inline_keyboard,
    build_futures_radar_inline_keyboard,
    build_futures_setup_inline_keyboard,
    build_main_reply_keyboard,
    build_screener_inline_keyboard,
    edit_telegram_message,
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
        WATCHLIST_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
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


def _compute_full_coin_bundle(
    symbol: str,
    timeframe: str = "1h",
    allow_synthetic_fallback: bool = False,
    force_refresh: bool = False,
) -> Tuple[pd.DataFrame, MarketForecast, Dict[str, MarketForecast], Dict[str, float], float]:
    tf = timeframe.lower() if timeframe.lower() in ("15m", "1h", "4h", "1d") else "1h"
    tf_key = tf.upper()
    sym_key = symbol.upper()
    now_t = time.time()

    if not force_refresh:
        with _CACHE_LOCK:
            cached = _BUNDLE_CACHE.get(sym_key)
            if cached and (now_t - cached[0]) <= CACHE_TTL_SEC:
                _, tf_data_c, tf_forecasts_c, mtf_scores_c, curr_p_c = cached
                return tf_data_c[tf_key], tf_forecasts_c[tf_key], tf_forecasts_c, mtf_scores_c, curr_p_c

    cfg = AnalysisConfig(
        exchange=ExchangeConfig(symbol=sym_key, timeframe=tf, limit=210),
    )
    fetcher = CryptoDataFetcher(cfg.exchange)

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_tf = ex.submit(
            fetcher.fetch_multi_timeframe_parallel,
            symbol=sym_key,
            timeframes=["15m", "1h", "4h", "1d"],
            limit=210,
            allow_synthetic_fallback=allow_synthetic_fallback,
        )
        fut_intel = ex.submit(fetcher.fetch_order_flow_intel, symbol=sym_key)
        raw_tf_dict, _ = fut_tf.result()
        intel = fut_intel.result()

    ind = TechnicalIndicators(cfg.indicators)
    pat = CandlestickPatternDetector(cfg.patterns)
    sig = SignalEngine(cfg.indicators)

    ordered_tfs = ["15M", "1H", "4H", "1D"]
    tf_data: Dict[str, pd.DataFrame] = {}
    for k in ordered_tfs:
        df_i = ind.enrich(raw_tf_dict[k])
        df_p = pat.detect_all(df_i)
        tf_data[k] = sig.evaluate(df_p)

    tf_forecasts: Dict[str, MarketForecast] = {}
    mtf_scores: Dict[str, float] = {}
    htf_prev: Optional[float] = None
    for k in reversed(ordered_tfs):
        fc_k = sig.generate_forecast(
            tf_data[k],
            order_flow=intel,
            htf_score=htf_prev,
            symbol=sym_key,
        )
        tf_forecasts[k] = fc_k
        mtf_scores[k] = fc_k.score
        htf_prev = fc_k.score

    df_active = tf_data[tf_key]
    fc_active = tf_forecasts[tf_key]
    current_price = float(df_active["close"].iloc[-1])

    with _CACHE_LOCK:
        _BUNDLE_CACHE[sym_key] = (now_t, tf_data, tf_forecasts, mtf_scores, current_price)

    return df_active, fc_active, tf_forecasts, mtf_scores, current_price


def _analyze_single_coin(
    symbol: str,
    timeframe: str = "1h",
    force_refresh: bool = False,
) -> Tuple[str, Dict[str, Any], pd.DataFrame, MarketForecast, float]:
    tf = timeframe.lower() if timeframe.lower() in ("15m", "1h", "4h", "1d") else "1h"
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


def _analyze_single_coin_for_scan(
    sym: str,
    tf: str,
    btc_df: Optional[pd.DataFrame] = None,
    btc_score: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    try:
        cfg = AnalysisConfig(exchange=ExchangeConfig(symbol=sym, timeframe=tf, limit=200))
        fetcher = CryptoDataFetcher(cfg.exchange)
        df, _ = fetcher.fetch_ohlcv(allow_synthetic_fallback=True)
        current_price = float(df["close"].iloc[-1])
        intel = fetcher.fetch_order_flow_intel(symbol=sym)
        df = TechnicalIndicators(cfg.indicators).enrich(df)
        df = CandlestickPatternDetector(cfg.patterns).detect_all(df)
        sig = SignalEngine(cfg.indicators)
        df = sig.evaluate(df)
        fc = sig.generate_forecast(
            df,
            order_flow=intel,
            btc_regime_score=btc_score if not sym.startswith("BTC/") else None,
            symbol=sym,
            btc_df=btc_df if not sym.startswith("BTC/") else None,
        )
        p_fmt = ",.4f" if current_price < 10.0 else ",.2f"
        if fc.score >= 15:
            trend_lbl = f"📈 Yükselen ({fc.score:+.0f})"
        elif fc.score <= -15:
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
        }
    except Exception:
        return None


def _scan_watchlist_parallel(
    timeframe: str = "1h",
    only_high_quality: bool = False,
    force_refresh: bool = False,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    tf = timeframe.lower() if timeframe.lower() in ("15m", "1h", "4h", "1d") else "1h"
    now_t = time.time()
    results: Optional[List[Dict[str, Any]]] = None

    if not force_refresh:
        with _CACHE_LOCK:
            cached_s = _SCAN_CACHE.get(tf)
            if cached_s and (now_t - cached_s[0]) <= CACHE_TTL_SEC:
                results = list(cached_s[1])

    if results is None:
        symbols_to_scan = list(dict.fromkeys(_load_shared_watchlist() + DEFAULT_WATCHLIST))[:10]

        btc_df_ref: Optional[pd.DataFrame] = None
        btc_score_ref: Optional[float] = None
        try:
            cfg_btc = AnalysisConfig(exchange=ExchangeConfig(symbol="BTC/USDT", timeframe=tf, limit=200))
            f_btc = CryptoDataFetcher(cfg_btc.exchange)
            df_b, _ = f_btc.fetch_ohlcv(allow_synthetic_fallback=True)
            df_b = TechnicalIndicators(cfg_btc.indicators).enrich(df_b)
            df_b = CandlestickPatternDetector(cfg_btc.patterns).detect_all(df_b)
            sig_b = SignalEngine(cfg_btc.indicators)
            df_b = sig_b.evaluate(df_b)
            fc_b = sig_b.generate_forecast(df_b, symbol="BTC/USDT")
            btc_df_ref = df_b
            btc_score_ref = fc_b.score
        except Exception:
            pass

        results = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = {
                pool.submit(_analyze_single_coin_for_scan, sym, tf, btc_df_ref, btc_score_ref): sym
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

    lines = [
        "⏰ <b>AKILLI ALARM &amp; 7/24 RADAR MERKEZİ</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📡 <b>7/24 Kırılım &amp; Balina Radarı:</b> {'🟢 <b>AÇIK</b> (Otomatik Tarama Aktif)' if radar_on else '🔴 <b>KAPALI</b>'}",
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

    lines.append("━━━━━━━━━━━━━━━━━━━━━━\n<i>👇 Alttaki dokunmatik butonlarla Radar ve Alarmlarınızı yönetebilirsiniz:</i>")
    return "\n".join(lines)


def _build_kasa_inline_keyboard(symbol: str, tf_up: str, active_cap: float) -> Dict[str, Any]:
    caps = [500, 1000, 2500, 5000]
    cap_row = []
    for c in caps:
        lbl = f"✅ {c}$" if abs(active_cap - c) < 1 else f"💼 {c}$"
        cap_row.append({"text": lbl, "callback_data": f"kasa:{symbol}:{tf_up}:{c}"})
    return {
        "inline_keyboard": [
            cap_row,
            [
                {"text": "📊 4 Kart Analize Dön", "callback_data": f"an:{symbol}:{tf_up}"},
                {"text": "🖼️ Grafik Gönder", "callback_data": f"chart:{symbol}:{tf_up}"},
            ],
        ]
    }


def _build_help_html(chat_id: str) -> str:
    return (
        "👋 <b>Akıllı Kripto Karar-Destek &amp; Vadeli Radar Terminali (v8.0)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Botumuz **herkese açık** olarak çalışmaktadır! <b>Ekranın altındaki sabit menüyü</b> veya mesajların altındaki <b>dokunmatik butonları</b> kullanabilirsiniz!\n\n"
        "⚡ <b>Vadeli İşlemler (Futures) Kurulum &amp; Güven Radarı:</b>\n"
        "• <code>/vadeli ONDO 1h</code> — Destek/Direnç, R:R ve Güven Notuna (0-100) Göre Vadeli Long/Short Giriş, TP1/TP2/TP3 ve Stop Planı\n"
        "• <code>/vadelitara 1h</code> — Tüm Coinleri Tarar, Sadece Güvenli Vadeli Kurulumları Listeler\n\n"
        "📲 <b>Temel Sorgu &amp; Grafik Komutları:</b>\n"
        "• <code>ONDO</code> veya <code>ONDO 4h</code> — 4 Kartlı Detaylı Analiz + Dokunmatik Butonlar\n"
        "• <code>/grafik ONDO 1h</code> — Destek, Direnç, Mıknatıs ve Hedef Çizgili Grafik Görseli\n"
        "• <code>/miknatis ONDO</code> — 15M/1H/4H/1D Mıknatıs (POC) &amp; Likidasyon Haritası\n"
        "• <code>/kasa ONDO 1000</code> — Stop Mesafesine Göre Kasa &amp; Risk Hesaplayıcı\n\n"
        "🚀 <b>Tarama &amp; Küresel Piyasa Komutları:</b>\n"
        "• <code>/tara 1h</code> — İzleme Listesini Paralel Tarar\n"
        "• <code>/firsat 1h</code> — Sadece Güçlü Kurulum &amp; Balina Fırsatlarını Filtreler\n"
        "• <code>/piyasa</code> veya <code>/nakit</code> — Küresel Para Giriş/Çıkışı &amp; Seans Özeti\n\n"
        "⏰ <b>Alarm, Radar &amp; Liste Yönetimi:</b>\n"
        "• <code>/alarm ONDO 0.3620</code> — Hedef Fiyata Anlık Bildirim Alarmı Kurar\n"
        "• <code>/alarmlar</code> veya <code>/radar</code> — 7/24 Otomatik Radar &amp; Alarm Kontrol Paneli\n"
        "• <code>/liste</code> — Tıklanabilir Coin Seçim Menüsü\n"
        "• <code>/ekle PEPE</code> | <code>/cikar PEPE</code> — İzleme Listesini Düzenler\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>Durum:</b> Herkese Açık &amp; Sınırsız Kullanım"
    )


# ===========================================================================
# PROACTIVE BACKGROUND CHECKS
# ===========================================================================
def _check_price_alarms(bot_token: str, chat_id: str) -> None:
    state = load_telegram_state()
    alarms = state.get("alarms", [])
    if not alarms or not chat_id:
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
                "<i>👇 Güncel kırılım, para girişi ve yeni hedefleri görmek için dokunun:</i>"
            )
            kb = {
                "inline_keyboard": [
                    [
                        {"text": f"📊 {sym} (15M) Analiz", "callback_data": f"an:{sym}:15M"},
                        {"text": f"📊 {sym} (1H) Analiz", "callback_data": f"an:{sym}:1H"},
                    ],
                    [
                        {"text": f"🖼️ {sym} Grafik Gönder", "callback_data": f"chart:{sym}:1H"},
                    ],
                ]
            }
            send_telegram_message(bot_token, chat_id, alert_html, reply_markup=kb)
        else:
            remaining_alarms.append(a)

    if triggered_any:
        state["alarms"] = remaining_alarms
        save_telegram_state(state)


def _run_proactive_radar_cycle(bot_token: str, chat_id: str, force: bool = False) -> int:
    state = load_telegram_state()
    if not force and not state.get("radar_enabled", True):
        return 0
    if not chat_id:
        return 0

    _, _, results = _scan_watchlist_parallel("1h", only_high_quality=False)
    cooldowns: Dict[str, float] = state.get("radar_cooldowns", {})
    now_ts = time.time()
    alerts_sent = 0

    for r in results:
        sym = r["symbol"]
        fc: MarketForecast = r["fc"]
        last_sent = float(cooldowns.get(sym, 0.0))
        if not force and (now_ts - last_sent) < 7200:
            continue

        reasons: List[str] = []
        if fc.readiness_score_5 >= 4 and abs(fc.score) >= 22:
            tr_txt = "YÜKSELİŞ" if fc.score > 0 else "DÜŞÜŞ"
            reasons.append(f"🚦 <b>Güçlü {tr_txt} Kurulumu:</b> Hazırlık <b>{fc.readiness_score_5}/5</b> (Puan: {fc.score:+.0f}/100)")
        if fc.whale_accumulation_score >= 70:
            reasons.append(f"🐋 <b>Güçlü Balina Toplaması:</b> Balina Skoru <b>{fc.whale_accumulation_score:.0f}/100</b> (Nakit: {r['delta_str']})")
        elif fc.whale_accumulation_score <= 30:
            reasons.append(f"🐋 <b>Güçlü Balina Satışı / Çıkışı:</b> Balina Skoru <b>{fc.whale_accumulation_score:.0f}/100</b> (Nakit: {r['delta_str']})")
        if fc.squeeze_energy_pct >= 80:
            reasons.append(f"💥 <b>Yüksek Sıkışma Alarmı:</b> Sıkışma <b>%{fc.squeeze_energy_pct:.0f}</b> (±%{fc.expected_breakout_move_pct:.1f} sert hareket yakın)")

        if reasons:
            p_fmt = ",.4f" if r["price"] < 10.0 else ",.2f"
            sup_s = format(fc.nearest_support, p_fmt) if fc.nearest_support else "N/A"
            res_s = format(fc.nearest_resistance, p_fmt) if fc.nearest_resistance else "N/A"
            tp1_s = format(fc.tp1_price, p_fmt) if fc.tp1_price > 0 else "N/A"
            stop_s = format(fc.stop_price, p_fmt) if fc.stop_price > 0 else "N/A"

            radar_html = (
                f"📡 <b>OTOMATİK RADAR UYARISI: {sym} [1H]</b>\n"
                f"💰 <b>Fiyat:</b> <code>{r['price_str']} USDT</code>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join([f"• { rs }" for rs in reasons])
                + "\n\n"
                f"• 🟢 <b>Destek:</b> <code>{sup_s}</code> | 🔴 <b>Direnç:</b> <code>{res_s}</code>\n"
                f"• 🎯 <b>1. Hedef:</b> <code>{tp1_s}</code> | 🛡️ <b>Stop:</b> <code>{stop_s}</code>\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            )
            kb = build_analysis_inline_keyboard(sym, "1H")
            send_telegram_message(bot_token, chat_id, radar_html, reply_markup=kb)
            cooldowns[sym] = now_ts
            alerts_sent += 1
            if alerts_sent >= 3 and not force:
                break

    state["radar_cooldowns"] = cooldowns
    save_telegram_state(state)
    return alerts_sent


def _check_auto_session_bulletin(bot_token: str, chat_id: str) -> None:
    state = load_telegram_state()
    if not state.get("auto_session_summary", True) or not chat_id:
        return
    lt = time.localtime()
    hm = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
    day_key = f"{lt.tm_year}-{lt.tm_yday}"

    session_tag = ""
    if hm in ("09:00", "09:01"):
        session_tag = f"{day_key}_MORNING"
    elif hm in ("16:30", "16:31"):
        session_tag = f"{day_key}_NY_OPEN"

    if session_tag and state.get("last_session_tag") != session_tag:
        state["last_session_tag"] = session_tag
        save_telegram_state(state)
        _, _, results = _scan_watchlist_parallel("1h", only_high_quality=False)
        if results:
            sess_tr = results[0]["fc"].session_status_tr
            html_mkt = format_market_overview_telegram_html(results, sess_tr, "1H")
            kb = build_screener_inline_keyboard(results, "1H", False)
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

    if action in ("an", "an_ref") and len(parts) >= 3:
        sym = parts[1]
        tf = parts[2]
        is_ref = action == "an_ref"
        answer_callback_query(
            bot_token,
            cq_id,
            f"🔄 {sym} ({tf}) canlı verilerle yenileniyor..." if is_ref else f"⏳ {sym} ({tf}) analiz açılıyor...",
        )
        with _CACHE_LOCK:
            cached_b = _BUNDLE_CACHE.get(sym.upper())
            is_cold = is_ref or (cached_b is None) or ((time.time() - cached_b[0]) > CACHE_TTL_SEC)
        if is_cold and not is_photo_msg and msg_id:
            edit_telegram_message(
                bot_token,
                chat_id,
                msg_id,
                f"⏳ <b>{sym} [{tf.upper()}]</b> canlı borsa verileri çekiliyor ve 4 kart analiz hazırlanıyor...",
            )
        html_text, kb, _, _, _ = _analyze_single_coin(sym, tf, force_refresh=is_ref)
        if not is_photo_msg and msg_id:
            ok = edit_telegram_message(bot_token, chat_id, msg_id, html_text, reply_markup=kb)
            if not ok:
                send_telegram_message(bot_token, chat_id, html_text, reply_markup=kb)
        else:
            send_telegram_message(bot_token, chat_id, html_text, reply_markup=kb)

    elif action == "chart" and len(parts) >= 3:
        sym = parts[1]
        tf = parts[2]
        answer_callback_query(bot_token, cq_id, f"🖼️ {sym} ({tf}) grafiği hazırlanıyor...")
        df_act, fc_act, _, _, curr_p = _compute_full_coin_bundle(sym, tf)
        png_bytes = generate_telegram_chart_png(df_act, fc_act, sym, tf)
        kb = build_analysis_inline_keyboard(sym, tf)
        if png_bytes:
            p_fmt = ",.4f" if curr_p < 10.0 else ",.2f"
            tr_lbl = "📈 Yükselen" if fc_act.score >= 15 else ("📉 Düşen" if fc_act.score <= -15 else "⚖️ Yatay")
            caption = (
                f"🖼️ <b>{sym} [{tf.upper()}] GRAFİK &amp; SEVİYELER</b>\n"
                f"• <b>Trend:</b> {tr_lbl} ({fc_act.score:+.0f}/100) | <b>Hazırlık:</b> {fc_act.readiness_score_5}/5\n"
                f"• 💰 <b>Fiyat:</b> <code>{format(curr_p, p_fmt)} USDT</code> | 🧲 <b>Mıknatıs:</b> <code>{format(fc_act.poc_price, p_fmt)}</code>\n"
                f"• 🎯 <b>Hedef:</b> <code>{format(fc_act.tp1_price, p_fmt)}</code> ➔ <code>{format(fc_act.tp2_price, p_fmt)}</code> | 🛡️ <b>Stop:</b> <code>{format(fc_act.stop_price, p_fmt)}</code>"
            )
            send_telegram_photo(bot_token, chat_id, png_bytes, caption_html=caption, reply_markup=kb)
        else:
            send_telegram_message(bot_token, chat_id, "❌ Grafik görseli oluşturulamadı.", reply_markup=kb)

    elif action == "liq" and len(parts) >= 3:
        sym = parts[1]
        tf = parts[2]
        answer_callback_query(bot_token, cq_id, f"🧲 {sym} Mıknatıs & Likidasyon haritası açılıyor...")
        _, _, tf_fcs, _, curr_p = _compute_full_coin_bundle(sym, tf)
        html_liq = format_liquidation_magnet_telegram_html(sym, tf_fcs, curr_p)
        kb = build_analysis_inline_keyboard(sym, tf)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_liq, reply_markup=kb):
                send_telegram_message(bot_token, chat_id, html_liq, reply_markup=kb)
        else:
            send_telegram_message(bot_token, chat_id, html_liq, reply_markup=kb)

    elif action == "kasa" and len(parts) >= 3:
        sym = parts[1]
        tf = parts[2]
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

    elif action in ("al_res", "al_sup") and len(parts) >= 3:
        sym = parts[1]
        tf = parts[2]
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
        add_price_alarm(sym, target_p, curr_p, note=note)
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
                    "ℹ️ <b>Radar Kontrolü Tamamlandı:</b> Şu an izleme listenizde acil kırılım (4/5+), aşırı balina (>=70) veya patlama sıkışması (>=%80) kriterini tetikleyen coin bulunmuyor.",
                )
            return

        html_al = _build_alarm_radar_status_html(state)
        kb_al = build_alarm_radar_inline_keyboard(state)
        if not edit_telegram_message(bot_token, chat_id, msg_id, html_al, reply_markup=kb_al):
            send_telegram_message(bot_token, chat_id, html_al, reply_markup=kb_al)

    elif action == "coins":
        tf = parts[1] if len(parts) >= 2 else "1H"
        answer_callback_query(bot_token, cq_id, f"🪙 Coin Seçim Menüsü ({tf})")
        wl = _load_shared_watchlist()
        now_hm = time.strftime("%H:%M:%S")
        html_c = (
            f"🪙 <b>AKTİF İZLEME LİSTENİZ ({tf.upper()} DİLİMİ)</b> <i>({now_hm})</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Detaylı 4 kart analizini görmek istediğiniz coinin butonuna dokunun veya alttan zaman dilimini değiştirin:</i>"
        )
        kb_c = build_coin_list_inline_keyboard(wl, tf)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_c, reply_markup=kb_c):
                send_telegram_message(bot_token, chat_id, html_c, reply_markup=kb_c)
        else:
            send_telegram_message(bot_token, chat_id, html_c, reply_markup=kb_c)

    elif action == "scan":
        tf = parts[1] if len(parts) >= 2 else "1H"
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

    elif action == "market":
        tf = parts[1] if len(parts) >= 2 else "1H"
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

    elif action in ("fut", "fut_ref") and len(parts) >= 3:
        sym = parts[1]
        tf = parts[2]
        is_ref = action == "fut_ref"
        answer_callback_query(
            bot_token,
            cq_id,
            f"⚡ {sym} ({tf}) Vadeli İşlem (Long/Short) & Güven Radarı hesaplanıyor...",
        )
        with _CACHE_LOCK:
            cached_b = _BUNDLE_CACHE.get(sym.upper())
            is_cold = is_ref or (cached_b is None) or ((time.time() - cached_b[0]) > CACHE_TTL_SEC)
        if is_cold and not is_photo_msg and msg_id:
            edit_telegram_message(
                bot_token,
                chat_id,
                msg_id,
                f"⚡ <b>{sym} [{tf.upper()}]</b> Vadeli İşlem (Long/Short) giriş, TP, Stop ve güven notu hesaplanıyor...",
            )
        _, fc_act, _, mtf_sc, curr_p = _compute_full_coin_bundle(sym, tf, force_refresh=is_ref)
        html_fut = format_futures_setup_telegram_html(fc_act, sym, tf, curr_p, mtf_scores=mtf_sc)
        kb_fut = build_futures_setup_inline_keyboard(sym, tf)
        if not is_photo_msg and msg_id:
            if not edit_telegram_message(bot_token, chat_id, msg_id, html_fut, reply_markup=kb_fut):
                send_telegram_message(bot_token, chat_id, html_fut, reply_markup=kb_fut)
        else:
            send_telegram_message(bot_token, chat_id, html_fut, reply_markup=kb_fut)

    elif action == "fut_scan":
        tf = parts[1] if len(parts) >= 2 else "1H"
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
    else:
        answer_callback_query(bot_token, cq_id, "✅ İşlem alındı.")


def _map_reply_keyboard_text(raw_text: str) -> str:
    t = raw_text.strip()
    t_low = t.lower()
    if "coin seç" in t_low or "coin listesi" in t_low or t.startswith("🪙"):
        return "/liste"
    if "vadeli" in t_low or t.startswith("⚡"):
        return "/vadelitara 1h"
    if "tümünü tara" in t_low or t.startswith("🚀"):
        return "/tara 1h"
    if "fırsatlar" in t_low or "firsatlar" in t_low or t.startswith("🎯"):
        return "/firsat 1h"
    if "piyasa" in t_low or "nakit özeti" in t_low or t.startswith("🌍"):
        return "/piyasa"
    if "alarmlarım" in t_low or "alarmlarim" in t_low or t.startswith("⏰"):
        return "/alarmlar"
    if "komutlar" in t_low or "yardım" in t_low or "yardim" in t_low or t.startswith("📋"):
        return "/yardim"
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
                "👇 <b>Hızlı Başlangıç:</b> Analiz etmek istediğiniz coine dokunun:",
                reply_markup=build_coin_list_inline_keyboard(wl, "1H"),
            )

        elif cmd == "/analiz":
            sym = _normalize_symbol(parts[1]) if len(parts) >= 2 else "ONDO/USDT"
            tf = parts[2].lower() if len(parts) >= 3 else "1h"
            send_telegram_message(
                bot_token,
                chat_id,
                f"⏳ <b>{sym} [{tf.upper()}]</b> için 4 kart analiz, kırılım ve likidasyon seviyeleri hesaplanıyor...",
            )
            report_html, kb, df_act, fc_act, _ = _analyze_single_coin(sym, tf)
            send_telegram_message(bot_token, chat_id, report_html, reply_markup=kb)
            if load_telegram_state().get("send_chart_with_analysis", False):
                png_b = generate_telegram_chart_png(df_act, fc_act, sym, tf)
                if png_b:
                    send_telegram_photo(bot_token, chat_id, png_b, caption_html=f"🖼️ <b>{sym} [{tf.upper()}] Grafik Görünümü</b>")

        elif cmd in ("/grafik", "/chart"):
            sym = _normalize_symbol(parts[1]) if len(parts) >= 2 else "ONDO/USDT"
            tf = parts[2].lower() if len(parts) >= 3 else "1h"
            send_telegram_message(bot_token, chat_id, f"🖼️ <b>{sym} [{tf.upper()}]</b> grafiği çiziliyor...")
            df_act, fc_act, _, _, curr_p = _compute_full_coin_bundle(sym, tf)
            png_b = generate_telegram_chart_png(df_act, fc_act, sym, tf)
            kb = build_analysis_inline_keyboard(sym, tf.upper())
            if png_b:
                p_fmt = ",.4f" if curr_p < 10.0 else ",.2f"
                cap = (
                    f"🖼️ <b>{sym} [{tf.upper()}] GRAFİK &amp; KRİTİK SEVİYELER</b>\n"
                    f"💰 <b>Fiyat:</b> <code>{format(curr_p, p_fmt)} USDT</code> | 🚦 <b>Hazırlık:</b> {fc_act.readiness_score_5}/5\n"
                    f"🎯 <b>Hedefler:</b> <code>{format(fc_act.tp1_price, p_fmt)}</code> ➔ <code>{format(fc_act.tp2_price, p_fmt)}</code> | 🛡️ <b>Stop:</b> <code>{format(fc_act.stop_price, p_fmt)}</code>"
                )
                send_telegram_photo(bot_token, chat_id, png_b, caption_html=cap, reply_markup=kb)
            else:
                send_telegram_message(bot_token, chat_id, "❌ Grafik oluşturulamadı.", reply_markup=kb)

        elif cmd in ("/miknatis", "/likidasyon", "/poc"):
            sym = _normalize_symbol(parts[1]) if len(parts) >= 2 else "ONDO/USDT"
            _, _, tf_fcs, _, curr_p = _compute_full_coin_bundle(sym, "1h")
            html_liq = format_liquidation_magnet_telegram_html(sym, tf_fcs, curr_p)
            send_telegram_message(
                bot_token,
                chat_id,
                html_liq,
                reply_markup=build_analysis_inline_keyboard(sym, "1H"),
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
            _, fc_act, _, _, curr_p = _compute_full_coin_bundle(sym, "1h")
            html_kasa = format_position_size_telegram_html(fc_act, sym, "1H", curr_p, capital_usd=cap_val, risk_pct=risk_p)
            send_telegram_message(
                bot_token,
                chat_id,
                html_kasa,
                reply_markup=_build_kasa_inline_keyboard(sym, "1H", cap_val),
            )

        elif cmd in ("/vadeli", "/futures"):
            if len(parts) < 2 or parts[1].lower() in ("15m", "1h", "4h", "1d", "tara"):
                tf = parts[1].lower() if (len(parts) >= 2 and parts[1].lower() in ("15m", "1h", "4h", "1d")) else "1h"
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
                tf = parts[2].lower() if len(parts) >= 3 else "1h"
                send_telegram_message(
                    bot_token,
                    chat_id,
                    f"⚡ <b>{sym} [{tf.upper()}]</b> Vadeli İşlem (Long/Short) giriş, TP, Stop ve güven notu hesaplanıyor...",
                )
                _, fc_act, _, mtf_sc, curr_p = _compute_full_coin_bundle(sym, tf)
                html_fut = format_futures_setup_telegram_html(fc_act, sym, tf, curr_p, mtf_scores=mtf_sc)
                kb_fut = build_futures_setup_inline_keyboard(sym, tf)
                send_telegram_message(bot_token, chat_id, html_fut, reply_markup=kb_fut)

        elif cmd in ("/vadelitara", "/vadeliradar"):
            tf = parts[1].lower() if len(parts) >= 2 else "1h"
            send_telegram_message(
                bot_token,
                chat_id,
                f"📡 <b>[{tf.upper()}]</b> Vadeli İşlem (Futures) Radarı tüm coinleri güven notu ve R:R filtresiyle tarıyor...",
            )
            _, _, results = _scan_watchlist_parallel(tf, only_high_quality=False)
            html_fs = format_futures_radar_scan_telegram_html(results, tf)
            kb_fs = build_futures_radar_inline_keyboard(results, tf)
            send_telegram_message(bot_token, chat_id, html_fs, reply_markup=kb_fs)

        elif cmd == "/tara":
            tf = parts[1].lower() if len(parts) >= 2 else "1h"
            send_telegram_message(
                bot_token,
                chat_id,
                f"🔍 <b>[{tf.upper()}]</b> Paralel çoklu coin taraması yapılıyor...",
            )
            scan_html, kb_s, _ = _scan_watchlist_parallel(tf, only_high_quality=False)
            send_telegram_message(bot_token, chat_id, scan_html, reply_markup=kb_s)

        elif cmd == "/firsat":
            tf = parts[1].lower() if len(parts) >= 2 else "1h"
            send_telegram_message(
                bot_token,
                chat_id,
                f"🎯 <b>[{tf.upper()}]</b> En güçlü hazırlık onaylı ve balina izli fırsatlar filtreleniyor...",
            )
            scan_html, kb_s, _ = _scan_watchlist_parallel(tf, only_high_quality=True)
            send_telegram_message(bot_token, chat_id, scan_html, reply_markup=kb_s)

        elif cmd in ("/piyasa", "/nakit", "/makro"):
            tf = parts[1].lower() if len(parts) >= 2 else "1h"
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
                    entry = add_price_alarm(sym, target_p, curr_p)
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
                "🪙 <b>AKTİF İZLEME LİSTENİZ</b>\n<i>Analizini açmak istediğiniz coinin butonuna dokunun:</i>",
                reply_markup=build_coin_list_inline_keyboard(wl, "1H"),
            )

        elif cmd == "/ekle" and len(parts) >= 2:
            sym = _normalize_symbol(parts[1])
            wl = _load_shared_watchlist()
            if sym not in wl:
                wl.append(sym)
                _save_shared_watchlist(wl)
            send_telegram_message(
                bot_token,
                chat_id,
                f"✅ <b>{sym}</b> izleme listenize eklendi!",
                reply_markup=build_coin_list_inline_keyboard(wl, "1H"),
            )

        elif cmd == "/cikar" and len(parts) >= 2:
            sym = _normalize_symbol(parts[1])
            wl = [x for x in _load_shared_watchlist() if x != sym]
            _save_shared_watchlist(wl)
            send_telegram_message(
                bot_token,
                chat_id,
                f"🗑️ <b>{sym}</b> izleme listenizden çıkarıldı.",
                reply_markup=build_coin_list_inline_keyboard(wl, "1H"),
            )

        elif not cmd.startswith("/") and 2 <= len(parts[0]) <= 12:
            sym = _normalize_symbol(parts[0])
            tf = parts[1].lower() if len(parts) >= 2 else "1h"
            send_telegram_message(
                bot_token,
                chat_id,
                f"⏳ <b>{sym} [{tf.upper()}]</b> analiz ediliyor...",
            )
            report_html, kb, df_act, fc_act, _ = _analyze_single_coin(sym, tf)
            send_telegram_message(bot_token, chat_id, report_html, reply_markup=kb)
            if load_telegram_state().get("send_chart_with_analysis", False):
                png_b = generate_telegram_chart_png(df_act, fc_act, sym, tf)
                if png_b:
                    send_telegram_photo(bot_token, chat_id, png_b, caption_html=f"🖼️ <b>{sym} [{tf.upper()}] Grafik Görünümü</b>")

    except Exception as cmd_err:
        _log(f"Komut işleme hatası ({text}): {cmd_err}")
        wl = _load_shared_watchlist()
        send_telegram_message(
            bot_token,
            chat_id,
            "⚠️ <b>Sembol Borsada Bulunamadı veya Veri Alınamadı:</b>\n"
            f"Girilen komut/coin (<code>{text}</code>) borsada doğrulanamadı. Lütfen yazımı kontrol edin veya aşağıdaki listeden dokunarak seçin:",
            reply_markup=build_coin_list_inline_keyboard(wl, "1H"),
        )


def _safe_callback_worker(bot_token: str, cq: Dict[str, Any], cq_chat_id: str) -> None:
    try:
        _handle_callback_query(bot_token, cq)
    except Exception as cq_err:
        _log(f"Callback hatası ({cq.get('data')}): {cq_err}")
        if cq_chat_id:
            send_telegram_message(
                bot_token,
                cq_chat_id,
                "⚠️ İstek işlenirken geçici bir borsa/veri hatası oluştu. Lütfen tekrar dokunun.",
            )


# ===========================================================================
# MAIN 24/7 POLLING & PROACTIVE RADAR LOOP (OPEN TO ALL)
# ===========================================================================
def run_polling_bot(bot_token: str) -> None:
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

    _log(f"🤖 Herkese Açık Akıllı Kripto İnteraktif Telegram Botu & Radar Başlatıldı (PID: {os.getpid()})!")
    offset = 0
    last_alarm_check = 0.0
    last_radar_check = time.time()
    worker_pool = ThreadPoolExecutor(max_workers=6)

    while True:
        try:
            now_t = time.time()
            saved_cfg = load_telegram_config()
            target_chat_id = saved_cfg.get("chat_id", "").strip()

            if target_chat_id and (now_t - last_alarm_check) >= 30.0:
                last_alarm_check = now_t
                worker_pool.submit(_check_price_alarms, bot_token, target_chat_id)
                worker_pool.submit(_check_auto_session_bulletin, bot_token, target_chat_id)

            state_curr = load_telegram_state()
            radar_int = float(state_curr.get("radar_interval_sec", 600))
            if target_chat_id and state_curr.get("radar_enabled", True) and (now_t - last_radar_check) >= radar_int:
                last_radar_check = now_t
                worker_pool.submit(_run_proactive_radar_cycle, bot_token, target_chat_id, False)

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

                # Herkes butonlara dokunabilir
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

                # Yetki filtresi tamamen kaldırıldı: Gelen her kullanıcı veya grup komutları işleyebilir
                worker_pool.submit(_handle_message_command, bot_token, chat_id, text)

        except KeyboardInterrupt:
            _log("👋 Telegram Botu durduruldu.")
            break
        except Exception as e:
            _log(f"⚠️ Geçici bağlantı uyarısı: {e}")
            time.sleep(3)


if __name__ == "__main__":
    cfg = load_telegram_config()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("bot_token", "")
    if not token:
        print("❗ Telegram Bot Token bulunamadı.")
        print("Lütfen Streamlit arayüzünün sol menüsündeki '📲 Mobil & Telegram Bildirim Merkezi' bölümünden Bot Token kaydedin")
        print("veya TELEGRAM_BOT_TOKEN ortam değişkenini tanımlayın.")
        sys.exit(1)
    run_polling_bot(token)
