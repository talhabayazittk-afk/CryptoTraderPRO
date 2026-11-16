"""
Comprehensive X (Twitter) Auto-Publisher, OAuth 1.0a Signer, Media Uploader & Crypto Tweet Formatter (v1.0).
Uses 100% Python standard library (`hmac`, `hashlib`, `base64`, `urllib.request`, `urllib.parse`, `json`, `uuid`)
so zero external third-party packages are required.

Capabilities:
  1. Pure-stdlib OAuth 1.0a HMAC-SHA1 request signing for X API v2 (`/2/tweets`) and v1.1 Media Upload
  2. Automatic dark-mode PNG chart upload (`upload.twitter.com/1.1/media/upload.json`) and tweet attachment
  3. Accurate X (Twitter) weighted character counter (280-char standard limit aware of emojis & Turkish chars)
  4. 3 Publishing Modes:
       - `SHORT_280`: Single punchy Crypto X post (<= 280 weighted chars) + PNG Chart (Works on Free & All accounts)
       - `THREAD`: 2-Tweet Flood/Thread (Tweet 1: Chart + Core Levels, Tweet 2: Reply with MTF, Flow & Roadmap)
       - `LONG_PREMIUM`: Detailed long-form X post + PNG Chart (For X Premium accounts)
  5. 24/7 Proactive Auto-Radar & Session Bulletin rate-limiter, per-coin cooldowns, daily quota guard & post history log
"""
import base64
import hashlib
import hmac
import io
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .signals import MarketForecast

ROOT_DIR = Path(__file__).resolve().parent.parent
X_CONFIG_FILE = ROOT_DIR / "x_config.json"
X_STATE_FILE = ROOT_DIR / "x_state.json"


# ===========================================================================
# 1. X (TWITTER) CREDENTIALS & PERSISTENT STATE MANAGEMENT
# ===========================================================================
def _clean_cred(raw: str) -> str:
    """Sanitizes user-pasted X API keys/tokens (strips quotes, key= prefixes, and whitespace)."""
    s = str(raw or "").strip()
    if "=" in s and not s.startswith("http"):
        left, right = s.split("=", 1)
        if left.strip().upper().replace("_", "").isalnum():
            s = right.strip()
    return s.strip("\"'` \t\r\n")


def load_x_config() -> Dict[str, str]:
    """
    Loads saved X (Twitter) API v2 / OAuth 1.0a User Context credentials from:
      1. Local `x_config.json`
      2. Environment variables (`X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`)
      3. Streamlit secrets (`st.secrets`)
    """
    env_ck = _clean_cred(os.environ.get("X_API_KEY", "") or os.environ.get("TWITTER_API_KEY", ""))
    env_cs = _clean_cred(os.environ.get("X_API_SECRET", "") or os.environ.get("TWITTER_API_SECRET", ""))
    env_at = _clean_cred(os.environ.get("X_ACCESS_TOKEN", "") or os.environ.get("TWITTER_ACCESS_TOKEN", ""))
    env_as = _clean_cred(
        os.environ.get("X_ACCESS_TOKEN_SECRET", "") or os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "")
    )

    if not (env_ck and env_cs and env_at and env_as):
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                env_ck = env_ck or _clean_cred(st.secrets.get("X_API_KEY", ""))
                env_cs = env_cs or _clean_cred(st.secrets.get("X_API_SECRET", ""))
                env_at = env_at or _clean_cred(st.secrets.get("X_ACCESS_TOKEN", ""))
                env_as = env_as or _clean_cred(st.secrets.get("X_ACCESS_TOKEN_SECRET", ""))
        except Exception:
            pass

    if X_CONFIG_FILE.exists():
        try:
            data = json.loads(X_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "api_key": _clean_cred(data.get("api_key", "")) or env_ck,
                    "api_secret": _clean_cred(data.get("api_secret", "")) or env_cs,
                    "access_token": _clean_cred(data.get("access_token", "")) or env_at,
                    "access_token_secret": _clean_cred(data.get("access_token_secret", "")) or env_as,
                }
        except Exception:
            pass

    return {
        "api_key": env_ck,
        "api_secret": env_cs,
        "access_token": env_at,
        "access_token_secret": env_as,
    }


def save_x_config(
    api_key: str,
    api_secret: str,
    access_token: str,
    access_token_secret: str,
) -> bool:
    """Persists X (Twitter) OAuth 1.0a credentials locally to `x_config.json`."""
    try:
        payload = {
            "api_key": _clean_cred(api_key),
            "api_secret": _clean_cred(api_secret),
            "access_token": _clean_cred(access_token),
            "access_token_secret": _clean_cred(access_token_secret),
        }
        X_CONFIG_FILE.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def is_x_configured(cfg: Optional[Dict[str, str]] = None) -> bool:
    """Returns True if all 4 required OAuth 1.0a credentials are non-empty."""
    c = cfg if cfg is not None else load_x_config()
    return bool(
        c.get("api_key", "").strip()
        and c.get("api_secret", "").strip()
        and c.get("access_token", "").strip()
        and c.get("access_token_secret", "").strip()
    )


def _default_x_state() -> Dict[str, Any]:
    return {
        "x_auto_radar_enabled": True,          # 7/24 automatic breakout/whale/squeeze X posts
        "x_auto_session_bulletin": True,       # Automatic 09:00 & 16:30 global market X post
        "x_auto_futures_radar": False,         # Optional automatic A-grade futures setup X posts
        "x_attach_chart": True,                # Upload & attach dark-mode PNG chart to X posts
        "x_post_mode": "SHORT_280",            # SHORT_280 | THREAD | LONG_PREMIUM
        "x_radar_interval_sec": 1800,          # Check every 30 minutes
        "x_coin_cooldown_sec": 14400,          # 4 hours cooldown per coin on X
        "x_max_daily_posts": 15,               # Safe guard for X Free Tier (17 posts / 24h)
        "x_custom_hashtags": "#Kripto #Bitcoin",
        "x_cooldowns": {},                     # symbol -> last_post_epoch
        "x_daily_counts": {},                  # YYYY-MM-DD -> int count
        "x_last_session_tag": "",
        "x_post_history": [],                  # Last 20 published posts [{time, title, tweet_id, url}]
    }


def load_x_state() -> Dict[str, Any]:
    """Loads persistent X auto-publisher state and settings."""
    base = _default_x_state()
    if X_STATE_FILE.exists():
        try:
            data = json.loads(X_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base.update(data)
        except Exception:
            pass
    return base


def save_x_state(state: Dict[str, Any]) -> bool:
    """Saves persistent X auto-publisher state to disk."""
    try:
        X_STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def get_x_daily_post_count(state: Optional[Dict[str, Any]] = None) -> int:
    """Returns how many automatic/manual posts were sent today (local date)."""
    st = state if state is not None else load_x_state()
    today_key = time.strftime("%Y-%m-%d")
    counts = st.get("x_daily_counts", {})
    if not isinstance(counts, dict):
        return 0
    return int(counts.get(today_key, 0))


def record_x_post_success(
    tweet_id: str,
    title: str,
    symbol: str = "",
) -> str:
    """
    Increments today's X post counter, prunes old dates, and appends the live post URL
    to `x_post_history` (retaining the latest 20 posts). Returns the public X URL.
    """
    st = load_x_state()
    today_key = time.strftime("%Y-%m-%d")
    counts = st.get("x_daily_counts", {})
    if not isinstance(counts, dict):
        counts = {}
    # Keep only last 7 days in counts dict
    counts[today_key] = int(counts.get(today_key, 0)) + 1
    if len(counts) > 7:
        for old_k in sorted(counts.keys())[:-7]:
            counts.pop(old_k, None)
    st["x_daily_counts"] = counts

    url = f"https://x.com/i/web/status/{tweet_id}" if tweet_id else ""
    history = st.get("x_post_history", [])
    if not isinstance(history, list):
        history = []
    history.insert(
        0,
        {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol.upper() if symbol else "GENEL",
            "title": title,
            "tweet_id": str(tweet_id),
            "url": url,
        },
    )
    st["x_post_history"] = history[:20]
    save_x_state(st)
    return url


# ===========================================================================
# 2. TWITTER WEIGHTED CHARACTER COUNTER & 280-CHAR SMART FITTER
# ===========================================================================
def x_weighted_length(text: str) -> int:
    """
    Computes X (Twitter) v3 weighted character length:
      - URLs count as 23 chars.
      - Code points U+0000 .. U+10FF (all ASCII, Latin, and Turkish chars ğüşıöçĞÜŞİÖÇ) count as 1.
      - Code points > U+10FF (Emojis, symbols, box drawing) count as 2.
    """
    if not text:
        return 0
    # Replace URLs with 23-char placeholder
    cleaned = re.sub(r"https?://\S+", "x" * 23, text)
    total = 0
    for ch in cleaned:
        cp = ord(ch)
        # Skip zero-width joiners / variation selectors inside emoji sequences if needed,
        # or count conservatively so we never exceed 280.
        if cp <= 0x10FF:
            total += 1
        else:
            total += 2
    return total


def fit_x_text_280(text: str, max_weight: int = 278) -> str:
    """
    Ensures a tweet never exceeds X's 280 weighted-character limit.
    Trims lines or trailing characters gracefully while preserving hashtags/YTD if possible.
    """
    s = (text or "").strip()
    if x_weighted_length(s) <= max_weight:
        return s

    # Walk character by character up to max_weight - 3
    acc: List[str] = []
    curr_w = 0
    target_w = max_weight - 3
    for ch in s:
        w = 1 if ord(ch) <= 0x10FF else 2
        if curr_w + w > target_w:
            break
        acc.append(ch)
        curr_w += w
    trimmed = "".join(acc).rstrip()
    return f"{trimmed}..."


def build_x_intent_url(text: str) -> str:
    """
    Builds an official, zero-cost X Web Intent URL (`https://x.com/intent/tweet?text=...`)
    that opens X on web or mobile app with the analysis text pre-filled.
    """
    fitted = fit_x_text_280(text, 278)
    return f"https://x.com/intent/tweet?text={urllib.parse.quote(fitted, safe='')}"


def copy_chart_png_to_windows_clipboard(photo_bytes: Optional[bytes]) -> bool:
    """
    Copies PNG chart image bytes directly to the Windows Clipboard using built-in .NET
    `System.Windows.Forms.Clipboard` so the user can simply press `Ctrl+V` inside the X compose box.
    """
    if not photo_bytes or os.name != "nt":
        return False
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tf.write(photo_bytes)
            tmp_path = tf.name
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            f"$img = [System.Drawing.Image]::FromFile('{tmp_path}'); "
            "[System.Windows.Forms.Clipboard]::SetImage($img); "
            "$img.Dispose()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# ===========================================================================
# 3. PURE-STDLIB OAUTH 1.0A SIGNER, MEDIA UPLOAD (v1.1) & TWEET POST (v2)
# ===========================================================================
def _pct_encode(val: Any) -> str:
    """RFC 5849 Section 3.6 percent-encoding (safe='')."""
    return urllib.parse.quote(str(val), safe="-._~")


def _build_oauth1_header(
    method: str,
    url: str,
    api_key: str,
    api_secret: str,
    access_token: str,
    access_token_secret: str,
    extra_params: Optional[Dict[str, str]] = None,
) -> str:
    """
    Generates an OAuth 1.0a `Authorization: OAuth ...` header signed with HMAC-SHA1.
    Note: Per RFC 5849 Section 3.4.1.3.1, `application/json` and `multipart/form-data`
    request bodies are NOT included in the signature base string.
    """
    oauth_params: Dict[str, str] = {
        "oauth_consumer_key": _clean_cred(api_key),
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": _clean_cred(access_token),
        "oauth_version": "1.0",
    }

    parsed_url = urllib.parse.urlsplit(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

    # Combine oauth_params + query string params + optional extra form params
    sig_params: List[Tuple[str, str]] = []
    for k, v in oauth_params.items():
        sig_params.append((_pct_encode(k), _pct_encode(v)))
    if parsed_url.query:
        for k, v in urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True):
            sig_params.append((_pct_encode(k), _pct_encode(v)))
    if extra_params:
        for k, v in extra_params.items():
            sig_params.append((_pct_encode(k), _pct_encode(v)))

    sig_params.sort(key=lambda pair: (pair[0], pair[1]))
    normalized_params = "&".join(f"{k}={v}" for k, v in sig_params)

    base_string = "&".join(
        [
            _pct_encode(method.upper()),
            _pct_encode(base_url),
            _pct_encode(normalized_params),
        ]
    )
    signing_key = f"{_pct_encode(_clean_cred(api_secret))}&{_pct_encode(_clean_cred(access_token_secret))}"
    digest = hmac.new(
        signing_key.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    oauth_params["oauth_signature"] = base64.b64encode(digest).decode("utf-8")

    header_parts = [f'{_pct_encode(k)}="{_pct_encode(v)}"' for k, v in sorted(oauth_params.items())]
    return "OAuth " + ", ".join(header_parts)


def upload_x_media_png(
    photo_bytes: bytes,
    cfg: Optional[Dict[str, str]] = None,
    timeout: int = 25,
) -> Tuple[Optional[str], str]:
    """
    Uploads PNG chart bytes to X via `https://upload.twitter.com/1.1/media/upload.json`
    using OAuth 1.0a multipart/form-data.
    Returns `(media_id_string, error_message_if_any)`.
    """
    c = cfg if cfg is not None else load_x_config()
    if not is_x_configured(c):
        return None, "Eksik X API anahtarları."
    if not photo_bytes:
        return None, "Görsel verisi boş."

    url = "https://upload.twitter.com/1.1/media/upload.json"
    auth_header = _build_oauth1_header(
        method="POST",
        url=url,
        api_key=c["api_key"],
        api_secret=c["api_secret"],
        access_token=c["access_token"],
        access_token_secret=c["access_token_secret"],
    )

    boundary = f"----AntigravityXMedia{uuid.uuid4().hex}"
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(b'Content-Disposition: form-data; name="media"; filename="chart.png"\r\n')
    body.write(b"Content-Type: image/png\r\n\r\n")
    body.write(photo_bytes)
    body.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    req = urllib.request.Request(
        url,
        data=body.getvalue(),
        headers={
            "Authorization": auth_header,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "SmartCryptoTerminal/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            media_id = str(res.get("media_id_string") or res.get("media_id") or "")
            if media_id:
                return media_id, ""
            return None, f"Medya ID alınamadı: {res}"
    except urllib.error.HTTPError as e:
        try:
            err_txt = e.read().decode("utf-8", errors="ignore")
        except Exception:
            err_txt = str(e)
        return None, f"X Medya Yükleme Hatası (HTTP {e.code}): {err_txt[:220]}"
    except Exception as e:
        return None, f"X Medya Bağlantı Hatası: {e}"


def post_x_tweet(
    text: str,
    photo_bytes: Optional[bytes] = None,
    reply_to_tweet_id: Optional[str] = None,
    cfg: Optional[Dict[str, str]] = None,
    timeout: int = 20,
    enforce_280: bool = True,
) -> Tuple[bool, str, Optional[str]]:
    """
    Publishes a single post to X using `POST https://api.twitter.com/2/tweets` with optional PNG chart.
    Returns `(success, status_message_tr, tweet_id)`.
    """
    c = cfg if cfg is not None else load_x_config()
    if not is_x_configured(c):
        return (
            False,
            "⚠️ Lütfen önce X (Twitter) API Anahtarlarınızı (API Key, API Secret, Access Token, Access Token Secret) kaydedin.",
            None,
        )

    final_text = fit_x_text_280(text, 278) if enforce_280 else (text or "").strip()
    if not final_text:
        return False, "❌ Gönderilecek X metni boş.", None

    media_id: Optional[str] = None
    media_warn = ""
    if photo_bytes:
        media_id, media_err = upload_x_media_png(photo_bytes, cfg=c, timeout=timeout + 5)
        if not media_id and media_err:
            media_warn = f" (Not: Grafik yüklenemedi, sadece metin paylaşıldı: {media_err})"

    url = "https://api.twitter.com/2/tweets"
    auth_header = _build_oauth1_header(
        method="POST",
        url=url,
        api_key=c["api_key"],
        api_secret=c["api_secret"],
        access_token=c["access_token"],
        access_token_secret=c["access_token_secret"],
    )

    payload_dict: Dict[str, Any] = {"text": final_text}
    if media_id:
        payload_dict["media"] = {"media_ids": [media_id]}
    if reply_to_tweet_id:
        payload_dict["reply"] = {"in_reply_to_tweet_id": str(reply_to_tweet_id)}

    payload_bytes = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload_bytes,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "User-Agent": "SmartCryptoTerminal/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            data_obj = body.get("data") or {}
            tweet_id = str(data_obj.get("id", ""))
            if tweet_id:
                tweet_url = f"https://x.com/i/web/status/{tweet_id}"
                return (
                    True,
                    f"✅ Analiz X (Twitter) hesabınızda başarıyla paylaşıldı! 🔗 {tweet_url}{media_warn}",
                    tweet_id,
                )
            return False, f"X API beklenmeyen yanıt: {body}", None
    except urllib.error.HTTPError as e:
        try:
            err_raw = e.read().decode("utf-8", errors="ignore")
            err_json = json.loads(err_raw)
            detail = err_json.get("detail") or err_json.get("title") or err_raw
        except Exception:
            detail = str(e)

        if e.code == 401:
            return (
                False,
                "❌ X API HTTP 401 (Yetkisiz): API Key, API Secret, Access Token veya Access Token Secret hatalı ya da süresi dolmuş. "
                "Lütfen X Developer Portal (developer.x.com) üzerinden anahtarlarınızı kontrol edin.",
                None,
            )
        if e.code == 402:
            clip_ok = copy_chart_png_to_windows_clipboard(photo_bytes)
            intent_u = build_x_intent_url(final_text)
            clip_msg = " 📋 Grafik görseli panonuza (Ctrl+V) otomatik kopyalandı!" if clip_ok else ""
            return (
                False,
                f"💳 X API HTTP 402 (Kredi Bakiyesi $0 - 'credits depleted'): X Developer Portal artık resmi API çağrıları için "
                f"ön ödemeli kredi (Prepaid Credits) talep ediyor.{clip_msg} "
                f"Hiçbir ücret ödemeden hemen paylaşmak için 👉 [🐦 Ücretsiz X Paylaşım Penceresini Aç (Sadece Ctrl+V Yapıp Gönderin)]({intent_u})",
                None,
            )
        if e.code == 403:
            return (
                False,
                f"❌ X API HTTP 403 (İzin Hatası): Uygulamanızın 'Read and Write' (Okuma ve Yazma) izni açık olmayabilir veya aynı içerik mükerrer gönderildi. Detay: {detail}",
                None,
            )
        if e.code == 429:
            return (
                False,
                "⏳ X API HTTP 429 (Günlük/Saatlik Limit Doldu): X Ücretsiz API kotası (24 saatte ~17 gönderi) sınırına ulaşıldı.",
                None,
            )
        return False, f"❌ X API Hatası (HTTP {e.code}): {detail}", None
    except Exception as e:
        return False, f"❌ X Bağlantı Hatası: {e}", None


def publish_x_content(
    tweets: List[str],
    photo_bytes: Optional[bytes] = None,
    title: str = "Kripto Analiz",
    symbol: str = "",
    cfg: Optional[Dict[str, str]] = None,
    mode: Optional[str] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    High-level publisher supporting:
      - `SHORT_280`: Single tweet (<=280 weighted chars) + PNG Chart
      - `THREAD`: Multi-tweet flood/chain where Tweet 1 has the PNG Chart and Tweet 2+ replies to it
      - `LONG_PREMIUM`: Single long-form tweet + PNG Chart without 280-char truncation
    Automatically records the published tweet in `x_state.json` history.
    """
    st = load_x_state()
    active_mode = (mode or st.get("x_post_mode", "SHORT_280")).upper()
    attach_chart = bool(st.get("x_attach_chart", True))
    chart_to_send = photo_bytes if attach_chart else None

    clean_tweets = [t.strip() for t in tweets if t and t.strip()]
    if not clean_tweets:
        return False, "❌ Paylaşılacak içerik oluşturulamadı.", None

    if active_mode == "LONG_PREMIUM":
        combined = "\n\n".join(clean_tweets)
        ok, msg, tid = post_x_tweet(
            text=combined,
            photo_bytes=chart_to_send,
            cfg=cfg,
            enforce_280=False,
        )
        if ok and tid:
            record_x_post_success(tid, title=title, symbol=symbol)
        return ok, msg, tid

    if active_mode == "THREAD" and len(clean_tweets) > 1:
        first_tid: Optional[str] = None
        prev_tid: Optional[str] = None
        for idx, tw_text in enumerate(clean_tweets):
            ok, msg, tid = post_x_tweet(
                text=tw_text,
                photo_bytes=chart_to_send if idx == 0 else None,
                reply_to_tweet_id=prev_tid,
                cfg=cfg,
                enforce_280=True,
            )
            if not ok:
                if first_tid:
                    url = record_x_post_success(first_tid, title=f"{title} (Kısmi Zincir)", symbol=symbol)
                    return True, f"⚠️ İlk tweet paylaşıldı ({url}), ancak {idx + 1}. zincir tweet gönderilemedi: {msg}", first_tid
                return False, msg, None
            if idx == 0:
                first_tid = tid
            prev_tid = tid
            if idx < len(clean_tweets) - 1:
                time.sleep(0.8)

        if first_tid:
            url = record_x_post_success(first_tid, title=f"{title} ({len(clean_tweets)} Tweet Zincir)", symbol=symbol)
            return True, f"✅ {len(clean_tweets)} Tweetlik Analiz Zinciri (Flood) ve Grafik X'te paylaşıldı! 🔗 {url}", first_tid
        return False, "❌ Zincir paylaşılamadı.", None

    # Default: SHORT_280 single post
    ok, msg, tid = post_x_tweet(
        text=clean_tweets[0],
        photo_bytes=chart_to_send,
        cfg=cfg,
        enforce_280=True,
    )
    if ok and tid:
        record_x_post_success(tid, title=title, symbol=symbol)
    return ok, msg, tid


# ===========================================================================
# 4. CRYPTO X (TWITTER) TWEET & THREAD FORMATTERS
# ===========================================================================
def _fmt_p(val: Optional[float], ref_price: float) -> str:
    if val is None or pd.isna(val) or val <= 0:
        return "N/A"
    p_fmt = ",.4f" if ref_price < 10.0 else ",.2f"
    return format(float(val), p_fmt)


def _coin_cashtag(symbol: str) -> Tuple[str, str]:
    """Returns `('$ONDO', 'ONDO')` from `'ONDO/USDT'`."""
    base = str(symbol or "BTC").upper().split("/")[0].split("-")[0].strip()
    return f"${base}", base


def format_coin_analysis_x_post(
    fc: MarketForecast,
    symbol: str,
    timeframe: str = "4H",
    current_price: float = 0.0,
    mtf_scores: Optional[Dict[str, float]] = None,
    mode: Optional[str] = None,
    custom_hashtags: Optional[str] = None,
) -> List[str]:
    """
    Formats a single-coin structural analysis into high-engagement Crypto X post(s).
    Returns `List[str]` (1 item for SHORT_280, 2 items for THREAD / LONG_PREMIUM).
    """
    st = load_x_state()
    active_mode = (mode or st.get("x_post_mode", "SHORT_280")).upper()
    tags_extra = (custom_hashtags if custom_hashtags is not None else st.get("x_custom_hashtags", "#Kripto")).strip()

    cashtag, base_sym = _coin_cashtag(symbol)
    tf_up = timeframe.upper()
    p_str = _fmt_p(current_price, current_price)
    sup_str = _fmt_p(fc.nearest_support, current_price)
    res_str = _fmt_p(fc.nearest_resistance, current_price)
    poc_str = _fmt_p(fc.poc_price, current_price)

    t_state = getattr(fc, "trend_state", "")
    if t_state == "UPTREND" or (not t_state and fc.score >= 15):
        tr_short = f"📈 Yükselen ({fc.score:+.0f})"
    elif t_state == "DOWNTREND" or (not t_state and fc.score <= -15):
        tr_short = f"📉 Düşen ({fc.score:+.0f})"
    else:
        tr_short = f"⚖️ Yatay ({fc.score:+.0f})"

    sup_strong = getattr(fc, "nearest_support_score", 0.0) >= 62.0
    res_strong = getattr(fc, "nearest_resistance_score", 0.0) >= 62.0
    sup_lbl = "🛡️ Güçlü Destek" if sup_strong else "🟢 Destek"
    res_lbl = "🧱 Güçlü Direnç" if res_strong else "🔴 Direnç"

    sr_act_type = getattr(fc, "sr_action_type", "NONE")
    sr_act_str = getattr(fc, "sr_action_status_tr", "")
    if sr_act_type != "NONE" and sr_act_str:
        short_act = sr_act_str.split(".")[0].strip()
        if len(short_act) > 42:
            short_act = short_act[:39].rstrip() + "..."
        status_line = f"🚨 {short_act}"
    elif fc.squeeze_energy_pct >= 68:
        status_line = f"💥 Sıkışma: %{fc.squeeze_energy_pct:.0f} (±%{fc.expected_breakout_move_pct:.1f})"
    else:
        swing_s = getattr(fc, "swing_structure_tr", "Dengeli Yapı")[:34]
        status_line = f"📐 Yapı: {swing_s}"

    wh_score = fc.whale_accumulation_score
    wh_txt = "Topluyor" if wh_score >= 60 else ("Satıyor" if wh_score <= 40 else "Nötr")

    tweet1_lines = [
        f"📊 {cashtag} [{tf_up}] Teknik Analiz",
        f"💰 Fiyat: {p_str}$ | {tr_short}",
        f"{sup_lbl}: {sup_str}$",
        f"{res_lbl}: {res_str}$",
        status_line,
        f"🐋 Balina: {wh_txt} ({wh_score:.0f}) | 🧲 POC: {poc_str}$",
        f"⚖️ YTD #{base_sym} {tags_extra}".strip(),
    ]
    tweet1 = fit_x_text_280("\n".join(tweet1_lines), 278)

    if active_mode == "SHORT_280":
        return [tweet1]

    # Build Tweet 2 for THREAD or LONG_PREMIUM
    mtf_parts = []
    if mtf_scores:
        for tf_k in ("15M", "1H", "4H", "1D"):
            if tf_k in mtf_scores:
                sc_k = mtf_scores[tf_k]
                ic_k = "📈" if sc_k >= 15 else ("📉" if sc_k <= -15 else "⚖️")
                mtf_parts.append(f"{tf_k}:{ic_k}{sc_k:+.0f}")
    mtf_line = "⏱️ " + " | ".join(mtf_parts) if mtf_parts else ""

    net_d = fc.net_delta_20_usd
    if abs(net_d) >= 1_000_000:
        d_str = f"{net_d / 1_000_000:+,.1f}M$"
    elif abs(net_d) >= 1_000:
        d_str = f"{net_d / 1_000:+,.1f}K$"
    else:
        d_str = f"{net_d:+,.0f}$"

    guidance = getattr(fc, "plain_guidance_tr", "") or f"{sup_str}$ desteği ile {res_str}$ direnci izlenmeli."
    if len(guidance) > 110:
        guidance = guidance[:107].rstrip() + "..."

    tweet2_lines = [f"🧭 {cashtag} [{tf_up}] Detaylı Yol Haritası (2/2)"]
    if mtf_line:
        tweet2_lines.append(mtf_line)
    tweet2_lines.extend(
        [
            f"💸 Nakit Akışı: {d_str} | 🚦 Hazırlık: {fc.readiness_score_5}/5",
            f"📌 {guidance}",
            "⚖️ Yatırım tavsiyesi değildir (YTD).",
        ]
    )
    tweet2 = fit_x_text_280("\n".join(tweet2_lines), 278) if active_mode == "THREAD" else "\n".join(tweet2_lines)
    return [tweet1, tweet2]


def format_futures_setup_x_post(
    fc: MarketForecast,
    symbol: str,
    timeframe: str = "4H",
    current_price: float = 0.0,
    mode: Optional[str] = None,
    custom_hashtags: Optional[str] = None,
) -> List[str]:
    """
    Formats a Perpetual Futures (Vadeli İşlem) setup into Crypto X post(s).
    """
    st = load_x_state()
    active_mode = (mode or st.get("x_post_mode", "SHORT_280")).upper()
    tags_extra = (custom_hashtags if custom_hashtags is not None else st.get("x_custom_hashtags", "#Kripto")).strip()

    cashtag, base_sym = _coin_cashtag(symbol)
    tf_up = timeframe.upper()
    fs = fc.futures_setup
    p_str = _fmt_p(current_price, current_price)
    sup_str = _fmt_p(fc.nearest_support, current_price)
    res_str = _fmt_p(fc.nearest_resistance, current_price)

    if not fs.is_tradeable:
        warn_s = fs.risk_warnings_tr[0] if fs.risk_warnings_tr else "R:R ve teknik yapı şu an riskli."
        if len(warn_s) > 65:
            warn_s = warn_s[:62].rstrip() + "..."
        t1 = fit_x_text_280(
            "\n".join(
                [
                    f"🛑 {cashtag} [{tf_up}] Vadeli Risk Kalkanı",
                    f"💰 Fiyat: {p_str}$ | Güven: {fs.confidence_score:.0f}/100 ({fs.confidence_grade})",
                    f"⚠️ {warn_s}",
                    f"🟢 Destek: {sup_str}$ | 🔴 Direnç: {res_str}$",
                    f"🧲 POC: {_fmt_p(fc.poc_price, current_price)}$ | YTD #{base_sym}",
                ]
            ),
            278,
        )
        return [t1]

    dir_ic = "🟢 LONG" if fs.direction == "LONG" else "🔴 SHORT"
    t1_lines = [
        f"⚡ {cashtag} [{tf_up}] Vadeli Planı: {dir_ic}",
        f"🎖️ Güven: {fs.confidence_score:.0f}/100 ({fs.confidence_grade}) | R:R 1:{fs.rr_ratio:.1f}",
        f"🎯 Giriş: {_fmt_p(fs.entry_price, current_price)}$",
        f"✅ TP1: {_fmt_p(fs.tp1_price, current_price)}$ | TP2: {_fmt_p(fs.tp2_price, current_price)}$",
        f"🛡️ Stop: {_fmt_p(fs.stop_price, current_price)}$ (Maks {fs.max_safe_leverage}x)",
        f"⚖️ YTD #{base_sym} {tags_extra}".strip(),
    ]
    t1 = fit_x_text_280("\n".join(t1_lines), 278)
    if active_mode == "SHORT_280":
        return [t1]

    t2_lines = [
        f"📐 {cashtag} [{tf_up}] Vadeli Teknik Detaylar (2/2)",
        f"🚀 Uzatılmış TP3: {_fmt_p(fs.tp3_price, current_price)}$",
        f"🧱 Destek: {sup_str}$ | Direnç: {res_str}$",
    ]
    for pf in fs.positive_factors_tr[:2]:
        t2_lines.append(f"• ✅ {pf[:55]}")
    t2_lines.append("⚖️ Yatırım tavsiyesi değildir (YTD).")
    t2 = fit_x_text_280("\n".join(t2_lines), 278) if active_mode == "THREAD" else "\n".join(t2_lines)
    return [t1, t2]


def format_radar_alert_x_post(
    symbol: str,
    timeframe: str,
    current_price: float,
    fc: MarketForecast,
    reasons: List[str],
    header_title: str = "",
    mode: Optional[str] = None,
) -> List[str]:
    """
    Formats a 24/7 Proactive Breakout / Trap (SFP) / Whale / Squeeze Radar alert for automatic X posting.
    """
    st = load_x_state()
    active_mode = (mode or st.get("x_post_mode", "SHORT_280")).upper()
    tags_extra = st.get("x_custom_hashtags", "#Kripto").strip()

    cashtag, base_sym = _coin_cashtag(symbol)
    tf_up = timeframe.upper()
    p_str = _fmt_p(current_price, current_price)
    sup_str = _fmt_p(fc.nearest_support, current_price)
    res_str = _fmt_p(fc.nearest_resistance, current_price)
    poc_str = _fmt_p(fc.poc_price, current_price)

    clean_hdr = re.sub(r"<[^>]+>", "", header_title or "").replace(symbol, cashtag).strip()
    if not clean_hdr:
        clean_hdr = f"📡 RADAR UYARISI: {cashtag} [{tf_up}]"

    clean_reasons = []
    for r in reasons[:2]:
        cr = re.sub(r"<[^>]+>", "", r).strip()
        if len(cr) > 58:
            cr = cr[:55].rstrip() + "..."
        clean_reasons.append(f"• {cr}")

    t1_lines = [
        clean_hdr,
        f"💰 Fiyat: {p_str}$ | 🚦 Hazırlık: {fc.readiness_score_5}/5",
        *clean_reasons,
        f"🟢 Destek: {sup_str}$ | 🔴 Direnç: {res_str}$",
        f"🧲 POC: {poc_str}$ | YTD #{base_sym} {tags_extra}".strip(),
    ]
    t1 = fit_x_text_280("\n".join(t1_lines), 278)
    if active_mode == "SHORT_280":
        return [t1]

    guidance = getattr(fc, "plain_guidance_tr", "") or f"{sup_str}$ desteği ve {res_str}$ direnci takip edilmeli."
    t2 = fit_x_text_280(
        "\n".join(
            [
                f"🧭 {cashtag} [{tf_up}] Radar Yol Haritası (2/2)",
                f"🐋 Balina Skoru: {fc.whale_accumulation_score:.0f}/100 | Trend: {fc.score:+.0f}/100",
                f"📌 {guidance[:110]}",
                "⚖️ Yatırım tavsiyesi değildir (YTD).",
            ]
        ),
        278,
    )
    return [t1, t2]


def format_screener_x_post(
    rows: List[Dict[str, Any]],
    timeframe: str = "4H",
    only_high_quality: bool = False,
    mode: Optional[str] = None,
) -> List[str]:
    """Formats the Multi-Coin Screener summary for X."""
    st = load_x_state()
    active_mode = (mode or st.get("x_post_mode", "SHORT_280")).upper()
    tf_up = timeframe.upper()
    title = f"🎯 Güçlü Kripto Fırsat Radarı [{tf_up}]" if only_high_quality else f"🚀 Kripto Tarama Özeti [{tf_up}]"

    lines = [title]
    for idx, r in enumerate(rows[:4], start=1):
        sym = str(r.get("Coin", r.get("symbol", "")))
        cashtag, _ = _coin_cashtag(sym)
        fc_obj: Optional[MarketForecast] = r.get("_fc_4h") or r.get("fc")
        if fc_obj:
            ic = "📈" if fc_obj.score >= 15 else ("📉" if fc_obj.score <= -15 else "⚖️")
            lines.append(
                f"{idx}. {cashtag}: {ic}{fc_obj.score:+.0f} | 🚦{fc_obj.readiness_score_5}/5 | 🐋{fc_obj.whale_accumulation_score:.0f}"
            )
        else:
            yon = str(r.get("Yön & Skor", r.get("1S Trend", "")))[:16]
            onay = str(r.get("Onay", ""))
            lines.append(f"{idx}. {cashtag} — {yon} ({onay})")

    lines.append("⚖️ YTD #Kripto #Bitcoin #Altcoin")
    t1 = fit_x_text_280("\n".join(lines), 278)
    if active_mode == "SHORT_280" or len(rows) <= 4:
        return [t1]

    lines2 = [f"📋 Kripto Tarama Devamı [{tf_up}] (2/2)"]
    for idx, r in enumerate(rows[4:9], start=5):
        sym = str(r.get("Coin", r.get("symbol", "")))
        cashtag, _ = _coin_cashtag(sym)
        fc_obj = r.get("_fc_4h") or r.get("fc")
        if fc_obj:
            ic = "📈" if fc_obj.score >= 15 else ("📉" if fc_obj.score <= -15 else "⚖️")
            lines2.append(
                f"{idx}. {cashtag}: {ic}{fc_obj.score:+.0f} | 🚦{fc_obj.readiness_score_5}/5 | 🐋{fc_obj.whale_accumulation_score:.0f}"
            )
    lines2.append("⚖️ Yatırım tavsiyesi değildir (YTD).")
    return [t1, fit_x_text_280("\n".join(lines2), 278)]


def format_breakout_radar_x_post(
    rows: List[Dict[str, Any]],
    timeframe: str = "4H",
    mode: Optional[str] = None,
) -> List[str]:
    """Formats Support/Resistance Breakout & SFP Trap Radar for X."""
    tf_up = timeframe.upper()
    lines = [f"🚨 Destek/Direnç Kırılım Radarı [{tf_up}]"]
    for r in rows[:4]:
        sym = str(r.get("symbol", r.get("Coin", "")))
        cashtag, _ = _coin_cashtag(sym)
        price = float(r.get("price", r.get("_raw_price", 0.0)))
        fc: Optional[MarketForecast] = r.get("fc") or r.get("_fc_4h")
        p_s = _fmt_p(price, price)
        if fc:
            act_t = getattr(fc, "sr_action_type", "NONE")
            if act_t == "BULL_SR_BREAKOUT":
                st_s = "🚀 Direnç Kırıldı"
            elif act_t == "BEAR_SR_BREAKDOWN":
                st_s = "🩸 Destek Kırıldı"
            elif "SFP" in act_t:
                st_s = "🪤 Tuzak (SFP)"
            elif "RETEST" in act_t:
                st_s = "🔄 Retest Onayı"
            else:
                res_p = _fmt_p(fc.nearest_resistance, price)
                sup_p = _fmt_p(fc.nearest_support, price)
                st_s = f"D:{sup_p} / R:{res_p}"
            lines.append(f"• {cashtag} ({p_s}$): {st_s}")
    lines.append("⚖️ YTD #Kripto #Bitcoin")
    return [fit_x_text_280("\n".join(lines), 278)]


def format_futures_radar_x_post(
    rows: List[Dict[str, Any]],
    timeframe: str = "4H",
    mode: Optional[str] = None,
) -> List[str]:
    """Formats Perpetual Futures Radar scan for X."""
    tf_up = timeframe.upper()
    tradeables = [
        r for r in rows if (r.get("fc") or r.get("_fc_4h")) and (r.get("fc") or r.get("_fc_4h")).futures_setup.is_tradeable
    ]
    lines = [f"⚡ Vadeli İşlem (Futures) Radarı [{tf_up}]"]
    if not tradeables:
        lines.append("🛑 Şu an yüksek güvenli (>=62p) vadeli kurulum yok; risk kalkanı aktif.")
        for r in rows[:3]:
            sym = str(r.get("symbol", r.get("Coin", "")))
            cashtag, _ = _coin_cashtag(sym)
            fc = r.get("fc") or r.get("_fc_4h")
            if fc and fc.futures_setup:
                lines.append(f"• {cashtag}: Güven {fc.futures_setup.confidence_score:.0f}/100 (Beklemede)")
    else:
        for r in tradeables[:3]:
            sym = str(r.get("symbol", r.get("Coin", "")))
            cashtag, _ = _coin_cashtag(sym)
            fc = r.get("fc") or r.get("_fc_4h")
            fs = fc.futures_setup
            p = float(r.get("price", r.get("_raw_price", fs.entry_price)))
            ic = "🟢L" if fs.direction == "LONG" else "🔴S"
            lines.append(
                f"• {cashtag} {ic} ({fs.confidence_grade}): Giriş {_fmt_p(fs.entry_price, p)}$ | TP1 {_fmt_p(fs.tp1_price, p)}$ | SL {_fmt_p(fs.stop_price, p)}$"
            )
    lines.append("⚖️ YTD #Kripto #Futures")
    return [fit_x_text_280("\n".join(lines), 278)]


def format_market_overview_x_post(
    coin_summaries: List[Dict[str, Any]],
    session_status_tr: str,
    timeframe: str = "4H",
    mode: Optional[str] = None,
) -> List[str]:
    """Formats Global Market & Cash Flow bulletin for X."""
    tf_up = timeframe.upper()
    bulls = [c for c in coin_summaries if c["score"] >= 15]
    bears = [c for c in coin_summaries if c["score"] <= -15]
    neutrals = [c for c in coin_summaries if -15 < c["score"] < 15]

    by_inflow = sorted(coin_summaries, key=lambda x: x["cmf"], reverse=True)
    by_whale = sorted(coin_summaries, key=lambda x: x["whale"], reverse=True)
    top_in = by_inflow[0] if by_inflow else None
    top_wh = by_whale[0] if by_whale else None

    if len(bulls) > len(bears) * 1.3:
        mood = "🟢 Alıcılı İklim"
    elif len(bears) > len(bulls) * 1.3:
        mood = "🔴 Satıcılı İklim"
    else:
        mood = "⚖️ Seçici/Dengeli"

    lines = [
        f"🌍 Kripto Piyasa & Nakit Özeti [{tf_up}]",
        f"🧭 İklim: {mood}",
        f"📊 Yükselen: {len(bulls)} | Düşen: {len(bears)} | Yatay: {len(neutrals)}",
    ]
    if top_in:
        c_in, _ = _coin_cashtag(top_in["symbol"])
        lines.append(f"💸 En Güçlü Giriş: {c_in} ({top_in['delta_str']})")
    if top_wh:
        c_wh, _ = _coin_cashtag(top_wh["symbol"])
        lines.append(f"🐋 Balina Lideri: {c_wh} ({top_wh['whale']:.0f}/100)")
    lines.append("⚖️ YTD #Bitcoin #Kripto #Altcoin")
    return [fit_x_text_280("\n".join(lines), 278)]
