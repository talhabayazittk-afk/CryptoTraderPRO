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
