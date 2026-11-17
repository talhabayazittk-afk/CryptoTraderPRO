"""
Phase 3 Unified Single-Source-of-Truth Multi-Timeframe Analysis Pipeline (`AnalysisPipeline`).
Guarantees 100% identical numbers, support/resistance walls, cash-flow metrics, and forecasts
across the Streamlit Web UI (`app.py`), 24/7 Telegram/X Bot (`telegram_bot.py`), and CLI (`main.py`),
while automatically auditing & logging live setups in `SignalLedger` (`signal_ledger.db`).
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from .config import AnalysisConfig, ChartConfig, ExchangeConfig, IndicatorConfig, PatternConfig
from .data_fetcher import CryptoDataFetcher, OrderFlowIntel
from .indicators import TechnicalIndicators
from .patterns import CandlestickPatternDetector
from .signal_ledger import SignalLedger
from .signals import MarketForecast, SignalEngine, SupportResistanceLevel


@dataclass
class CoinAnalysisBundle:
    """Canonical multi-timeframe output container shared by Web UI, Telegram Bot, and X Publisher."""
    symbol: str
    source_used: str
    tf_data: Dict[str, pd.DataFrame]
    tf_forecasts: Dict[str, MarketForecast]
    order_flow: OrderFlowIntel
    mtf_scores: Dict[str, float]
    current_price: float


class AnalysisPipeline:
    """
    Canonical top-down (`1D -> 4H -> 1H -> 15M`) institutional analysis orchestrator.
    """

    @staticmethod
    def run_coin_bundle(
        symbol: str,
        exchange_id: str = "binance",
        timeframes: Sequence[str] = ("15m", "1h", "4h", "1d"),
        limit: int = 500,
        btc_regime_scores: Optional[Dict[str, float]] = None,
        btc_tf_data: Optional[Dict[str, pd.DataFrame]] = None,
        sample_capital_usd: float = 1000.0,
        risk_pct: float = 1.0,
        allow_synthetic_fallback: bool = False,
        enable_ledger: bool = True,
        ledger: Optional[SignalLedger] = None,
    ) -> CoinAnalysisBundle:
        sym_up = symbol.strip().upper()
        ex_low = exchange_id.strip().lower()
        tf_list = [t.lower() for t in timeframes]
        ordered_tfs = [t.upper() for t in tf_list]

        base_cfg = AnalysisConfig(
            exchange=ExchangeConfig(
                primary_exchange=ex_low,
                symbol=sym_up,
                timeframe=tf_list[0] if tf_list else "4h",
                limit=limit,
            ),
            indicators=IndicatorConfig(),
            patterns=PatternConfig(),
            chart=ChartConfig(),
        )
        fetcher = CryptoDataFetcher(base_cfg.exchange)
        indicators = TechnicalIndicators(base_cfg.indicators)
        detector = CandlestickPatternDetector(base_cfg.patterns)
        signal_engine = SignalEngine(base_cfg.indicators)

        # Fetch all timeframes (500-bar warmup) AND OrderFlowIntel concurrently
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_tf = pool.submit(
                fetcher.fetch_multi_timeframe_parallel,
                symbol=sym_up,
                timeframes=tf_list,
                limit=limit,
                exchange_id=ex_low,
                allow_synthetic_fallback=allow_synthetic_fallback,
            )
            fut_intel = pool.submit(
                fetcher.fetch_order_flow_intel,
                symbol=sym_up,
                exchange_id=ex_low,
            )
            raw_tf_dict, source_used = fut_tf.result()
            order_flow = fut_intel.result()

        tf_data: Dict[str, pd.DataFrame] = {}
        for tf_key in ordered_tfs:
            df_ind = indicators.enrich(raw_tf_dict[tf_key])
            df_pat = detector.detect_all(df_ind)
            tf_data[tf_key] = signal_engine.evaluate(df_pat)

        # Evaluate strictly from highest timeframe (1D -> 4H -> 1H -> 15M)
        tf_forecasts: Dict[str, MarketForecast] = {}
        mtf_scores: Dict[str, float] = {}
        htf_prev_score: Optional[float] = None
        anchor_4h_score: Optional[float] = None
        htf_sr_pool: List[SupportResistanceLevel] = []

        for tf_key in reversed(ordered_tfs):
            df_final = tf_data[tf_key]
            btc_score = (
                btc_regime_scores.get(tf_key)
                if (btc_regime_scores and not sym_up.startswith("BTC/"))
                else None
            )
            btc_df = (
                btc_tf_data.get(tf_key)
                if (btc_tf_data and not sym_up.startswith("BTC/"))
                else None
            )

            # Anchor lower timeframes (15M) to both 1H and 4H macro tide so 4H trend is never lost
            eff_htf_score = htf_prev_score
            if tf_key == "15M" and htf_prev_score is not None and anchor_4h_score is not None:
                eff_htf_score = 0.60 * htf_prev_score + 0.40 * anchor_4h_score

            fc = signal_engine.generate_forecast(
                df_final,
                order_flow=order_flow,
                htf_score=eff_htf_score,
                btc_regime_score=btc_score,
                symbol=sym_up,
                btc_df=btc_df,
                sample_capital_usd=sample_capital_usd,
                risk_pct=risk_pct,
                htf_sr_levels=list(htf_sr_pool) if htf_sr_pool else None,
            )
            tf_forecasts[tf_key] = fc
            mtf_scores[tf_key] = fc.score
            htf_prev_score = fc.score
            if tf_key == "4H":
                anchor_4h_score = fc.score
            if tf_key in ("1D", "4H"):
                htf_sr_pool.extend(fc.support_levels[:2])
                htf_sr_pool.extend(fc.resistance_levels[:2])

        tf_forecasts = {k: tf_forecasts[k] for k in ordered_tfs}
        mtf_scores = {k: mtf_scores[k] for k in ordered_tfs}

        # Automatically verify open ledger signals & record newly qualified setups
        if enable_ledger and not allow_synthetic_fallback and source_used != "SIMULATED_FALLBACK":
            try:
                active_ledger = ledger or SignalLedger()
                for tf_key in ordered_tfs:
                    if tf_key in ("1H", "4H", "1D"):
                        active_ledger.evaluate_open_signals_with_df(sym_up, tf_key, tf_data[tf_key])
                        active_ledger.record_signal_if_qualified(
                            sym_up, tf_key, source_used, tf_forecasts[tf_key], tf_data[tf_key]
                        )
            except Exception:
                pass

        ref_tf = "4H" if "4H" in tf_data else ordered_tfs[-1]
        curr_p = float(tf_data[ref_tf]["close"].iloc[-1])

        return CoinAnalysisBundle(
            symbol=sym_up,
            source_used=source_used,
            tf_data=tf_data,
            tf_forecasts=tf_forecasts,
            order_flow=order_flow,
            mtf_scores=mtf_scores,
            current_price=curr_p,
        )

    @staticmethod
    def attach_ai_summary(
        bundle: CoinAnalysisBundle,
        timeframe: str = "4H",
        model: Optional[str] = None,
        force_refresh: bool = False,
        enable_ai: bool = True,
    ) -> Any:
        """
        Generates (or fetches from cache) a Hybrid AI + Quant v10 Direction & Contradiction Report
        for `bundle.tf_forecasts[timeframe]` and fuses it into `fc`.
        When `enable_ai=False` or Ollama is offline, runs the full Standalone Quantitative Synthesis v10.
        """
        from .local_ai import DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_MODEL, generate_ai_executive_summary

        tf_up = timeframe.upper()
        if tf_up not in bundle.tf_forecasts:
            tf_up = next(iter(bundle.tf_forecasts.keys()))
        fc = bundle.tf_forecasts[tf_up]
        df_tf = bundle.tf_data.get(tf_up)
        curr_p = float(df_tf["close"].iloc[-1]) if df_tf is not None and len(df_tf) > 0 else bundle.current_price
        eff_url = DEFAULT_OLLAMA_BASE_URL if enable_ai else "http://127.0.0.1:1"
        rep = generate_ai_executive_summary(
            symbol=bundle.symbol,
            timeframe=tf_up,
            current_price=curr_p,
            fc=fc,
            mtf_scores=bundle.mtf_scores,
            order_flow=bundle.order_flow,
            model=model or DEFAULT_OLLAMA_MODEL,
            base_url=eff_url,
            force_refresh=force_refresh,
            apply_fusion=True,
        )
        fc.ai_report = rep
        bundle.mtf_scores[tf_up] = fc.score
        return rep
