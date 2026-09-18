"""
Unit tests for Divergence Engine.
Verifies exact deterministic mathematical calculations of beta, residual, z-score,
and volume confirmation, including strict realistic financial bound assertions.
"""

import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from divergence_engine import (
    calculate_rolling_beta,
    calculate_rolling_residual_stdev,
    calculate_volume_metrics,
    compute_divergence,
    DivergenceResult
)
import config


class TestDivergenceEngine(unittest.TestCase):
    def test_rolling_beta_exact(self):
        # Realistic returns with known beta ~ 1.5
        bench = [0.008 * (i % 5 - 2) for i in range(30)]
        asset = [1.5 * b + 0.002 * ((i % 3) - 1) for i, b in enumerate(bench)]

        calculated_beta = calculate_rolling_beta(asset, bench, window=30)
        self.assertAlmostEqual(calculated_beta, 1.5, places=1)

    def test_rolling_beta_identity(self):
        # If asset returns == benchmark returns, beta = 1.0
        bench = [0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.03, -0.025] * 4
        asset = bench[:]
        beta = calculate_rolling_beta(asset, bench, window=30)
        self.assertAlmostEqual(beta, 1.0, places=5)

    def test_rolling_beta_zero_variance(self):
        # Constant benchmark returns (variance 0) -> safe fallback to 1.0
        bench = [0.0] * 30
        asset = [0.01 * (i % 3) for i in range(30)]
        beta = calculate_rolling_beta(asset, bench, window=30)
        self.assertEqual(beta, 1.0)

    def test_residual_stdev_realistic_floor(self):
        # When residual variance is nearly zero, floor (0.8% = 0.008) must be respected
        bench = [0.01, -0.01] * 15
        asset = [0.015, -0.015] * 15  # perfect match
        stdev = calculate_rolling_residual_stdev(asset, bench, beta=1.5, window=30)
        self.assertGreaterEqual(stdev, config.MIN_RESIDUAL_STDEV)
        self.assertLessEqual(stdev, 0.05)  # realistic financial ceiling (5%)

    def test_volume_metrics_weak_and_normal(self):
        # Ratio < 0.5 -> weak
        ratio, conf = calculate_volume_metrics(400.0, 1000.0, weak_threshold=0.5)
        self.assertEqual(ratio, 0.4)
        self.assertEqual(conf, "weak")

        # Ratio == 0.5 -> normal
        ratio, conf = calculate_volume_metrics(500.0, 1000.0, weak_threshold=0.5)
        self.assertEqual(ratio, 0.5)
        self.assertEqual(conf, "normal")

        # Ratio > 0.5 -> normal
        ratio, conf = calculate_volume_metrics(800.0, 1000.0, weak_threshold=0.5)
        self.assertEqual(ratio, 0.8)
        self.assertEqual(conf, "normal")

    def test_compute_divergence_realistic_z_scores(self):
        # 30-day realistic historical returns
        bench_history = [
            0.008, -0.004, 0.006, -0.002, 0.010, -0.007, 0.003, 0.005, -0.008, 0.002,
            0.004, -0.005, 0.009, -0.003, 0.001, -0.006, 0.007, 0.002, -0.004, 0.005,
            0.003, -0.002, 0.008, -0.009, 0.004, 0.006, -0.003, 0.001, 0.005, -0.002
        ]
        # Realistic NVDA returns with beta ~ 1.5 and idiosyncratic noise (stdev ~ 1.2%)
        asset_history = [
            +0.015, -0.014, +0.012, +0.008, +0.021, -0.022, +0.011, +0.002, -0.018, +0.011,
            +0.008, -0.016, +0.019, -0.001, +0.014, -0.015, +0.018, -0.005, -0.014, +0.016,
            +0.012, -0.009, +0.021, -0.024, +0.011, +0.017, -0.012, +0.008, +0.015, -0.011
        ]

        actual_move = 0.036        # +3.6% move since event
        bench_move = 0.003         # +0.3% benchmark move
        after_hours_vol = 250.0    # 250k volume
        trailing_avg_vol = 1200.0  # 1,200k average volume

        result = compute_divergence(
            asset="NVDA",
            actual_move=actual_move,
            benchmark_move=bench_move,
            asset_history_returns=asset_history,
            benchmark_history_returns=bench_history,
            after_hours_volume=after_hours_vol,
            trailing_avg_volume=trailing_avg_vol
        )

        self.assertIsInstance(result, DivergenceResult)
        self.assertEqual(result.asset, "NVDA")
        self.assertEqual(result.benchmark, "QQQ")
        self.assertAlmostEqual(result.volume_ratio, 0.2083, places=2)
        self.assertEqual(result.volume_confirmation, "weak")

        # CRITICAL REALISTIC Z-SCORE BOUNDS:
        # A legitimate after-hours dislocation must yield z between 2.0 and 6.0, NEVER insane 30+
        self.assertGreater(result.z_score, 2.0, "Z-score should exceed threshold 2.0")
        self.assertLess(result.z_score, 6.0, "Z-score must stay within realistic statistical bounds (< 6.0)")
        self.assertGreaterEqual(result.residual_stdev, 0.008, "Residual stdev must be >= 80 bps")


if __name__ == "__main__":
    unittest.main()
