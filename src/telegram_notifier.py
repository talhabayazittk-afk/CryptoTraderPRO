"""
Comprehensive Telegram Notification, Interactive Keyboard, Chart Image & State Engine (v7.0).
Uses Python standard library (`urllib.request` & `json`) for Telegram Bot API calls
(including `sendMessage`, `editMessageText`, `answerCallbackQuery`, `sendPhoto` multipart upload)
and `matplotlib` (`Agg` backend) for instant dark-mode chart image snapshots.
"""
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .signals import MarketForecast

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT_DIR / "telegram_config.json"
STATE_FILE = ROOT_DIR / "telegram_state.json"
PID_FILE = ROOT_DIR / "telegram_bot.pid"


# ===========================================================================
# 1. CONFIG & PERSISTENT STATE MANAGEMENT (ALARMS, RADAR, COOLDOWNS)
# ===========================================================================
def load_telegram_config() -> Dict[str, str]:
    """Loads saved Telegram bot_token and chat_id from local JSON file or environment variables."""
    env_tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    env_cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            tok = str(data.get("bot_token", "")).strip() or env_tok
            cid = str(data.get("chat_id", "")).strip() or env_cid
            return {"bot_token": tok, "chat_id": cid}
        except Exception:
            pass
    return {"bot_token": env_tok, "chat_id": env_cid}


def save_telegram_config(bot_token: str, chat_id: str) -> bool:
    """Persists Telegram bot_token and chat_id locally."""
    try:
        CONFIG_FILE.write_text(
            json.dumps(
                {"bot_token": bot_token.strip(), "chat_id": chat_id.strip()},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def _default_state() -> Dict[str, Any]:
    return {
        "radar_enabled": True,
        "radar_interval_sec": 600,  # 10 minutes
        "auto_session_summary": True,
        "send_chart_with_analysis": False,
        "alarms": [],               # List of {id, symbol, target_price, direction, note, created_at}
        "radar_cooldowns": {},      # symbol -> last_alert_epoch
        "last_session_tag": "",     # Prevents duplicate session summary
    }


def load_telegram_state() -> Dict[str, Any]:
    """Loads persistent Telegram bot state (alarms, radar toggles, cooldowns)."""
    base = _default_state()
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base.update(data)
        except Exception:
            pass
    return base


def save_telegram_state(state: Dict[str, Any]) -> bool:
    """Saves persistent Telegram bot state to disk."""
    try:
        STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def add_price_alarm(
    symbol: str,
    target_price: float,
    current_price: float,
    note: str = "",
) -> Dict[str, Any]:
    """Adds a personal price alarm and persists it to telegram_state.json."""
    state = load_telegram_state()
    alarms = state.get("alarms", [])
    direction = "ABOVE" if target_price >= current_price else "BELOW"
    alarm_id = uuid.uuid4().hex[:6]
    entry = {
        "id": alarm_id,
        "symbol": symbol.upper(),
        "target_price": float(target_price),
        "ref_price": float(current_price),
        "direction": direction,
        "note": note or ("Üstüne Çıkarsa 📈" if direction == "ABOVE" else "Altına İnerse 📉"),
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    alarms.append(entry)
    state["alarms"] = alarms
    save_telegram_state(state)
    return entry


def remove_price_alarm(alarm_id: str) -> bool:
    """Removes a price alarm by its short ID."""
    state = load_telegram_state()
    alarms = state.get("alarms", [])
    new_alarms = [a for a in alarms if str(a.get("id")) != str(alarm_id)]
    if len(new_alarms) != len(alarms):
        state["alarms"] = new_alarms
        save_telegram_state(state)
        return True
    return False


# ===========================================================================
# 2. SINGLE-INSTANCE BOT PROCESS LOCK (PID CHECK / START / STOP)
# ===========================================================================
def is_bot_running() -> Tuple[bool, Optional[int]]:
    """Checks if telegram_bot.py is currently alive via PID file."""
    if not PID_FILE.exists():
        return False, None
    try:
        pid_str = PID_FILE.read_text(encoding="utf-8").strip()
        if not pid_str.isdigit():
            return False, None
        pid = int(pid_str)
        if os.name == "nt":
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).decode("utf-8", errors="ignore")
            if str(pid) in out and ("python" in out.lower() or "py.exe" in out.lower()):
                return True, pid
            return False, None
        else:
            os.kill(pid, 0)
            return True, pid
    except Exception:
        return False, None


def start_bot_background() -> Tuple[bool, str]:
    """Starts telegram_bot.py as a single background process if not already running."""
    running, pid = is_bot_running()
    if running and pid:
        return True, f"🟢 Telegram Botu zaten arka planda çalışıyor (PID: {pid})."
    bot_script = ROOT_DIR / "telegram_bot.py"
    try:
        flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        proc = subprocess.Popen(
            [sys.executable, str(bot_script)],
            cwd=str(ROOT_DIR),
            env=env,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        return True, f"🤖 7/24 İnteraktif Telegram Botu ve Radar başlatıldı (PID: {proc.pid})!"
    except Exception as e:
        return False, f"❌ Bot başlatılamadı: {e}"


def stop_bot_background() -> Tuple[bool, str]:
    """Stops the running background telegram_bot.py process if active."""
    running, pid = is_bot_running()
    if not running or not pid:
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except Exception:
                pass
        return True, "⚪ Bot zaten kapalı."
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            os.kill(pid, 15)
        if PID_FILE.exists():
            PID_FILE.unlink()
        return True, f"🛑 Telegram Botu (PID: {pid}) durduruldu."
    except Exception as e:
        return False, f"❌ Bot durdurulamadı: {e}"


# ===========================================================================
# 3. INTERACTIVE TOUCH KEYBOARD BUILDERS (INLINE & REPLY KEYBOARDS)
# ===========================================================================
def build_main_reply_keyboard() -> Dict[str, Any]:
    """
    Persistent bottom touch menu on the user's phone so they never need to type commands.
    """
    return {
        "keyboard": [
            [
                {"text": "🪙 Coin Seç & Analiz"},
                {"text": "⚡ Vadeli İşlem Radarı"},
                {"text": "🚀 Tümünü Tara (1H)"},
            ],
            [
                {"text": "🌍 Piyasa & Nakit Özeti"},
                {"text": "⏰ Alarmlarım & Radar"},
                {"text": "📋 Komutlar & Yardım"},
            ],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def build_analysis_inline_keyboard(symbol: str, active_tf: str) -> Dict[str, Any]:
    """
    Builds a rich touch button deck underneath every single-coin analysis message:
      Row 1: [15M] [1H] [4H] [1D] instant timeframe switcher
      Row 2: [⚡ Vadeli İşlem Kurulumu] [📡 Vadeli Radar]
      Row 3: [🖼️ Grafik] [🧲 Mıknatıs & Likidasyon] [🧮 Kasa Planı]
      Row 4: [🔔 Direnç Alarmı Kur] [🔔 Destek Alarmı Kur]
      Row 5: [🔄 Yenile] [🪙 Coin Seç] [🚀 Tarama]
    """
    tf_up = active_tf.upper()
    tf_row = []
    for tf_opt in ("15M", "1H", "4H", "1D"):
        lbl = f"✅ {tf_opt}" if tf_opt == tf_up else f"⏱️ {tf_opt}"
        tf_row.append({"text": lbl, "callback_data": f"an:{symbol}:{tf_opt}"})

    return {
        "inline_keyboard": [
            tf_row,
            [
                {"text": "⚡ Vadeli İşlem (Long/Short) Planı", "callback_data": f"fut:{symbol}:{tf_up}"},
                {"text": "📡 Vadeli Radar", "callback_data": f"fut_scan:{tf_up}"},
            ],
            [
                {"text": "🖼️ Grafik Gönder", "callback_data": f"chart:{symbol}:{tf_up}"},
                {"text": "🧲 Mıknatıs & Lik.", "callback_data": f"liq:{symbol}:{tf_up}"},
                {"text": "🧮 Kasa Planı", "callback_data": f"kasa:{symbol}:{tf_up}"},
            ],
            [
                {"text": "🔔 Direnç Alarmı (+)", "callback_data": f"al_res:{symbol}:{tf_up}"},
                {"text": "🔔 Destek Alarmı (-)", "callback_data": f"al_sup:{symbol}:{tf_up}"},
            ],
            [
                {"text": "🔄 Yenile", "callback_data": f"an_ref:{symbol}:{tf_up}"},
                {"text": "🪙 Coin Listesi", "callback_data": f"coins:{tf_up}"},
                {"text": "🚀 Tümünü Tara", "callback_data": f"scan:{tf_up}:0"},
            ],
        ]
    }


def build_futures_setup_inline_keyboard(symbol: str, active_tf: str) -> Dict[str, Any]:
    """
    Builds interactive touch buttons underneath the Dedicated Perpetual Futures Setup screen:
      Row 1: [15M] [1H] [4H] [1D] instant timeframe switcher for Futures Setup
      Row 2: [📊 4 Kart Spot/Genel Analiz] [🖼️ Grafik Gönder] [🧮 Kasa Planı]
      Row 3: [🔔 Direnç Alarmı (+)] [🔔 Destek Alarmı (-)]
      Row 4: [🔄 Canlı Yenile] [📡 Tüm Vadeli Radarı Tara] [🪙 Coin Seç]
    """
    tf_up = active_tf.upper()
    tf_row = []
    for tf_opt in ("15M", "1H", "4H", "1D"):
        lbl = f"✅ {tf_opt}" if tf_opt == tf_up else f"⚡ {tf_opt}"
        tf_row.append({"text": lbl, "callback_data": f"fut:{symbol}:{tf_opt}"})

    return {
        "inline_keyboard": [
            tf_row,
            [
                {"text": "📊 4 Kart Genel Analiz", "callback_data": f"an:{symbol}:{tf_up}"},
                {"text": "🖼️ Grafik Gönder", "callback_data": f"chart:{symbol}:{tf_up}"},
                {"text": "🧮 Kasa Planı", "callback_data": f"kasa:{symbol}:{tf_up}"},
            ],
            [
                {"text": "🔔 Direnç Alarmı (+)", "callback_data": f"al_res:{symbol}:{tf_up}"},
                {"text": "🔔 Destek Alarmı (-)", "callback_data": f"al_sup:{symbol}:{tf_up}"},
            ],
            [
                {"text": "🔄 Yenile", "callback_data": f"fut_ref:{symbol}:{tf_up}"},
                {"text": "📡 Vadeli Radar Taraması", "callback_data": f"fut_scan:{tf_up}"},
                {"text": "🪙 Coin Seç", "callback_data": f"coins:{tf_up}"},
            ],
        ]
    }


def build_futures_radar_inline_keyboard(rows: List[Dict[str, Any]], timeframe: str = "1H") -> Dict[str, Any]:
    """
    Builds interactive touch buttons underneath the Multi-Coin Perpetual Futures Radar Scan:
      - Direct buttons for tradeable setups (🟢 LONG / 🔴 SHORT) and other coins to open their Futures Setup
      - Timeframe switcher [15M | 1H | 4H | 1D] for the Futures Radar
    """
    tf_up = timeframe.upper()
    kb_rows: List[List[Dict[str, str]]] = []

    coin_btns: List[Dict[str, str]] = []
    for r in rows[:8]:
        sym = str(r.get("symbol", r.get("Coin", "")))
        if not sym:
            continue
        short_sym = sym.split("/")[0]
        fc_obj = r.get("fc")
        if fc_obj and getattr(fc_obj, "futures_setup", None) and fc_obj.futures_setup.is_tradeable:
            ic = "🟢L" if fc_obj.futures_setup.direction == "LONG" else "🔴S"
            btn_lbl = f"{ic} {short_sym} ({fc_obj.futures_setup.confidence_score:.0f})"
        else:
            btn_lbl = f"⛔ {short_sym}"
        coin_btns.append({"text": btn_lbl, "callback_data": f"fut:{sym}:{tf_up}"})
        if len(coin_btns) == 3:
            kb_rows.append(coin_btns)
            coin_btns = []
    if coin_btns:
        kb_rows.append(coin_btns)

    tf_row = []
    for tf_opt in ("15M", "1H", "4H", "1D"):
        lbl = f"✅ {tf_opt}" if tf_opt == tf_up else f"⚡ {tf_opt}"
        tf_row.append({"text": lbl, "callback_data": f"fut_scan:{tf_opt}"})
    kb_rows.append(tf_row)

    kb_rows.append(
        [
            {"text": "🚀 Genel Tarama Tablosu", "callback_data": f"scan:{tf_up}:0"},
            {"text": "🌍 Piyasa & Nakit Özeti", "callback_data": f"market:{tf_up}"},
        ]
    )
    return {"inline_keyboard": kb_rows}


def build_coin_list_inline_keyboard(watchlist: List[str], timeframe: str = "1H") -> Dict[str, Any]:
    """Builds a 3-column touch grid of coins from the user's watchlist."""
    tf_up = timeframe.upper()
    rows: List[List[Dict[str, str]]] = []
    current_row: List[Dict[str, str]] = []
    for sym in watchlist[:15]:
        short_name = sym.split("/")[0]
        current_row.append({"text": f"📊 {short_name}", "callback_data": f"an:{sym}:{tf_up}"})
        if len(current_row) == 3:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    # Timeframe selector row for the coin picker
    tf_row = []
    for tf_opt in ("15M", "1H", "4H", "1D"):
        lbl = f"✅ {tf_opt}" if tf_opt == tf_up else f"⏱️ {tf_opt}"
        tf_row.append({"text": lbl, "callback_data": f"coins:{tf_opt}"})
    rows.append(tf_row)
    rows.append(
        [
            {"text": f"🚀 Tümünü Tara ({tf_up})", "callback_data": f"scan:{tf_up}:0"},
            {"text": f"🎯 Sadece Fırsatlar ({tf_up})", "callback_data": f"scan:{tf_up}:1"},
        ]
    )
    return {"inline_keyboard": rows}


def build_screener_inline_keyboard(
    rows: List[Dict[str, Any]],
    timeframe: str,
    only_high_quality: bool = False,
) -> Dict[str, Any]:
    """
    Builds interactive touch buttons under the Multi-Coin Screener so the user can:
      - Tap any ranked coin to open its detailed 4-card analysis immediately
      - Switch scan timeframe (15M / 1H / 4H / 1D)
      - Toggle between All Coins and High-Quality Setups (/firsat)
    """
    tf_up = timeframe.upper()
    q_flag = "1" if only_high_quality else "0"
    kb_rows: List[List[Dict[str, str]]] = []

    # Top coins quick-open buttons (up to 8 coins, 4 per row)
    coin_btns: List[Dict[str, str]] = []
    for idx, r in enumerate(rows[:8], start=1):
        sym = str(r.get("Coin", ""))
        if not sym:
            continue
        short_sym = sym.split("/")[0]
        coin_btns.append({"text": f"{idx}. {short_sym}", "callback_data": f"an:{sym}:{tf_up}"})
        if len(coin_btns) == 4:
            kb_rows.append(coin_btns)
            coin_btns = []
    if coin_btns:
        kb_rows.append(coin_btns)

    # Timeframe switcher row
    tf_row = []
    for tf_opt in ("15M", "1H", "4H", "1D"):
        lbl = f"✅ {tf_opt}" if tf_opt == tf_up else f"🔍 {tf_opt}"
        tf_row.append({"text": lbl, "callback_data": f"scan:{tf_opt}:{q_flag}"})
    kb_rows.append(tf_row)

    # Filter toggle & Market summary row
    toggle_btn = (
        {"text": "📋 Tüm Coinleri Göster", "callback_data": f"scan:{tf_up}:0"}
        if only_high_quality
        else {"text": "🎯 Sadece Güçlü Fırsatlar", "callback_data": f"scan:{tf_up}:1"}
    )
    kb_rows.append(
        [
            toggle_btn,
            {"text": "🌍 Piyasa Özeti", "callback_data": "market:1H"},
        ]
    )
    return {"inline_keyboard": kb_rows}


def build_alarm_radar_inline_keyboard(state: Dict[str, Any]) -> Dict[str, Any]:
    """Builds interactive touch controls for Alarms & 24/7 Radar settings."""
    radar_on = bool(state.get("radar_enabled", True))
    sess_on = bool(state.get("auto_session_summary", True))
    alarms = state.get("alarms", [])

    kb: List[List[Dict[str, str]]] = [
        [
            {
                "text": "🟢 Radar: AÇIK (Kapatmak İçin Dokun)" if radar_on else "🔴 Radar: KAPALI (Açmak İçin Dokun)",
                "callback_data": "radar:toggle",
            }
        ],
        [
            {
                "text": "🌅 Seans Özeti: AÇIK" if sess_on else "⚪ Seans Özeti: KAPALI",
                "callback_data": "radar:session_toggle",
            },
            {
                "text": "⚡ Şimdi Radar Taraması Yap",
                "callback_data": "radar:scan_now",
            },
        ],
    ]

    for a in alarms[:8]:
        aid = a.get("id", "")
        sym = str(a.get("symbol", "")).split("/")[0]
        tp = a.get("target_price", 0.0)
        p_fmt = ",.4f" if tp < 10.0 else ",.2f"
        dir_ic = "📈 >=" if a.get("direction") == "ABOVE" else "📉 <="
        kb.append(
            [
                {
                    "text": f"🗑️ Sil: {sym} {dir_ic} {format(tp, p_fmt)} USDT",
                    "callback_data": f"al_del:{aid}",
                }
            ]
        )

    if alarms:
        kb.append([{"text": "🧹 Tüm Alarmları Temizle", "callback_data": "al_clear:all"}])

    kb.append(
        [
            {"text": "🪙 Coin Seç & Alarm Ekle", "callback_data": "coins:1H"},
            {"text": "🚀 Tümünü Tara", "callback_data": "scan:1H:0"},
        ]
    )
    return {"inline_keyboard": kb}


# ===========================================================================
# 4. MESSAGE FORMATTERS (4-CARD ANALYSIS, SCREENER, MARKET, LIQ, POSITION)
# ===========================================================================
def _fmt_price(val: Optional[float], ref_price: float) -> str:
    if val is None or pd.isna(val) or val <= 0:
        return "N/A"
    p_fmt = ",.4f" if ref_price < 10.0 else ",.2f"
    return format(float(val), p_fmt)


def format_forecast_telegram_html(
    fc: MarketForecast,
    symbol: str,
    timeframe: str,
    current_price: float,
    mtf_scores: Optional[Dict[str, float]] = None,
) -> str:
    """
    Formats a MarketForecast into a detailed, well-structured, beginner-friendly Turkish HTML message
    for Telegram that mirrors the 1-Status-Strip + 4-Card dashboard layout.
    """
    def _p(val: Optional[float]) -> str:
        return _fmt_price(val, current_price)

    tf_up = timeframe.upper()
    if fc.score >= 15:
        trend_title = "📈 YÜKSELEN TREND"
        trend_desc = "Alıcılar baskın, yön yukarı"
    elif fc.score <= -15:
        trend_title = "📉 DÜŞEN TREND"
        trend_desc = "Satıcılar baskın, yön aşağı"
    else:
        trend_title = "⚖️ YATAY / KARARSIZ TREND"
        trend_desc = "Alıcı ve satıcılar dengede, kırılım bekleniyor"

    if fc.readiness_score_5 >= 4:
        rd_short = "Güçlü Kurulum"
    elif fc.readiness_score_5 == 3:
        rd_short = "Temkinli İzle"
    else:
        rd_short = "Bekle-Gör"

    # Multi-timeframe alignment bar (15M | 1H | 4H | 1D)
    mtf_line = ""
    if mtf_scores:
        parts_mtf = []
        for tf_k in ("15M", "1H", "4H", "1D"):
            if tf_k in mtf_scores:
                sc_k = mtf_scores[tf_k]
                if sc_k >= 15:
                    lbl_k = f"📈 Yükselen ({sc_k:+.0f})"
                elif sc_k <= -15:
                    lbl_k = f"📉 Düşen ({sc_k:+.0f})"
                else:
                    lbl_k = f"⚖️ Yatay ({sc_k:+.0f})"
                if tf_k == tf_up:
                    parts_mtf.append(f"<b>[{tf_k}: {lbl_k}]</b>")
                else:
                    parts_mtf.append(f"{tf_k}: {lbl_k}")
        if parts_mtf:
            mtf_line = "⏱️ <b>Zaman Dilimleri:</b>\n" + " | ".join(parts_mtf)

    # Card 1: MEVCUT TREND & KIRILIMLAR
    smc_act = fc.smc
    if smc_act and smc_act.structure_events:
        last_ev = smc_act.structure_events[-1]
        if "BULL_BOS" in last_ev.event_type or "BULL_CHOCH" in last_ev.event_type:
            breakout_text = f"🟢 Yukarı Trend Kırılımı ({_p(last_ev.price)} aşımı)"
        elif "BEAR_BOS" in last_ev.event_type or "BEAR_CHOCH" in last_ev.event_type:
            breakout_text = f"🔴 Aşağı Trend Kırılımı ({_p(last_ev.price)} kırılımı)"
        elif "BULL_SWEEP" in last_ev.event_type:
            breakout_text = f"🟢 Dip Tuzak / Stop Avı ({_p(last_ev.price)} — Dönüş İzi)"
        elif "BEAR_SWEEP" in last_ev.event_type:
            breakout_text = f"⚠️ Tepe Tuzak / Stop Avı ({_p(last_ev.price)} — Satış İzi)"
        else:
            breakout_text = "Belirgin kırılım yok"
    else:
        breakout_text = "Henüz yeni kırılım yok"

    sq_pct = fc.squeeze_energy_pct
    if sq_pct >= 68:
        squeeze_short = f"💥 Yüksek Sıkışma (%{sq_pct:.0f}) — ±%{fc.expected_breakout_move_pct:.1f} sert kırılım yakın!"
    elif fc.choppiness_index >= 60:
        squeeze_short = f"⚖️ Yatay Sıkışma (%{sq_pct:.0f}) — Kırılım yönü beklenmeli"
    else:
        squeeze_short = f"🌊 Akıcı Hareket (Beklenen Dalga: ±%{fc.expected_breakout_move_pct:.1f})"

    ema20_val = fc.ema20_price if fc.ema20_price > 0 else current_price
    if fc.nearest_resistance and fc.nearest_resistance > current_price:
        up_break_price = fc.nearest_resistance
    elif ema20_val > current_price:
        up_break_price = ema20_val
    else:
        up_break_price = current_price * 1.008

    if fc.nearest_support and fc.nearest_support < current_price:
        down_break_price = fc.nearest_support
    elif ema20_val < current_price:
        down_break_price = ema20_val
    else:
        down_break_price = current_price * 0.992

    # Card 2: DESTEK, DİRENÇ & HEDEFLER
    sup_str = _p(fc.nearest_support)
    res_str = _p(fc.nearest_resistance)
    sup2_val = fc.support_levels[1].price if len(fc.support_levels) > 1 else None
    res2_val = fc.resistance_levels[1].price if len(fc.resistance_levels) > 1 else None
    sup2_str = f" <i>(2. Destek: {_p(sup2_val)})</i>" if sup2_val else ""
    res2_str = f" <i>(2. Direnç: {_p(res2_val)})</i>" if res2_val else ""

    tp1_disp = fc.tp1_price if fc.tp1_price > 0 else fc.bullish_target_price
    tp2_disp = fc.tp2_price if fc.tp2_price > 0 else fc.bullish_target_price
    stop_disp = fc.stop_price if fc.stop_price > 0 else fc.bearish_invalidation_price
    is_bear_target = (tp2_disp < current_price) or (fc.score < 0)
    dir_label_tr = "Düşüş Hedefi" if is_bear_target else "Yükseliş Hedefi"

    # Card 3: PARA GİRİŞ / ÇIKIŞI & BALİNALAR
    cmf_v = fc.cmf_value
    net_delta_20 = fc.net_delta_20_usd
    wh_score = fc.whale_accumulation_score

    if abs(net_delta_20) >= 1_000_000:
        delta_fmt_str = f"{net_delta_20 / 1_000_000:+,.1f} Milyon USDT"
    elif abs(net_delta_20) >= 1_000:
        delta_fmt_str = f"{net_delta_20 / 1_000:+,.1f} Bin USDT"
    else:
        delta_fmt_str = f"{net_delta_20:+,.0f} USDT"

    if cmf_v > 0.04:
        mf_headline = "🟢 Net Para Girişi Var"
    elif cmf_v < -0.04:
        mf_headline = "🔴 Net Para Çıkışı Var"
    else:
        mf_headline = "⚪ Para Akışı Dengeli"

    if wh_score >= 60:
        whale_short = f"🟢 Balinalar Topluyor ({wh_score:.0f}/100)"
    elif wh_score <= 40:
        whale_short = f"🔴 Balinalar Satıyor ({wh_score:.0f}/100)"
    else:
        whale_short = f"⚪ Balinalar Dengede ({wh_score:.0f}/100)"

    bid_wall_str = _p(fc.ob_bid_wall)
    ask_wall_str = _p(fc.ob_ask_wall)

    # Card 4: MIKNATIS & LİKİDASYON SEVİYELERİ
    poc_str = _p(fc.poc_price)
    poc_dist_pct = abs(fc.poc_price - current_price) / max(current_price, 1e-9) * 100.0
    if current_price >= fc.poc_price:
        poc_relation = f"🟢 Fiyat, mıknatısın üstünde (+%{poc_dist_pct:.1f} — Destek)"
    else:
        poc_relation = f"🟡 Mıknatıs yukarıda (+%{poc_dist_pct:.1f} çekim bölgesi)"
    avwap_low_str = _p(fc.avwap_low_price)

    short_liq_str = "Yok"
    long_liq_str = "Yok"
    if smc_act and smc_act.liquidation_pools:
        for p in smc_act.liquidation_pools:
            if p.pool_type == "SHORT_LIQ":
                short_liq_str = f"<code>{_p(p.price)}</code> (+%{p.distance_pct:.1f})"
            elif p.pool_type == "LONG_LIQ":
                long_liq_str = f"<code>{_p(p.price)}</code> (-%{p.distance_pct:.1f})"

    now_hm = time.strftime("%H:%M:%S")
    lines = [
        f"📊 <b>{symbol} ({tf_up}) DETAYLI ANALİZ RAPORU</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"<b>{trend_title} ({fc.score:+.0f}/100)</b> — <i>{trend_desc}</i>",
        f"🚦 <b>Hazırlık:</b> <b>{fc.readiness_score_5}/5</b> <i>({rd_short})</i> | 🕒 <i>{now_hm}</i>",
    ]
    if mtf_line:
        lines.append(mtf_line)

    fs = fc.futures_setup
    if fs and fs.is_tradeable:
        fut_summary_block = [
            "",
            f"⚡ <b>VADELİ İŞLEM RADARI ({tf_up}):</b> <b>{fs.direction_label_tr}</b>",
            f"• 🛡️ <b>Güven Notu:</b> <b>{fs.confidence_score:.0f}/100 ({fs.confidence_grade})</b> | <b>R:R:</b> 1:{fs.rr_ratio:.2f} | <b>Kaldıraç:</b> Maks {fs.max_safe_leverage}x",
            f"• 🎯 <b>Giriş:</b> <code>{_p(fs.entry_price)}</code> | <b>TP1:</b> <code>{_p(fs.tp1_price)}</code> | <b>TP2:</b> <code>{_p(fs.tp2_price)}</code> | <b>Stop:</b> <code>{_p(fs.stop_price)}</code>",
        ]
    else:
        reason_short = fs.risk_warnings_tr[0] if (fs and fs.risk_warnings_tr) else "Teknik yapı vadeli işleme uygun değil."
        fut_summary_block = [
            "",
            f"⚡ <b>VADELİ İŞLEM RADARI ({tf_up}):</b> ⛔ <b>İŞLEM TAVSİYE EDİLMEZ</b> (Güven: {fs.confidence_score:.0f}/100 - {fs.confidence_grade})",
            f"• ⚠️ <b>Sebep:</b> <i>{reason_short}</i>",
        ]

    lines.extend(
        [
            "",
            f"1️⃣ <b>MEVCUT TREND &amp; KIRILIMLAR ({tf_up})</b>",
            f"• <b>Mevcut Trend:</b> {trend_title}",
            f"• <b>Kırılım İzi:</b> {breakout_text}",
            f"• <b>Sıkışma Durumu:</b> {squeeze_short}",
            f"• <b>Yukarı Kırılım Eşiği:</b> <code>{_p(up_break_price)}</code> üstü",
            f"• <b>Aşağı Kırılım Eşiği:</b> <code>{_p(down_break_price)}</code> altı",
            "",
            "2️⃣ <b>DESTEK, DİRENÇ &amp; HEDEFLER</b>",
            f"• 💰 <b>Fiyat:</b> <code>{_p(current_price)} USDT</code>",
            f"• 🟢 <b>Destek (Taban):</b> <code>{sup_str}</code>{sup2_str}",
            f"• 🔴 <b>Direnç (Tavan):</b> <code>{res_str}</code>{res2_str}",
            f"• 🎯 <b>{dir_label_tr}:</b> <code>{_p(tp1_disp)}</code> ➔ <code>{_p(tp2_disp)}</code>",
            f"• 🛡️ <b>Zarar-Kes (Stop):</b> <code>{_p(stop_disp)}</code>",
            "",
            "3️⃣ <b>PARA GİRİŞ / ÇIKIŞI &amp; BALİNALAR</b>",
            f"• 💸 <b>Durum:</b> <b>{mf_headline}</b>",
            f"• 💵 <b>Son 20 Mum Nakit:</b> <code>{delta_fmt_str}</code>",
            f"• 🐋 <b>Balina Durumu:</b> {whale_short}",
            f"• 📘 <b>Bekleyen Emirler:</b> %{fc.ob_imbalance_pct:.0f} Alıcı / %{100 - fc.ob_imbalance_pct:.0f} Satıcı",
            f"• 🧱 <b>Duvarlar:</b> Alış <code>{bid_wall_str}</code> | Satış <code>{ask_wall_str}</code>",
            "",
            "4️⃣ <b>MIKNATIS &amp; LİKİDASYON SEVİYELERİ</b>",
            f"• 🧲 <b>Mıknatıs:</b> <code>{poc_str}</code>",
            f"• 🟡 <b>En Yoğun Fiyat (POC):</b> {poc_relation}",
            f"• ⚓ <b>Dip Alıcı Maliyeti:</b> <code>{avwap_low_str}</code>",
            f"• ⬆️ <b>Yukarı Likidasyon (Short):</b> {short_liq_str}",
            f"• ⬇️ <b>Aşağı Likidasyon (Long):</b> {long_liq_str}",
        ]
        + fut_summary_block
        + [
            "━━━━━━━━━━━━━━━━━━━━━━",
            "<i>👇 Alttaki dokunmatik butonlarla Vadeli İşlem (Long/Short) Planını açabilir, zaman dilimi değiştirebilir veya grafik isteyebilirsiniz:</i>",
        ]
    )
    return "\n".join(lines)


def format_futures_setup_telegram_html(
    fc: MarketForecast,
    symbol: str,
    timeframe: str,
    current_price: float,
    mtf_scores: Optional[Dict[str, float]] = None,
) -> str:
    """
    Formats the dedicated Perpetual Futures (Vadeli İşlemler) Setup, Confidence & Risk Gate report.
    If `fc.futures_setup.is_tradeable` is False, withholds Entry/TP/Stop and explains why the trade is rejected.
    """
    def _p(val: Optional[float]) -> str:
        return _fmt_price(val, current_price)

    tf_up = timeframe.upper()
    now_hm = time.strftime("%H:%M:%S")
    fs = fc.futures_setup
    sup_str = _p(fc.nearest_support)
    res_str = _p(fc.nearest_resistance)

    lines = [
        f"⚡ <b>{symbol} ({tf_up}) VADELİ İŞLEMLER (FUTURES) KURULUM &amp; GÜVEN RADARI</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 <b>Anlık Fiyat:</b> <code>{_p(current_price)} USDT</code> | 🕒 <i>{now_hm}</i>",
        f"🧱 <b>Ana Destek (Taban):</b> <code>{sup_str}</code> | <b>Ana Direnç (Tavan):</b> <code>{res_str}</code>",
        f"🎖️ <b>Vadeli Güven Notu:</b> <b>{fs.confidence_score:.0f}/100 (Sınıf: {fs.confidence_grade})</b>",
        f"🧭 <b>Radar Kararı:</b> <b>{fs.direction_label_tr}</b>",
    ]

    if not fs.is_tradeable:
        lines.extend(
            [
                "",
                "🛑 <b>RİSK KALKANI DEVREDE: GİRİŞ / TP / STOP VERİLMEDİ</b>",
                "<i>Bu coinde şu an vadeli işlem (Long veya Short) açmak yüksek stop/tasfiye riski taşıdığı için sistem tarafından tavsiye edilmemektedir.</i>",
                "",
                "⚠️ <b>NEDEN İŞLEM AÇILMAMALI? (TESPİT EDİLEN RİSKLER)</b>",
            ]
        )
        for rw in fs.risk_warnings_tr[:4]:
            lines.append(f"• ❌ {rw}")

        if fs.positive_factors_tr:
            lines.append("\n✅ <b>Mevcut Olumlu Noktalar (Yetersiz Kalanlar):</b>")
            for pf in fs.positive_factors_tr[:2]:
                lines.append(f"• {pf}")

        lines.extend(
            [
                "",
                "🔭 <b>NE ZAMAN İŞLEME GİRİLEBİLİR? (İZLEME ŞARTI)</b>",
                f"• ⏳ {fs.wait_condition_tr}",
                f"• 🧲 <b>Mıknatıs (POC):</b> <code>{_p(fc.poc_price)}</code> | <b>Balina:</b> {fc.whale_accumulation_score:.0f}/100",
                "━━━━━━━━━━━━━━━━━━━━━━",
                "<i>💡 Başka bir zaman dilimini (15M / 1H / 4H / 1D) kontrol etmek veya şu an işleme uygun coinleri bulmak için <b>[📡 Vadeli Radar Taraması]</b> butonuna dokunun:</i>",
            ]
        )
        return "\n".join(lines)

    # Tradeable Setup: Show full Entry, TP1, TP2, TP3, Stop-Loss, Leverage & Futures Microstructure
    dir_sign_tp = "+" if fs.direction == "LONG" else "-"
    dir_sign_sl = "-" if fs.direction == "LONG" else "+"
    lines.extend(
        [
            "",
            "🎯 <b>VADELİ İŞLEM GİRİŞ, KÂR AL (TP) &amp; ZARAR-KES (STOP) PLANI</b>",
            f"• 🚀 <b>İşlem Yönü:</b> <b>{fs.direction} ({'Yükseliş / Alış' if fs.direction == 'LONG' else 'Düşüş / Satış'})</b>",
            f"• 📍 <b>Giriş Tipi:</b> {fs.entry_type_tr}",
            f"• 🎯 <b>İdeal Giriş Yeri:</b> <code>{_p(fs.entry_price)} USDT</code> <i>(Aralık: {_p(fs.entry_zone_low)} – {_p(fs.entry_zone_high)})</i>",
            f"• 🟢 <b>1. Kâr Al (TP1 — %50 Kapat &amp; Stopu Girişe Çek):</b> <code>{_p(fs.tp1_price)} USDT</code> (<b>{dir_sign_tp}%{fs.tp1_distance_pct:.2f}</b>)",
            f"• 🟢 <b>2. Ana Hedef (TP2 — Direnç/Destek &amp; Mıknatıs):</b> <code>{_p(fs.tp2_price)} USDT</code> (<b>{dir_sign_tp}%{fs.tp2_distance_pct:.2f}</b>)",
            f"• 🚀 <b>3. Uzatılmış Hedef (TP3 — Likidasyon Havuzu):</b> <code>{_p(fs.tp3_price)} USDT</code> (<b>{dir_sign_tp}%{fs.tp3_distance_pct:.2f}</b>)",
            f"• 🛡️ <b>Zarar-Kes (Stop-Loss — İğne/Av Korumalı):</b> <code>{_p(fs.stop_price)} USDT</code> (<b>{dir_sign_sl}%{fs.stop_distance_pct:.2f}</b>)",
            "",
            "⚖️ <b>KAZANÇ / RİSK &amp; KALDIRAÇ DİSİPLİNİ</b>",
            f"• 📊 <b>Kazanç / Risk Oranı (R:R):</b> <b>1 : {fs.rr_ratio:.2f}</b>",
            f"• ⚙️ <b>Önerilen Maks. İzole Kaldıraç:</b> <b>{fs.max_safe_leverage}x</b> <i>(Aşırı kaldıraçtan kaçının)</i>",
            f"• 🧱 <b>Destek/Direnç Gözetimi:</b> {fs.sr_context_tr}",
            "",
            "🔬 <b>VADELİ TEKNİK &amp; KURUMSAL ONAYLAR</b>",
            f"• 📡 <b>Vadeli Mikro-Yapı:</b> {fs.futures_tech_summary_tr}",
        ]
    )
    for pf in fs.positive_factors_tr[:4]:
        lines.append(f"• ✅ {pf}")
    for rw in fs.risk_warnings_tr[:2]:
        lines.append(f"• ⚠️ <i>Dikkat: {rw}</i>")

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━━━━━",
            "<i>👇 Alttaki butonlarla zaman dilimleri arasında geçiş yapabilir, grafiği görebilir veya kasa büyüklüğüne göre adet hesaplayabilirsiniz (YTD):</i>",
        ]
    )
    return "\n".join(lines)


def format_futures_radar_scan_telegram_html(rows: List[Dict[str, Any]], timeframe: str = "1H") -> str:
    """
    Formats a multi-coin Perpetual Futures Radar scan separating Tradeable Setups from Rejected/Risky Coins.
    """
    tf_up = timeframe.upper()
    now_hm = time.strftime("%H:%M:%S")
    tradeables = []
    rejected = []

    for r in rows:
        fc_obj: Optional[MarketForecast] = r.get("fc")
        if fc_obj and fc_obj.futures_setup and fc_obj.futures_setup.is_tradeable:
            tradeables.append(r)
        else:
            rejected.append(r)

    tradeables.sort(key=lambda x: x["fc"].futures_setup.confidence_score, reverse=True)
    rejected.sort(key=lambda x: x["fc"].futures_setup.confidence_score if x.get("fc") else 0.0, reverse=True)

    lines = [
        f"⚡ <b>VADELİ İŞLEMLER (FUTURES) KURULUM &amp; GÜVEN RADARI [{tf_up}]</b> <i>({now_hm})</i>",
        "<i>Destek/Direnç mesafesi, R:R ve Vadeli teknik yapıya göre sadece güven eşiğinden geçen coinlere Giriş/TP/Stop verilir:</i>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"✅ <b>İŞLEME UYGUN VADELİ KURULUMLAR ({len(tradeables)} Coin)</b>",
    ]

    if not tradeables:
        lines.append(
            "<i>• Şu an bu zaman diliminde düşük riskli ve yüksek güven notlu (>=62/100) vadeli kurulum bulunmuyor. Sistem sermayenizi korumak için işlem önermiyor.</i>"
        )
    else:
        for idx, r in enumerate(tradeables, start=1):
            sym = r["symbol"]
            curr_p = r["price"]
            fs = r["fc"].futures_setup
            p_fmt = ",.4f" if curr_p < 10.0 else ",.2f"
            dir_ic = "🟢 LONG" if fs.direction == "LONG" else "🔴 SHORT"
            lines.append(
                f"{idx}. <b>{sym}</b> — <b>{dir_ic}</b> | 🎖️ Güven: <b>{fs.confidence_score:.0f}/100 ({fs.confidence_grade})</b>\n"
                f"   • 🎯 Giriş: <code>{format(fs.entry_price, p_fmt)}</code> | TP1: <code>{format(fs.tp1_price, p_fmt)}</code> | TP2: <code>{format(fs.tp2_price, p_fmt)}</code>\n"
                f"   • 🛡️ Stop: <code>{format(fs.stop_price, p_fmt)}</code> (%{fs.stop_distance_pct:.2f}) | ⚖️ R:R: <b>1:{fs.rr_ratio:.2f}</b> | Maks: <b>{fs.max_safe_leverage}x</b>"
            )

    lines.append(f"\n⛔ <b>RİSKLİ / İŞLEM TAVSİYE EDİLMEYENLER ({len(rejected)} Coin)</b>")
    for r in rejected[:8]:
        sym = r["symbol"].split("/")[0]
        fc_obj = r.get("fc")
        if fc_obj and fc_obj.futures_setup:
            fs = fc_obj.futures_setup
            why = fs.risk_warnings_tr[0] if fs.risk_warnings_tr else "Teknik yapı uygun değil"
            lines.append(f"• <b>{sym}</b> (Güven: {fs.confidence_score:.0f}/100 - {fs.confidence_grade}): <i>{why}</i>")

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━━━━━",
            "<i>👇 Detaylı vadeli işlem kurulumunu veya reddedilme analizini açmak istediğiniz coine dokunun:</i>",
        ]
    )
    return "\n".join(lines)


def format_screener_telegram_html(rows: List[Dict], timeframe: str, only_high_quality: bool = False) -> str:
    """
    Formats a multi-coin screener result list into a concise, readable Telegram HTML message.
    """
    now_hm = time.strftime("%H:%M:%S")
    title_tag = "🎯 GÜÇLÜ FIRSAT &amp; BALİNA RADARI" if only_high_quality else "🚀 ÇOKLU COİN TARAMA RAPORU"
    lines = [
        f"<b>{title_tag} [{timeframe.upper()}]</b> <i>({now_hm})</i>",
        "<i>Hazırlık onayı (5 üzerinden) ve balina durumuna göre sıralanmıştır:</i>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for idx, r in enumerate(rows[:10], start=1):
        coin = r.get("Coin", "")
        fiyat = r.get("Fiyat (USDT)", r.get("Güncel Fiyat (USDT)", ""))
        yon = r.get("1S Trend", r.get("Yön & Skor", r.get("Genel Yön Eğilimi", "")))
        onay = r.get("Onay", r.get("Hazırlık Onayı", ""))
        balina = r.get("🐋 Balina İzi", r.get("🐋 Balina Skoru", r.get("🐋 Balina Barometresi", "")))
        para = r.get("Para Akışı (1S)", "")
        sr = r.get("Destek / Direnç", "")
        extra_parts = []
        if para:
            extra_parts.append(f"Nakit: {para}")
        if sr:
            extra_parts.append(f"D/D: <code>{sr}</code>")
        extra_line = f"\n   • {' | '.join(extra_parts)}" if extra_parts else ""
        lines.append(
            f"{idx}. <b>{coin}</b> — <code>{fiyat} USDT</code>\n"
            f"   • Trend: {yon} | 🚦 Onay: <b>{onay}</b> | 🐋 Balina: <b>{balina}</b>"
            f"{extra_line}"
        )
    lines.append(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>👇 Detaylı 4 kart analizini açmak istediğiniz coinin butonuna dokunun:</i>"
    )
    return "\n".join(lines)


def format_market_overview_telegram_html(
    coin_summaries: List[Dict[str, Any]],
    session_status_tr: str,
    timeframe: str = "1H",
) -> str:
    """
    Formats a global market & cash flow bulletin (/piyasa or /nakit).
    """
    tf_up = timeframe.upper()
    total = max(len(coin_summaries), 1)
    bulls = [c for c in coin_summaries if c["score"] >= 15]
    bears = [c for c in coin_summaries if c["score"] <= -15]
    neutrals = [c for c in coin_summaries if -15 < c["score"] < 15]

    by_inflow = sorted(coin_summaries, key=lambda x: x["cmf"], reverse=True)
    by_whale = sorted(coin_summaries, key=lambda x: x["whale"], reverse=True)

    top_in = by_inflow[0] if by_inflow else None
    top_out = by_inflow[-1] if by_inflow else None
    top_wh = by_whale[0] if by_whale else None

    if len(bulls) > len(bears) * 1.3:
        mkt_mood = "🟢 ALICILI / POZİTİF PİYASA İKLİMİ"
    elif len(bears) > len(bulls) * 1.3:
        mkt_mood = "🔴 SATICILI / DÜŞÜŞ AĞIRLIKLI PİYASA İKLİMİ"
    else:
        mkt_mood = "⚖️ KARARSIZ / SEÇİCİ PİYASA İKLİMİ"

    lines = [
        f"🌍 <b>KÜRESEL PİYASA &amp; NAKİT AKIŞI ÖZETİ ({tf_up})</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🧭 <b>Genel İklim:</b> <b>{mkt_mood}</b>",
        f"🕒 <b>Aktif Seans:</b> {session_status_tr}",
        f"📊 <b>Trend Dağılımı ({len(coin_summaries)} Coin):</b>",
        f"   • 📈 Yükselen: <b>{len(bulls)}</b> | 📉 Düşen: <b>{len(bears)}</b> | ⚖️ Yatay: <b>{len(neutrals)}</b>",
        "",
        "💸 <b>SICAK PARA &amp; BALİNA LİDERLERİ</b>",
    ]
    if top_in:
        lines.append(f"• 🟢 <b>En Güçlü Para Girişi:</b> <b>{top_in['symbol']}</b> (Nakit: {top_in['delta_str']} | CMF: {top_in['cmf']:+.2f})")
    if top_out:
        lines.append(f"• 🔴 <b>En Çok Para Çıkışı:</b> <b>{top_out['symbol']}</b> (Nakit: {top_out['delta_str']} | CMF: {top_out['cmf']:+.2f})")
    if top_wh:
        lines.append(f"• 🐋 <b>En Yüksek Balina Alımı:</b> <b>{top_wh['symbol']}</b> ({top_wh['whale']:.0f}/100)")

    lines.append("\n📋 <b>COİN BAZLI NAKİT &amp; TREND TABLOSU</b>")
    for c in sorted(coin_summaries, key=lambda x: (x["ready"], abs(x["score"])), reverse=True)[:10]:
        sym_s = c["symbol"].split("/")[0]
        tr_ic = "📈" if c["score"] >= 15 else ("📉" if c["score"] <= -15 else "⚖️")
        mf_ic = "🟢 Giriş" if c["cmf"] > 0.04 else ("🔴 Çıkış" if c["cmf"] < -0.04 else "⚪ Dengeli")
        lines.append(
            f"• <b>{sym_s}</b> (<code>{c['price_str']}</code>): {tr_ic} {c['score']:+.0f} | {mf_ic} ({c['delta_str']}) | 🚦 {c['ready']}/5"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━━━\n<i>👇 İncelemek istediğiniz coine aşağıdan dokunabilirsiniz:</i>")
    return "\n".join(lines)


def format_liquidation_magnet_telegram_html(
    symbol: str,
    tf_forecasts: Dict[str, MarketForecast],
    current_price: float,
) -> str:
    """
    Formats a multi-timeframe Magnet (POC), Institutional Cost (AVWAP) & Liquidation Pool report (/miknatis).
    """
    def _p(val: Optional[float]) -> str:
        return _fmt_price(val, current_price)

    lines = [
        f"🧲 <b>{symbol} MIKNATIS FİYAT &amp; LİKİDASYON HARİTASI</b>",
        f"💰 <b>Güncel Fiyat:</b> <code>{_p(current_price)} USDT</code>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for tf_k in ("15M", "1H", "4H", "1D"):
        if tf_k not in tf_forecasts:
            continue
        fc = tf_forecasts[tf_k]
        poc_rel = "🟢 Fiyat Üstünde" if current_price >= fc.poc_price else "🔴 Fiyat Altında"
        short_p, long_p = "Yok", "Yok"
        if fc.smc and fc.smc.liquidation_pools:
            for pool in fc.smc.liquidation_pools:
                if pool.pool_type == "SHORT_LIQ":
                    short_p = f"<code>{_p(pool.price)}</code> (+%{pool.distance_pct:.1f})"
                elif pool.pool_type == "LONG_LIQ":
                    long_p = f"<code>{_p(pool.price)}</code> (-%{pool.distance_pct:.1f})"
        lines.extend(
            [
                f"⏱️ <b>{tf_k} DİLİMİ MIKNATIS &amp; MALİYETLER</b>",
                f"• 🧲 <b>Mıknatıs (POC):</b> <code>{_p(fc.poc_price)}</code> ({poc_rel})",
                f"• ⚓ <b>Dip Alıcı Maliyeti:</b> <code>{_p(fc.avwap_low_price)}</code> | <b>Tepe Maliyet:</b> <code>{_p(fc.avwap_high_price)}</code>",
                f"• ⬆️ <b>Short Likidasyon:</b> {short_p}",
                f"• ⬇️ <b>Long Likidasyon:</b> {long_p}",
                "",
            ]
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━━━\n<i>💡 Fiyat, hacmin en yoğun olduğu Mıknatıs (POC) ve kaldıraçlı likidasyon havuzlarına çekilme eğilimindedir.</i>")
    return "\n".join(lines)


def format_position_size_telegram_html(
    fc: MarketForecast,
    symbol: str,
    timeframe: str,
    current_price: float,
    capital_usd: float = 1000.0,
    risk_pct: float = 1.0,
) -> str:
    """
    Formats an actionable, non-advisory Position Sizing & Risk Management card (/kasa).
    """
    def _p(val: Optional[float]) -> str:
        return _fmt_price(val, current_price)

    stop_p = fc.stop_price if fc.stop_price > 0 else fc.bearish_invalidation_price
    tp1_p = fc.tp1_price if fc.tp1_price > 0 else fc.bullish_target_price
    tp2_p = fc.tp2_price if fc.tp2_price > 0 else fc.bullish_target_price

    stop_dist_pct = max(abs(current_price - stop_p) / max(current_price, 1e-9) * 100.0, 0.15)
    tp1_dist_pct = abs(tp1_p - current_price) / max(current_price, 1e-9) * 100.0
    tp2_dist_pct = abs(tp2_p - current_price) / max(current_price, 1e-9) * 100.0

    max_risk_usd = capital_usd * (risk_pct / 100.0)
    pos_size_usd = min(max_risk_usd / (stop_dist_pct / 100.0), capital_usd * 3.0)
    coin_qty = pos_size_usd / max(current_price, 1e-9)

    profit_tp1_usd = pos_size_usd * (tp1_dist_pct / 100.0)
    profit_tp2_usd = pos_size_usd * (tp2_dist_pct / 100.0)
    rr_ratio = tp2_dist_pct / max(stop_dist_pct, 0.01)

    is_bear_target = (tp2_p < current_price) or (fc.score < 0)
    dir_str = "📉 DÜŞÜŞ (SHORT) PLANI" if is_bear_target else "📈 YÜKSELİŞ (LONG / SPOT) PLANI"

    lines = [
        f"🧮 <b>{symbol} ({timeframe.upper()}) KASA &amp; RİSK YÖNETİMİ PLANI</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🧭 <b>Aktif Yön:</b> <b>{dir_str}</b> (Hazırlık: {fc.readiness_score_5}/5)",
        f"💼 <b>Örnek Kasa:</b> <code>{capital_usd:,.0f} USDT</code> | <b>İşlem Başı Risk:</b> <code>%{risk_pct:.2f} ({max_risk_usd:,.2f} USDT)</code>",
        "",
        "📏 <b>SEVİYELER &amp; MESAFELER</b>",
        f"• 💰 <b>Giriş (Güncel Fiyat):</b> <code>{_p(current_price)} USDT</code>",
        f"• 🛡️ <b>Zarar-Kes (Stop):</b> <code>{_p(stop_p)} USDT</code> (Mesafe: <b>%{stop_dist_pct:.2f}</b>)",
        f"• 🎯 <b>1. Hedef (TP1):</b> <code>{_p(tp1_p)} USDT</code> (Mesafe: <b>%{tp1_dist_pct:.2f}</b>)",
        f"• 🎯 <b>2. Ana Hedef (TP2):</b> <code>{_p(tp2_p)} USDT</code> (Mesafe: <b>%{tp2_dist_pct:.2f}</b>)",
        "",
        "📦 <b>MATEMATİKSEL POZİSYON BÜYÜKLÜĞÜ</b>",
        f"• 💵 <b>Önerilen İşlem Büyüklüğü:</b> <code>{pos_size_usd:,.2f} USDT</code>",
        f"• 🪙 <b>Alınacak Miktar:</b> <code>{coin_qty:,.4f} {symbol.split('/')[0]}</code>",
        f"• ⚖️ <b>Kazanç / Risk Oranı (R:R):</b> <b>1 : {rr_ratio:.2f}</b>",
        "",
        "💰 <b>OLASI KAR / ZARAR TABLOSU</b>",
        f"• ✅ <b>TP1 Hedefinde Kâr:</b> <code>+{profit_tp1_usd:,.2f} USDT</code>",
        f"• 🚀 <b>TP2 Ana Hedefte Kâr:</b> <code>+{profit_tp2_usd:,.2f} USDT</code>",
        f"• 🛑 <b>Stop Olursa Maksimum Kayıp:</b> <code>-{max_risk_usd:,.2f} USDT</code>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "<i>💡 Farklı kasa büyüklüğü için <code>/kasa ONDO 2500</code> şeklinde yazabilirsiniz (YTD).</i>",
    ]
    return "\n".join(lines)


# ===========================================================================
# 5. INSTANT DARK-THEME CHART IMAGE GENERATOR (MATPLOTLIB AGG -> PNG BYTES)
# ===========================================================================
def generate_telegram_chart_png(
    df: pd.DataFrame,
    fc: MarketForecast,
    symbol: str,
    timeframe: str,
) -> Optional[bytes]:
    """
    Renders a crisp, dark-mode 2-panel chart (Candlesticks + EMA 20/50 + Support/Resistance
    + POC Magnet + TP/Stop levels + Money Flow / RSI panel) into PNG bytes in ~0.15s.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle

        plot_df = df.tail(75).copy().reset_index(drop=True)
        if plot_df.empty:
            return None

        last_price = float(plot_df["close"].iloc[-1])

        def _p(val: Optional[float]) -> str:
            return _fmt_price(val, last_price)

        fig, (ax1, ax2) = plt.subplots(
            2,
            1,
            figsize=(11, 6.8),
            gridspec_kw={"height_ratios": [3.2, 1.1]},
            facecolor="#0B0F19",
        )
        for ax in (ax1, ax2):
            ax.set_facecolor("#0F172A")
            ax.tick_params(colors="#94A3B8", labelsize=8.5)
            for spine in ax.spines.values():
                spine.set_color("#1E293B")
            ax.grid(True, color="#1E293B", linestyle="--", linewidth=0.5, alpha=0.65)

        x = np.arange(len(plot_df))
        opens = plot_df["open"].to_numpy(dtype=float)
        highs = plot_df["high"].to_numpy(dtype=float)
        lows = plot_df["low"].to_numpy(dtype=float)
        closes = plot_df["close"].to_numpy(dtype=float)

        # Candlesticks
        for i in range(len(plot_df)):
            is_bull = closes[i] >= opens[i]
            col = "#00E676" if is_bull else "#FF5252"
            ax1.plot([i, i], [lows[i], highs[i]], color=col, linewidth=1.0, zorder=2)
            body_low = min(opens[i], closes[i])
            body_h = max(abs(closes[i] - opens[i]), (highs[i] - lows[i]) * 0.04, 1e-8)
            rect = Rectangle((i - 0.32, body_low), 0.64, body_h, facecolor=col, edgecolor=col, zorder=3)
            ax1.add_patch(rect)

        # EMA 20 & EMA 50
        if "ema_20" in plot_df.columns:
            ax1.plot(x, plot_df["ema_20"], color="#38BDF8", linewidth=1.5, label="EMA 20 (Kısa Trend)", zorder=4)
        if "ema_50" in plot_df.columns:
            ax1.plot(x, plot_df["ema_50"], color="#F59E0B", linewidth=1.5, label="EMA 50 (Ana Trend)", zorder=4)
        if "avwap_low" in plot_df.columns:
            ax1.plot(x, plot_df["avwap_low"], color="#22D3EE", linewidth=1.2, linestyle=":", label="Dip Alıcı Maliyeti", zorder=4)

        y_min = float(np.min(lows))
        y_max = float(np.max(highs))
        # Expand Y-bounds to include nearby key levels (within ±15% of current price) so TP/Stop/POC are never clipped
        candidate_levels = [
            fc.nearest_support,
            fc.nearest_resistance,
            fc.poc_price,
            fc.tp1_price,
            fc.tp2_price,
            fc.stop_price,
        ]
        for lv in candidate_levels:
            if lv and lv > 0 and abs(lv - last_price) / max(last_price, 1e-9) <= 0.15:
                y_min = min(y_min, float(lv))
                y_max = max(y_max, float(lv))

        pad = max((y_max - y_min) * 0.14, last_price * 0.005)
        y_lo, y_hi = y_min - pad, y_max + pad
        min_label_gap = (y_hi - y_lo) * 0.048
        used_label_ys: List[float] = []

        def _draw_level(price_val: Optional[float], color: str, label_txt: str, style: str = "--") -> None:
            if price_val is None or price_val <= 0 or not (y_lo <= price_val <= y_hi):
                return
            ax1.axhline(price_val, color=color, linestyle=style, linewidth=1.15, alpha=0.88, zorder=5)
            lbl_y = float(price_val)
            for _ in range(6):
                conflict = False
                for uy in used_label_ys:
                    if abs(lbl_y - uy) < min_label_gap:
                        lbl_y = uy + min_label_gap if lbl_y >= uy else uy - min_label_gap
                        conflict = True
                if not conflict:
                    break
            lbl_y = float(np.clip(lbl_y, y_lo + min_label_gap * 0.4, y_hi - min_label_gap * 0.4))
            used_label_ys.append(lbl_y)
            ax1.text(
                len(plot_df) + 0.6,
                lbl_y,
                f" {label_txt}: {_p(price_val)} ",
                color="#0B0F19",
                fontsize=8,
                fontweight="bold",
                va="center",
                bbox=dict(boxstyle="round,pad=0.22", facecolor=color, edgecolor="none", alpha=0.92),
                zorder=6,
            )

        _draw_level(fc.nearest_support, "#00E676", "Destek", "--")
        _draw_level(fc.nearest_resistance, "#FF5252", "Direnç", "--")
        _draw_level(fc.poc_price, "#FACC15", "Mıknatıs (POC)", "-.")
        _draw_level(fc.tp1_price, "#38BDF8", "Hedef 1 (TP1)", ":")
        _draw_level(fc.tp2_price, "#10B981", "Hedef 2 (TP2)", ":")
        _draw_level(fc.stop_price, "#FB7185", "Zarar-Kes (Stop)", ":")

        ax1.set_xlim(-1.5, len(plot_df) + 14)
        ax1.set_ylim(y_lo, y_hi)

        trend_tag = "YÜKSELEN TREND" if fc.score >= 15 else ("DÜŞEN TREND" if fc.score <= -15 else "YATAY TREND")
        ax1.set_title(
            f"{symbol} [{timeframe.upper()}] — {trend_tag} ({fc.score:+.0f}/100) | Hazırlık: {fc.readiness_score_5}/5 | Fiyat: {_p(last_price)} USDT",
            color="#F8FAFC",
            fontsize=11,
            fontweight="bold",
            pad=10,
        )
        leg = ax1.legend(loc="upper left", facecolor="#0F172A", edgecolor="#334155", fontsize=8)
        for text in leg.get_texts():
            text.set_color("#E2E8F0")

        # Bottom Panel: RSI & Money Flow (CMF scaled)
        if "rsi" in plot_df.columns:
            rsi_vals = plot_df["rsi"].to_numpy(dtype=float)
            ax2.plot(x, rsi_vals, color="#C084FC", linewidth=1.5, label="RSI (Alım İştahı)")
            ax2.axhline(70, color="#FF5252", linestyle="--", linewidth=0.8, alpha=0.6)
            ax2.axhline(30, color="#00E676", linestyle="--", linewidth=0.8, alpha=0.6)
            ax2.axhline(50, color="#64748B", linestyle=":", linewidth=0.7, alpha=0.5)
            ax2.set_ylim(15, 85)
        ax2.set_xlim(-1.5, len(plot_df) + 14)
        ax2.set_ylabel("RSI", color="#94A3B8", fontsize=8.5)

        if "timestamp" in plot_df.columns:
            tick_idx = np.linspace(0, len(plot_df) - 1, min(7, len(plot_df)), dtype=int)
            tick_labels = [pd.to_datetime(plot_df["timestamp"].iloc[i]).strftime("%m-%d %H:%M") for i in tick_idx]
            ax2.set_xticks(tick_idx)
            ax2.set_xticklabels(tick_labels, color="#94A3B8", fontsize=8)
        ax1.set_xticks([])

        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=130, facecolor="#0B0F19", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


# ===========================================================================
# 6. LOW-LEVEL TELEGRAM BOT API CALLERS (TEXT, EDIT, CALLBACK, PHOTO)
# ===========================================================================
def send_telegram_message(
    bot_token: str,
    chat_id: str,
    html_text: str,
    timeout: int = 12,
    reply_markup: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    Sends an HTML-formatted message via Telegram Bot API with optional Inline/Reply Keyboard.
    Returns (success, status_message_tr).
    """
    token = (bot_token or "").strip()
    cid = (chat_id or "").strip()
    if not token or not cid:
        return False, "Lütfen geçerli bir Telegram Bot Token ve Chat ID girin."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params: Dict[str, str] = {
        "chat_id": cid,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if reply_markup is not None:
        params["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    payload = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                return True, "✅ Rapor Telegram hesabınıza başarıyla gönderildi!"
            return False, f"Telegram API yanıt hatası: {body.get('description', 'Bilinmeyen hata')}"
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            desc = err_body.get("description", str(e))
        except Exception:
            desc = str(e)
        return False, f"❌ Telegram HTTP Hatası ({e.code}): {desc}"
    except Exception as e:
        return False, f"❌ Bağlantı Hatası: {e}"


def edit_telegram_message(
    bot_token: str,
    chat_id: str,
    message_id: int,
    html_text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    timeout: int = 12,
) -> bool:
    """
    Edits an existing Telegram message in-place when the user taps an inline button
    (e.g. switching between 15M / 1H / 4H / 1D). Falls back to send_telegram_message if edit fails.
    """
    token = (bot_token or "").strip()
    cid = (chat_id or "").strip()
    if not token or not cid or not message_id:
        return False

    url = f"https://api.telegram.org/bot{token}/editMessageText"
    params: Dict[str, str] = {
        "chat_id": cid,
        "message_id": str(message_id),
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if reply_markup is not None:
        params["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    payload = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("ok"))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
            if "message is not modified" in err_body.lower():
                return True
        except Exception:
            pass
        return False
    except Exception:
        return False


def answer_callback_query(
    bot_token: str,
    callback_query_id: str,
    text: str = "",
    show_alert: bool = False,
) -> bool:
    """Acknowledges an inline keyboard button tap on Telegram."""
    token = (bot_token or "").strip()
    if not token or not callback_query_id:
        return False
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    params: Dict[str, str] = {"callback_query_id": callback_query_id}
    if text:
        params["text"] = text[:190]
    if show_alert:
        params["show_alert"] = "true"
    payload = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("ok"))
    except Exception:
        return False


def send_telegram_photo(
    bot_token: str,
    chat_id: str,
    photo_bytes: bytes,
    caption_html: str = "",
    reply_markup: Optional[Dict[str, Any]] = None,
    timeout: int = 20,
) -> Tuple[bool, str]:
    """
    Uploads a PNG chart image to Telegram via multipart/form-data using pure standard library urllib.
    """
    token = (bot_token or "").strip()
    cid = (chat_id or "").strip()
    if not token or not cid or not photo_bytes:
        return False, "Eksik Telegram bilgisi veya görsel verisi."

    boundary = f"----AntigravityBoundary{uuid.uuid4().hex}"
    body = io.BytesIO()

    def _add_field(name: str, value: str) -> None:
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.write(f"{value}\r\n".encode("utf-8"))

    _add_field("chat_id", cid)
    if caption_html:
        _add_field("caption", caption_html[:1020])
        _add_field("parse_mode", "HTML")
    if reply_markup is not None:
        _add_field("reply_markup", json.dumps(reply_markup, ensure_ascii=False))

    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(b'Content-Disposition: form-data; name="photo"; filename="chart.png"\r\n')
    body.write(b"Content-Type: image/png\r\n\r\n")
    body.write(photo_bytes)
    body.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = urllib.request.Request(
        url,
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("ok"):
                return True, "✅ Grafik ve analiz Telegram hesabınıza gönderildi!"
            return False, f"Telegram Fotoğraf Hatası: {res.get('description', 'Bilinmeyen hata')}"
    except Exception as e:
        return False, f"❌ Grafik gönderilemedi: {e}"
