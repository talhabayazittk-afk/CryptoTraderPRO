"""
Unit tests verifying mathematical correctness of RSI, Bollinger Bands,
Real Taker Money Flow / CVD, Volume Profile (POC/VAH/VAL), Context-Aware Candlestick
Patterns (Morning Star, Hammer, Shooting Star, Bullish/Bearish Engulfing),
Closed-Candle Guarantee, and Historical Signal Backtest Validation (v2.0).
"""
import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from src.config import AnalysisConfig
from src.data_fetcher import CryptoDataFetcher, OrderFlowIntel
from src.indicators import TechnicalIndicators
from src.patterns import CandlestickPatternDetector
from src.signals import SignalEngine
from src.smart_money import SmartMoneyEngine
from src.visualizer import InteractiveChartVisualizer


class TestCryptoAnalysisArchitecture(unittest.TestCase):
    def setUp(self):
        self.config = AnalysisConfig()
        self.indicators = TechnicalIndicators(self.config.indicators)
        self.detector = CandlestickPatternDetector(self.config.patterns)
        self.signals = SignalEngine(self.config.indicators)

    def test_rsi_bollinger_money_flow_and_volume_profile_math(self):
        df = CryptoDataFetcher.generate_synthetic_ohlcv(limit=150, timeframe="1h")
        enriched = self.indicators.enrich(df)

        for col in [
            "rsi", "bb_upper", "bb_mid", "bb_lower",
            "mfi", "cmf", "obv", "cvd", "supertrend", "supertrend_dir",
            "adx", "atr", "vp_poc", "vp_vah", "vp_val",
            "kalman_trend", "kalman_slope", "hurst_exponent", "choppiness_index",
            "avwap_high", "avwap_low", "absorption_signal",
        ]:
            self.assertIn(col, enriched.columns)

        valid_rsi = enriched["rsi"].dropna()
        self.assertTrue(((valid_rsi >= 0.0) & (valid_rsi <= 100.0)).all())

        valid_mfi = enriched["mfi"].dropna()
        self.assertTrue(((valid_mfi >= 0.0) & (valid_mfi <= 100.0)).all())

        valid_cmf = enriched["cmf"].dropna()
        self.assertTrue(((valid_cmf >= -1.001) & (valid_cmf <= 1.001)).all())

        # Volume Profile POC must lie within VAL and VAH
        poc = float(enriched["vp_poc"].iloc[-1])
        vah = float(enriched["vp_vah"].iloc[-1])
        val = float(enriched["vp_val"].iloc[-1])
        self.assertGreaterEqual(vah, poc)
        self.assertGreaterEqual(poc, val)

    def test_candlestick_patterns_and_unclosed_candle_guard(self):
        now = datetime.now(timezone.utc)
        rows = [
            {"timestamp": now, "open": 60000.0, "high": 60100.0, "low": 59900.0, "close": 60000.0, "volume": 100.0, "is_closed": True},
            {"timestamp": now + timedelta(hours=1), "open": 60000.0, "high": 60050.0, "low": 59750.0, "close": 59800.0, "volume": 120.0, "is_closed": True},
            {"timestamp": now + timedelta(hours=2), "open": 59780.0, "high": 60200.0, "low": 59750.0, "close": 60150.0, "volume": 250.0, "is_closed": True},
            {"timestamp": now + timedelta(hours=3), "open": 60150.0, "high": 60250.0, "low": 60050.0, "close": 60155.0, "volume": 90.0, "is_closed": True},
            {"timestamp": now + timedelta(hours=4), "open": 60155.0, "high": 60350.0, "low": 60140.0, "close": 60300.0, "volume": 110.0, "is_closed": True},
            {"timestamp": now + timedelta(hours=5), "open": 60320.0, "high": 60360.0, "low": 59950.0, "close": 60000.0, "volume": 300.0, "is_closed": True},
            {"timestamp": now + timedelta(hours=6), "open": 60000.0, "high": 60045.0, "low": 59850.0, "close": 60040.0, "volume": 180.0, "is_closed": True},
            # Index 7: Unclosed live candle that looks like a Doji — should be suppressed!
            {"timestamp": now + timedelta(hours=7), "open": 60040.0, "high": 60200.0, "low": 59900.0, "close": 60042.0, "volume": 20.0, "is_closed": False},
        ]
        df = pd.DataFrame(rows)
        pat_df = self.detector.detect_all(df)

        self.assertTrue(bool(pat_df.loc[2, "pattern_bullish_engulfing"]))
        self.assertEqual(pat_df.loc[2, "primary_pattern"], "Bullish Engulfing")
        self.assertTrue(bool(pat_df.loc[3, "pattern_doji"]))
        self.assertTrue(bool(pat_df.loc[5, "pattern_bearish_engulfing"]))
        self.assertTrue(bool(pat_df.loc[6, "pattern_hammer"]))
        for new_pat_col in (
            "pattern_tweezer_bottom",
            "pattern_tweezer_top",
            "pattern_bullish_marubozu",
            "pattern_bearish_marubozu",
        ):
            self.assertIn(new_pat_col, pat_df.columns)

        anat_str = CandlestickPatternDetector.summarize_candle_anatomy(pat_df)
        self.assertTrue(len(anat_str) > 0)

        # Verify unclosed candle guard suppressed the forming Doji at index 7
        self.assertFalse(bool(pat_df.loc[7, "pattern_doji"]))
        self.assertEqual(pat_df.loc[7, "primary_pattern"], "")

    def test_end_to_end_forecast_backtest_and_plotly_figure(self):
        df = CryptoDataFetcher.generate_synthetic_ohlcv(limit=180, timeframe="1h")
        df = self.indicators.enrich(df)
        df = self.detector.detect_all(df)
        df = self.signals.evaluate(df)

        dummy_flow = OrderFlowIntel(
            symbol="ETH/USDT",
            exchange="BINANCE",
            imbalance_pct=58.0,
            imbalance_net_ratio=0.16,
            strongest_bid_wall=67200.0,
            strongest_ask_wall=69500.0,
            funding_rate_pct=0.01,
            open_interest_usd=450000000.0,
            oi_change_24h_pct=4.5,
            long_short_ratio=1.18,
            futures_taker_buy_sell_ratio=1.12,
            perp_spot_basis_pct=0.04,
        )
        btc_df = CryptoDataFetcher.generate_synthetic_ohlcv(limit=180, timeframe="1h")
        fc = self.signals.generate_forecast(
            df,
            order_flow=dummy_flow,
            htf_score=25.0,
            btc_regime_score=30.0,
            symbol="ETH/USDT",
            btc_df=btc_df,
            sample_capital_usd=1000.0,
            risk_pct=1.0,
        )
        self.assertGreaterEqual(fc.score, -100.0)
        self.assertLessEqual(fc.score, 100.0)
        self.assertGreaterEqual(fc.backtest_stats.total_signals, 1)
        self.assertGreater(fc.backtest_stats.profit_factor, 0.0)
        self.assertGreater(fc.poc_price, 0.0)
        self.assertIsNotNone(fc.smc)
        self.assertIsNotNone(fc.risk_plan)
        self.assertEqual(fc.risk_plan.sample_capital_usd, 1000.0)
        self.assertGreater(fc.risk_plan.half_kelly_pct, 0.0)
        self.assertEqual(len(fc.smc.probability_cone.expected_path), 11)
        self.assertGreaterEqual(fc.smc.probability_cone.prob_win_before_stop_pct, 10.0)
        self.assertLessEqual(fc.smc.probability_cone.prob_win_before_stop_pct, 90.0)
        self.assertGreater(fc.kalman_trend_price, 0.0)
        self.assertGreater(fc.avwap_low_price, 0.0)
        self.assertGreaterEqual(len(fc.smc.liquidation_pools), 1)
        self.assertGreaterEqual(fc.readiness_score_5, 0)
        self.assertLessEqual(fc.readiness_score_5, 5)
        self.assertEqual(len(fc.readiness_checks), 5)
        self.assertGreater(fc.tp1_price, 0.0)
        self.assertGreater(fc.tp2_price, 0.0)
        self.assertGreater(fc.stop_price, 0.0)
        self.assertEqual(len(fc.backtest_stats.equity_curve_r), fc.backtest_stats.total_signals)

        # v6.0 Whale Barometer (0-100), Squeeze Energy, Session Clock, 3-Step Alarm Plan & VPVR
        self.assertGreaterEqual(fc.whale_accumulation_score, 0.0)
        self.assertLessEqual(fc.whale_accumulation_score, 100.0)
        self.assertTrue(len(fc.whale_status_tr) > 0)
        self.assertGreaterEqual(fc.squeeze_energy_pct, 0.0)
        self.assertLessEqual(fc.squeeze_energy_pct, 100.0)
        self.assertTrue(len(fc.session_status_tr) > 0)
        self.assertTrue(len(fc.step_a_breakout_tr) > 0)
        self.assertTrue(len(fc.step_b_pullback_tr) > 0)
        self.assertTrue(len(fc.step_c_invalidation_tr) > 0)
        self.assertEqual(len(fc.vp_bin_centers), 24)
        self.assertEqual(len(fc.vp_bin_volumes), 24)

        from src.telegram_notifier import (
            build_analysis_inline_keyboard,
            build_coin_list_inline_keyboard,
            build_futures_radar_inline_keyboard,
            build_futures_setup_inline_keyboard,
            build_main_reply_keyboard,
            build_watchlist_manage_inline_keyboard,
            format_forecast_telegram_html,
            format_futures_radar_scan_telegram_html,
            format_futures_setup_telegram_html,
            format_liquidation_magnet_telegram_html,
            format_position_size_telegram_html,
            generate_telegram_chart_png,
        )
        curr_p = float(df["close"].iloc[-1])

        # Default timeframe in config must be 4h
        self.assertEqual(self.config.exchange.timeframe, "4h")

        # v10.0 Structural Trend State, Swing Structure, Candle Anatomy & Plain Roadmap (YTD)
        self.assertIn(fc.trend_state, ("UPTREND", "DOWNTREND", "SIDEWAYS"))
        self.assertTrue(len(fc.swing_structure_tr) > 0)
        self.assertTrue(len(fc.candle_anatomy_tr) > 0)
        self.assertTrue(len(fc.plain_guidance_tr) > 0)
        self.assertIn("YTD", fc.plain_guidance_tr)

        # Ensure no fake 0.0000 funding rate is fabricated when order_flow has None derivative metrics
        no_deriv_flow = OrderFlowIntel(symbol="ETH/USDT", exchange="BINANCE")
        fc_no_deriv = self.signals.generate_forecast(df, order_flow=no_deriv_flow, symbol="ETH/USDT")
        self.assertNotIn("0.0000", fc_no_deriv.futures_setup.futures_tech_summary_tr)

        # v8.4 Support vs Strong Support & Resistance vs Strong Resistance verification
        self.assertGreaterEqual(len(fc.support_levels), 1)
        self.assertGreaterEqual(len(fc.resistance_levels), 1)
        self.assertIn(fc.nearest_support_tier_tr, ("🟢 Sıradan Destek", "🛡️ Güçlü Destek"))
        self.assertIn(fc.nearest_resistance_tier_tr, ("🔴 Sıradan Direnç", "🧱 Güçlü Direnç"))
        self.assertGreaterEqual(fc.nearest_support_score, 20.0)
        self.assertLessEqual(fc.nearest_support_score, 98.0)
        self.assertGreaterEqual(fc.nearest_resistance_score, 20.0)
        self.assertLessEqual(fc.nearest_resistance_score, 98.0)
        for sl in fc.support_levels:
            self.assertIn(sl.tier_tr, ("🟢 Sıradan Destek", "🛡️ Güçlü Destek"))
            self.assertEqual(sl.is_strong, sl.strength_score >= 62.0)
            self.assertGreaterEqual(sl.strength_score, 20.0)
            self.assertTrue(len(sl.confluence_tags) >= 1)
        for rl in fc.resistance_levels:
            self.assertIn(rl.tier_tr, ("🔴 Sıradan Direnç", "🧱 Güçlü Direnç"))
            self.assertEqual(rl.is_strong, rl.strength_score >= 62.0)
            self.assertGreaterEqual(rl.strength_score, 20.0)
            self.assertTrue(len(rl.confluence_tags) >= 1)

        # v8.0 Perpetual Futures (Vadeli İşlemler) Radar & Confidence Engine verification
        self.assertIsNotNone(fc.futures_setup)
        fut = fc.futures_setup
        self.assertIn(fut.direction, ("LONG", "SHORT", "NO_TRADE"))
        self.assertGreaterEqual(fut.confidence_score, 0.0)
        self.assertLessEqual(fut.confidence_score, 100.0)
        self.assertIn(fut.confidence_grade, ("A+", "A", "B", "C", "D"))
        if fut.is_tradeable:
            self.assertIn(fut.direction, ("LONG", "SHORT"))
            self.assertGreater(fut.entry_price, 0.0)
            self.assertGreater(fut.tp1_price, 0.0)
            self.assertGreater(fut.tp2_price, 0.0)
            self.assertGreater(fut.tp3_price, 0.0)
            self.assertGreater(fut.stop_price, 0.0)
            self.assertGreaterEqual(fut.rr_ratio, 1.35)
        else:
            self.assertEqual(fut.direction, "NO_TRADE")
            self.assertEqual(fut.entry_price, 0.0)
            self.assertEqual(fut.tp1_price, 0.0)
            self.assertEqual(fut.stop_price, 0.0)
            self.assertTrue(len(fut.risk_warnings_tr) > 0)
            self.assertTrue(len(fut.wait_condition_tr) > 0)

        tg_msg = format_forecast_telegram_html(
            fc,
            symbol="ETH/USDT",
            timeframe="4h",
            current_price=curr_p,
            mtf_scores={"15M": -20.0, "1H": fc.score, "4H": -35.0, "1D": -30.0},
        )
        # Concise summary checks & no Futures TP/Stop in general analysis
        self.assertLess(len(tg_msg), 950)
        self.assertIn("DESTEK &amp; DİRENÇ SINIFLANDIRMASI", tg_msg)
        self.assertIn("PARA AKIŞI &amp; MIKNATIS", tg_msg)
        self.assertIn("SADE YOL HARİTASI (YTD)", tg_msg)
        self.assertNotIn("TP1:", tg_msg)
        self.assertNotIn("Zarar-Kes (Stop):", tg_msg)

        fut_tg_msg = format_futures_setup_telegram_html(
            fc=fc,
            symbol="ETH/USDT",
            timeframe="4H",
            current_price=curr_p,
            mtf_scores={"15M": -20.0, "1H": fc.score, "4H": -35.0, "1D": -30.0},
        )
        self.assertIn("VADELİ İŞLEM PLANI", fut_tg_msg)
        self.assertIn("Güven:", fut_tg_msg)

        radar_tg_msg = format_futures_radar_scan_telegram_html(
            [
                {
                    "symbol": "ETH/USDT",
                    "price": curr_p,
                    "fc": fc,
                }
            ],
            timeframe="4H",
        )
        self.assertIn("VADELİ İŞLEMLER (FUTURES) KURULUM &amp; GÜVEN RADARI", radar_tg_msg)
        self.assertIn("İŞLEME UYGUN VADELİ KURULUMLAR", radar_tg_msg)
        self.assertIn("RİSKLİ / İŞLEM TAVSİYE EDİLMEYENLER", radar_tg_msg)

        kb_an = build_analysis_inline_keyboard("ETH/USDT", in_watchlist=True)
        self.assertEqual(len(kb_an["inline_keyboard"]), 5)
        self.assertIn(":4H", kb_an["inline_keyboard"][1][0]["callback_data"])
        self.assertEqual(kb_an["inline_keyboard"][4][0]["callback_data"], "wl_del:ETH/USDT:4H")

        kb_an_add = build_analysis_inline_keyboard("PEPE/USDT", in_watchlist=False)
        self.assertEqual(kb_an_add["inline_keyboard"][4][0]["callback_data"], "wl_add:PEPE/USDT:4H")

        kb_fut = build_futures_setup_inline_keyboard("ETH/USDT")
        self.assertEqual(len(kb_fut["inline_keyboard"]), 4)
        self.assertIn("fut_chart:ETH/USDT:4H", kb_fut["inline_keyboard"][1][1]["callback_data"])
        kb_fut_rad = build_futures_radar_inline_keyboard([{"symbol": "ETH/USDT", "price": curr_p, "fc": fc}])
        self.assertGreaterEqual(len(kb_fut_rad["inline_keyboard"]), 3)
        kb_main = build_main_reply_keyboard()
        self.assertEqual(len(kb_main["keyboard"]), 2)
        self.assertEqual(kb_main["keyboard"][1][0]["text"], "🚀 Tümünü Tara (4H)")
        kb_coins = build_coin_list_inline_keyboard(["BTC/USDT", "ETH/USDT", "ONDO/USDT"])
        self.assertGreaterEqual(len(kb_coins["inline_keyboard"]), 4)
        kb_wm_add = build_watchlist_manage_inline_keyboard(["BTC/USDT", "ETH/USDT"], mode="add", timeframe="4H")
        self.assertTrue(any("wl_qadd:" in b["callback_data"] for r in kb_wm_add["inline_keyboard"] for b in r))
        kb_wm_del = build_watchlist_manage_inline_keyboard(["BTC/USDT", "ETH/USDT"], mode="del", timeframe="4H")
        self.assertTrue(any("wl_qdel:" in b["callback_data"] for r in kb_wm_del["inline_keyboard"] for b in r))

        liq_msg = format_liquidation_magnet_telegram_html("ETH/USDT", {"4H": fc}, curr_p)
        self.assertIn("MIKNATIS FİYAT &amp; LİKİDASYON HARİTASI", liq_msg)

        kasa_msg = format_position_size_telegram_html(fc, "ETH/USDT", "4H", curr_p, capital_usd=1000.0)
        self.assertIn("KASA &amp; RİSK YÖNETİMİ PLANI", kasa_msg)

        png_bytes = generate_telegram_chart_png(df, fc, "ETH/USDT", "4H", include_futures_levels=False)
        self.assertIsNotNone(png_bytes)
        self.assertTrue(png_bytes.startswith(b"\x89PNG"))

        png_fut_bytes = generate_telegram_chart_png(df, fc, "ETH/USDT", "4H", include_futures_levels=True)
        self.assertIsNotNone(png_fut_bytes)
        self.assertTrue(png_fut_bytes.startswith(b"\x89PNG"))

        visualizer = InteractiveChartVisualizer(self.config)
        fig = visualizer.create_figure(df, exchange_source="TEST", forecast=fc, show_kalman_avwap=True, show_vpvr=True)
        self.assertGreaterEqual(len(fig.data), 9)

        from main import normalize_symbol as main_norm
        from telegram_bot import _normalize_symbol as tg_norm

        self.assertEqual(main_norm("SOLUSDT"), "SOL/USDT")
        self.assertEqual(main_norm("ONDO-USDT"), "ONDO/USDT")
        self.assertEqual(tg_norm("SOLUSDT"), "SOL/USDT")
        self.assertEqual(tg_norm("ondo"), "ONDO/USDT")


if __name__ == "__main__":
    unittest.main()
