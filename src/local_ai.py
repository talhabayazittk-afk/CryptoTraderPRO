"""
Hybrid Institutional Direction Co-Pilot, Healthy Money-Flow Auditor & Standalone Synthesis Engine (`src/local_ai.py`).

Dual-Core Architecture (Works at 100% Institutional Power Both WITH and WITHOUT Local AI):
  1. Core 1 — Standalone Quantitative Engine v10.0 (`SignalEngine`):
     Computes 6-layer regime-weighted direction scores, Healthy Money-Flow Persistence & Velocity,
     Kaufman Trend Efficiency, Volatility Band-Walk vs Mean-Reversion separation, and exact S/R levels.
     When Ollama is offline (e.g., PC Ollama closed or Cloud deployment), produces a complete, deep
     multi-factor institutional synthesis (`⚙️ Bağımsız Kantitatif Motor v10`) with zero degradation.
  2. Core 2 — Local AI Ensemble Co-Pilot (`Ollama / qwen2.5:3b`):
     When online, audits the 6-layer vector + flow health + cross-layer tensions, generates natural
     Turkish synthesis (`ozet`, `celiski_yorumu`), and provides a bounded conviction calibration
     (`ai_score_delta` within `[-8, +8]`) that refines direction confidence while strictly obeying
     Python's hard MTF & Cash-Flow Contradiction Locks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .data_fetcher import OrderFlowIntel
from .signals import MarketForecast

DEFAULT_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

_STATUS_LOCK = threading.Lock()
_STATUS_CACHE: Tuple[float, bool, List[str], str] = (0.0, False, [], DEFAULT_OLLAMA_MODEL)
STATUS_CACHE_TTL_SEC = 15.0

_SUMMARY_LOCK = threading.Lock()
_SUMMARY_CACHE: Dict[str, Tuple[float, "AIExecutiveReport"]] = {}
SUMMARY_CACHE_TTL_SEC = 300.0  # 5 minutes per (symbol, tf, market-state fingerprint)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")

STANCE_META_TR: Dict[str, Tuple[str, str]] = {
    "BULLISH": ("🟢 GÜÇLÜ / KOŞULLU YÜKSELİŞ YÖNÜ", "#00E676"),
    "BEARISH": ("🔴 GÜÇLÜ / KOŞULLU DÜŞÜŞ YÖNÜ", "#FF5252"),
    "CONTRADICTION_TRAP": ("⚠️ ÇELİŞKİ & TUZAK RİSKİ — TEMKİNLİ İZLE", "#F59E0B"),
    "NEUTRAL_WAIT": ("⚖️ YATAY DENGE — KIRILIM ONAYI BEKLE", "#FACC15"),
}


@dataclass
class AIExecutiveReport:
    """Structured Hybrid / Standalone Executive Direction & Contradiction Report."""
    symbol: str
    timeframe: str
    stance_code: str = "NEUTRAL_WAIT"
    stance_tr: str = "⚖️ YATAY DENGE — KIRILIM ONAYI BEKLE"
    accent_color: str = "#FACC15"
    executive_summary_tr: str = ""
    contradiction_comment_tr: str = ""
    action_plan_tr: str = ""
    flow_health_tr: str = ""
    ai_score_delta: float = 0.0
    engine_mode_tr: str = "⚙️ Bağımsız Kantitatif Motor v10 (Tam Kapasite)"
    detected_tensions: List[str] = field(default_factory=list)
    model_used: str = DEFAULT_OLLAMA_MODEL
    is_ai_generated: bool = False
    from_cache: bool = False
    latency_sec: float = 0.0
    error_note: str = ""


def _fmt_p(val: Optional[float], ref_price: float) -> str:
    if val is None or val <= 0:
        return "Belirsiz"
    p_fmt = ",.4f" if ref_price < 10.0 else ",.2f"
    return format(float(val), p_fmt)


def _fmt_usd_verbal(val: Optional[float]) -> str:
    """Formats signed USD delta verbally so small LLMs never misread '-' signs."""
    if val is None:
        return "veri yok"
    v = float(val)
    abs_v = abs(v)
    if abs_v >= 1_000_000:
        num_s = f"{abs_v / 1_000_000:,.2f}M dolar"
    elif abs_v >= 1_000:
        num_s = f"{abs_v / 1_000:,.1f}K dolar"
    else:
        num_s = f"{abs_v:,.0f} dolar"
    if v > 0:
        return f"{num_s} net alım girişi"
    if v < 0:
        return f"{num_s} net satış çıkışı"
    return "dengeli akış"


def _sanitize_tr_text(raw: str) -> str:
    """Cleans whitespace, removes any stray CJK characters or markdown fences."""
    if not raw:
        return ""
    cleaned = _CJK_RE.sub("", str(raw))
    cleaned = cleaned.replace("```", "").replace("**", "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def check_ollama_status(
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    preferred_model: str = DEFAULT_OLLAMA_MODEL,
    force_refresh: bool = False,
    timeout: float = 1.8,
) -> Tuple[bool, List[str], str]:
    """
    Checks whether local Ollama HTTP API is online and lists installed models.
    Returns `(is_online, model_names, resolved_model)`.
    """
    global _STATUS_CACHE
    now_t = time.time()
    with _STATUS_LOCK:
        ts_c, online_c, models_c, active_c = _STATUS_CACHE
        if not force_refresh and (now_t - ts_c) <= STATUS_CACHE_TTL_SEC:
            chosen = preferred_model if preferred_model in models_c else active_c
            return online_c, list(models_c), chosen

    url = f"{base_url.rstrip('/')}/api/tags"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            raw_models = payload.get("models") or []
            names = [str(m.get("name", "")).strip() for m in raw_models if m.get("name")]
            if preferred_model in names:
                resolved = preferred_model
            elif any(n.startswith("qwen2.5") or n.startswith("qwen3") for n in names):
                resolved = next(n for n in names if n.startswith("qwen2.5") or n.startswith("qwen3"))
            elif names:
                resolved = names[0]
            else:
                resolved = preferred_model
            with _STATUS_LOCK:
                _STATUS_CACHE = (now_t, bool(names), names, resolved)
            return bool(names), names, resolved
    except Exception:
        with _STATUS_LOCK:
            _STATUS_CACHE = (now_t, False, [], preferred_model)
        return False, [], preferred_model


def detect_analytical_contradictions(
    fc: MarketForecast,
    current_price: float,
    timeframe: str = "4H",
    mtf_scores: Optional[Dict[str, float]] = None,
    order_flow: Optional[OrderFlowIntel] = None,
) -> List[str]:
    """
    Deterministically extracts cross-layer analytical contradictions, unhealthy money flows,
    and trap risks in Python so both Standalone Mode and Hybrid AI Mode operate with zero blind spots.
    """
    tensions: List[str] = []
    tf_up = timeframe.upper()
    base_score = getattr(fc, "quant_score_raw", fc.score) or fc.score
    fh_score = getattr(fc, "flow_health_score", 0.0)

    # 1. Existing pipeline contradiction veto
    veto_str = getattr(fc, "contradiction_veto_tr", "")
    if veto_str:
        tensions.append(f"Sistem Çelişki Kilidi: {veto_str}")

    # 2. Multi-timeframe (HTF vs LTF) divergence
    if mtf_scores:
        sc_1d = mtf_scores.get("1D")
        sc_4h = mtf_scores.get("4H")
        sc_1h = mtf_scores.get("1H")
        sc_15m = mtf_scores.get("15M")
        htf_bear = (sc_1d is not None and sc_1d <= -15) or (sc_4h is not None and sc_4h <= -15)
        htf_bull = (sc_1d is not None and sc_1d >= 15) or (sc_4h is not None and sc_4h >= 15)
        ltf_bull = (sc_1h is not None and sc_1h >= 15) or (sc_15m is not None and sc_15m >= 18)
        ltf_bear = (sc_1h is not None and sc_1h <= -15) or (sc_15m is not None and sc_15m <= -18)

        if htf_bear and (base_score >= 12 or ltf_bull):
            tensions.append(
                "Zaman Dilimi Çelişkisi: Ana trend (4H/1D) düşüş yönlüyken alt periyotta tepki alımı var; üst trende karşı Boğa Tuzağı (Bull Trap) riski bulunuyor."
            )
        elif htf_bull and (base_score <= -12 or ltf_bear):
            tensions.append(
                "Zaman Dilimi Çelişkisi: Ana trend (4H/1D) yükseliş yönlüyken kısa vadede satış baskısı var; destek üzerinde tutunma teyit edilmeli."
            )

    # 3. Healthy Money-Flow vs Price Direction Divergence
    if base_score >= 14 and (fc.cmf_value < -0.04 or fc.net_delta_20_usd < -25_000 or fh_score <= -18.0):
        tensions.append(
            f"Fiyat-Nakit Uyumsuzluğu: Teknik skor pozitif ({base_score:+.0f}) görünse de para giriş sağlığı zayıf ({fh_score:+.0f}/100, {_fmt_usd_verbal(fc.net_delta_20_usd)}); hacimsiz yükseliş tuzağı olabilir."
        )
    elif base_score <= -14 and ((fc.cmf_value > 0.04 and fc.whale_accumulation_score >= 58) or fh_score >= 20.0):
        tensions.append(
            f"Gizli Dip Toplaması: Fiyat baskı altında olsa da para giriş sağlığı pozitif ({fh_score:+.0f}/100) ve Balina Skoru {fc.whale_accumulation_score:.0f}/100; dipte kurumsal toplama (absorpsiyon) izi var."
        )

    # 4. Spot vs Perpetual Futures Leverage Foam / Short-Squeeze Fuel
    spot_4h = getattr(fc, "spot_delta_4h_usd", None)
    perp_4h = getattr(fc, "perp_delta_4h_usd", None)
    funding = getattr(fc, "oi_weighted_funding_pct", None)
    if funding is None and order_flow is not None:
        funding = getattr(order_flow, "funding_rate_pct", None)

    if spot_4h is not None and perp_4h is not None:
        if spot_4h < 0 and perp_4h > 0 and abs(perp_4h) > abs(spot_4h) * 0.5:
            tensions.append(
                f"Spot-Vadeli Ayrışması (Kaldıraç Köpüğü): 4 saatlik Spot piyasada {_fmt_usd_verbal(spot_4h)} varken vadeli işlemlerde {_fmt_usd_verbal(perp_4h)} görülüyor; spot desteği olmayan yükseliş Long Squeeze riskine açıktır."
            )
        elif spot_4h > 0 and perp_4h < 0:
            tensions.append(
                f"Spot Birikim vs Vadeli Satış: Spot piyasada {_fmt_usd_verbal(spot_4h)} varken vadeli tarafta {_fmt_usd_verbal(perp_4h)} var; direnç kırılırsa açığa satış sıkıştırması (Short Squeeze) tetiklenebilir."
            )

    if funding is not None:
        if funding >= 0.03 and base_score > 0:
            tensions.append(
                f"Yüksek Fonlama Uyarısı: Pozitif fonlama (%{funding:+.4f}) aşırı kalabalık Long pozisyon birikimine işaret ediyor; sert iğneli düzeltme riski yüksek."
            )
        elif funding <= -0.025 and base_score < 0:
            tensions.append(
                f"Negatif Fonlama Uyarısı: Negatif fonlama (%{funding:+.4f}) kalabalık Short birikimini gösteriyor; ani yukarı tepki (Short Squeeze) gelebilir."
            )

    # 5. Proximity to Major Support / Resistance Wall (Room-to-Run check)
    if current_price > 0:
        if fc.nearest_resistance and fc.nearest_resistance > current_price:
            dist_res_pct = ((fc.nearest_resistance - current_price) / current_price) * 100.0
            if base_score >= 15 and dist_res_pct <= 0.85:
                tensions.append(
                    f"Direnç Duvarı Yakınlığı: Fiyat ({_fmt_p(current_price, current_price)}) en yakın dirence ({_fmt_p(fc.nearest_resistance, current_price)}) sadece %{dist_res_pct:.2f} uzaklıkta; direnç aşımı beklenmeden giriş yapmak risklidir."
                )
        if fc.nearest_support and fc.nearest_support < current_price:
            dist_sup_pct = ((current_price - fc.nearest_support) / current_price) * 100.0
            if base_score <= -15 and dist_sup_pct <= 0.85:
                tensions.append(
                    f"Destek Duvarı Yakınlığı: Fiyat ({_fmt_p(current_price, current_price)}) güçlü desteğe ({_fmt_p(fc.nearest_support, current_price)}) sadece %{dist_sup_pct:.2f} uzaklıkta; destek kırılmadan satış kovalamak dip tepkisine yakalanabilir."
                )

    # 6. Futures Setup Risk Gate Veto (if non-tradeable while directional score looks strong)
    fut = getattr(fc, "futures_setup", None)
    if fut is not None and not fut.is_tradeable and abs(base_score) >= 18:
        veto_reasons = getattr(fut, "veto_reasons_tr", []) or []
        top_reason = veto_reasons[0] if veto_reasons else getattr(fut, "summary_tr", "Risk/Ödül oranı yetersiz")
        tensions.append(
            f"Vadeli Radar Risk Kapısı ({tf_up}): Yön skoru {base_score:+.0f} olsa da Vadeli İşlem Motoru kurulumu onaylamadı ({top_reason})."
        )

    # 7. High Choppiness / Low Efficiency Whipsaw Regime
    eff_r = getattr(fc, "efficiency_ratio", 0.35)
    if (fc.choppiness_index >= 61.8 or eff_r < 0.16) and abs(base_score) >= 15:
        tensions.append(
            f"Testere Piyasası Uyarısı: Trend verimliliği düşük (%{eff_r*100:.0f}) ve Choppiness ({fc.choppiness_index:.1f}) yüksek; yatay sıkışmada sahte kırılım olasılığı artıyor."
        )

    return tensions


def _determine_stance_and_plan(
    symbol: str,
    timeframe: str,
    current_price: float,
    fc: MarketForecast,
    tensions: List[str],
) -> Tuple[str, str, str, str]:
    """
    Determines 100% mathematically consistent `(stance_code, stance_tr, accent_color, action_plan_tr)`
    using verified support/resistance/POC levels.
    """
    sup_s = _fmt_p(fc.nearest_support, current_price)
    res_s = _fmt_p(fc.nearest_resistance, current_price)
    poc_s = _fmt_p(fc.poc_price, current_price)
    fut = getattr(fc, "futures_setup", None)

    has_hard_veto = bool(getattr(fc, "contradiction_veto_tr", "")) or (
        fut is not None and not fut.is_tradeable and abs(fc.score) >= 18
    )
    if has_hard_veto or len(tensions) >= 2:
        stance_code = "CONTRADICTION_TRAP"
    elif fc.score >= 18 and fc.readiness_score_5 >= 3 and len(tensions) == 0:
        stance_code = "BULLISH"
    elif fc.score <= -18 and fc.readiness_score_5 >= 3 and len(tensions) == 0:
        stance_code = "BEARISH"
    elif fc.score >= 22 and len(tensions) <= 1:
        stance_code = "BULLISH"
    elif fc.score <= -22 and len(tensions) <= 1:
        stance_code = "BEARISH"
    else:
        stance_code = "CONTRADICTION_TRAP" if tensions else "NEUTRAL_WAIT"

    stance_tr, accent = STANCE_META_TR[stance_code]

    if stance_code == "BULLISH":
        tp_s = _fmt_p(fc.tp1_price if fc.tp1_price > current_price else fc.bullish_target_price, current_price)
        action_plan = (
            f"Fiyat {sup_s} USDT desteği üzerinde tutundukça pozitif yön korunur; "
            f"{res_s} USDT direnci hacimli aşılırsa {tp_s} USDT hedefi, {sup_s} altı kapanışta ise senaryo iptali izlenmelidir (YTD)."
        )
    elif stance_code == "BEARISH":
        tp_s = _fmt_p(fc.tp1_price if (0 < fc.tp1_price < current_price) else fc.bearish_target_price, current_price)
        action_plan = (
            f"Fiyat {res_s} USDT direnci (ve {poc_s} POC) altında kaldıkça satış baskısı sürebilir; "
            f"{sup_s} USDT desteği kırılırsa {tp_s} USDT bölgesi, {res_s} üstü kapanışta ise düşüş iptali takip edilmelidir (YTD)."
        )
    elif stance_code == "CONTRADICTION_TRAP":
        action_plan = (
            f"Katmanlar arası çelişki nedeniyle ara bölgede acele işlem yerine {res_s} USDT direnci üstünde net mum kapanışı "
            f"veya {sup_s} USDT desteğinde sağlıklı nakit girişi beklenmelidir; hacim mıknatısı (POC) {poc_s} USDT seviyesindedir (YTD)."
        )
    else:
        action_plan = (
            f"Yatay denge bandında yön onayı için yukarıda {res_s} USDT direncinin aşılması, aşağıda ise {sup_s} USDT "
            f"desteğinin kırılması izlenmelidir (POC: {poc_s} USDT) (YTD)."
        )

    return stance_code, stance_tr, accent, action_plan


def _build_standalone_quant_synthesis(
    symbol: str,
    timeframe: str,
    current_price: float,
    fc: MarketForecast,
    tensions: List[str],
    mtf_scores: Optional[Dict[str, float]],
    model_name: str,
    error_note: str = "",
) -> AIExecutiveReport:
    """
    Full-Power Standalone Quantitative Direction & Money-Flow Synthesis Engine (v10.0).
    Produces deep, institutional-grade Turkish analysis directly from the 6 quantitative layers
    whenever local AI is offline, disabled, or running in a cloud environment.
    """
    tf_up = timeframe.upper()
    stance_code, stance_tr, accent, action_txt = _determine_stance_and_plan(
        symbol=symbol,
        timeframe=tf_up,
        current_price=current_price,
        fc=fc,
        tensions=tensions,
    )
    poc_s = _fmt_p(fc.poc_price, current_price)
    fh_score = getattr(fc, "flow_health_score", fc.money_flow_score)
    fh_tr = getattr(fc, "flow_health_tr", fc.money_flow_status_tr)
    eff_pct = getattr(fc, "efficiency_ratio", 0.35) * 100.0

    # Multi-timeframe alignment check
    mtf_desc = ""
    if mtf_scores and len(mtf_scores) >= 2:
        bull_tfs = [k for k in ("15M", "1H", "4H", "1D") if k in mtf_scores and mtf_scores[k] >= 15]
        bear_tfs = [k for k in ("15M", "1H", "4H", "1D") if k in mtf_scores and mtf_scores[k] <= -15]
        if len(bull_tfs) >= 3:
            mtf_desc = f"Çoklu zaman dilimlerinde ({', '.join(bull_tfs)}) güçlü yükseliş uyumu hakim. "
        elif len(bear_tfs) >= 3:
            mtf_desc = f"Çoklu zaman dilimlerinde ({', '.join(bear_tfs)}) baskın düşüş uyumu izleniyor. "
        else:
            mtf_desc = "Zaman dilimleri arasında geçiş/kararsızlık dengesi görülüyor. "

    exec_sum = (
        f"{symbol} ({tf_up}) bağımsız kantitatif motorda {fc.score:+.0f}/100 bileşik yön puanı "
        f"(Trend: {fc.trend_score:+.0f}, Para Sağlığı: {fh_score:+.0f}, Momentum: {fc.momentum_score:+.0f}, Trend Verimi: %{eff_pct:.0f}) "
        f"ve %{fc.confidence_pct:.0f} katman uyumuyla {fc.verdict_tr.lower()} üretiyor. "
        f"{mtf_desc}Hacim mıknatısı (POC) {poc_s} USDT seviyesinde konumlanıyor."
    )

    if tensions:
        contra_txt = " ".join(tensions[:2])
    else:
        contra_txt = (
            f"Katmanlar tam uyumlu: {fh_tr} ile teknik indikatörler (EMA/Kalman, VWMACD ve Hacim Profili) aynı yönü doğruluyor; "
            "kaldıraç köpüğü veya sahte kırılım uyarısı bulunmuyor."
        )

    return AIExecutiveReport(
        symbol=symbol,
        timeframe=tf_up,
        stance_code=stance_code,
        stance_tr=stance_tr,
        accent_color=accent,
        executive_summary_tr=exec_sum,
        contradiction_comment_tr=contra_txt,
        action_plan_tr=action_txt,
        flow_health_tr=fh_tr,
        ai_score_delta=0.0,
        engine_mode_tr="⚙️ Bağımsız Kantitatif Motor v10 (Tam Kapasite)",
        detected_tensions=list(tensions),
        model_used=model_name,
        is_ai_generated=False,
        from_cache=False,
        latency_sec=0.0,
        error_note=error_note,
    )


def apply_hybrid_direction_fusion(fc: MarketForecast, rep: AIExecutiveReport) -> None:
    """
    Safely fuses bounded AI conviction calibration (`rep.ai_score_delta`) with Python's
    raw quantitative score (`fc.quant_score_raw`), while preserving hard MTF/Flow Contradiction Locks.
    """
    fc.ai_report = rep
    base_raw = float(getattr(fc, "quant_score_raw", fc.score))
    if not rep.is_ai_generated:
        fc.ai_score_adjustment = 0.0
        fc.engine_mode_tr = "⚙️ Bağımsız Kantitatif Motor v10 (Tam Kapasite)"
        return

    delta = float(np.clip(rep.ai_score_delta, -8.0, 8.0))
    new_score = float(np.clip(base_raw + delta, -100.0, 100.0))

    # Never violate hard pipeline Contradiction Veto Lock
    if getattr(fc, "contradiction_veto_tr", ""):
        if base_raw <= 12.0 and new_score > 12.0:
            new_score = 12.0
        elif base_raw >= -12.0 and new_score < -12.0:
            new_score = -12.0

    fc.ai_score_adjustment = round(new_score - base_raw, 1)
    fc.score = new_score
    if rep.stance_code == "CONTRADICTION_TRAP" and fc.confidence_pct > 58.0:
        fc.confidence_pct = max(45.0, fc.confidence_pct - 5.0)
    elif abs(fc.ai_score_adjustment) >= 3.0 and np.sign(fc.ai_score_adjustment) == np.sign(base_raw):
        fc.confidence_pct = min(96.0, fc.confidence_pct + 3.0)
    fc.engine_mode_tr = f"🧠 Hibrit Yön Motoru (Kantitatif v10 + {rep.model_used})"


def _compute_cache_key(
    symbol: str,
    timeframe: str,
    current_price: float,
    fc: MarketForecast,
    mtf_scores: Optional[Dict[str, float]],
    model_name: str,
) -> str:
    base_sc = getattr(fc, "quant_score_raw", fc.score)
    fh_sc = getattr(fc, "flow_health_score", 0.0)
    mtf_part = json.dumps(
        {k: round(float(v), 0) for k, v in sorted((mtf_scores or {}).items())},
        sort_keys=True,
    )
    raw_sig = (
        f"{symbol.upper()}|{timeframe.upper()}|{model_name}|"
        f"sc:{round(base_sc, 0)}|fh:{round(fh_sc, 0)}|rd:{fc.readiness_score_5}|"
        f"sup:{_fmt_p(fc.nearest_support, current_price)}|res:{_fmt_p(fc.nearest_resistance, current_price)}|"
        f"cmf:{round(fc.cmf_value, 2)}|mtf:{mtf_part}"
    )
    return hashlib.sha1(raw_sig.encode("utf-8")).hexdigest()


def generate_ai_executive_summary(
    symbol: str,
    timeframe: str,
    current_price: float,
    fc: MarketForecast,
    mtf_scores: Optional[Dict[str, float]] = None,
    order_flow: Optional[OrderFlowIntel] = None,
    model: str = DEFAULT_OLLAMA_MODEL,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    force_refresh: bool = False,
    timeout: float = 40.0,
    apply_fusion: bool = True,
) -> AIExecutiveReport:
    """
    Generates a Hybrid AI + Quantitative Direction & Healthy Money-Flow Report via Ollama,
    or falls back seamlessly to the full-power v10.0 Standalone Quantitative Synthesis Engine.
    """
    sym_up = symbol.strip().upper()
    tf_up = timeframe.strip().upper()
    tensions = detect_analytical_contradictions(
        fc=fc,
        current_price=current_price,
        timeframe=tf_up,
        mtf_scores=mtf_scores,
        order_flow=order_flow,
    )

    online, _, resolved_model = check_ollama_status(
        base_url=base_url,
        preferred_model=model,
        force_refresh=False,
    )
    if not online:
        rep_fb = _build_standalone_quant_synthesis(
            symbol=sym_up,
            timeframe=tf_up,
            current_price=current_price,
            fc=fc,
            tensions=tensions,
            mtf_scores=mtf_scores,
            model_name=resolved_model,
            error_note="Lokal AI kapalı — Bağımsız Kantitatif Motor v10 tam kapasite devrede.",
        )
        if apply_fusion:
            apply_hybrid_direction_fusion(fc, rep_fb)
        return rep_fb

    cache_key = _compute_cache_key(sym_up, tf_up, current_price, fc, mtf_scores, resolved_model)
    now_t = time.time()
    if not force_refresh:
        with _SUMMARY_LOCK:
            cached = _SUMMARY_CACHE.get(cache_key)
            if cached and (now_t - cached[0]) <= SUMMARY_CACHE_TTL_SEC:
                rep_c = cached[1]
                rep_copy = AIExecutiveReport(
                    symbol=rep_c.symbol,
                    timeframe=rep_c.timeframe,
                    stance_code=rep_c.stance_code,
                    stance_tr=rep_c.stance_tr,
                    accent_color=rep_c.accent_color,
                    executive_summary_tr=rep_c.executive_summary_tr,
                    contradiction_comment_tr=rep_c.contradiction_comment_tr,
                    action_plan_tr=rep_c.action_plan_tr,
                    flow_health_tr=rep_c.flow_health_tr,
                    ai_score_delta=rep_c.ai_score_delta,
                    engine_mode_tr=rep_c.engine_mode_tr,
                    detected_tensions=list(rep_c.detected_tensions),
                    model_used=rep_c.model_used,
                    is_ai_generated=rep_c.is_ai_generated,
                    from_cache=True,
                    latency_sec=rep_c.latency_sec,
                    error_note=rep_c.error_note,
                )
                if apply_fusion:
                    apply_hybrid_direction_fusion(fc, rep_copy)
                return rep_copy

    base_score = float(getattr(fc, "quant_score_raw", fc.score))
    fh_score = float(getattr(fc, "flow_health_score", fc.money_flow_score))
    fh_tr = getattr(fc, "flow_health_tr", fc.money_flow_status_tr)
    eff_pct = getattr(fc, "efficiency_ratio", 0.35) * 100.0

    if mtf_scores:
        mtf_parts = []
        for k in ("15M", "1H", "4H", "1D"):
            if k in mtf_scores:
                v = mtf_scores[k]
                lbl = "yükseliş" if v >= 15 else ("düşüş" if v <= -15 else "yatay")
                mtf_parts.append(f"{k}:{lbl}({v:+.0f})")
        mtf_verbal = ", ".join(mtf_parts)
    else:
        mtf_verbal = f"{tf_up}:{base_score:+.0f}"

    flow_verbal = _fmt_usd_verbal(fc.net_delta_20_usd)
    tension_verbal = " | ".join(tensions[:2]) if tensions else "Katmanlar uyumlu, önemli bir çelişki veya tuzak sinyali yok."

    system_prompt = (
        "Sen kıdemli bir Türk kripto kantitatif analistisin. Yalnızca verilen gerçek bilgileri kullan, "
        "fiyat uydurma. Kurallı, eksiksiz ve akıcı Türkçe cümleler kur; yarım cümle bırakma. "
        "SADECE şu 3 alanlı JSON'u üret:\n"
        '{"yon_kalitesi":"GUCLU_UYUM|NORMAL_UYUM|ZAYIF_CELISKILI|TUZAK_RISKI",'
        '"ozet":"Trend yönü, indikatör gücü ve para giriş sağlığını sentezleyen 2 tam cümle.",'
        '"celiski_yorumu":"Varsa çelişki ve tuzak riskini, yoksa para akışı ile indikatörlerin uyumunu anlatan 1-2 tam cümle."}'
    )
    user_prompt = (
        f"Parite: {sym_up} ({tf_up}), Fiyat: {_fmt_p(current_price, current_price)} USDT. "
        f"Kantitatif Yön: {fc.verdict_tr} (Skor {base_score:+.0f}/100, Trend:{fc.trend_score:+.0f}, Momentum:{fc.momentum_score:+.0f}, Verim:%{eff_pct:.0f}). "
        f"Zaman Dilimleri: {mtf_verbal}. "
        f"Para Giriş Sağlığı: {fh_score:+.0f}/100 ({flow_verbal}, Balina:{fc.whale_accumulation_score:.0f}/100). "
        f"Çelişki Denetimi: {tension_verbal}"
    )

    req_body = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "format": "json",
        "stream": False,
        "keep_alive": "20m",
        "options": {
            "temperature": 0.15,
            "top_p": 0.85,
            "num_predict": 230,
        },
    }

    t0 = time.perf_counter()
    url = f"{base_url.rstrip('/')}/api/chat"
    req = urllib.request.Request(
        url,
        data=json.dumps(req_body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_resp = json.loads(resp.read().decode("utf-8"))
        elapsed = round(time.perf_counter() - t0, 2)
        content_str = str((raw_resp.get("message") or {}).get("content", "")).strip()
        parsed = json.loads(content_str)

        exec_tr = _sanitize_tr_text(parsed.get("ozet") or parsed.get("executive_summary_tr") or "")
        contra_tr = _sanitize_tr_text(parsed.get("celiski_yorumu") or parsed.get("contradiction_comment_tr") or "")
        qual_tag = str(parsed.get("yon_kalitesi") or "NORMAL_UYUM").upper().strip()

        if len(exec_tr) < 15 or len(contra_tr) < 15:
            raise ValueError("AI yanıtı çok kısa veya eksik")

        # Compute bounded Hybrid AI Conviction Adjustment (-8..+6 pts)
        ai_delta = 0.0
        dir_sign = 1.0 if base_score >= 12.0 else (-1.0 if base_score <= -12.0 else 0.0)
        if dir_sign != 0.0:
            if "GUCLU" in qual_tag and not tensions and np.sign(fh_score) == dir_sign:
                ai_delta = 5.5 * dir_sign
            elif "NORMAL" in qual_tag and not tensions:
                ai_delta = 2.5 * dir_sign
            elif "TUZAK" in qual_tag or len(tensions) >= 2:
                ai_delta = -7.0 * dir_sign
            elif "ZAYIF" in qual_tag or len(tensions) == 1:
                ai_delta = -3.5 * dir_sign

        stance_code, stance_tr, accent, action_plan_tr = _determine_stance_and_plan(
            symbol=sym_up,
            timeframe=tf_up,
            current_price=current_price,
            fc=fc,
            tensions=tensions,
        )
        if "TUZAK" in qual_tag and len(tensions) >= 1:
            stance_code = "CONTRADICTION_TRAP"
            stance_tr, accent = STANCE_META_TR[stance_code]

        report = AIExecutiveReport(
            symbol=sym_up,
            timeframe=tf_up,
            stance_code=stance_code,
            stance_tr=stance_tr,
            accent_color=accent,
            executive_summary_tr=exec_tr,
            contradiction_comment_tr=contra_tr,
            action_plan_tr=action_plan_tr,
            flow_health_tr=fh_tr,
            ai_score_delta=round(ai_delta, 1),
            engine_mode_tr=f"🧠 Hibrit Yön Motoru (Kantitatif v10 + {resolved_model})",
            detected_tensions=list(tensions),
            model_used=resolved_model,
            is_ai_generated=True,
            from_cache=False,
            latency_sec=elapsed,
        )
        with _SUMMARY_LOCK:
            _SUMMARY_CACHE[cache_key] = (time.time(), report)
        if apply_fusion:
            apply_hybrid_direction_fusion(fc, report)
        return report

    except Exception as exc:
        rep_fb = _build_standalone_quant_synthesis(
            symbol=sym_up,
            timeframe=tf_up,
            current_price=current_price,
            fc=fc,
            tensions=tensions,
            mtf_scores=mtf_scores,
            model_name=resolved_model,
            error_note=f"AI yanıtı alınamadı ({type(exc).__name__}); Bağımsız Kantitatif Motor v10 devrede.",
        )
        if apply_fusion:
            apply_hybrid_direction_fusion(fc, rep_fb)
        return rep_fb


def format_ai_summary_telegram_html(rep: AIExecutiveReport, current_price: float = 0.0) -> str:
    """Formats `AIExecutiveReport` into a clean, mobile-friendly Telegram HTML message."""
    src_badge = (
        f"🧠 Hibrit AI (<code>{html.escape(rep.model_used)}</code>"
        + (" · ⚡Önbellek" if rep.from_cache else f" · {rep.latency_sec:.1f}sn")
        + (f" · Katkı: {rep.ai_score_delta:+.1f}p)" if abs(rep.ai_score_delta) >= 0.5 else ")")
        if rep.is_ai_generated
        else "⚙️ Bağımsız Kantitatif Motor v10 (Tam Kapasite)"
    )
    p_line = (
        f"💰 <b>Güncel Fiyat:</b> <code>{_fmt_p(current_price, current_price)} USDT</code> | "
        if current_price > 0
        else ""
    )
    lines = [
        f"🧠 <b>{html.escape(rep.symbol)} ({html.escape(rep.timeframe)}) HİBRİT YÖN, PARA SAĞLIĞI &amp; ÇELİŞKİ RAPORU</b>",
        f"{p_line}{src_badge}",
        f"🚦 <b>Karar Duruşu:</b> <b>{html.escape(rep.stance_tr)}</b>",
    ]
    if rep.flow_health_tr:
        lines.append(f"💧 <b>Para Giriş Sağlığı:</b> {html.escape(rep.flow_health_tr)}")
    lines.extend(
        [
            "━━━━━━━━━━━━",
            f"📌 <b>Yönetici &amp; Yön Özeti:</b>\n{html.escape(rep.executive_summary_tr)}",
            "",
            f"⚖️ <b>Çelişki &amp; Tuzak Denetimi:</b>\n{html.escape(rep.contradiction_comment_tr)}",
            "",
            f"🎯 <b>Koşullu İzleme Planı:</b>\n{html.escape(rep.action_plan_tr)}",
        ]
    )
    if rep.detected_tensions:
        lines.append("━━━━━━━━━━━━")
        lines.append("🔎 <b>Tespit Edilen Matematiksel Uyarılar:</b>")
        for t_item in rep.detected_tensions[:3]:
            short_t = t_item.split(":")[0].strip() if ":" in t_item else t_item[:65]
            rest_t = t_item.split(":", 1)[1].strip() if ":" in t_item else ""
            if len(rest_t) > 115:
                rest_t = rest_t[:112].rstrip() + "..."
            lines.append(
                f"• <b>{html.escape(short_t)}:</b> {html.escape(rest_t)}"
                if rest_t
                else f"• {html.escape(short_t)}"
            )
    return "\n".join(lines)


def build_ai_summary_inline_keyboard(symbol: str, active_tf: str = "4H") -> Dict[str, Any]:
    """Builds interactive inline buttons under the Telegram AI Executive Summary view."""
    sym_up = symbol.upper()
    tf_up = active_tf.upper()
    tf_row = [
        {
            "text": f"✅ {tf_opt}" if tf_opt == tf_up else f"🧠 {tf_opt}",
            "callback_data": f"ai_sum:{sym_up}:{tf_opt}",
        }
        for tf_opt in ("15M", "1H", "4H", "1D")
    ]
    return {
        "inline_keyboard": [
            tf_row,
            [
                {"text": "🔄 AI Yorumunu Yenile", "callback_data": f"ai_ref:{sym_up}:{tf_up}"},
                {"text": "📊 Grafikli Analize Dön", "callback_data": f"an:{sym_up}:{tf_up}"},
            ],
            [
                {"text": "⚡ Vadeli İşlem Planı", "callback_data": f"fut:{sym_up}:{tf_up}"},
                {"text": "🧮 Kasa Planı", "callback_data": f"kasa:{sym_up}:{tf_up}"},
                {"text": "🪙 Coin Seç", "callback_data": f"coins:{tf_up}"},
            ],
        ]
    }


@dataclass
class UnifiedCoinAnalysis:
    """
    Single-output, strictly chart- and exchange-data-grounded synthesized coin analysis.
    Blends Trend, Dynamic Trendlines, Support/Resistance, Real Cash Flow, Real Exchange Liquidation Map,
    First-Sweep Liquidation Probability, and Technical Verdict with zero fluff or hallucination.
    """
    symbol: str
    timeframe: str
    current_price: float
    trend_direction: str               # "UP", "DOWN", "SIDEWAYS"
    trend_headline_tr: str             # e.g. "ONDO/4H şu an düşen trend yönünde seyrediyor."
    accent_color: str                  # "#00E676", "#FF5252", "#FACC15"
    trend_breakout_label_tr: str       # "Düşen trend kırılım seviyesi" / "Yükselen trend kırılım seviyesi" / ...
    trend_breakout_value_tr: str
    support_tr: str
    strong_support_tr: str
    resistance_tr: str
    strong_resistance_tr: str
    money_flow_tr: str
    liquidation_levels_tr: str
    expected_first_liq_tr: str
    expected_first_liq_side: str       # "LONG_LIQ", "SHORT_LIQ", "NONE"
    expected_first_liq_prob_pct: int
    technical_verdict_tr: str
    explanation_tr: str
    liquidation_source_tr: str
    plain_text_tr: str


def _fmt_usd_compact(val: Optional[float], signed: bool = True) -> str:
    if val is None:
        return "Veri yok"
    v = float(val)
    if np.isnan(v):
        return "Veri yok"
    sign = "+" if (signed and v > 0) else ("-" if v < 0 else "")
    av = abs(v)
    if av >= 1_000_000_000:
        return f"{sign}${av / 1_000_000_000:,.2f}B"
    if av >= 1_000_000:
        return f"{sign}${av / 1_000_000:,.2f}M"
    if av >= 1_000:
        return f"{sign}${av / 1_000:,.1f}K"
    return f"{sign}${av:,.0f}"


def _fmt_px(val: Optional[float], ref_price: float) -> str:
    if val is None or val <= 0:
        return "Belirlenemedi"
    if ref_price < 0.1:
        return f"${float(val):,.5f}"
    if ref_price < 10.0:
        return f"${float(val):,.4f}"
    return f"${float(val):,.2f}"


def _pct_dist(level: float, ref_price: float) -> float:
    return ((level - ref_price) / max(ref_price, 1e-9)) * 100.0


def build_unified_coin_analysis(
    symbol: str,
    timeframe: str,
    df: Any,
    fc: MarketForecast,
    mtf_scores: Optional[Dict[str, float]] = None,
    order_flow: Optional[OrderFlowIntel] = None,
    current_price: float = 0.0,
) -> UnifiedCoinAnalysis:
    """
    Produces a single, harmonized, strictly factual Turkish technical + cash-flow + liquidation analysis
    from real OHLCV indicators, S/R levels, order flow, and live exchange liquidation map data.
    """
    tf_up = timeframe.upper()
    tf_disp = tf_up.lower()
    base_coin = symbol.split("/")[0].upper()
    mtf_scores = mtf_scores or {}
    last_row = df.iloc[-1] if (df is not None and len(df) > 0) else {}
    curr_p = float(last_row.get("close", 0.0)) if hasattr(last_row, "get") else 0.0
    if curr_p <= 0 and current_price > 0:
        curr_p = float(current_price)
    if curr_p <= 0 and fc.nearest_support and fc.nearest_resistance:
        curr_p = 0.5 * (fc.nearest_support + fc.nearest_resistance)

    ema20 = float(last_row.get("ema_20", getattr(fc, "ema20_price", curr_p) or curr_p)) if hasattr(last_row, "get") else (getattr(fc, "ema20_price", curr_p) or curr_p)
    ema50 = float(last_row.get("ema_50", curr_p)) if hasattr(last_row, "get") else curr_p
    ema200 = float(last_row.get("ema_200", 0.0)) if hasattr(last_row, "get") else 0.0
    rsi14 = float(last_row.get("rsi", 50.0)) if hasattr(last_row, "get") else 50.0
    adx14 = float(last_row.get("adx", 20.0)) if hasattr(last_row, "get") else 20.0
    macd_hist = float(last_row.get("macd_hist", 0.0)) if hasattr(last_row, "get") else 0.0
    cmf_v = float(last_row.get("cmf", getattr(fc, "cmf_value", 0.0))) if hasattr(last_row, "get") else float(getattr(fc, "cmf_value", 0.0))

    # 1. Trend Direction (strictly anchored to score, trend_score, EMA alignment)
    if fc.score >= 15.0 or (fc.trend_score >= 18.0 and curr_p > ema50 and fc.score >= 5.0):
        trend_dir = "UP"
        accent_color = "#00E676"
        trend_headline = f"{base_coin}/{tf_disp} şu an yükselen trend yönünde seyrediyor."
    elif fc.score <= -15.0 or (fc.trend_score <= -18.0 and curr_p < ema50 and fc.score <= -5.0):
        trend_dir = "DOWN"
        accent_color = "#FF5252"
        trend_headline = f"{base_coin}/{tf_disp} şu an düşen trend yönünde seyrediyor."
    else:
        trend_dir = "SIDEWAYS"
        accent_color = "#FACC15"
        trend_headline = f"{base_coin}/{tf_disp} şu an yatay / sıkışma bandında seyrediyor."

    # 2. Support / Strong Support / Resistance / Strong Resistance
    sups = [s for s in (fc.support_levels or []) if s.price < curr_p * 0.999]
    ress = [r for r in (fc.resistance_levels or []) if r.price > curr_p * 1.001]

    sup_primary = sups[0] if sups else None
    sup_strong = None
    if sups:
        deeper_sups = sups[1:]
        if deeper_sups:
            sup_strong = max(
                deeper_sups,
                key=lambda s: (
                    1 if getattr(s, "htf_confirmed", False) else 0,
                    getattr(s, "strength_score", 0.0),
                ),
            )
        else:
            sup_strong = sup_primary

    res_primary = ress[0] if ress else None
    res_strong = None
    if ress:
        deeper_ress = ress[1:]
        if deeper_ress:
            res_strong = max(
                deeper_ress,
                key=lambda r: (
                    1 if getattr(r, "htf_confirmed", False) else 0,
                    getattr(r, "strength_score", 0.0),
                ),
            )
        else:
            res_strong = res_primary

    def _fmt_sr(lvl: Any, fallback_p: Optional[float] = None) -> str:
        if lvl is not None and lvl.price > 0:
            d = _pct_dist(lvl.price, curr_p)
            htf_tag = " · Üst Periyot" if getattr(lvl, "htf_confirmed", False) else ""
            sc = getattr(lvl, "strength_score", 0.0)
            sc_tag = f" · Güç {sc:.0f}/100" if sc > 0 else ""
            return f"{_fmt_px(lvl.price, curr_p)} ({d:+.2f}%{sc_tag}{htf_tag})"
        if fallback_p and fallback_p > 0:
            d = _pct_dist(fallback_p, curr_p)
            return f"{_fmt_px(fallback_p, curr_p)} ({d:+.2f}%)"
        return "Yakın seviye tespit edilmedi"

    support_tr = _fmt_sr(sup_primary, fc.nearest_support)
    strong_support_tr = _fmt_sr(sup_strong, sup_primary.price if sup_primary else fc.nearest_support)
    resistance_tr = _fmt_sr(res_primary, fc.nearest_resistance)
    strong_resistance_tr = _fmt_sr(res_strong, res_primary.price if res_primary else fc.nearest_resistance)

    # 3. Trend Breakout Level (Dynamic Trendline -> EMA50 -> Structural S/R)
    tl = getattr(fc, "trendlines", None)
    breakout_price_num: Optional[float] = None
    if trend_dir == "DOWN":
        trend_breakout_label = "Düşen trend kırılım seviyesi"
        if tl is not None and tl.has_resistance_line and tl.res_current_price > curr_p * 1.001:
            breakout_price_num = float(tl.res_current_price)
            bp_basis = "Düşen Trend Çizgisi"
        elif ema50 > curr_p * 1.002 and ema50 < curr_p * 1.18:
            breakout_price_num = ema50
            bp_basis = "EMA50 Kırılımı"
        elif res_primary is not None:
            breakout_price_num = float(res_primary.price)
            bp_basis = "İlk Yapısal Direnç"
        else:
            bp_basis = ""
        if breakout_price_num:
            trend_breakout_val = f"{_fmt_px(breakout_price_num, curr_p)} ({_pct_dist(breakout_price_num, curr_p):+.2f}% · {bp_basis} üzeri kapanış)"
        else:
            trend_breakout_val = "Net kırılım çizgisi yok"
    elif trend_dir == "UP":
        trend_breakout_label = "Yükselen trend kırılım seviyesi"
        if tl is not None and tl.has_support_line and 0 < tl.sup_current_price < curr_p * 0.999:
            breakout_price_num = float(tl.sup_current_price)
            bp_basis = "Yükselen Trend Çizgisi"
        elif 0 < ema50 < curr_p * 0.998 and ema50 > curr_p * 0.82:
            breakout_price_num = ema50
            bp_basis = "EMA50 Kırılımı"
        elif sup_primary is not None:
            breakout_price_num = float(sup_primary.price)
            bp_basis = "İlk Yapısal Destek"
        else:
            bp_basis = ""
        if breakout_price_num:
            trend_breakout_val = f"{_fmt_px(breakout_price_num, curr_p)} ({_pct_dist(breakout_price_num, curr_p):+.2f}% · {bp_basis} altı kapanış)"
        else:
            trend_breakout_val = "Net kırılım çizgisi yok"
    else:
        trend_breakout_label = "Yatay bant kırılım seviyeleri"
        up_p = (
            float(tl.res_current_price)
            if (tl is not None and tl.has_resistance_line and tl.res_current_price > curr_p * 1.001)
            else (float(res_primary.price) if res_primary else curr_p * 1.015)
        )
        dn_p = (
            float(tl.sup_current_price)
            if (tl is not None and tl.has_support_line and 0 < tl.sup_current_price < curr_p * 0.999)
            else (float(sup_primary.price) if sup_primary else curr_p * 0.985)
        )
        trend_breakout_val = (
            f"Yukarı {_fmt_px(up_p, curr_p)} ({_pct_dist(up_p, curr_p):+.2f}%) | "
            f"Aşağı {_fmt_px(dn_p, curr_p)} ({_pct_dist(dn_p, curr_p):+.2f}%)"
        )

    # 4. Real Money Inflow / Outflow & Order-Book Wall Levels
    sp_1h = getattr(fc, "spot_delta_1h_usd", None)
    sp_4h = getattr(fc, "spot_delta_4h_usd", None)
    sp_24h = getattr(fc, "spot_delta_24h_usd", None)
    pp_24h = getattr(fc, "perp_delta_24h_usd", None)
    if order_flow is not None:
        if sp_1h is None:
            sp_1h = order_flow.spot_delta_1h_usd
        if sp_4h is None:
            sp_4h = order_flow.spot_delta_4h_usd
        if sp_24h is None:
            sp_24h = order_flow.spot_delta_24h_usd
        if pp_24h is None:
            pp_24h = order_flow.perp_cvd_delta_24h_usd

    flow_bits: List[str] = []
    if sp_24h is not None:
        flow_bits.append(
            f"Spot Net Akış (1S / 4S / 24S): {_fmt_usd_compact(sp_1h)} / {_fmt_usd_compact(sp_4h)} / {_fmt_usd_compact(sp_24h)}"
        )
    elif df is not None and "net_money_delta_usd" in df.columns:
        nd20 = float(df["net_money_delta_usd"].tail(20).sum())
        flow_bits.append(f"Son 20 Mum Net Hacim Akışı: {_fmt_usd_compact(nd20)}")

    if pp_24h is not None:
        flow_bits.append(f"Vadeli 24S Taker: {_fmt_usd_compact(pp_24h)}")

    if order_flow is not None and order_flow.strongest_bid_wall > 0 and order_flow.strongest_ask_wall > 0:
        flow_bits.append(
            f"Alış Duvarı {_fmt_px(order_flow.strongest_bid_wall, curr_p)} / "
            f"Satış Duvarı {_fmt_px(order_flow.strongest_ask_wall, curr_p)} (Emir Defteri: %{order_flow.imbalance_pct:.0f} Alış)"
        )
    money_flow_tr = " · ".join(flow_bits) if flow_bits else f"CMF: {cmf_v:+.2f}"

    # 5. Real Exchange-Backed Liquidation Levels
    liq_map = getattr(order_flow, "liquidation_map", None) if order_flow is not None else None
    short_p: Optional[float] = None
    short_d: Optional[float] = None
    short_usd: float = 0.0
    long_p: Optional[float] = None
    long_d: Optional[float] = None
    long_usd: float = 0.0
    liq_parts: List[str] = []
    liq_source_tr = ""

    if liq_map is not None and liq_map.is_real_data and (liq_map.short_clusters or liq_map.long_clusters):
        liq_source_tr = liq_map.source_summary or "Binance OI-Profil"
        if liq_map.short_clusters:
            sc0 = liq_map.short_clusters[0]
            short_p, short_d, short_usd = sc0.price, sc0.distance_pct, sc0.estimated_usd
            s_strs = [
                f"{_fmt_px(c.price, curr_p)} (+%{c.distance_pct:.2f} · {c.leverage_tag} ~{_fmt_usd_compact(c.estimated_usd, signed=False)})"
                for c in liq_map.short_clusters[:2]
            ]
            liq_parts.append("Short (Yukarı): " + " | ".join(s_strs))
        if liq_map.long_clusters:
            lc0 = liq_map.long_clusters[0]
            long_p, long_d, long_usd = lc0.price, lc0.distance_pct, lc0.estimated_usd
            l_strs = [
                f"{_fmt_px(c.price, curr_p)} (-%{c.distance_pct:.2f} · {c.leverage_tag} ~{_fmt_usd_compact(c.estimated_usd, signed=False)})"
                for c in liq_map.long_clusters[:2]
            ]
            liq_parts.append("Long (Aşağı): " + " | ".join(l_strs))
        if liq_map.executed_liq_count_24h > 0:
            liq_parts.append(
                f"24S Gerçek Tasfiye: Long {_fmt_usd_compact(liq_map.executed_long_liq_24h_usd, signed=False)} / "
                f"Short {_fmt_usd_compact(liq_map.executed_short_liq_24h_usd, signed=False)}"
            )
        liquidation_levels_tr = " · ".join(liq_parts) + f" [{liq_source_tr}]"
    else:
        # Fallback to SMC swing-derived pools if coin has no futures OI feed
        liq_source_tr = "Grafik Tahmini (Vadeli OI Yok)"
        if fc.smc and fc.smc.liquidation_pools:
            for lp in fc.smc.liquidation_pools:
                if lp.pool_type == "SHORT_LIQ" and short_p is None:
                    short_p, short_d, short_usd = lp.price, lp.distance_pct, max(1.0, lp.density_score * 100_000.0)
                    liq_parts.append(f"Short (Yukarı): {_fmt_px(lp.price, curr_p)} (+%{lp.distance_pct:.2f})")
                elif lp.pool_type == "LONG_LIQ" and long_p is None:
                    long_p, long_d, long_usd = lp.price, lp.distance_pct, max(1.0, lp.density_score * 100_000.0)
                    liq_parts.append(f"Long (Aşağı): {_fmt_px(lp.price, curr_p)} (-%{lp.distance_pct:.2f})")
        liquidation_levels_tr = (
            " · ".join(liq_parts) + f" [{liq_source_tr}]"
            if liq_parts
            else "Aktif likidasyon kümesi tespit edilmedi."
        )

    # 6. Expected First Liquidation Sweep & Quantitative Probability
    # First-passage-time distance ratio + USD cluster gravity + active trend drift + real flow/funding pressure
    expected_side = "NONE"
    expected_prob = 50
    if short_p is not None and long_p is not None and short_d is not None and long_d is not None:
        d_s = max(short_d, 0.25)
        d_l = max(long_d, 0.25)
        p_dist_short = d_l / (d_s + d_l)  # Exact Brownian first-hitting-time probability
        p_grav_short = (
            short_usd / (short_usd + long_usd)
            if (short_usd > 0 and long_usd > 0)
            else 0.50
        )
        trend_shift = float(np.clip(fc.score / 100.0, -1.0, 1.0)) * 0.20

        flow_shift = 0.0
        if sp_4h is not None:
            flow_shift += 0.04 if sp_4h > 0 else (-0.04 if sp_4h < 0 else 0.0)
        fr_val = (
            order_flow.oi_weighted_funding_pct
            if (order_flow is not None and order_flow.oi_weighted_funding_pct is not None)
            else (order_flow.funding_rate_pct if order_flow is not None else None)
        )
        if fr_val is not None:
            if fr_val >= 0.025:
                flow_shift -= 0.04  # Crowded longs increase downside sweep odds
            elif fr_val <= -0.01:
                flow_shift += 0.04  # Crowded shorts increase upside squeeze odds

        prob_short = 0.55 * p_dist_short + 0.15 * p_grav_short + 0.15 + trend_shift + flow_shift
        prob_short = float(np.clip(prob_short, 0.22, 0.78))
        prob_long = 1.0 - prob_short

        reasons: List[str] = []
        if prob_short >= prob_long:
            expected_side = "SHORT_LIQ"
            expected_prob = int(round(prob_short * 100))
            if d_s < d_l:
                reasons.append("fiyata daha yakın")
            if fc.score >= 10:
                reasons.append("yükselen trend yönünde")
            if short_usd > long_usd * 1.15:
                reasons.append("likidasyon yoğunluğu daha yüksek")
            if not reasons:
                reasons.append("akış ve mesafe dengesi yukarı ağırlıklı")
            expected_first_liq_tr = (
                f"Short Likidasyon (Yukarı) — {_fmt_px(short_p, curr_p)} (+%{short_d:.2f}) | "
                f"Olasılık: %{expected_prob} ({', '.join(reasons)})"
            )
        else:
            expected_side = "LONG_LIQ"
            expected_prob = int(round(prob_long * 100))
            if d_l < d_s:
                reasons.append("fiyata daha yakın")
            if fc.score <= -10:
                reasons.append("düşen trend yönünde")
            if long_usd > short_usd * 1.15:
                reasons.append("likidasyon yoğunluğu daha yüksek")
            if not reasons:
                reasons.append("akış ve mesafe dengesi aşağı ağırlıklı")
            expected_first_liq_tr = (
                f"Long Likidasyon (Aşağı) — {_fmt_px(long_p, curr_p)} (-%{long_d:.2f}) | "
                f"Olasılık: %{expected_prob} ({', '.join(reasons)})"
            )
    elif long_p is not None and long_d is not None:
        expected_side = "LONG_LIQ"
        expected_prob = 62
        expected_first_liq_tr = f"Long Likidasyon (Aşağı) — {_fmt_px(long_p, curr_p)} (-%{long_d:.2f}) | Olasılık: %{expected_prob}"
    elif short_p is not None and short_d is not None:
        expected_side = "SHORT_LIQ"
        expected_prob = 62
        expected_first_liq_tr = f"Short Likidasyon (Yukarı) — {_fmt_px(short_p, curr_p)} (+%{short_d:.2f}) | Olasılık: %{expected_prob}"
    else:
        expected_first_liq_tr = "Öncelikli likidasyon hedefi hesaplanamadı."

    # 7. Technical Verdict & Factual Explanation (Zero Fluff, 100% Real Chart Numbers)
    ema_rel_bits: List[str] = []
    if ema20 > 0:
        ema_rel_bits.append(f"EMA20 ({_fmt_px(ema20, curr_p)}) {'üzerinde' if curr_p >= ema20 else 'altında'}")
    if ema50 > 0:
        ema_rel_bits.append(f"EMA50 ({_fmt_px(ema50, curr_p)}) {'üzerinde' if curr_p >= ema50 else 'altında'}")
    if ema200 > 0:
        ema_rel_bits.append(f"EMA200 ({_fmt_px(ema200, curr_p)}) {'üzerinde' if curr_p >= ema200 else 'altında'}")

    mtf_str = " | ".join(
        f"{k}: {mtf_scores[k]:+.0f}"
        for k in ("15M", "1H", "4H", "1D")
        if k in mtf_scores
    )

    if rsi14 >= 70:
        rsi_note = f"RSI {rsi14:.1f} (aşırı alım)"
    elif rsi14 <= 30:
        rsi_note = f"RSI {rsi14:.1f} (aşırı satım)"
    else:
        rsi_note = f"RSI {rsi14:.1f}"
    macd_note = "MACD pozitif" if macd_hist > 0 else "MACD negatif"
    adx_note = f"ADX {adx14:.1f} ({'güçlü trend' if adx14 >= 25 else 'zayıf/yatay momentum'})"

    deriv_bits: List[str] = []
    if order_flow is not None:
        fr_disp = order_flow.oi_weighted_funding_pct if order_flow.oi_weighted_funding_pct is not None else order_flow.funding_rate_pct
        if fr_disp is not None:
            deriv_bits.append(f"Fonlama %{fr_disp:+.4f}")
        if order_flow.oi_change_24h_pct is not None:
            deriv_bits.append(f"24S OI {order_flow.oi_change_24h_pct:+.1f}%")
        if order_flow.long_short_ratio is not None:
            deriv_bits.append(f"L/S {order_flow.long_short_ratio:.2f}")

    if trend_dir == "DOWN":
        verdict = "Satış baskısı baskın; düşen trend kırılımı gelmeden tepki alımları riskli."
        cond_line = (
            f"Fiyat {_fmt_px(breakout_price_num, curr_p)} üzerinde kapanış yapmadıkça aşağıda "
            f"{_fmt_px(sup_primary.price if sup_primary else fc.nearest_support, curr_p)} desteği"
            + (f" ve {_fmt_px(long_p, curr_p)} long likidasyon bölgesi" if long_p else "")
            + " öncelikli takip seviyesidir."
        )
    elif trend_dir == "UP":
        verdict = "Alıcı kontrolü sürüyor; yükselen trend desteği korundukça yukarı yapı geçerli."
        cond_line = (
            f"Fiyat {_fmt_px(breakout_price_num, curr_p)} üzerinde kaldıkça yukarıda "
            f"{_fmt_px(res_primary.price if res_primary else fc.nearest_resistance, curr_p)} direnci"
            + (f" ve {_fmt_px(short_p, curr_p)} short likidasyon bölgesi" if short_p else "")
            + " hedefte kalır; bu seviye altında kapanış yapıyı zayıflatır."
        )
    else:
        verdict = "Net trend yönü yok; sıkışma bandının kırıldığı yöne göre hareket beklenmeli."
        cond_line = (
            f"Yukarıda {_fmt_px(res_primary.price if res_primary else fc.nearest_resistance, curr_p)} üzeri "
            f"veya aşağıda {_fmt_px(sup_primary.price if sup_primary else fc.nearest_support, curr_p)} altı "
            f"hacimli mum kapanışı yeni yönü teyit eder."
        )

    expl_sentences = [
        f"Fiyat ({_fmt_px(curr_p, curr_p)}) şu an {', '.join(ema_rel_bits)} konumlanıyor." if ema_rel_bits else "",
        f"Göstergeler: {rsi_note}, {macd_note}, {adx_note}" + (f" | Çoklu zaman skoru ({mtf_str})." if mtf_str else "."),
        (f"Türev verileri: {', '.join(deriv_bits)}." if deriv_bits else ""),
        cond_line,
    ]
    explanation_tr = " ".join(s for s in expl_sentences if s).strip()

    plain_lines = [
        trend_headline,
        f"{trend_breakout_label} = {trend_breakout_val}",
        f"Destek = {support_tr}",
        f"Güçlü destek = {strong_support_tr}",
        f"Direnç = {resistance_tr}",
        f"Güçlü Direnç = {strong_resistance_tr}",
        "",
        f"Coinin para giriş çıkış seviyeleri = {money_flow_tr}",
        f"Likiditasyon seviyeleri = {liquidation_levels_tr}",
        f"Önce almasını beklediğin likiditasyon seviyesi/olasılık = {expected_first_liq_tr}",
        "",
        f"Teknik ne diyor ? {verdict}",
        f"Açıklama: {explanation_tr}",
    ]
    plain_text_tr = "\n".join(plain_lines)

    return UnifiedCoinAnalysis(
        symbol=symbol.upper(),
        timeframe=tf_up,
        current_price=curr_p,
        trend_direction=trend_dir,
        trend_headline_tr=trend_headline,
        accent_color=accent_color,
        trend_breakout_label_tr=trend_breakout_label,
        trend_breakout_value_tr=trend_breakout_val,
        support_tr=support_tr,
        strong_support_tr=strong_support_tr,
        resistance_tr=resistance_tr,
        strong_resistance_tr=strong_resistance_tr,
        money_flow_tr=money_flow_tr,
        liquidation_levels_tr=liquidation_levels_tr,
        expected_first_liq_tr=expected_first_liq_tr,
        expected_first_liq_side=expected_side,
        expected_first_liq_prob_pct=expected_prob,
        technical_verdict_tr=verdict,
        explanation_tr=explanation_tr,
        liquidation_source_tr=liq_source_tr,
        plain_text_tr=plain_text_tr,
    )


def format_unified_analysis_telegram_html(u: UnifiedCoinAnalysis) -> str:
    """Formats `UnifiedCoinAnalysis` cleanly in Telegram HTML."""
    icon = "🟢" if u.trend_direction == "UP" else ("🔴" if u.trend_direction == "DOWN" else "🟡")
    return "\n".join(
        [
            f"{icon} <b>{html.escape(u.trend_headline_tr)}</b>",
            f"💰 <b>Anlık Fiyat:</b> <code>{html.escape(_fmt_px(u.current_price, u.current_price))}</code>",
            "━━━━━━━━━━━━",
            f"📐 <b>{html.escape(u.trend_breakout_label_tr)}:</b> {html.escape(u.trend_breakout_value_tr)}",
            f"🟢 <b>Destek:</b> {html.escape(u.support_tr)}",
            f"🛡️ <b>Güçlü Destek:</b> {html.escape(u.strong_support_tr)}",
            f"🔴 <b>Direnç:</b> {html.escape(u.resistance_tr)}",
            f"🧱 <b>Güçlü Direnç:</b> {html.escape(u.strong_resistance_tr)}",
            "━━━━━━━━━━━━",
            f"💵 <b>Para Giriş / Çıkış:</b> {html.escape(u.money_flow_tr)}",
            f"🧲 <b>Likidasyon Seviyeleri:</b> {html.escape(u.liquidation_levels_tr)}",
            f"🎯 <b>Önce Beklenen Likidasyon / Olasılık:</b> {html.escape(u.expected_first_liq_tr)}",
            "━━━━━━━━━━━━",
            f"📊 <b>Teknik ne diyor?</b> {html.escape(u.technical_verdict_tr)}",
            f"📝 <b>Açıklama:</b> {html.escape(u.explanation_tr)}",
        ]
    )
