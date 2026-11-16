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
WATCHLIST_FILE = ROOT_DIR / "watchlist.json"

DEFAULT_SHARED_WATCHLIST = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ONDO/USDT",
    "SUI/USDT",
    "FET/USDT",
    "AVAX/USDT",
    "LINK/USDT",
]

POPULAR_QUICK_COINS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "SUI/USDT",
    "ONDO/USDT",
    "FET/USDT",
    "TON/USDT",
    "NEAR/USDT",
    "INJ/USDT",
    "ARB/USDT",
    "OP/USDT",
    "APT/USDT",
    "RENDER/USDT",
    "AAVE/USDT",
    "PEPE/USDT",
    "TIA/USDT",
]


def load_shared_watchlist() -> List[str]:
    """Loads shared watchlist.json used by both Web UI and Telegram Bot."""
    if WATCHLIST_FILE.exists():
        try:
            data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return [str(x).strip().upper() for x in data if str(x).strip()]
        except Exception:
            pass
    return list(DEFAULT_SHARED_WATCHLIST)


def save_shared_watchlist(coins: List[str]) -> bool:
    """Saves shared watchlist.json cleanly without duplicates."""
    try:
        clean = list(dict.fromkeys([str(c).strip().upper() for c in coins if str(c).strip()]))
        WATCHLIST_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


# ===========================================================================
# 1. CONFIG & PERSISTENT STATE MANAGEMENT (ALARMS, RADAR, COOLDOWNS)
# ===========================================================================
def _clean_bot_token(raw: str) -> str:
    """Sanitizes user-pasted bot token (strips quotes, TOML key prefixes, whitespace, and leading 'bot')."""
    s = str(raw or "").strip()
    if "=" in s:
        s = s.split("=", 1)[1].strip()
    s = s.strip("\"'` \t\r\n")
    if s.lower().startswith("bot") and ":" in s and s[3:4].isdigit():
        s = s[3:]
    return s.strip()


def _clean_chat_id(raw: str) -> str:
    """Sanitizes user-pasted chat ID (strips quotes, TOML key prefixes, and whitespace)."""
    s = str(raw or "").strip()
    if "=" in s:
        s = s.split("=", 1)[1].strip()
    return s.strip("\"'` \t\r\n")


def load_telegram_config() -> Dict[str, str]:
    """Loads saved Telegram bot_token and chat_id from local JSON file, Streamlit secrets, or environment variables."""
    env_tok = _clean_bot_token(os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    env_cid = _clean_chat_id(os.environ.get("TELEGRAM_CHAT_ID", ""))
    if not env_tok or not env_cid:
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                env_tok = env_tok or _clean_bot_token(st.secrets.get("TELEGRAM_BOT_TOKEN", ""))
                env_cid = env_cid or _clean_chat_id(st.secrets.get("TELEGRAM_CHAT_ID", ""))
        except Exception:
            pass
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            tok = _clean_bot_token(data.get("bot_token", "")) or env_tok
            cid = _clean_chat_id(data.get("chat_id", "")) or env_cid
            return {"bot_token": tok, "chat_id": cid}
        except Exception:
            pass
    return {"bot_token": env_tok, "chat_id": env_cid}


def save_telegram_config(bot_token: str, chat_id: str) -> bool:
    """Persists Telegram bot_token and chat_id locally."""
    try:
        CONFIG_FILE.write_text(
            json.dumps(
                {"bot_token": _clean_bot_token(bot_token), "chat_id": _clean_chat_id(chat_id)},
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
        "primary_exchange": "binance",
        "radar_enabled": True,
        "radar_interval_sec": 600,  # 10 minutes
        "auto_session_summary": True,
        "send_chart_with_analysis": True,
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
    chat_id: str = "",
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
        "chat_id": str(chat_id).strip(),
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
        return True, f"🟢 7/24 Bot & Radar zaten arka planda çalışıyor (PID: {pid})."
    bot_script = ROOT_DIR / "telegram_bot.py"
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        cfg = load_telegram_config()
        if cfg.get("bot_token"):
            env["TELEGRAM_BOT_TOKEN"] = cfg["bot_token"]
        if cfg.get("chat_id"):
            env["TELEGRAM_CHAT_ID"] = cfg["chat_id"]
        try:
            from .x_publisher import load_x_config
            x_cfg = load_x_config()
            if x_cfg.get("api_key"):
                env["X_API_KEY"] = x_cfg["api_key"]
            if x_cfg.get("api_secret"):
                env["X_API_SECRET"] = x_cfg["api_secret"]
            if x_cfg.get("access_token"):
                env["X_ACCESS_TOKEN"] = x_cfg["access_token"]
            if x_cfg.get("access_token_secret"):
                env["X_ACCESS_TOKEN_SECRET"] = x_cfg["access_token_secret"]
        except Exception:
            pass

        popen_kwargs: Dict[str, Any] = {
            "cwd": str(ROOT_DIR),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen([sys.executable, str(bot_script)], **popen_kwargs)
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        return True, f"🤖 7/24 İnteraktif Telegram & X (Twitter) Otomatik Radar Botu başlatıldı (PID: {proc.pid})!"
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
                {"text": "🚨 Kırılım Radarı"},
                {"text": "⚡ Vadeli İşlem Radarı"},
            ],
            [
                {"text": "🚀 Tümünü Tara (4H)"},
                {"text": "🌍 Piyasa & Nakit Özeti"},
                {"text": "⏰ Alarmlarım & Radar"},
            ],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def build_analysis_inline_keyboard(
    symbol: str,
    active_tf: str = "4H",
    in_watchlist: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Builds a rich touch button deck underneath every single-coin analysis message:
      Row 1: [15M] [1H] [4H] [1D] instant timeframe switcher
      Row 2: [⚡ Vadeli İşlem Kurulumu] [🚨 Kırılım Radarı]
      Row 3: [🖼️ Grafik] [🧲 Mıknatıs & Likidasyon] [🧮 Kasa Planı]
      Row 4: [🔔 Direnç Alarmı Kur] [🔔 Destek Alarmı Kur]
      Row 5: [➕ Listeye Ekle / ➖ Çıkar] [🪙 Coin Listesi] [🚀 Tarama]
    """
    tf_up = active_tf.upper()
    sym_up = symbol.upper()
    if in_watchlist is None:
        in_watchlist = sym_up in load_shared_watchlist()

    tf_row = []
    for tf_opt in ("15M", "1H", "4H", "1D"):
        lbl = f"✅ {tf_opt}" if tf_opt == tf_up else f"⏱️ {tf_opt}"
        tf_row.append({"text": lbl, "callback_data": f"an:{sym_up}:{tf_opt}"})

    wl_btn = (
        {"text": "➖ Listeden Çıkar", "callback_data": f"wl_del:{sym_up}:{tf_up}"}
        if in_watchlist
        else {"text": "➕ Listeye Ekle", "callback_data": f"wl_add:{sym_up}:{tf_up}"}
    )

    return {
        "inline_keyboard": [
            tf_row,
            [
                {"text": "⚡ Vadeli İşlem (Long/Short) Planı", "callback_data": f"fut:{sym_up}:{tf_up}"},
                {"text": "🚨 Kırılım Radarı", "callback_data": f"brk_scan:{tf_up}"},
            ],
            [
                {"text": "🖼️ Grafik Gönder", "callback_data": f"chart:{sym_up}:{tf_up}"},
                {"text": "🧲 Mıknatıs & Lik.", "callback_data": f"liq:{sym_up}:{tf_up}"},
                {"text": "🧮 Kasa Planı", "callback_data": f"kasa:{sym_up}:{tf_up}"},
            ],
            [
                {"text": "🔔 Direnç Alarmı (+)", "callback_data": f"al_res:{sym_up}:{tf_up}"},
                {"text": "🔔 Destek Alarmı (-)", "callback_data": f"al_sup:{sym_up}:{tf_up}"},
                {"text": "🐦 X'te Paylaş", "callback_data": f"x_post:{sym_up}:{tf_up}"},
            ],
            [
                wl_btn,
                {"text": "🪙 Coin Listesi", "callback_data": f"coins:{tf_up}"},
                {"text": "🔄 Yenile", "callback_data": f"an_ref:{sym_up}:{tf_up}"},
            ],
        ]
    }


def build_futures_setup_inline_keyboard(symbol: str, active_tf: str = "4H") -> Dict[str, Any]:
    """
    Builds interactive touch buttons underneath the Dedicated Perpetual Futures Setup screen:
      Row 1: [15M] [1H] [4H] [1D] instant timeframe switcher for Futures Setup
      Row 2: [📊 Genel Analiz] [🖼️ Vadeli Grafik] [🧮 Kasa Planı]
      Row 3: [🔔 Direnç Alarmı (+)] [🔔 Destek Alarmı (-)] [🐦 X'te Paylaş]
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
                {"text": "📊 Genel Analiz", "callback_data": f"an:{symbol}:{tf_up}"},
                {"text": "🖼️ Vadeli Grafik", "callback_data": f"fut_chart:{symbol}:{tf_up}"},
                {"text": "🧮 Kasa Planı", "callback_data": f"kasa:{symbol}:{tf_up}"},
            ],
            [
                {"text": "🔔 Direnç Alarmı (+)", "callback_data": f"al_res:{symbol}:{tf_up}"},
                {"text": "🔔 Destek Alarmı (-)", "callback_data": f"al_sup:{symbol}:{tf_up}"},
                {"text": "🐦 X'te Paylaş", "callback_data": f"x_fut:{symbol}:{tf_up}"},
            ],
            [
                {"text": "🔄 Yenile", "callback_data": f"fut_ref:{symbol}:{tf_up}"},
                {"text": "📡 Vadeli Radar Taraması", "callback_data": f"fut_scan:{tf_up}"},
                {"text": "🪙 Coin Seç", "callback_data": f"coins:{tf_up}"},
            ],
        ]
    }


def build_futures_radar_inline_keyboard(rows: List[Dict[str, Any]], timeframe: str = "4H") -> Dict[str, Any]:
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
            {"text": "🐦 X'te Paylaş", "callback_data": f"x_fut_scan:{tf_up}"},
        ]
    )
    return {"inline_keyboard": kb_rows}


def build_coin_list_inline_keyboard(watchlist: List[str], timeframe: str = "4H") -> Dict[str, Any]:
    """Builds a 3-column touch grid of coins from the user's watchlist + Add/Remove Coin buttons."""
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

    # Interactive Watchlist Add / Remove Row
    rows.append(
        [
            {"text": "➕ Yeni Coin Ekle", "callback_data": f"wl_menu:add:{tf_up}"},
            {"text": "➖ Coin Çıkar", "callback_data": f"wl_menu:del:{tf_up}"},
        ]
    )

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


def build_watchlist_manage_inline_keyboard(
    watchlist: List[str],
    mode: str = "add",
    timeframe: str = "4H",
) -> Dict[str, Any]:
    """
    Builds a 1-tap interactive Coin Add / Remove management deck for Telegram:
      - mode="add": shows popular liquid coins not yet in `watchlist` for instant 1-tap addition
      - mode="del": shows current coins in `watchlist` for instant 1-tap removal
    """
    tf_up = timeframe.upper()
    rows: List[List[Dict[str, str]]] = []
    wl_set = {c.upper() for c in watchlist}

    if mode == "del":
        curr: List[Dict[str, str]] = []
        for sym in watchlist[:15]:
            short_n = sym.split("/")[0]
            curr.append({"text": f"🗑️ {short_n}", "callback_data": f"wl_qdel:{sym}:{tf_up}"})
            if len(curr) == 3:
                rows.append(curr)
                curr = []
        if curr:
            rows.append(curr)
        rows.append(
            [
                {"text": "➕ Coin Ekleme Menüsü", "callback_data": f"wl_menu:add:{tf_up}"},
                {"text": "🔙 Coin Listesine Dön", "callback_data": f"coins:{tf_up}"},
            ]
        )
    else:
        candidates = [c for c in POPULAR_QUICK_COINS if c.upper() not in wl_set][:12]
        curr = []
        for sym in candidates:
            short_n = sym.split("/")[0]
            curr.append({"text": f"➕ {short_n}", "callback_data": f"wl_qadd:{sym}:{tf_up}"})
            if len(curr) == 3:
                rows.append(curr)
                curr = []
        if curr:
            rows.append(curr)
        rows.append(
            [
                {"text": "➖ Coin Çıkarma Menüsü", "callback_data": f"wl_menu:del:{tf_up}"},
                {"text": "🔙 Coin Listesine Dön", "callback_data": f"coins:{tf_up}"},
            ]
        )
    return {"inline_keyboard": rows}


def build_screener_inline_keyboard(
    rows: List[Dict[str, Any]],
    timeframe: str = "4H",
    only_high_quality: bool = False,
) -> Dict[str, Any]:
    """
    Builds interactive touch buttons under the Multi-Coin Screener so the user can:
      - Tap any ranked coin to open its detailed analysis immediately
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
            {"text": "🌍 Piyasa Özeti", "callback_data": f"market:{tf_up}"},
            {"text": "🐦 X'te Paylaş", "callback_data": f"x_scan:{tf_up}:{q_flag}"},
        ]
    )
    return {"inline_keyboard": kb_rows}


def build_alarm_radar_inline_keyboard(state: Dict[str, Any]) -> Dict[str, Any]:
    """Builds interactive touch controls for Alarms & 24/7 Telegram + X (Twitter) Radar settings."""
    radar_on = bool(state.get("radar_enabled", True))
    sess_on = bool(state.get("auto_session_summary", True))
    alarms = state.get("alarms", [])
    try:
        from .x_publisher import load_x_state
        x_st = load_x_state()
        x_radar_on = bool(x_st.get("x_auto_radar_enabled", True))
    except Exception:
        x_radar_on = True

    kb: List[List[Dict[str, str]]] = [
        [
            {
                "text": "🟢 Telegram Radar: AÇIK" if radar_on else "🔴 Telegram Radar: KAPALI",
                "callback_data": "radar:toggle",
            },
            {
                "text": "🐦 X Otomatik Radar: AÇIK" if x_radar_on else "⚪ X Otomatik Radar: KAPALI",
                "callback_data": "x_radar:toggle",
            },
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
            {"text": "🪙 Coin Seç & Alarm Ekle", "callback_data": "coins:4H"},
            {"text": "🚀 Tümünü Tara", "callback_data": "scan:4H:0"},
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
    timeframe: str = "4H",
    current_price: float = 0.0,
    mtf_scores: Optional[Dict[str, float]] = None,
) -> str:
    """
    Formats a MarketForecast into a short, concise, high-signal Turkish HTML message for Telegram.
    Does NOT include Futures Stop/TP levels (those belong exclusively to the Futures analysis view).
    Clearly distinguishes:
      - Trend Regime: Yükselen Trend / Düşen Trend / Yatay Trend + Swing Structure (HH/HL, LH/LL)
      - Candlestick Anatomy: Last closed candle structure & volume
      - Strong ('🛡️ Güçlü Destek' / '🧱 Güçlü Direnç') vs Ordinary ('🟢 Sıradan Destek' / '🔴 Sıradan Direnç')
      - Beginner-friendly plain roadmap (YTD)
    """
    def _p(val: Optional[float]) -> str:
        return _fmt_price(val, current_price)

    tf_up = timeframe.upper()
    t_state = getattr(fc, "trend_state", "")
    if t_state == "UPTREND" or (not t_state and fc.score >= 15):
        trend_title = "📈 YÜKSELEN TREND"
    elif t_state == "DOWNTREND" or (not t_state and fc.score <= -15):
        trend_title = "📉 DÜŞEN TREND"
    else:
        trend_title = "⚖️ YATAY TREND"

    swing_str = getattr(fc, "swing_structure_tr", "") or "Dengeli Pivot"
    candle_str = getattr(fc, "candle_anatomy_tr", "") or getattr(fc, "last_pattern_tr", "")
    if len(candle_str) > 46:
        candle_str = candle_str[:43].rstrip() + "..."

    # Compact multi-timeframe alignment bar (15M | 1H | 4H | 1D)
    mtf_line = ""
    if mtf_scores:
        parts_mtf = []
        for tf_k in ("15M", "1H", "4H", "1D"):
            if tf_k in mtf_scores:
                sc_k = mtf_scores[tf_k]
                ic_k = "📈" if sc_k >= 15 else ("📉" if sc_k <= -15 else "⚖️")
                cell = f"{tf_k}:{ic_k}{sc_k:+.0f}"
                parts_mtf.append(f"<b>[{cell}]</b>" if tf_k == tf_up else cell)
        if parts_mtf:
            mtf_line = "⏱️ " + " | ".join(parts_mtf)

    # Support & Resistance (Strong vs Ordinary clearly separated)
    sup_str = _p(fc.nearest_support)
    res_str = _p(fc.nearest_resistance)
    sup1_tier = getattr(fc, "nearest_support_tier_tr", "🟢 Sıradan Destek")
    sup1_score = getattr(fc, "nearest_support_score", 0.0)
    sup1_reason = getattr(fc, "nearest_support_reason_tr", "")
    res1_tier = getattr(fc, "nearest_resistance_tier_tr", "🔴 Sıradan Direnç")
    res1_score = getattr(fc, "nearest_resistance_score", 0.0)
    res1_reason = getattr(fc, "nearest_resistance_reason_tr", "")

    sup1_short_r = (sup1_reason.split(" + ")[0] if sup1_reason else "")[:18]
    res1_short_r = (res1_reason.split(" + ")[0] if res1_reason else "")[:18]
    sup1_meta = f" ({sup1_score:.0f}p{f'·{sup1_short_r}' if sup1_short_r else ''})" if sup1_score > 0 else ""
    res1_meta = f" ({res1_score:.0f}p{f'·{res1_short_r}' if res1_short_r else ''})" if res1_score > 0 else ""

    sup2_inline = ""
    if len(fc.support_levels) > 1:
        s2_obj = fc.support_levels[1]
        s2_ic = "🛡️" if getattr(s2_obj, "is_strong", False) else "🟢"
        sup2_inline = f" | 2.{s2_ic}<code>{_p(s2_obj.price)}</code>"

    res2_inline = ""
    if len(fc.resistance_levels) > 1:
        r2_obj = fc.resistance_levels[1]
        r2_ic = "🧱" if getattr(r2_obj, "is_strong", False) else "🔴"
        res2_inline = f" | 2.{r2_ic}<code>{_p(r2_obj.price)}</code>"

    # Breakout / Level Action
    sr_act_type = getattr(fc, "sr_action_type", "NONE")
    sr_act_str = getattr(fc, "sr_action_status_tr", "")
    ema20_val = fc.ema20_price if fc.ema20_price > 0 else current_price
    up_break_price = fc.nearest_resistance if (fc.nearest_resistance and fc.nearest_resistance > current_price) else max(ema20_val, current_price * 1.008)
    down_break_price = fc.nearest_support if (fc.nearest_support and fc.nearest_support < current_price) else min(ema20_val, current_price * 0.992)

    if sr_act_type != "NONE" and sr_act_str:
        short_act = sr_act_str.split(".")[0].strip()
        if len(short_act) > 56:
            short_act = short_act[:53].rstrip() + "..."
        brk_line = f"• 🚨 <b>Durum:</b> {short_act}"
    elif fc.squeeze_energy_pct >= 68:
        brk_line = f"• 💥 <b>Sıkışma:</b> %{fc.squeeze_energy_pct:.0f} (±%{fc.expected_breakout_move_pct:.1f} kırılım yakın)"
    else:
        brk_line = f"• 📐 <b>Kırılım:</b> ⬆️<code>{_p(up_break_price)}</code> üstü | ⬇️<code>{_p(down_break_price)}</code> altı"

    # Cash Flow & Whales
    cmf_v = fc.cmf_value
    net_delta_20 = fc.net_delta_20_usd
    wh_score = fc.whale_accumulation_score
    if abs(net_delta_20) >= 1_000_000:
        delta_fmt_str = f"{net_delta_20 / 1_000_000:+,.1f}M$"
    elif abs(net_delta_20) >= 1_000:
        delta_fmt_str = f"{net_delta_20 / 1_000:+,.1f}K$"
    else:
        delta_fmt_str = f"{net_delta_20:+,.0f}$"

    mf_ic = "🟢 Giriş" if cmf_v > 0.04 else ("🔴 Çıkış" if cmf_v < -0.04 else "⚪ Dengeli")
    wh_ic = "🟢 Topluyor" if wh_score >= 60 else ("🔴 Satıyor" if wh_score <= 40 else "⚪ Nötr")
    poc_str = _p(fc.poc_price)
    now_hm = time.strftime("%H:%M")

    guidance_str = getattr(fc, "plain_guidance_tr", "") or (
        f"{sup_str} desteği ile {res_str} direnci arasındaki kırılım yönü belirler (YTD)."
    )
    if len(guidance_str) > 100:
        guidance_str = guidance_str[:93].rstrip() + " (YTD)."

    lines = [
        f"📊 <b>{symbol} ({tf_up}) GENEL &amp; YAPISAL ANALİZ</b> <i>({now_hm})</i>",
        f"💰 <b>Fiyat:</b> <code>{_p(current_price)} USDT</code> | <b>{trend_title} ({fc.score:+.0f})</b>",
        f"📐 <b>Yapı:</b> {swing_str} | 🕯️ <b>Mum:</b> {candle_str}",
    ]
    if mtf_line:
        lines.append(mtf_line)

    lines.extend(
        [
            "━━━━━━━━━━━━",
            "🧱 <b>DESTEK &amp; DİRENÇ SINIFLANDIRMASI</b>",
            f"• <b>{sup1_tier}:</b> <code>{sup_str}</code><i>{sup1_meta}</i>{sup2_inline}",
            f"• <b>{res1_tier}:</b> <code>{res_str}</code><i>{res1_meta}</i>{res2_inline}",
            brk_line,
            "━━━━━━━━━━━━",
            "🐋 <b>PARA AKIŞI &amp; MIKNATIS</b>",
            f"• <b>Nakit:</b> {mf_ic} (<code>{delta_fmt_str}</code>) | <b>Balina:</b> {wh_ic} ({wh_score:.0f}) | 🧲 <b>POC:</b> <code>{poc_str}</code>",
            f"🧭 <b>SADE YOL HARİTASI (YTD):</b> {guidance_str}",
        ]
    )
    return "\n".join(lines)


def format_futures_setup_telegram_html(
    fc: MarketForecast,
    symbol: str,
    timeframe: str = "4H",
    current_price: float = 0.0,
    mtf_scores: Optional[Dict[str, float]] = None,
) -> str:
    """
    Formats a concise, high-clarity Perpetual Futures (Vadeli İşlemler) Setup report.
    Shows Futures Entry, TP1, TP2, TP3, Stop-Loss, Leverage & Squeeze ONLY here when Futures analysis is selected.
    """
    def _p(val: Optional[float]) -> str:
        return _fmt_price(val, current_price)

    tf_up = timeframe.upper()
    now_hm = time.strftime("%H:%M")
    fs = fc.futures_setup
    sup_str = _p(fc.nearest_support)
    res_str = _p(fc.nearest_resistance)
    sup_tier = getattr(fc, "nearest_support_tier_tr", "🟢 Sıradan Destek")
    sup_sc = getattr(fc, "nearest_support_score", 0.0)
    res_tier = getattr(fc, "nearest_resistance_tier_tr", "🔴 Sıradan Direnç")
    res_sc = getattr(fc, "nearest_resistance_score", 0.0)
    lev_sq_str = getattr(fs, "leverage_squeeze_status_tr", "") or getattr(fc, "leverage_squeeze_status_tr", "")

    lines = [
        f"⚡ <b>{symbol} ({tf_up}) VADELİ İŞLEM PLANI</b> <i>({now_hm})</i>",
        f"💰 <b>Fiyat:</b> <code>{_p(current_price)} USDT</code> | 🎖️ <b>Vadeli Güven:</b> <b>{fs.confidence_score:.0f}/100 ({fs.confidence_grade})</b>",
        f"🧭 <b>Karar:</b> <b>{fs.direction_label_tr}</b>",
        f"• <b>{sup_tier} ({sup_sc:.0f}p):</b> <code>{sup_str}</code> | <b>{res_tier} ({res_sc:.0f}p):</b> <code>{res_str}</code>",
    ]
    if lev_sq_str:
        lines.append(f"• {lev_sq_str}")
    lines.append("━━━━━━━━━━━━")

    if not fs.is_tradeable:
        lines.append("🛑 <b>RİSK KALKANI: GİRİŞ / STOP / TP VERİLMEDİ</b>")
        for rw in fs.risk_warnings_tr[:2]:
            lines.append(f"• ❌ {rw}")
        lines.extend(
            [
                f"• ⏳ <b>Şart (YTD):</b> {fs.wait_condition_tr}",
                f"• 🧲 <b>Mıknatıs (POC):</b> <code>{_p(fc.poc_price)}</code> | 🐋 <b>Balina:</b> {fc.whale_accumulation_score:.0f}/100",
            ]
        )
        return "\n".join(lines)

    dir_sign_tp = "+" if fs.direction == "LONG" else "-"
    dir_sign_sl = "-" if fs.direction == "LONG" else "+"
    lines.extend(
        [
            f"🎯 <b>Giriş ({fs.direction}):</b> <code>{_p(fs.entry_price)} USDT</code> <i>({fs.entry_type_tr})</i>",
            f"• 🟢 <b>TP1 (%50 Kâr Al):</b> <code>{_p(fs.tp1_price)}</code> (<b>{dir_sign_tp}%{fs.tp1_distance_pct:.2f}</b>)",
            f"• 🟢 <b>TP2 (Ana Hedef):</b> <code>{_p(fs.tp2_price)}</code> (<b>{dir_sign_tp}%{fs.tp2_distance_pct:.2f}</b>)",
            f"• 🚀 <b>TP3 (Uzatılmış):</b> <code>{_p(fs.tp3_price)}</code> (<b>{dir_sign_tp}%{fs.tp3_distance_pct:.2f}</b>)",
            f"• 🛡️ <b>Zarar-Kes (Stop):</b> <code>{_p(fs.stop_price)}</code> (<b>{dir_sign_sl}%{fs.stop_distance_pct:.2f}</b> — İğne Korumalı)",
            "━━━━━━━━━━━━",
            f"⚖️ <b>R:R:</b> <b>1:{fs.rr_ratio:.2f}</b> | ⚙️ <b>Maks. İzole Kaldıraç:</b> <b>{fs.max_safe_leverage}x</b> (YTD)",
        ]
    )
    for pf in fs.positive_factors_tr[:2]:
        lines.append(f"• ✅ {pf}")
    if fs.risk_warnings_tr:
        lines.append(f"• ⚠️ <i>{fs.risk_warnings_tr[0]}</i>")
    return "\n".join(lines)


def format_futures_radar_scan_telegram_html(rows: List[Dict[str, Any]], timeframe: str = "4H") -> str:
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
    timeframe: str = "4H",
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
    ]
    if coin_summaries and getattr(coin_summaries[0].get("fc"), "macro_liquidity_tr", ""):
        mac_l = getattr(coin_summaries[0]["fc"], "macro_liquidity_tr", "")
        if mac_l and mac_l != "Makro Likidite Dengeli":
            lines.append(f"🌐 <b>Makro Pusula:</b> {mac_l}")
    lines.extend(
        [
            f"📊 <b>Trend Dağılımı ({len(coin_summaries)} Coin):</b>",
            f"   • 📈 Yükselen: <b>{len(bulls)}</b> | 📉 Düşen: <b>{len(bears)}</b> | ⚖️ Yatay: <b>{len(neutrals)}</b>",
            "",
            "💸 <b>SICAK PARA &amp; BALİNA LİDERLERİ</b>",
        ]
    )
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
    timeframe: str = "4H",
    current_price: float = 0.0,
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


def build_breakout_radar_inline_keyboard(rows: List[Dict[str, Any]], timeframe: str = "4H") -> Dict[str, Any]:
    """
    Builds interactive touch buttons underneath the Support/Resistance Breakout & SFP Radar screen:
      - Direct buttons for coins to open their full analysis or chart
      - Timeframe switcher [15M | 1H | 4H | 1D] for the Breakout Radar
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
        act_t = getattr(fc_obj, "sr_action_type", "NONE") if fc_obj else "NONE"
        tl_st = getattr(getattr(fc_obj, "trendlines", None), "breakout_status", "NONE") if fc_obj else "NONE"
        if act_t == "BULL_SR_BREAKOUT" or tl_st == "BULL_BREAKOUT":
            ic = "🚀"
        elif act_t == "BEAR_SR_BREAKDOWN" or tl_st == "BEAR_BREAKDOWN":
            ic = "🩸"
        elif "SFP" in act_t:
            ic = "🪤"
        elif "RETEST" in act_t:
            ic = "🔄"
        else:
            ic = "⏳"
        coin_btns.append({"text": f"{ic} {short_sym}", "callback_data": f"an:{sym}:{tf_up}"})
        if len(coin_btns) == 4:
            kb_rows.append(coin_btns)
            coin_btns = []
    if coin_btns:
        kb_rows.append(coin_btns)

    tf_row = []
    for tf_opt in ("15M", "1H", "4H", "1D"):
        lbl = f"✅ {tf_opt}" if tf_opt == tf_up else f"🚨 {tf_opt}"
        tf_row.append({"text": lbl, "callback_data": f"brk_scan:{tf_opt}"})
    kb_rows.append(tf_row)

    kb_rows.append(
        [
            {"text": "⚡ Vadeli İşlem Radarı", "callback_data": f"fut_scan:{tf_up}"},
            {"text": "🚀 Genel Tarama Tablosu", "callback_data": f"scan:{tf_up}:0"},
            {"text": "🐦 X'te Paylaş", "callback_data": f"x_brk_scan:{tf_up}"},
        ]
    )
    return {"inline_keyboard": kb_rows}


def format_breakout_radar_scan_telegram_html(rows: List[Dict[str, Any]], timeframe: str = "4h") -> str:
    """
    Formats the Multi-Coin Support/Resistance Breakout, Retest, SFP Trap & "How Does a Breakout Happen?" Radar.
    """
    tf_up = timeframe.upper()
    now_hm = time.strftime("%H:%M:%S")
    lines = [
        f"🚨 <b>DESTEK / DİRENÇ KIRILIM RADARI &amp; REHBERİ ({tf_up})</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "📐 <b>KIRILIM NASIL OLUR? (KURUMSAL TEKNİK KURAL):</b>",
        "• 📈 <b>Gerçek Direnç Kırılımı:</b> Fiyatın dirence sadece <i>iğne (fitil)</i> atması kırılım <b>değildir</b>! Kapanmış mum <b>gövdesinin</b> direnç bandı üstünde kapanması ve <b>Hacmin (RVOL ≥ 1.20x)</b> artması gerekir. Kırılan direnç <b>Yeni Destek</b> olur.",
        "• 📉 <b>Gerçek Destek Kırılımı:</b> Kapanmış mum <b>gövdesinin</b> destek bandı altında kapanması gerekir. Kırılan destek <b>Yeni Direnç</b> olur.",
        "• 🪤 <b>Sahte Kırılım (SFP / Tuzak):</b> Fiyat seviyenin dışına iğne atıp stopları patlattıktan sonra tekrar kanal içine kapanırsa <b>Ters Yöne Dönüş</b> sinyalidir!",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    active_events: List[str] = []
    near_events: List[str] = []

    for r in rows:
        sym = str(r.get("symbol", r.get("Coin", "")))
        fc: Optional[MarketForecast] = r.get("fc")
        if not fc:
            continue
        curr_p = float(r.get("price", 0.0))
        p_fmt = ",.4f" if curr_p < 10.0 else ",.2f"
        act_t = getattr(fc, "sr_action_type", "NONE")
        act_str = getattr(fc, "sr_action_status_tr", "")
        rvol = float(getattr(fc, "sr_breakout_rvol", 1.0) or 1.0)
        tl = getattr(fc, "trendlines", None)
        tl_st = getattr(tl, "breakout_status", "NONE") if tl else "NONE"
        tl_sum = getattr(tl, "summary_tr", "") if tl else ""

        sup_tier = getattr(fc, "nearest_support_tier_tr", "🟢 Sıradan Destek")
        res_tier = getattr(fc, "nearest_resistance_tier_tr", "🔴 Sıradan Direnç")
        sup_p = fc.nearest_support or curr_p * 0.99
        res_p = fc.nearest_resistance or curr_p * 1.01

        if act_t in ("BULL_SR_BREAKOUT", "BEAR_SR_BREAKDOWN") or tl_st in ("BULL_BREAKOUT", "BEAR_BREAKDOWN"):
            msg_txt = act_str if act_t in ("BULL_SR_BREAKOUT", "BEAR_SR_BREAKDOWN") else tl_sum
            active_events.append(
                f"• <b>{sym}</b> (<code>{format(curr_p, p_fmt)} USDT</code> | Hacim: <b>{rvol:.2f}x</b>)\n"
                f"  ↳ <b>{msg_txt}</b>\n"
                f"  ↳ {sup_tier}: <code>{format(sup_p, p_fmt)}</code> | {res_tier}: <code>{format(res_p, p_fmt)}</code>"
            )
        elif act_t in ("BULL_SFP", "BEAR_SFP", "BULL_RETEST", "BEAR_RETEST"):
            active_events.append(
                f"• <b>{sym}</b> (<code>{format(curr_p, p_fmt)} USDT</code> | Hacim: <b>{rvol:.2f}x</b>)\n"
                f"  ↳ {act_str}"
            )
        else:
            res_obj = fc.resistance_levels[0] if fc.resistance_levels else None
            sup_obj = fc.support_levels[0] if fc.support_levels else None
            res_bh = res_obj.band_high if res_obj else res_p
            sup_bl = sup_obj.band_low if sup_obj else sup_p
            dist_res_pct = abs(res_bh - curr_p) / max(curr_p, 1e-9) * 100.0
            dist_sup_pct = abs(curr_p - sup_bl) / max(curr_p, 1e-9) * 100.0
            if dist_res_pct <= dist_sup_pct:
                near_events.append(
                    f"• <b>{sym}</b> (<code>{format(curr_p, p_fmt)}</code>): 📈 <b>{res_tier} Kırılımına %{dist_res_pct:.2f}</b> ➔ "
                    f"<code>{format(res_bh, p_fmt)}</code> üstü kapanış"
                )
            else:
                near_events.append(
                    f"• <b>{sym}</b> (<code>{format(curr_p, p_fmt)}</code>): 📉 <b>{sup_tier} Kırılımına %{dist_sup_pct:.2f}</b> ➔ "
                    f"<code>{format(sup_bl, p_fmt)}</code> altı kapanış"
                )

    if active_events:
        lines.append(f"🔥 <b>AKTİF KIRILIM, TUZAK (SFP) &amp; RETEST TESPİTLERİ ({len(active_events)} Coin):</b>")
        lines.extend(active_events)
    else:
        lines.append("ℹ️ <i>Şu an bu zaman diliminde yeni tamamlanmış bir gövde kırılımı bulunmuyor.</i>")

    if near_events:
        lines.append("")
        lines.append("⏳ <b>KIRILIM EŞİĞİ TAKİP LİSTESİ (Kırılım İçin Gereken Mum Kapanışı):</b>")
        lines.extend(near_events[:8])

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🕒 <i>Son Tarama: {now_hm} | 7/24 Otomatik Kırılım Bildirimleri Aktif!</i>",
            "<i>👇 Grafiğini ve özet analizini görmek istediğiniz coine dokunun:</i>",
        ]
    )
    return "\n".join(lines)


# ===========================================================================
# 5. INSTANT DARK-THEME CHART IMAGE GENERATOR (MATPLOTLIB AGG -> PNG BYTES)
# ===========================================================================
def generate_telegram_chart_png(
    df: pd.DataFrame,
    fc: MarketForecast,
    symbol: str,
    timeframe: str = "4h",
    include_futures_levels: bool = False,
) -> Optional[bytes]:
    """
    Renders a crisp, dark-mode 2-panel chart (Candlesticks + EMA 20/50 + Support/Resistance
    + POC Magnet + RSI panel) into PNG bytes in ~0.15s.
    IMPORTANT:
      - When `include_futures_levels=False` (default for general analysis):
        Does NOT draw Futures Entry / TP1 / TP2 / Stop-Loss lines on the chart.
      - When `include_futures_levels=True` (selected via Vadeli Analiz):
        Draws Futures Entry, TP1, TP2, and Stop-Loss lines if `fc.futures_setup.is_tradeable`.
      - Explicitly labels Support & Resistance as 'Güçlü Destek' vs 'Sıradan Destek' and 'Güçlü Direnç' vs 'Sıradan Direnç'.
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
        candidate_levels = [
            fc.nearest_support,
            fc.nearest_resistance,
            fc.poc_price,
        ]
        if include_futures_levels and getattr(fc, "futures_setup", None) and fc.futures_setup.is_tradeable:
            candidate_levels.extend(
                [
                    fc.futures_setup.entry_price,
                    fc.futures_setup.tp1_price,
                    fc.futures_setup.tp2_price,
                    fc.futures_setup.stop_price,
                ]
            )
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

        for idx_s, sup in enumerate(getattr(fc, "support_levels", [])[:2], start=1):
            if y_lo <= sup.price <= y_hi:
                is_str_s = bool(getattr(sup, "is_strong", False))
                s_sc = float(getattr(sup, "strength_score", 45.0))
                ax1.axhspan(
                    max(sup.band_low, y_lo),
                    min(sup.band_high, y_hi),
                    color="#00E676",
                    alpha=0.12 if is_str_s else 0.05,
                    zorder=2,
                )
                s_lbl = f"{idx_s}. Güçlü Destek ({s_sc:.0f}p)" if is_str_s else f"{idx_s}. Sıradan Destek ({s_sc:.0f}p)"
                _draw_level(sup.price, "#00E676" if is_str_s else "#6EE7B7", s_lbl, "-" if is_str_s else "--")
        if not getattr(fc, "support_levels", None):
            is_str_s0 = getattr(fc, "nearest_support_score", 0.0) >= 62.0
            sup_chart_lbl = "Güçlü Destek" if is_str_s0 else "Sıradan Destek"
            _draw_level(fc.nearest_support, "#00E676" if is_str_s0 else "#6EE7B7", sup_chart_lbl, "-" if is_str_s0 else "--")

        for idx_r, res in enumerate(getattr(fc, "resistance_levels", [])[:2], start=1):
            if y_lo <= res.price <= y_hi:
                is_str_r = bool(getattr(res, "is_strong", False))
                r_sc = float(getattr(res, "strength_score", 45.0))
                ax1.axhspan(
                    max(res.band_low, y_lo),
                    min(res.band_high, y_hi),
                    color="#FF5252",
                    alpha=0.12 if is_str_r else 0.05,
                    zorder=2,
                )
                r_lbl = f"{idx_r}. Güçlü Direnç ({r_sc:.0f}p)" if is_str_r else f"{idx_r}. Sıradan Direnç ({r_sc:.0f}p)"
                _draw_level(res.price, "#FF5252" if is_str_r else "#FDA4AF", r_lbl, "-" if is_str_r else "--")
        if not getattr(fc, "resistance_levels", None):
            is_str_r0 = getattr(fc, "nearest_resistance_score", 0.0) >= 62.0
            res_chart_lbl = "Güçlü Direnç" if is_str_r0 else "Sıradan Direnç"
            _draw_level(fc.nearest_resistance, "#FF5252" if is_str_r0 else "#FDA4AF", res_chart_lbl, "-" if is_str_r0 else "--")

        _draw_level(fc.poc_price, "#FACC15", "Mıknatıs (POC)", "-.")
        if include_futures_levels and getattr(fc, "futures_setup", None) and fc.futures_setup.is_tradeable:
            _draw_level(fc.futures_setup.entry_price, "#E2E8F0", f"Vadeli Giriş ({fc.futures_setup.direction})", "-.")
            _draw_level(fc.futures_setup.tp1_price, "#38BDF8", "Hedef 1 (TP1)", ":")
            _draw_level(fc.futures_setup.tp2_price, "#10B981", "Hedef 2 (TP2)", ":")
            _draw_level(fc.futures_setup.stop_price, "#FB7185", "Zarar-Kes (Stop)", ":")

        # Draw Dynamic Trendlines & Breakout / SFP / Retest Banner Badge on PNG Chart
        tl_obj = getattr(fc, "trendlines", None)
        if tl_obj is not None and "timestamp" in plot_df.columns:
            ts_list = pd.to_datetime(plot_df["timestamp"]).tolist()
            if getattr(tl_obj, "has_support_line", False) and tl_obj.sup_x0 is not None and tl_obj.sup_y1 > 0:
                t0_s = pd.to_datetime(tl_obj.sup_x0)
                idx0_s = int(np.argmin([abs((t - t0_s).total_seconds()) for t in ts_list]))
                if y_lo <= tl_obj.sup_y1 <= y_hi:
                    ax1.plot([idx0_s, len(plot_df) - 1], [tl_obj.sup_y0, tl_obj.sup_y1], color="#10B981", linestyle="-.", linewidth=1.6, zorder=4)
            if getattr(tl_obj, "has_resistance_line", False) and tl_obj.res_x0 is not None and tl_obj.res_y1 > 0:
                t0_r = pd.to_datetime(tl_obj.res_x0)
                idx0_r = int(np.argmin([abs((t - t0_r).total_seconds()) for t in ts_list]))
                if y_lo <= tl_obj.res_y1 <= y_hi:
                    ax1.plot([idx0_r, len(plot_df) - 1], [tl_obj.res_y0, tl_obj.res_y1], color="#F43F5E", linestyle="-.", linewidth=1.6, zorder=4)

        sr_act_t = getattr(fc, "sr_action_type", "NONE")
        sr_act_p = float(getattr(fc, "sr_action_price", 0.0) or 0.0)
        tl_st_p = getattr(tl_obj, "breakout_status", "NONE") if tl_obj else "NONE"
        banner_txt = ""
        banner_col = "#38BDF8"
        if sr_act_t == "BULL_SR_BREAKOUT":
            banner_txt = f"DİRENÇ KIRILIMI GELDİ! ({_p(sr_act_p)} Üstü Mum Kapanışı ➔ Yeni Destek)"
            banner_col = "#00E676"
        elif sr_act_t == "BEAR_SR_BREAKDOWN":
            banner_txt = f"DESTEK KIRILIMI GELDİ! ({_p(sr_act_p)} Altı Mum Kapanışı ➔ Yeni Direnç)"
            banner_col = "#FF5252"
        elif sr_act_t == "BULL_SFP":
            banner_txt = f"SAHTE DESTEK KIRILIMI / AYI TUZAĞI (SFP @ {_p(sr_act_p)})"
            banner_col = "#38BDF8"
        elif sr_act_t == "BEAR_SFP":
            banner_txt = f"SAHTE DİRENÇ KIRILIMI / BOĞA TUZAĞI (SFP @ {_p(sr_act_p)})"
            banner_col = "#F59E0B"
        elif sr_act_t == "BULL_RETEST":
            banner_txt = f"ONAYLI DESTEK TESTİ / RETEST ({_p(sr_act_p)})"
            banner_col = "#34D399"
        elif sr_act_t == "BEAR_RETEST":
            banner_txt = f"ONAYLI DİRENÇ REDDİ / RETEST ({_p(sr_act_p)})"
            banner_col = "#FB7185"
        elif tl_st_p == "BULL_BREAKOUT":
            banner_txt = f"DÜŞEN TREND YUKARI KIRILDI! ({_p(tl_obj.res_current_price)})"
            banner_col = "#00E676"
        elif tl_st_p == "BEAR_BREAKDOWN":
            banner_txt = f"YÜKSELEN TREND AŞAĞI KIRILDI! ({_p(tl_obj.sup_current_price)})"
            banner_col = "#FF5252"

        if banner_txt:
            ax1.text(
                0.50,
                0.93,
                f" {banner_txt} ",
                transform=ax1.transAxes,
                color="#0B0F19",
                fontsize=8.8,
                fontweight="bold",
                ha="center",
                va="top",
                bbox=dict(boxstyle="round,pad=0.32", facecolor=banner_col, edgecolor="#0B0F19", alpha=0.94),
                zorder=8,
            )

        ax1.set_xlim(-1.5, len(plot_df) + 15.5)
        ax1.set_ylim(y_lo, y_hi)

        t_st_c = getattr(fc, "trend_state", "")
        if t_st_c == "UPTREND" or (not t_st_c and fc.score >= 15):
            trend_tag = "YÜKSELEN TREND"
        elif t_st_c == "DOWNTREND" or (not t_st_c and fc.score <= -15):
            trend_tag = "DÜŞEN TREND"
        else:
            trend_tag = "YATAY TREND"
        swing_tag = getattr(fc, "swing_structure_tr", "") or ""
        mode_tag = (
            f"VADELİ İŞLEM PLANI ({fc.futures_setup.direction})"
            if (include_futures_levels and getattr(fc, "futures_setup", None) and fc.futures_setup.is_tradeable)
            else ("VADELİ RİSK KALKANI" if include_futures_levels else f"{trend_tag} ({fc.score:+.0f}/100)")
        )
        sub_tag = f" | {swing_tag}" if (swing_tag and not include_futures_levels) else ""
        ax1.set_title(
            f"{symbol} [{timeframe.upper()}] — {mode_tag}{sub_tag} | Fiyat: {_p(last_price)} USDT",
            color="#F8FAFC",
            fontsize=10.5,
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
        ax2.set_xlim(-1.5, len(plot_df) + 15.5)
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
    token = _clean_bot_token(bot_token)
    cid = _clean_chat_id(chat_id)
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
        if e.code == 401:
            return (
                False,
                "❌ Telegram HTTP 401 (Yetkisiz/Geçersiz Token): Girilen Bot Token şu an geçersiz veya @BotFather tarafından iptal edilmiş (Revoked). "
                "Lütfen Telegram'da @BotFather'a gidip /token komutuyla güncel Token'ınızı alın ve sol menüye yapıştırıp Kaydet'e basın.",
            )
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
    If caption_html exceeds Telegram's 1024-char photo caption limit, sends the photo first and
    immediately sends the full HTML text + keyboard below it so HTML tags are never truncated.
    """
    token = _clean_bot_token(bot_token)
    cid = _clean_chat_id(chat_id)
    if not token or not cid or not photo_bytes:
        return False, "Eksik Telegram bilgisi veya görsel verisi."

    caption_fits = len(caption_html or "") <= 1020

    boundary = f"----AntigravityBoundary{uuid.uuid4().hex}"
    body = io.BytesIO()

    def _add_field(name: str, value: str) -> None:
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.write(f"{value}\r\n".encode("utf-8"))

    _add_field("chat_id", cid)
    if caption_html and caption_fits:
        _add_field("caption", caption_html)
        _add_field("parse_mode", "HTML")
    if reply_markup is not None and caption_fits:
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
                if caption_html and not caption_fits:
                    send_telegram_message(token, cid, caption_html, reply_markup=reply_markup)
                return True, "✅ Grafik ve analiz Telegram hesabınıza gönderildi!"
            return False, f"Telegram Fotoğraf Hatası: {res.get('description', 'Bilinmeyen hata')}"
    except Exception as e:
        return False, f"❌ Grafik gönderilemedi: {e}"


def edit_telegram_photo_message(
    bot_token: str,
    chat_id: str,
    message_id: int,
    photo_bytes: bytes,
    caption_html: str = "",
    reply_markup: Optional[Dict[str, Any]] = None,
    timeout: int = 20,
) -> bool:
    """
    Edits an existing Telegram photo message in-place with a new chart image and HTML caption
    via `editMessageMedia`. Returns True if updated in-place, False if the target message was text-only.
    """
    token = _clean_bot_token(bot_token)
    cid = _clean_chat_id(chat_id)
    if not token or not cid or not message_id or not photo_bytes or len(caption_html or "") > 1020:
        return False

    boundary = f"----AntigravityMediaBoundary{uuid.uuid4().hex}"
    body = io.BytesIO()

    def _add_field(name: str, value: str) -> None:
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.write(f"{value}\r\n".encode("utf-8"))

    media_obj: Dict[str, Any] = {
        "type": "photo",
        "media": "attach://chart_photo",
    }
    if caption_html:
        media_obj["caption"] = caption_html
        media_obj["parse_mode"] = "HTML"

    _add_field("chat_id", cid)
    _add_field("message_id", str(message_id))
    _add_field("media", json.dumps(media_obj, ensure_ascii=False))
    if reply_markup is not None:
        _add_field("reply_markup", json.dumps(reply_markup, ensure_ascii=False))

    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(b'Content-Disposition: form-data; name="chart_photo"; filename="chart.png"\r\n')
    body.write(b"Content-Type: image/png\r\n\r\n")
    body.write(photo_bytes)
    body.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = f"https://api.telegram.org/bot{token}/editMessageMedia"
    req = urllib.request.Request(
        url,
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return bool(res.get("ok"))
    except Exception:
        return False
