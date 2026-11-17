"""
Main Orchestrator CLI (v2.0) for Multi-Coin & Multi-Timeframe (15M, 1H, 4H, 1D) Crypto Market Analysis
(ETH, ONDO, BTC, ENA, etc.), Parallel Fetching, Real Taker Money Flow / CVD, Volume Profile (POC),
BTC Macro Regime Alignment, Historical Signal Backtesting, and Interactive Plotly Dashboards.
"""
import argparse
import logging
import sys
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.config import AnalysisConfig, ChartConfig, ExchangeConfig, IndicatorConfig, PatternConfig
from src.pipeline import AnalysisPipeline
from src.signals import MarketForecast
from src.visualizer import InteractiveChartVisualizer

DEFAULT_COINS = ["ETH/USDT", "ONDO/USDT", "BTC/USDT", "ENA/USDT"]
DEFAULT_TIMEFRAMES = ["1h", "4h", "1d"]


def setup_logging() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def normalize_symbol(coin: str) -> str:
    cleaned = coin.strip().upper().replace("-", "/")
    if "/" not in cleaned:
        if cleaned.endswith("USDT") and len(cleaned) > 4:
            return f"{cleaned[:-4]}/USDT"
        return f"{cleaned}/USDT"
    return cleaned


def build_output_filename(symbol: str, custom_output: str = "") -> str:
    if custom_output:
        return custom_output
    safe_sym = symbol.replace("/", "_").replace(":", "_").lower()
    return f"{safe_sym}_analiz_raporu.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Çoklu Kripto (ETH, ONDO, BTC, ENA) & Çok Katmanlı Para Akışı / Yön Tahmin Motoru (v2.0)"
    )
    parser.add_argument(
        "--symbols",
        "--symbol",
        nargs="+",
        default=DEFAULT_COINS,
        help="Analiz edilecek coin(ler) — örn: ETH ONDO BTC ENA (varsayılan: ETH ONDO BTC ENA)",
    )
    parser.add_argument(
        "--timeframes",
        "--timeframe",
        nargs="+",
        default=DEFAULT_TIMEFRAMES,
        help="Grafik içinde yer alacak zaman dilimleri (varsayılan: 1h 4h 1d)",
    )
    parser.add_argument(
        "--exchange",
        type=str,
        default="binance",
        choices=["binance", "bybit", "kraken", "okx"],
        help="Birincil kripto borsası (varsayılan: binance, otomatik bybit yedekli)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Her zaman dilimi için çekilecek mum sayısı (varsayılan: 500 — EMA200/RSI tam ısınma)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Tek bir coin analiz edilirken özel çıktı dosya adı",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Oluşturulan raporları varsayılan web tarayıcısında otomatik aç",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Lokal Ollama AI Yönetici Özeti & Çelişki Yorumu katmanını devre dışı bırak",
    )
    return parser.parse_args()


def analyze_coin_multi_timeframe(
    symbol: str,
    timeframes: List[str],
    exchange: str,
    limit: int,
    output_file: str,
    btc_regime_scores: Optional[Dict[str, float]] = None,
    btc_tf_data: Optional[Dict[str, pd.DataFrame]] = None,
    show: bool = False,
    enable_ai: bool = True,
) -> Tuple[Path, Dict[str, float], Dict[str, pd.DataFrame]]:
    base_config = AnalysisConfig(
        exchange=ExchangeConfig(
            primary_exchange=exchange,
            symbol=symbol,
            timeframe=timeframes[0],
            limit=limit,
        ),
        indicators=IndicatorConfig(),
        patterns=PatternConfig(),
        chart=ChartConfig(output_html=output_file),
    )

    bundle = AnalysisPipeline.run_coin_bundle(
        symbol=symbol,
        exchange_id=exchange,
        timeframes=timeframes,
        limit=limit,
        btc_regime_scores=btc_regime_scores,
        btc_tf_data=btc_tf_data,
        allow_synthetic_fallback=False,
        enable_ledger=True,
    )
    tf_data = bundle.tf_data
    tf_forecasts = bundle.tf_forecasts
    order_flow = bundle.order_flow
    source_used = bundle.source_used
    coin_scores = bundle.mtf_scores
    ordered_tfs = [tf.upper() for tf in timeframes]
    anchor_ai_tf = "4H" if "4H" in ordered_tfs else ordered_tfs[0]
    ai_rep = AnalysisPipeline.attach_ai_summary(bundle, timeframe=anchor_ai_tf, enable_ai=enable_ai)

    print("\n" + "=" * 106)
    print(f"  📊 {symbol} — KURUMSAL ÇOK KATMANLI YÖN, PARA SAĞLIĞI, SMC & GERÇEKÇİ BACKTEST RAPORU (v10.0)")
    print("=" * 106)
    print(f"  📘 Derin Emir Defteri : {order_flow.orderbook_status_tr}")
    print(f"  ⚡ Vadeli İşlemler    : {order_flow.futures_sentiment_tr}")
    if ai_rep is not None:
        ai_src_tag = (
            f"Hibrit: Kantitatif + Ollama/{ai_rep.model_used} ({ai_rep.latency_sec:.1f}s | Katkı:{ai_rep.ai_score_delta:+.1f}p)"
            if ai_rep.is_ai_generated
            else "Bağımsız Kantitatif Motor v10 (AI Olmadan Tam Kapasite)"
        )
        print(f"  🧠 Aktif Yön Motoru   : {ai_rep.stance_tr} [{anchor_ai_tf} · {ai_src_tag}]")
        if ai_rep.flow_health_tr:
            print(f"  💧 Para Giriş Sağlığı : {ai_rep.flow_health_tr}")
        print(f"  📌 Yönetici & Yön Öz. : {ai_rep.executive_summary_tr}")
        print(f"  ⚖️ Çelişki Denetimi   : {ai_rep.contradiction_comment_tr}")
        print(f"  🎯 İzleme Planı       : {ai_rep.action_plan_tr}")
    print("-" * 106)

    for tf_key in ordered_tfs:
        df_final = tf_data[tf_key]
        forecast = tf_forecasts[tf_key]
        last = df_final.iloc[-1]
        p_fmt = ",.4f" if float(df_final["close"].max()) < 10.0 else ",.2f"
        sup_str = (
            " / ".join([f"{format(s.price, p_fmt)}" for s in forecast.support_levels])
            if forecast.support_levels
            else "Yok"
        )
        res_str = (
            " / ".join([f"{format(r.price, p_fmt)}" for r in forecast.resistance_levels])
            if forecast.resistance_levels
            else "Yok"
        )

        print(
            f"  ⏱️ [{tf_key}] Fiyat: {format(last['close'], p_fmt)} USDT | "
            f"Hacim POC: {format(forecast.poc_price, p_fmt)} | RSI: {last['rsi']:.1f} | CMF: {last['cmf']:+.2f}"
        )
        print(f"     • Yön Endeksi     : {forecast.verdict_tr} (Skor: {forecast.score:+.0f}/100 | Uyum: %{forecast.confidence_pct:.0f})")
        print(f"     • Dinamik Rejim   : {forecast.regime_tr}")
        print(f"     • Para Akışı      : {forecast.money_flow_status_tr}")
        print(f"     • SMC & Likidite  : {forecast.smc.structure_summary_tr} | {forecast.smc.liquidity_summary_tr}")
        print(f"     • BTC RS & Makro  : {forecast.smc.relative_strength.status_tr} | {forecast.macro_context_tr}")
        print(f"     • Destek / Direnç : 🟢 {sup_str} USDT  |  🔴 {res_str} USDT")
        print(f"     • Backtest Özeti  : 🎯 {forecast.backtest_stats.summary_tr}")
        if forecast.risk_plan:
            print(f"     • Kasa/Risk Planı : 🧮 {forecast.risk_plan.summary_tr}")
        print(f"     • Boğa Senaryosu  : {forecast.bullish_scenario_tr}")
        print(f"     • Ayı Senaryosu   : {forecast.bearish_scenario_tr}")
        print("-" * 106)

    visualizer = InteractiveChartVisualizer(base_config)
    fig = visualizer.create_multi_timeframe_figure(
        tf_data=tf_data,
        tf_forecasts=tf_forecasts,
        exchange_source=source_used,
        default_tf=ordered_tfs[0],
    )
    saved_path = visualizer.save_html(
        fig=fig,
        output_path=output_file,
        tf_data=tf_data,
        tf_forecasts=tf_forecasts,
        order_flow=order_flow,
        exchange_source=source_used,
    )

    print(f"  ✅ [RAPOR KAYDEDİLDİ] -> {saved_path}")
    print("=" * 106)

    if show:
        webbrowser.open(saved_path.as_uri())

    return saved_path, coin_scores, tf_data


def run_pipeline(args: argparse.Namespace) -> List[Path]:
    symbols = [normalize_symbol(s) for s in args.symbols]
    saved_files: List[Path] = []

    # Analyze BTC/USDT first if present (or fetch its regime) so altcoins receive BTC Macro Regime & RS alignment
    btc_regime_scores: Dict[str, float] = {}
    btc_tf_data: Dict[str, pd.DataFrame] = {}
    if "BTC/USDT" in symbols:
        btc_out = build_output_filename("BTC/USDT", args.output if len(symbols) == 1 else "")
        btc_path, btc_regime_scores, btc_tf_data = analyze_coin_multi_timeframe(
            symbol="BTC/USDT",
            timeframes=args.timeframes,
            exchange=args.exchange,
            limit=args.limit,
            output_file=btc_out,
            btc_regime_scores=None,
            btc_tf_data=None,
            show=args.show,
            enable_ai=not args.no_ai,
        )
        saved_files.append(btc_path)

    for sym in symbols:
        if sym == "BTC/USDT":
            continue
        custom_out = args.output if len(symbols) == 1 else ""
        out_name = build_output_filename(sym, custom_out)
        path, _, _ = analyze_coin_multi_timeframe(
            symbol=sym,
            timeframes=args.timeframes,
            exchange=args.exchange,
            limit=args.limit,
            output_file=out_name,
            btc_regime_scores=btc_regime_scores,
            btc_tf_data=btc_tf_data,
            show=args.show,
            enable_ai=not args.no_ai,
        )
        saved_files.append(path)

    return saved_files


def main() -> int:
    setup_logging()
    args = parse_args()
    try:
        saved = run_pipeline(args)
        print("\n📌 Oluşturulan Profesyonel Kripto Analiz Dosyaları:")
        for p in saved:
            print(f"  • {p.name} -> {p}")
        return 0
    except Exception as exc:
        logging.error(f"Analiz hattı çalışırken hata oluştu: {exc}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
