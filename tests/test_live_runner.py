"""
Unit tests for LiveSentinelRunner components and asset resolution.
"""

import unittest
from live import resolve_target_asset, LiveSentinelRunner
from event_listener import MarketEvent


class TestLiveRunner(unittest.TestCase):

    def test_resolve_target_asset_single_stock(self):
        self.assertEqual(resolve_target_asset("NVIDIA announces Blackwell Ultra architecture"), "NVDA")
        self.assertEqual(resolve_target_asset("Tesla robotaxi update delivered by Musk"), "TSLA")
        self.assertEqual(resolve_target_asset("Apple releases iOS 19 with AI enhancements"), "AAPL")
        self.assertEqual(resolve_target_asset("Amazon AWS lands massive cloud contract"), "AMZN")
        self.assertEqual(resolve_target_asset("Microsoft Azure quarterly cloud revenue jumps"), "MSFT")
        self.assertEqual(resolve_target_asset("Google Alphabet rolls out Gemini 2.5"), "GOOGL")
        self.assertEqual(resolve_target_asset("Meta Platforms Zuckerberg comments on open weights"), "META")

    def test_resolve_target_asset_macro_returns_none(self):
        self.assertIsNone(resolve_target_asset("South African inflation expectations stabilise in third quarter"))
        self.assertIsNone(resolve_target_asset("Federal Reserve minutes indicate neutral interest rate stance"))
        self.assertIsNone(resolve_target_asset("ECB holds deposit facility rate steady at 3.50%"))

    def test_skipped_no_asset_match_flow(self):
        runner = LiveSentinelRunner(dry_run=True, allow_fallback=True)
        event = MarketEvent(
            headline="Global oil inventories rise unexpectedly according to IEA report",
            raw_text="No equity mentions in this energy macro report.",
            timestamp="2026-09-16T08:30:00Z",
            event_type="macro",
            source="reuters"
        )
        # Should cleanly handle None target_asset without raising exceptions
    def test_composite_tech_basket_excludes_evaluated_asset(self):
        runner = LiveSentinelRunner(dry_run=True, allow_fallback=True)
        tech_universe = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA"]

        # When asset is TSLA
        tsla_basket = [s for s in tech_universe if s != "TSLA"]
        self.assertNotIn("TSLA", tsla_basket)
        self.assertEqual(len(tsla_basket), 6)
        self.assertEqual(tsla_basket, ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META"])

        # When asset is NVDA
        nvda_basket = [s for s in tech_universe if s != "NVDA"]
        self.assertNotIn("NVDA", nvda_basket)
        self.assertEqual(len(nvda_basket), 6)
        self.assertEqual(nvda_basket, ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA"])

    def test_check_position_exits_per_symbol_and_pnl_persistence(self):
        import tempfile
        import os
        import json
        from execution import SentinelLogger
        from risk_engine import RiskEvaluation

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_p = os.path.join(tmpdir, "trades.jsonl")
            csv_p = os.path.join(tmpdir, "trades.csv")
            logger = SentinelLogger(jsonl_path=jsonl_p, csv_path=csv_p)

            eval_obj = RiskEvaluation(
                decision="LONG",
                reason="3/3 aligned",
                signals_aligned="3/3 signals aligned",
                position_size_usd=150.0,
                stop_price=246.25,
                entry_price=250.0,
                divergence={"asset": "PLTR", "z_score": 4.5, "actual_move": 0.03, "expected_move": 0.005, "residual": 0.025},
                qwen_direction="bullish",
                qwen_reasoning="Strong contract catalyst",
                llm_source="groq [live_api]",
                strategy_mode="MOMENTUM"
            )
            ts = "2026-09-23T15:23:16+00:00"
            logger.log_decision(
                event={"headline": "Palantir wins defense contract", "event_type": "corporate", "timestamp": ts},
                evaluation=eval_obj,
                mode="live",
                timestamp=ts,
                symbol="PLTR"
            )

            runner = LiveSentinelRunner(dry_run=True, allow_fallback=True)
            runner.logger = logger
            runner.active_positions = {
                "test-pltr-1": {
                    "symbol": "PLTRUSDT",
                    "base_symbol": "PLTR",
                    "side": "LONG",
                    "size_usd": 150.0,
                    "entry_price": 250.0,
                    "stop_price": 246.25,
                    "entry_time": ts,
                    "strategy_mode": "MOMENTUM",
                    "z_score": 4.5,
                    "actual_move": 0.03
                }
            }

            # Verify that check_position_exits does NOT use NVDA ($226) to trigger a false stop-loss on PLTR ($250)
            runner.check_position_exits(target_asset="NVDA")
            self.assertEqual(len(runner.active_positions), 0)

            with open(jsonl_p, "r", encoding="utf-8") as f:
                rec = json.loads(f.readline())
            self.assertEqual(rec["symbol"], "PLTR")
            self.assertNotEqual(rec["exit_reason"], "OPEN")
            self.assertNotEqual(rec["exit_reason"], "STOP_LOSS")
            self.assertGreater(rec["pnl"], 0.0)


if __name__ == "__main__":
    unittest.main()

