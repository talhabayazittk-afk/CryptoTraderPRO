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

        # v11.0 X (Twitter) Auto-Publisher, OAuth 1.0a Signer & 280-char Tweet Formatters verification
        from src.x_publisher import (
            _build_oauth1_header,
            fit_x_text_280,
            format_breakout_radar_x_post,
            format_coin_analysis_x_post,
            format_futures_radar_x_post,
            format_futures_setup_x_post,
            format_market_overview_x_post,
            format_radar_alert_x_post,
            format_screener_x_post,
            x_weighted_length,
        )

        # Verify OAuth 1.0a HMAC-SHA1 header generation
        oauth_hdr = _build_oauth1_header(
            method="POST",
            url="https://api.twitter.com/2/tweets",
            api_key="test_ck",
            api_secret="test_cs",
            access_token="test_at",
            access_token_secret="test_as",
        )
        self.assertTrue(oauth_hdr.startswith("OAuth "))
        self.assertIn('oauth_consumer_key="test_ck"', oauth_hdr)
        self.assertIn('oauth_signature_method="HMAC-SHA1"', oauth_hdr)
        self.assertIn("oauth_signature=", oauth_hdr)

        # Verify SHORT_280 single-tweet mode strictly obeys 280 weighted chars
        x_short = format_coin_analysis_x_post(
            fc,
            symbol="ETH/USDT",
            timeframe="4H",
            current_price=curr_p,
            mtf_scores={"15M": 10.0, "1H": 20.0, "4H": fc.score, "1D": 30.0},
            mode="SHORT_280",
        )
        self.assertEqual(len(x_short), 1)
        self.assertIn("$ETH", x_short[0])
        self.assertIn("YTD", x_short[0])
        self.assertLessEqual(x_weighted_length(x_short[0]), 280)

        # Verify THREAD (2-tweet flood) mode
        x_thread = format_coin_analysis_x_post(
            fc,
            symbol="ETH/USDT",
            timeframe="4H",
            current_price=curr_p,
            mtf_scores={"15M": 10.0, "1H": 20.0, "4H": fc.score, "1D": 30.0},
            mode="THREAD",
        )
        self.assertEqual(len(x_thread), 2)
        self.assertLessEqual(x_weighted_length(x_thread[0]), 280)
        self.assertLessEqual(x_weighted_length(x_thread[1]), 280)

        # Verify Futures, Radar Alert, Screener, Breakout & Market Overview X formatters
        x_fut = format_futures_setup_x_post(fc, "ETH/USDT", "4H", curr_p, mode="SHORT_280")
        self.assertEqual(len(x_fut), 1)
        self.assertLessEqual(x_weighted_length(x_fut[0]), 280)

        x_rad = format_radar_alert_x_post(
            "ETH/USDT",
            "4H",
            curr_p,
            fc,
            reasons=["🚀 Direnç kırılımı gerçekleşti", "🐋 Balina girişi: 75/100"],
            header_title="🚀 DİRENÇ KIRILIMI GELDİ: ETH/USDT [4H]",
            mode="SHORT_280",
        )
        self.assertEqual(len(x_rad), 1)
        self.assertLessEqual(x_weighted_length(x_rad[0]), 280)

        sample_rows = [
            {
                "Coin": "ETH/USDT",
                "symbol": "ETH/USDT",
                "price": curr_p,
                "price_str": f"{curr_p:,.2f}",
                "score": fc.score,
                "ready": fc.readiness_score_5,
                "whale": fc.whale_accumulation_score,
                "cmf": fc.cmf_value,
                "delta_str": "+1.2M$",
                "fc": fc,
                "_fc_4h": fc,
                "_raw_price": curr_p,
            }
        ]
        x_scr = format_screener_x_post(sample_rows, "4H", False, mode="SHORT_280")
        self.assertLessEqual(x_weighted_length(x_scr[0]), 280)
        x_brk = format_breakout_radar_x_post(sample_rows, "4H", mode="SHORT_280")
        self.assertLessEqual(x_weighted_length(x_brk[0]), 280)
        x_frad = format_futures_radar_x_post(sample_rows, "4H", mode="SHORT_280")
        self.assertLessEqual(x_weighted_length(x_frad[0]), 280)
        x_mkt = format_market_overview_x_post(sample_rows, "Avrupa & Londra Seansı", "4H", mode="SHORT_280")
        self.assertLessEqual(x_weighted_length(x_mkt[0]), 280)
        self.assertLessEqual(x_weighted_length(fit_x_text_280("🚀" * 200, 278)), 280)
        self.assertEqual(kb_an["inline_keyboard"][3][2]["callback_data"], "x_post:ETH/USDT:4H")
        self.assertEqual(kb_fut["inline_keyboard"][2][2]["callback_data"], "x_fut:ETH/USDT:4H")

    def test_phase1_zero_hallucination_and_no_repaint(self):
        import inspect
        import numpy as np

        # 1. Verify 500-bar warmup default & synthetic fallback disabled by default
        self.assertEqual(self.config.exchange.limit, 500)
        sig_fetch = inspect.signature(CryptoDataFetcher.fetch_ohlcv)
        self.assertFalse(sig_fetch.parameters["allow_synthetic_fallback"].default)
        sig_mtf = inspect.signature(CryptoDataFetcher.fetch_multi_timeframe_parallel)
        self.assertFalse(sig_mtf.parameters["allow_synthetic_fallback"].default)

        # 2. Verify DataIntegrityGuard catches stale feeds and dead/zero-volume books
        base_df = CryptoDataFetcher.generate_synthetic_ohlcv(limit=300, timeframe="4h")
        clean_df, rep_ok = CryptoDataFetcher.validate_ohlcv_integrity(
            base_df, timeframe="4h", source_exchange="BINANCE", check_staleness=False
        )
        self.assertTrue(rep_ok.is_healthy)
        self.assertTrue(rep_ok.has_warmup_bars)

        stale_df = base_df.copy()
        stale_df["timestamp"] = stale_df["timestamp"] - timedelta(days=10)
        _, rep_stale = CryptoDataFetcher.validate_ohlcv_integrity(
            stale_df, timeframe="4h", source_exchange="BINANCE", check_staleness=True
        )
        self.assertTrue(rep_stale.is_stale)
        self.assertFalse(rep_stale.is_healthy)

        dead_df = base_df.copy()
        dead_df.loc[dead_df.index[-8:], "volume"] = 0.0
        _, rep_dead = CryptoDataFetcher.validate_ohlcv_integrity(
            dead_df, timeframe="4h", source_exchange="BINANCE", check_staleness=False
        )
        self.assertFalse(rep_dead.is_healthy)

        # 3. Verify Zero Look-Ahead Bias in Anchored VWAP (pre-anchor bars must be NaN, not backfilled)
        avwap_df = self.indicators.compute_anchored_vwap(base_df, lookback=60)
        # Since lookback=60 on a 300-bar series, anchors are at index >= 240; index 0..239 must be NaN!
        self.assertTrue(np.isnan(avwap_df["avwap_high"].iloc[0]))
        self.assertTrue(np.isnan(avwap_df["avwap_low"].iloc[0]))
        self.assertFalse(np.isnan(avwap_df["avwap_high"].iloc[-1]))
        self.assertFalse(np.isnan(avwap_df["avwap_low"].iloc[-1]))

        # 4. Verify Zero Repainting when unclosed live candle (is_closed=False) has extreme wicks
        df_spike_up = base_df.copy()
        df_spike_up["is_closed"] = True
        df_spike_up.loc[df_spike_up.index[-1], "is_closed"] = False
        df_spike_up.loc[df_spike_up.index[-1], "high"] = float(df_spike_up["high"].max()) * 1.40

        df_spike_dn = base_df.copy()
        df_spike_dn["is_closed"] = True
        df_spike_dn.loc[df_spike_dn.index[-1], "is_closed"] = False
        df_spike_dn.loc[df_spike_dn.index[-1], "low"] = float(df_spike_dn["low"].min()) * 0.60

        enr_up = self.signals.evaluate(self.detector.detect_all(self.indicators.enrich(df_spike_up)))
        enr_dn = self.signals.evaluate(self.detector.detect_all(self.indicators.enrich(df_spike_dn)))

        # Closed-candle indicators & Volume Profile POC/VAH/VAL must be 100% identical despite wild unclosed wicks!
        self.assertAlmostEqual(float(enr_up["vp_poc"].iloc[-2]), float(enr_dn["vp_poc"].iloc[-2]), places=8)
        self.assertAlmostEqual(float(enr_up["vp_vah"].iloc[-2]), float(enr_dn["vp_vah"].iloc[-2]), places=8)
        self.assertAlmostEqual(float(enr_up["vp_val"].iloc[-2]), float(enr_dn["vp_val"].iloc[-2]), places=8)
        self.assertAlmostEqual(float(enr_up["ema_200"].iloc[-2]), float(enr_dn["ema_200"].iloc[-2]), places=8)
        self.assertAlmostEqual(float(enr_up["rsi"].iloc[-2]), float(enr_dn["rsi"].iloc[-2]), places=8)
        self.assertEqual(int(enr_up["supertrend_dir"].iloc[-2]), int(enr_dn["supertrend_dir"].iloc[-2]))
        self.assertAlmostEqual(float(enr_up["avwap_high"].iloc[-2]), float(enr_dn["avwap_high"].iloc[-2]), places=8)

        fc_up = self.signals.generate_forecast(enr_up, symbol="BTC/USDT")
        fc_dn = self.signals.generate_forecast(enr_dn, symbol="BTC/USDT")
        self.assertAlmostEqual(fc_up.fib_618_price, fc_dn.fib_618_price, places=8)
        self.assertAlmostEqual(fc_up.poc_price, fc_dn.poc_price, places=8)

        # 5. Verify Timestamp-Aligned BTC Relative Strength
        btc_shifted = base_df.iloc[:-3].copy()  # BTC missing last 3 bars -> timestamp merge aligns exact matching bars
        rs = SmartMoneyEngine.compute_relative_strength_vs_btc(base_df, btc_shifted, "ETH/USDT", lookback=30)
        self.assertAlmostEqual(rs.correlation_vs_btc, 1.0, places=5)
        self.assertAlmostEqual(rs.rs_ratio_change_pct, 0.0, places=5)

    def test_phase2_cashflow_zscore_spoofing_and_macro_compass(self):
        from src.data_fetcher import (
            MacroLiquidityIntel,
            _extract_standardized_1h_4h_24h_deltas,
            _merge_dual_probe_depth,
        )

        # 1. Dual-Probe Anti-Spoofing Verification
        probe1 = [[100.0, 10.0], [99.5, 200.0]]  # 99.5 has a huge flash spoof wall of 200 units ($19,900)
        probe2 = [[100.0, 10.0]]                 # 160ms later, the 99.5 wall vanished!
        verified_lvls, cancel_pct = _merge_dual_probe_depth(probe1, probe2)
        lvl_dict = dict(verified_lvls)
        self.assertEqual(lvl_dict[100.0], 10.0)
        self.assertAlmostEqual(lvl_dict[99.5], 50.0)  # Discounted by 75%
        self.assertGreater(cancel_pct, 60.0)

        # 2. Standardized 1H / 4H / 24H Closed-Candle Taker Delta Extraction
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        fake_1h_klines = []
        for k in range(25):
            open_ms = now_ms - (25 - k) * 3_600_000
            close_ms = open_ms + 3_599_999 if k < 24 else now_ms + 1_800_000  # last bar unclosed!
            # Closed bars: quote_vol=1000, taker_buy=600 -> taker_sell=400 -> net=+200$/h
            # Unclosed bar (k=24): huge fake spike +999999$ that MUST be ignored!
            q_vol = 1000.0 if k < 24 else 1_000_000.0
            tb_vol = 600.0 if k < 24 else 999_999.0
            fake_1h_klines.append([open_ms, 1, 2, 0.5, 1.5, 100, close_ms, q_vol, 50, 60, tb_vol, 0])

        d1h, d4h, d24h = _extract_standardized_1h_4h_24h_deltas(fake_1h_klines)
        self.assertAlmostEqual(d1h, 200.0, places=4)
        self.assertAlmostEqual(d4h, 800.0, places=4)
        self.assertAlmostEqual(d24h, 4800.0, places=4)

        # 3. Statistical Cash-Flow Z-Score Anomaly Detection
        df = CryptoDataFetcher.generate_synthetic_ohlcv(limit=120, timeframe="4h")
        df["real_net_delta_usd"] = 10_000.0
        df.loc[df.index[-3:], "real_net_delta_usd"] = 500_000.0  # Massive 3-bar whale inflow anomaly
        enr = self.signals.evaluate(self.detector.detect_all(self.indicators.enrich(df)))
        self.assertGreater(float(enr["delta_zscore"].iloc[-1]), 2.0)
        self.assertGreater(float(enr["flow_impulse_z"].iloc[-1]), 2.0)

        # 4. Spot vs. Perp Foam (Bull Trap) vs. Short Squeeze Fuel & Macro Liquidity Filter
        foam_flow = OrderFlowIntel(
            symbol="ONDO/USDT",
            exchange="BINANCE",
            spot_delta_1h_usd=-500_000.0,
            spot_delta_4h_usd=-2_200_000.0,
            spot_delta_24h_usd=-6_000_000.0,
            perp_delta_4h_usd=4_500_000.0,
            perp_cvd_delta_24h_usd=12_000_000.0,
            funding_rate_pct=0.035,
            oi_weighted_funding_pct=0.035,
            oi_change_24h_pct=6.5,
            futures_taker_buy_sell_ratio=1.12,
            macro_liquidity=MacroLiquidityIntel(
                btc_dominance_pct=60.2,
                usdt_dominance_pct=8.4,
                altcoin_season_bias=-12.0,
                regime_code="CASH_FLIGHT",
                summary_tr="🔴 Nakde (USDT) Kaçış",
            ),
        )
        squeeze_flow = OrderFlowIntel(
            symbol="ONDO/USDT",
            exchange="BINANCE",
            spot_delta_1h_usd=800_000.0,
            spot_delta_4h_usd=3_100_000.0,
            spot_delta_24h_usd=9_500_000.0,
            perp_delta_4h_usd=-1_000_000.0,
            funding_rate_pct=-0.018,
            oi_weighted_funding_pct=-0.018,
            oi_change_24h_pct=2.0,
            futures_taker_buy_sell_ratio=0.94,
            macro_liquidity=MacroLiquidityIntel(
                btc_dominance_pct=57.5,
                usdt_dominance_pct=7.1,
                altcoin_season_bias=12.0,
                regime_code="ALT_INFLOW",
                summary_tr="🟢 Altcoinlere Para Girişi",
            ),
        )

        fc_foam = self.signals.generate_forecast(enr, order_flow=foam_flow, symbol="ONDO/USDT")
        fc_sqz = self.signals.generate_forecast(enr, order_flow=squeeze_flow, symbol="ONDO/USDT")

        self.assertIn("KALDIRAÇ KÖPÜĞÜ", fc_foam.spot_perp_quality_tr)
        self.assertIn("Short Squeeze", fc_sqz.spot_perp_quality_tr)
        self.assertGreater(fc_sqz.money_flow_score, fc_foam.money_flow_score + 15.0)
        self.assertGreater(fc_sqz.macro_htf_score, fc_foam.macro_htf_score + 15.0)


if __name__ == "__main__":
    unittest.main()
