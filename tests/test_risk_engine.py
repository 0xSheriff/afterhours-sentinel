"""
Unit tests for Risk Engine.
Verifies trade decisions, direction conflict logic, volume & z-score gating,
position sizing, stop loss calculation, portfolio safety limits, and signal formatting.
"""

import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from divergence_engine import DivergenceResult
from risk_engine import evaluate_trade, PortfolioState, RiskEvaluation
import config


def make_sample_divergence(
    z_score: float = 2.5,
    actual_move: float = 0.04,
    volume_ratio: float = 0.3,
    volume_confirmation: str = "weak"
) -> DivergenceResult:
    """Helper to generate DivergenceResult for testing."""
    return DivergenceResult(
        asset="NVDA",
        benchmark="QQQ",
        beta=1.5,
        benchmark_move=0.005,
        expected_move=0.0075,
        actual_move=actual_move,
        residual=actual_move - 0.0075,
        residual_stdev=0.01,
        z_score=z_score,
        after_hours_volume=volume_ratio * 1000.0,
        trailing_avg_volume=1000.0,
        volume_ratio=volume_ratio,
        volume_confirmation=volume_confirmation
    )


class TestRiskEngine(unittest.TestCase):
    def test_clean_trade_candidate_short(self):
        # Bearish event, price moved up +4%, weak volume, z-score 2.8 -> SHORT
        div = make_sample_divergence(z_score=2.8, actual_move=0.04, volume_ratio=0.3, volume_confirmation="weak")
        state = PortfolioState(portfolio_balance=100_000.0, open_positions_count=0, daily_realized_loss_pct=0.0)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="bearish",
            qwen_reasoning="Macro tariff escalations significantly impair semiconductor supply chain.",
            current_price=120.0,
            portfolio_state=state
        )

        self.assertEqual(eval_res.decision, "SHORT")
        self.assertEqual(eval_res.signals_aligned, "3/3 signals aligned")
        self.assertEqual(eval_res.aligned_count, 3)
        self.assertEqual(len(eval_res.failed_conditions), 0)
        # Position size = 3% of 100,000 = 3,000 USD
        self.assertEqual(eval_res.position_size_usd, 3000.0)
        self.assertEqual(eval_res.entry_price, 120.0)
        # Stop loss for SHORT = entry * (1 + 0.015) = 120 * 1.015 = 121.8
        self.assertAlmostEqual(eval_res.stop_price, 121.8, places=2)

    def test_clean_trade_candidate_long(self):
        # Bullish event, price moved down -3.5%, weak volume, z-score -2.5 -> LONG
        div = make_sample_divergence(z_score=-2.5, actual_move=-0.035, volume_ratio=0.25, volume_confirmation="weak")
        state = PortfolioState(portfolio_balance=50_000.0, open_positions_count=1, daily_realized_loss_pct=0.005)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="bullish",
            qwen_reasoning="Unexpectedly strong cloud revenue beat and raised full-year forward guidance.",
            current_price=200.0,
            portfolio_state=state
        )

        self.assertEqual(eval_res.decision, "LONG")
        self.assertEqual(eval_res.signals_aligned, "3/3 signals aligned")
        self.assertEqual(eval_res.aligned_count, 3)
        # Position size = 3% of 50,000 = 1,500 USD
        self.assertEqual(eval_res.position_size_usd, 1500.0)
        self.assertEqual(eval_res.entry_price, 200.0)
        # Stop loss for LONG = entry * (1 - 0.015) = 200 * 0.985 = 197.0
        self.assertAlmostEqual(eval_res.stop_price, 197.0, places=2)

    def test_failed_volume_confirmation(self):
        # High volume (ratio 0.8 >= 0.5) -> volume confirmation is "normal" -> NO_TRADE
        div = make_sample_divergence(z_score=2.8, actual_move=0.04, volume_ratio=0.8, volume_confirmation="normal")
        state = PortfolioState(portfolio_balance=100_000.0)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="bearish",
            qwen_reasoning="Bearish export controls announced.",
            current_price=100.0,
            portfolio_state=state
        )

        self.assertEqual(eval_res.decision, "NO_TRADE")
        self.assertEqual(eval_res.signals_aligned, "2/3 signals aligned")
        self.assertEqual(eval_res.aligned_count, 2)
        self.assertTrue(any("Volume confirmation failed" in c for c in eval_res.failed_conditions))
        self.assertEqual(eval_res.position_size_usd, 0.0)
        self.assertEqual(eval_res.stop_price, 0.0)

    def test_failed_z_score_threshold(self):
        # Low z-score (1.2 <= 2.0) -> NO_TRADE
        div = make_sample_divergence(z_score=1.2, actual_move=0.01, volume_ratio=0.3, volume_confirmation="weak")
        state = PortfolioState(portfolio_balance=100_000.0)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="bearish",
            qwen_reasoning="Bearish export controls announced.",
            current_price=100.0,
            portfolio_state=state
        )

        self.assertEqual(eval_res.decision, "NO_TRADE")
        self.assertEqual(eval_res.signals_aligned, "2/3 signals aligned")
        self.assertTrue(any("Z-score threshold failed" in c for c in eval_res.failed_conditions))

    def test_direction_agreement_no_trade(self):
        # Bearish event AND price moved down -4% (agreement) -> NO_TRADE
        div = make_sample_divergence(z_score=-2.8, actual_move=-0.04, volume_ratio=0.3, volume_confirmation="weak")
        state = PortfolioState(portfolio_balance=100_000.0)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="bearish",
            qwen_reasoning="Bearish quarterly miss.",
            current_price=100.0,
            portfolio_state=state
        )

        self.assertEqual(eval_res.decision, "NO_TRADE")
        self.assertEqual(eval_res.signals_aligned, "2/3 signals aligned")
        self.assertTrue(any("agrees with price move" in c for c in eval_res.failed_conditions))

    def test_neutral_event_no_trade(self):
        # Neutral event -> NO_TRADE
        div = make_sample_divergence(z_score=2.8, actual_move=0.04, volume_ratio=0.3, volume_confirmation="weak")
        state = PortfolioState(portfolio_balance=100_000.0)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="neutral",
            qwen_reasoning="In-line economic data release with no directional bias.",
            current_price=100.0,
            portfolio_state=state
        )

        self.assertEqual(eval_res.decision, "NO_TRADE")
        self.assertTrue(any("neutral" in c for c in eval_res.failed_conditions))

    def test_daily_loss_limit_halts_trades(self):
        # 3 signals pass, but daily loss limit (2.1% >= 2.0%) reached -> NO_TRADE
        div = make_sample_divergence(z_score=2.8, actual_move=0.04, volume_ratio=0.3, volume_confirmation="weak")
        state = PortfolioState(portfolio_balance=100_000.0, open_positions_count=0, daily_realized_loss_pct=0.021)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="bearish",
            qwen_reasoning="Bearish guidance.",
            current_price=100.0,
            portfolio_state=state
        )

        self.assertEqual(eval_res.decision, "NO_TRADE")
        self.assertTrue(any("Daily loss limit reached" in c for c in eval_res.failed_conditions))

    def test_max_open_positions_halts_trades(self):
        # 3 signals pass, but already 2 open positions -> NO_TRADE
        div = make_sample_divergence(z_score=2.8, actual_move=0.04, volume_ratio=0.3, volume_confirmation="weak")
        state = PortfolioState(portfolio_balance=100_000.0, open_positions_count=2, daily_realized_loss_pct=0.0)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="bearish",
            qwen_reasoning="Bearish guidance.",
            current_price=100.0,
            portfolio_state=state
        )

        self.assertEqual(eval_res.decision, "NO_TRADE")
        self.assertTrue(any("Max open positions reached" in c for c in eval_res.failed_conditions))


if __name__ == "__main__":
    unittest.main()
