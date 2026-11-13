"""
Configuration settings and thresholds for the Crypto Quantitative Direction,
Money Flow & Multi-Timeframe Analysis Engine.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class ExchangeConfig:
    """Settings for CCXT exchange data retrieval (Spot + Futures + OrderBook)."""
    primary_exchange: str = "binance"
    fallback_exchanges: List[str] = field(
        default_factory=lambda: ["gate", "kucoin", "kraken", "coinbase", "cryptocom", "okx", "bybit"]
    )
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    limit: int = 200
    timeout_ms: int = 15000
    orderbook_depth: int = 50


@dataclass(frozen=True)
class IndicatorConfig:
    """Parameters for technical, trend, volatility, and money flow indicators."""
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    rsi_near_overbought: float = 60.0
    rsi_near_oversold: float = 40.0

    bb_period: int = 20
    bb_std_dev: float = 2.0

    ema_fast: int = 20
    ema_slow: int = 50
    ema_macro: int = 200

    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    adx_period: int = 14
    atr_period: int = 14
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0

    mfi_period: int = 14
    cmf_period: int = 20
    vol_sma_period: int = 20


@dataclass(frozen=True)
class PatternConfig:
    """Mathematical thresholds for candlestick pattern recognition."""
    doji_body_ratio: float = 0.10
    doji_extreme_shadow_ratio: float = 0.65

    pinbar_shadow_to_body_min: float = 2.0
    pinbar_opposite_shadow_max_ratio: float = 0.15
    pinbar_min_body_ratio: float = 0.05

    engulfing_min_body_expansion: float = 1.05


@dataclass(frozen=True)
class ChartConfig:
    """Visual styling and output settings for Plotly interactive charts."""
    theme: str = "plotly_dark"
    height: int = 960
    width: int = 1550
    output_html: str = "btc_usdt_analiz_raporu.html"
    up_color: str = "#00E676"
    down_color: str = "#FF5252"
    bb_upper_color: str = "rgba(148, 163, 184, 0.55)"
    bb_lower_color: str = "rgba(148, 163, 184, 0.55)"
    bb_mid_color: str = "rgba(250, 204, 21, 0.75)"
    bb_fill_color: str = "rgba(56, 189, 248, 0.05)"
    rsi_color: str = "#C084FC"


@dataclass(frozen=True)
class AnalysisConfig:
    """Master configuration container."""
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    patterns: PatternConfig = field(default_factory=PatternConfig)
    chart: ChartConfig = field(default_factory=ChartConfig)
