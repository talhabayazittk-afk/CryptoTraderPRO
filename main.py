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
    from src.local_ai import build_unified_coin_analysis

    unified_rep = build_unified_coin_analysis(
        symbol=symbol,
        timeframe=anchor_ai_tf,
        df=tf_data[anchor_ai_tf],
        fc=tf_forecasts[anchor_ai_tf],
        mtf_scores=coin_scores,
        order_flow=order_flow,
    )

    print("\n" + "=" * 96)
    print(f"  📊 {symbol} ({anchor_ai_tf}) [{source_used}] — SADELEŞTİRİLMİŞ TEKNİK & LİKİDASYON ANALİZİ")
    print("=" * 96)
    print(unified_rep.plain_text_tr)
    print("-" * 96)

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
