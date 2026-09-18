"""
Unit tests for Risk Engine.
Verifies trade decisions, direction conflict logic, volume & z-score gating,
position sizing, stop loss calculation, portfolio safety limits, and signal formatting.
"""

import unittest
import sys
import os
from typing import Optional

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from divergence_engine import DivergenceResult
from risk_engine import evaluate_trade, PortfolioState, RiskEvaluation
import config


def make_sample_divergence(
    z_score: float = 2.5,
    actual_move: float = 0.04,
    volume_ratio: float = 0.3,
    volume_confirmation: str = "weak",
    liquidity_condition: Optional[str] = None
) -> DivergenceResult:
    """Helper to generate DivergenceResult for testing."""
    kwargs = {}
    if liquidity_condition is not None:
        kwargs["liquidity_condition"] = liquidity_condition
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
        volume_confirmation=volume_confirmation,
        **kwargs
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

    def test_earnings_momentum_long(self):
        # Bullish earnings beat + positive price move (+3.5%) + confirming volume (1.2 >= 0.8) + |z| = 2.5 -> LONG
        div = make_sample_divergence(
            z_score=2.5,
            actual_move=0.035,
            volume_ratio=1.2,
            volume_confirmation="confirming",
            liquidity_condition="CONFIRMING_VOLUME"
        )
        state = PortfolioState(portfolio_balance=100_000.0)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="bullish",
            qwen_reasoning="Strong Q3 earnings beat with datacenter revenue surge.",
            current_price=100.0,
            portfolio_state=state,
            event_type="earnings"
        )

        self.assertEqual(eval_res.strategy_mode, "MOMENTUM")
        self.assertEqual(eval_res.decision, "LONG")
        self.assertEqual(eval_res.signals_aligned, "3/3 signals aligned")
        self.assertEqual(eval_res.aligned_count, 3)
        self.assertEqual(eval_res.direction_alignment, "ALIGNMENT")
        self.assertEqual(eval_res.position_size_usd, 3000.0)
        self.assertEqual(eval_res.entry_price, 100.0)
        # Stop loss for LONG: entry * (1 - 0.015) = 98.5
        self.assertAlmostEqual(eval_res.stop_price, 98.5, places=2)
        self.assertIn("MOMENTUM/PEAD", eval_res.reason)

    def test_earnings_momentum_short(self):
        # Bearish earnings miss + negative price move (-3.5%) + confirming volume (1.1 >= 0.8) + |z| = 2.5 -> SHORT
        div = make_sample_divergence(
            z_score=-2.5,
            actual_move=-0.035,
            volume_ratio=1.1,
            volume_confirmation="confirming",
            liquidity_condition="CONFIRMING_VOLUME"
        )
        state = PortfolioState(portfolio_balance=100_000.0)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="bearish",
            qwen_reasoning="Severe revenue miss and lowered guidance across all business lines.",
            current_price=100.0,
            portfolio_state=state,
            event_type="earnings"
        )

        self.assertEqual(eval_res.strategy_mode, "MOMENTUM")
        self.assertEqual(eval_res.decision, "SHORT")
        self.assertEqual(eval_res.signals_aligned, "3/3 signals aligned")
        self.assertEqual(eval_res.aligned_count, 3)
        self.assertEqual(eval_res.direction_alignment, "ALIGNMENT")
        self.assertEqual(eval_res.position_size_usd, 3000.0)
        self.assertEqual(eval_res.entry_price, 100.0)
        # Stop loss for SHORT: entry * (1 + 0.015) = 101.5
        self.assertAlmostEqual(eval_res.stop_price, 101.5, places=2)
        self.assertIn("MOMENTUM/PEAD", eval_res.reason)

    def test_earnings_alignment_rejected_when_volume_not_confirming(self):
        # Bullish earnings + positive move, but weak volume (0.35 < 0.8) -> NO_TRADE
        div = make_sample_divergence(
            z_score=2.5,
            actual_move=0.035,
            volume_ratio=0.35,
            volume_confirmation="weak",
            liquidity_condition="WEAK_LIQUIDITY"
        )
        state = PortfolioState(portfolio_balance=100_000.0)

        eval_res = evaluate_trade(
            divergence=div,
            qwen_direction="bullish",
            qwen_reasoning="Earnings beat with light trading volume.",
            current_price=100.0,
            portfolio_state=state,
            event_type="earnings"
        )

        self.assertEqual(eval_res.strategy_mode, "MOMENTUM")
        self.assertEqual(eval_res.decision, "NO_TRADE")
        self.assertEqual(eval_res.signals_aligned, "2/3 signals aligned")
        self.assertTrue(any("Volume confirmation failed" in c for c in eval_res.failed_conditions))

    def test_regression_macro_event_requires_contradiction_and_weak_liquidity(self):
        # Proves non-earnings (macro/geopolitical) still requires CONTRADICTION and WEAK_LIQUIDITY
        state = PortfolioState(portfolio_balance=100_000.0)

        # Case A: Macro event with aligned price and high volume -> NO_TRADE (cannot trade momentum in macro)
        div_aligned = make_sample_divergence(
            z_score=2.8,
            actual_move=0.04,
            volume_ratio=1.2,
            volume_confirmation="confirming",
            liquidity_condition="CONFIRMING_VOLUME"
        )
        res_aligned = evaluate_trade(
            divergence=div_aligned,
            qwen_direction="bullish",
            qwen_reasoning="Broad economic stimulus package passed.",
            current_price=100.0,
            portfolio_state=state,
            event_type="macro"
        )
        self.assertEqual(res_aligned.strategy_mode, "MEAN_REVERSION")
        self.assertEqual(res_aligned.decision, "NO_TRADE")
        self.assertTrue(any("Direction alignment confirmed" in c for c in res_aligned.failed_conditions))

        # Case B: Macro event with contradiction on weak liquidity -> SHORT (valid fade)
        div_fade = make_sample_divergence(
            z_score=2.8,
            actual_move=0.04,
            volume_ratio=0.3,
            volume_confirmation="weak",
            liquidity_condition="WEAK_LIQUIDITY"
        )
        res_fade = evaluate_trade(
            divergence=div_fade,
            qwen_direction="bearish",
            qwen_reasoning="Emergency interest rate hike and credit tightening.",
            current_price=100.0,
            portfolio_state=state,
            event_type="geopolitical"
        )
        self.assertEqual(res_fade.strategy_mode, "MEAN_REVERSION")
        self.assertEqual(res_fade.decision, "SHORT")
        self.assertEqual(res_fade.signals_aligned, "3/3 signals aligned")


if __name__ == "__main__":
    unittest.main()

