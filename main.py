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
from src.data_fetcher import CryptoDataFetcher
from src.indicators import TechnicalIndicators
from src.patterns import CandlestickPatternDetector
from src.signals import MarketForecast, SignalEngine
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

    fetcher = CryptoDataFetcher(base_config.exchange)
    indicators = TechnicalIndicators(base_config.indicators)
    detector = CandlestickPatternDetector(base_config.patterns)
    signal_engine = SignalEngine(base_config.indicators)

    # 1. Parallel fetch all timeframes + OrderBook & Futures Intelligence
    raw_tf_dict, source_used = fetcher.fetch_multi_timeframe_parallel(
        symbol=symbol,
        timeframes=timeframes,
        limit=limit,
        exchange_id=exchange,
    )
    order_flow = fetcher.fetch_order_flow_intel(symbol=symbol, exchange_id=exchange)

    tf_data: Dict[str, pd.DataFrame] = {}
    tf_forecasts: Dict[str, MarketForecast] = {}
    coin_scores: Dict[str, float] = {}

    # 2. Enrich and evaluate from Highest Timeframe (e.g., 1D -> 4H -> 1H) so HTF score feeds into LTF
    ordered_tfs = [tf.upper() for tf in timeframes]
    for tf_key in ordered_tfs:
        df_ind = indicators.enrich(raw_tf_dict[tf_key])
        df_pat = detector.detect_all(df_ind)
        tf_data[tf_key] = signal_engine.evaluate(df_pat)

    htf_prev_score: Optional[float] = None
    for tf_key in reversed(ordered_tfs):
        df_final = tf_data[tf_key]
        btc_score = (
            btc_regime_scores.get(tf_key)
            if (btc_regime_scores and not symbol.startswith("BTC/"))
            else None
        )
        btc_df = btc_tf_data.get(tf_key) if btc_tf_data else None
        fc = signal_engine.generate_forecast(
            df_final,
            order_flow=order_flow,
            htf_score=htf_prev_score,
            btc_regime_score=btc_score,
            symbol=symbol,
            btc_df=btc_df,
        )
        tf_forecasts[tf_key] = fc
        coin_scores[tf_key] = fc.score
        htf_prev_score = fc.score

    # Restore original timeframe ordering in dictionary
    tf_forecasts = {k: tf_forecasts[k] for k in ordered_tfs}

    print("\n" + "=" * 106)
    print(f"  📊 {symbol} — KURUMSAL ÇOK KATMANLI YÖN, SMC, OLASILIK KONİSİ & GERÇEKÇİ BACKTEST RAPORU (v3.0)")
    print("=" * 106)
    print(f"  📘 Derin Emir Defteri : {order_flow.orderbook_status_tr}")
    print(f"  ⚡ Vadeli İşlemler    : {order_flow.futures_sentiment_tr}")
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
        btc_out = args.output if len(symbols) == 1 else build_output_filename("BTC/USDT")
        btc_path, btc_regime_scores, btc_tf_data = analyze_coin_multi_timeframe(
            symbol="BTC/USDT",
            timeframes=args.timeframes,
            exchange=args.exchange,
            limit=args.limit,
            output_file=btc_out,
            btc_regime_scores=None,
            btc_tf_data=None,
            show=args.show,
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
