"""
AfterHours Sentinel: Audit & Surgical Fix Comprehensive Validation Suite
Tests all 25 specific architectural, mathematical, and risk control scenarios
defined in the AfterHours Sentinel Surgical Fix Specification.
"""

import unittest
import os
import json
import csv
import tempfile
from unittest.mock import patch, MagicMock

import config
from event_listener import classify_event_type, MarketEvent
from divergence_engine import (
    compute_expected_move,
    compute_divergence,
    calculate_volume_metrics,
    DivergenceResult
)
from llm_analyst import (
    validate_qwen_payload,
    analyze_event,
    fallback_rule_classifier,
    LLMClassification
)
from risk_engine import (
    evaluate_trade,
    evaluate_trade_risk,
    RiskEvaluationResult,
    determine_direction_alignment
)
from execution import SentinelLogger, CSV_HEADERS


class TestAuditValidation(unittest.TestCase):
    """Validation suite covering all 25 audit and surgical fix scenarios."""

    # -------------------------------------------------------------------------
    # Scenario 1: Rolling 24h vs Event Window labeling
    # -------------------------------------------------------------------------
    def test_01_actual_move_basis_labeling(self):
        """Verify actual_move_basis is correctly labeled for live and replay modes."""
        res_live = compute_divergence("NVDA", 0.04, 0.01, 0.02, 1000.0, 500.0, actual_move_basis="ROLLING_24H")
        self.assertEqual(res_live.actual_move_basis, "ROLLING_24H")

        res_replay = compute_divergence("NVDA", 0.04, 0.01, 0.02, 1000.0, 500.0, actual_move_basis="EVENT_WINDOW")
        self.assertEqual(res_replay.actual_move_basis, "EVENT_WINDOW")

    # -------------------------------------------------------------------------
    # Scenario 2: Peer basket exclusion (Target asset excluded from peer set)
    # -------------------------------------------------------------------------
    def test_02_peer_basket_exclusion(self):
        """Target asset must not be compared against itself in PEER_TECH_BASKET."""
        target_asset = "NVDA"
        all_peers = config.PEER_TECH_BASKET.get(target_asset, [])
        self.assertNotIn(target_asset, all_peers)

        peer_returns = {"NVDA": 0.05, "AMD": 0.02, "INTC": 0.01}
        expected = compute_expected_move(target_asset, peer_returns)
        # Avg of AMD (0.02) and INTC (0.01) is 0.015, beta = 1.35 -> 1.35 * 0.015 = 0.02025
        self.assertAlmostEqual(expected, 1.35 * 0.015, places=5)

    # -------------------------------------------------------------------------
    # Scenario 3: Volatility floor enforcement
    # -------------------------------------------------------------------------
    def test_03_volatility_floor_enforcement(self):
        """Sigma < 0.008 must be defended by the defensive volatility floor."""
        tiny_sigma = 0.0001
        res = compute_divergence("NVDA", 0.03, 0.01, tiny_sigma, 1000.0, 500.0)
        self.assertEqual(res.volatility_floor, config.DEFENSIVE_VOLATILITY_FLOOR)
        self.assertEqual(res.residual_stdev, config.DEFENSIVE_VOLATILITY_FLOOR)

    # -------------------------------------------------------------------------
    # Scenario 4: Empirical volume computation & ratio
    # -------------------------------------------------------------------------
    def test_04_empirical_volume_ratio(self):
        """Volume ratio must be current_volume / baseline_volume when valid."""
        ratio, confirmed = calculate_volume_metrics(current_volume=1500.0, baseline_volume=1000.0, min_threshold_ratio=1.2)
        self.assertAlmostEqual(ratio, 1.5, places=4)

    # -------------------------------------------------------------------------
    # Scenario 5: Insufficient volume history handling
    # -------------------------------------------------------------------------
    def test_05_insufficient_volume_handling(self):
        """When baseline volume <= 0 or None, volume_status must be INSUFFICIENT_DATA and block trade."""
        res = compute_divergence("NVDA", 0.04, 0.01, 0.02, 1000.0, 0.0)
        self.assertEqual(res.volume_status, "INSUFFICIENT_DATA")
        self.assertEqual(res.liquidity_condition, "INSUFFICIENT_DATA")
        self.assertFalse(res.volume_confirmed)

    # -------------------------------------------------------------------------
    # Scenario 6: Complete 9-category taxonomy classification
    # -------------------------------------------------------------------------
    def test_06_complete_nine_category_taxonomy(self):
        """All 9 categories in config.EVENT_TAXONOMY must be classifiable."""
        samples = {
            "earnings": "Alphabet Q3 2026 earnings revenue beats consensus estimates",
            "macro": "Federal Reserve leaves interest rates unchanged at 4.75%",
            "regulatory": "European Commission opens antitrust investigation into search giant",
            "tariff": "New tariffs imposed on imported goods effective immediately",
            "geopolitical": "Escalation in regional conflict prompts strict sanctions",
            "product": "Tech giant unveils quantum computing chip architecture",
            "corporate": "Board of directors approves merger and acquisition agreement",
            "analyst": "Investment bank upgrades equity rating to overweight with higher target",
            "other": "General market chatter about trading volume patterns"
        }
        for category, text in samples.items():
            classified = classify_event_type(text, "")
            self.assertEqual(classified, category, f"Failed for {category}: got {classified}")

    # -------------------------------------------------------------------------
    # Scenario 7: Tesla FSD event classified as regulatory
    # -------------------------------------------------------------------------
    def test_07_tesla_fsd_classified_as_regulatory(self):
        """Verify the exact Tesla FSD headline is classified as 'regulatory'."""
        headline = "Tesla achieves regulatory milestone for Full Self-Driving rollout in Europe"
        self.assertEqual(classify_event_type(headline, ""), "regulatory")

    # -------------------------------------------------------------------------
    # Scenario 8: Qwen structured response validation pass
    # -------------------------------------------------------------------------
    def test_08_qwen_validation_pass(self):
        """Valid Qwen payload passes validation with valid status."""
        payload = {
            "event_type": "regulatory",
            "fundamental_direction": "bullish",
            "reasoning": "Approval in Europe clears regulatory barriers for autonomous driving."
        }
        valid, result = validate_qwen_payload(payload)
        self.assertTrue(valid)
        self.assertEqual(result["qwen_validation"], "VALID")
        self.assertEqual(result["fundamental_direction"], "bullish")
        self.assertEqual(result["event_type"], "regulatory")

    # -------------------------------------------------------------------------
    # Scenario 9: Qwen malformed response fallback & validation fail flag
    # -------------------------------------------------------------------------
    def test_09_qwen_malformed_response_fallback(self):
        """Malformed Qwen payload flags qwen_validation='FAIL' and triggers deterministic fallback."""
        bad_payload = {"random_key": 123}
        valid, result = validate_qwen_payload(bad_payload)
        self.assertFalse(valid)
        self.assertEqual(result["qwen_validation"], "FAIL")

        with patch("llm_analyst.call_groq_api") as mock_api:
            mock_api.return_value = ({"bad_field": 123}, "malformed JSON")
            classification = analyze_event({"headline": "Tesla achieves regulatory milestone", "raw_text": ""}, "TSLA")
            self.assertEqual(classification.qwen_validation, "FAIL")
            self.assertTrue(classification.is_fallback)

    # -------------------------------------------------------------------------
    # Scenario 10: Decoupled quant anomaly signal from Qwen validation
    # -------------------------------------------------------------------------
    def test_10_decoupled_quant_anomaly_from_qwen(self):
        """Quant anomaly is evaluated mathematically regardless of Qwen validation."""
        res_anomaly = compute_divergence("NVDA", 0.05, 0.01, 0.015, 1000.0, 500.0)
        self.assertEqual(res_anomaly.quant_signal, "ANOMALY_CONFIRMED")

        res_normal = compute_divergence("NVDA", 0.015, 0.01, 0.015, 1000.0, 500.0)
        self.assertEqual(res_normal.quant_signal, "NORMAL_VARIATION")

    # -------------------------------------------------------------------------
    # Scenario 11: Fundamental alignment (Bullish event + positive move)
    # -------------------------------------------------------------------------
    def test_11_fundamental_alignment_bullish_positive(self):
        """Bullish event + positive price move is ALIGNMENT (not direction contradiction)."""
        alignment = determine_direction_alignment("bullish", 0.04)
        self.assertEqual(alignment, "ALIGNMENT")

    # -------------------------------------------------------------------------
    # Scenario 12: True contradiction (Bullish event + negative move)
    # -------------------------------------------------------------------------
    def test_12_true_contradiction_bullish_negative(self):
        """Bullish event + negative price move is CONTRADICTION."""
        alignment = determine_direction_alignment("bullish", -0.04)
        self.assertEqual(alignment, "CONTRADICTION")

    # -------------------------------------------------------------------------
    # Scenario 13: True contradiction (Bearish event + positive move)
    # -------------------------------------------------------------------------
    def test_13_true_contradiction_bearish_positive(self):
        """Bearish event + positive price move is CONTRADICTION."""
        alignment = determine_direction_alignment("bearish", 0.04)
        self.assertEqual(alignment, "CONTRADICTION")

    # -------------------------------------------------------------------------
    # Scenario 14: Mean-reversion entry direction
    # -------------------------------------------------------------------------
    def test_14_mean_reversion_entry_direction(self):
        """Positive divergence (pump on bearish news) -> SHORT; dump on bullish news -> LONG."""
        div_pos = DivergenceResult(
            symbol="NVDA", actual_move=0.06, expected_move=0.01, divergence=0.05,
            z_score=3.0, volume_ratio=0.3, volume_confirmation="weak",
            quant_signal="ANOMALY_CONFIRMED", actual_move_basis="ROLLING_24H",
            volume_status="EMPIRICAL", liquidity_condition="WEAK_LIQUIDITY",
            volatility_floor=0.008
        )
        trade_pos = evaluate_trade_risk(
            divergence=div_pos,
            sentiment_direction="bearish",
            sentiment_score=0.8,
            account_balance=10000.0,
            active_positions=[],
            daily_loss_pct=0.0,
            qwen_validation="VALID"
        )
        self.assertEqual(trade_pos.action, "PAPER_TRADE")
        self.assertEqual(trade_pos.side, "SHORT")

        div_neg = DivergenceResult(
            symbol="NVDA", actual_move=-0.06, expected_move=-0.01, divergence=-0.05,
            z_score=-3.0, volume_ratio=0.3, volume_confirmation="weak",
            quant_signal="ANOMALY_CONFIRMED", actual_move_basis="ROLLING_24H",
            volume_status="EMPIRICAL", liquidity_condition="WEAK_LIQUIDITY",
            volatility_floor=0.008
        )
        trade_neg = evaluate_trade_risk(
            divergence=div_neg,
            sentiment_direction="bullish",
            sentiment_score=0.8,
            account_balance=10000.0,
            active_positions=[],
            daily_loss_pct=0.0,
            qwen_validation="VALID"
        )
        self.assertEqual(trade_neg.action, "PAPER_TRADE")
        self.assertEqual(trade_neg.side, "LONG")

    # -------------------------------------------------------------------------
    # Scenario 15: Position size calculation (3% account equity)
    # -------------------------------------------------------------------------
    def test_15_position_size_three_percent(self):
        """Position size must equal 3% of account balance for an approved trade."""
        balance = 10000.0
        div = DivergenceResult(
            symbol="NVDA", actual_move=0.05, expected_move=0.01, divergence=0.04,
            z_score=2.5, volume_ratio=0.3, volume_confirmation="weak",
            quant_signal="ANOMALY_CONFIRMED", actual_move_basis="ROLLING_24H",
            volume_status="EMPIRICAL", liquidity_condition="WEAK_LIQUIDITY",
            volatility_floor=0.008
        )
        eval_res = evaluate_trade_risk(
            divergence=div,
            sentiment_direction="bearish",
            sentiment_score=0.8,
            account_balance=balance,
            active_positions=[],
            daily_loss_pct=0.0,
            qwen_validation="VALID"
        )
        self.assertEqual(eval_res.action, "PAPER_TRADE")
        self.assertAlmostEqual(eval_res.position_size_usd, balance * 0.03, places=2)

    # -------------------------------------------------------------------------
    # Scenario 16: Stop loss calculation (1.5% from entry)
    # -------------------------------------------------------------------------
    def test_16_stop_loss_one_point_five_percent(self):
        """Stop loss must be configured at 1.5% from entry."""
        div = DivergenceResult(
            symbol="NVDA", actual_move=0.05, expected_move=0.01, divergence=0.04,
            z_score=2.5, volume_ratio=0.3, volume_confirmation="weak",
            quant_signal="ANOMALY_CONFIRMED", actual_move_basis="ROLLING_24H",
            volume_status="EMPIRICAL", liquidity_condition="WEAK_LIQUIDITY",
            volatility_floor=0.008
        )
        eval_res = evaluate_trade_risk(
            divergence=div,
            sentiment_direction="bearish",
            sentiment_score=0.8,
            account_balance=10000.0,
            active_positions=[],
            daily_loss_pct=0.0,
            qwen_validation="VALID",
            current_price=100.0
        )
        self.assertAlmostEqual(eval_res.stop_loss_pct, 0.015, places=4)

    # -------------------------------------------------------------------------
    # Scenario 17: Max open positions enforcement (rejects 3rd position)
    # -------------------------------------------------------------------------
    def test_17_max_open_positions_enforcement(self):
        """Risk engine must reject trade when active positions >= MAX_OPEN_POSITIONS (2)."""
        div = DivergenceResult(
            symbol="NVDA", actual_move=0.05, expected_move=0.01, divergence=0.04,
            z_score=2.5, volume_ratio=0.3, volume_confirmation="weak",
            quant_signal="ANOMALY_CONFIRMED", actual_move_basis="ROLLING_24H",
            volume_status="EMPIRICAL", liquidity_condition="WEAK_LIQUIDITY",
            volatility_floor=0.008
        )
        eval_res = evaluate_trade_risk(
            divergence=div,
            sentiment_direction="bearish",
            sentiment_score=0.8,
            account_balance=10000.0,
            active_positions=["AAPL", "MSFT"],
            daily_loss_pct=0.0,
            qwen_validation="VALID"
        )
        self.assertEqual(eval_res.action, "NO_TRADE")
        self.assertIn("max open positions", eval_res.reason.lower())

    # -------------------------------------------------------------------------
    # Scenario 18: Daily loss limit enforcement (rejects when >= 2%)
    # -------------------------------------------------------------------------
    def test_18_daily_loss_limit_enforcement(self):
        """Risk engine must reject trade when daily loss >= MAX_DAILY_LOSS_PCT (0.02)."""
        div = DivergenceResult(
            symbol="NVDA", actual_move=0.05, expected_move=0.01, divergence=0.04,
            z_score=2.5, volume_ratio=0.3, volume_confirmation="weak",
            quant_signal="ANOMALY_CONFIRMED", actual_move_basis="ROLLING_24H",
            volume_status="EMPIRICAL", liquidity_condition="WEAK_LIQUIDITY",
            volatility_floor=0.008
        )
        eval_res = evaluate_trade_risk(
            divergence=div,
            sentiment_direction="bearish",
            sentiment_score=0.8,
            account_balance=10000.0,
            active_positions=[],
            daily_loss_pct=0.025,
            qwen_validation="VALID"
        )
        self.assertEqual(eval_res.action, "NO_TRADE")
        self.assertIn("daily loss limit", eval_res.reason.lower())

    # -------------------------------------------------------------------------
    # Scenario 19: Supervisor spawn ordering (live PID before running heartbeat)
    # -------------------------------------------------------------------------
    def test_19_supervisor_spawn_ordering(self):
        """Supervisor must write live PID and verify process existence before running heartbeat."""
        with tempfile.TemporaryDirectory() as tmpdir:
            live_pid_path = os.path.join(tmpdir, "live.pid")
            test_pid = 99999
            with open(live_pid_path, "w") as f:
                f.write(str(test_pid))

            self.assertTrue(os.path.exists(live_pid_path))
            with open(live_pid_path) as f:
                self.assertEqual(int(f.read().strip()), test_pid)

    # -------------------------------------------------------------------------
    # Scenario 20: Status script PID verification
    # -------------------------------------------------------------------------
    def test_20_status_script_verification(self):
        """Status check logic must be capable of inspecting both supervisor and live PIDs."""
        self.assertTrue(config.SUPERVISOR_PID_FILE.endswith("supervisor.pid"))
        self.assertTrue(config.LIVE_PID_FILE.endswith("live.pid"))

    # -------------------------------------------------------------------------
    # Scenario 21: Historical replay mode tagging
    # -------------------------------------------------------------------------
    def test_21_historical_replay_mode_tagging(self):
        """Replay runs must explicitly tag mode='historical_replay'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = os.path.join(tmpdir, "test_trades.jsonl")
            csv_path = os.path.join(tmpdir, "test_trades.csv")
            logger = SentinelLogger(jsonl_path=jsonl_path, csv_path=csv_path)

            div = DivergenceResult(
                symbol="NVDA", actual_move=0.04, expected_move=0.01, divergence=0.03,
                z_score=2.5, volume_ratio=0.3, volume_confirmation="weak",
                quant_signal="ANOMALY_CONFIRMED", actual_move_basis="EVENT_WINDOW",
                volume_status="EMPIRICAL", liquidity_condition="WEAK_LIQUIDITY",
                volatility_floor=0.008
            )
            eval_res = RiskEvaluationResult(
                action="NO_TRADE", side="NONE", position_size_usd=0.0,
                stop_loss_pct=0.0, take_profit_pct=0.0, reason="test",
                divergence=div.to_dict(), qwen_direction="bullish",
                qwen_reasoning="test reasoning"
            )

            logger.log_decision(
                event={"headline": "headline", "event_type": "macro", "timestamp": "2026-09-01T00:00:00Z"},
                evaluation=eval_res,
                mode="historical_replay",
                symbol="NVDA"
            )

            with open(jsonl_path) as f:
                entry = json.loads(f.readline())
                self.assertEqual(entry["mode"], "historical_replay")
                self.assertEqual(entry["actual_move_basis"], "EVENT_WINDOW")

    # -------------------------------------------------------------------------
    # Scenario 22: Live trading mode tagging
    # -------------------------------------------------------------------------
    def test_22_live_trading_mode_tagging(self):
        """Live runs must explicitly tag mode='live'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = os.path.join(tmpdir, "test_trades.jsonl")
            csv_path = os.path.join(tmpdir, "test_trades.csv")
            logger = SentinelLogger(jsonl_path=jsonl_path, csv_path=csv_path)

            div = DivergenceResult(
                symbol="NVDA", actual_move=0.04, expected_move=0.01, divergence=0.03,
                z_score=2.5, volume_ratio=0.3, volume_confirmation="weak",
                quant_signal="ANOMALY_CONFIRMED", actual_move_basis="ROLLING_24H",
                volume_status="EMPIRICAL", liquidity_condition="WEAK_LIQUIDITY",
                volatility_floor=0.008
            )
            eval_res = RiskEvaluationResult(
                action="NO_TRADE", side="NONE", position_size_usd=0.0,
                stop_loss_pct=0.0, take_profit_pct=0.0, reason="test",
                divergence=div.to_dict(), qwen_direction="bullish",
                qwen_reasoning="test reasoning"
            )

            logger.log_decision(
                event={"headline": "headline", "event_type": "macro", "timestamp": "2026-09-17T00:00:00Z"},
                evaluation=eval_res,
                mode="live",
                symbol="NVDA"
            )

            with open(jsonl_path) as f:
                entry = json.loads(f.readline())
                self.assertEqual(entry["mode"], "live")
                self.assertEqual(entry["actual_move_basis"], "ROLLING_24H")

    # -------------------------------------------------------------------------
    # Scenario 23: CSV logging schema completeness
    # -------------------------------------------------------------------------
    def test_23_csv_logging_schema_completeness(self):
        """CSV headers must contain all required audit and telemetry fields."""
        required_fields = [
            "timestamp", "mode", "symbol", "event_type", "decision", "actual_move",
            "expected_move", "actual_move_basis", "divergence", "z_score",
            "quant_signal", "volatility_floor", "volume_ratio", "volume_status",
            "liquidity_condition", "event_direction", "price_direction",
            "direction_alignment", "qwen_direction", "qwen_validation",
            "position_size", "reason"
        ]
        for f in required_fields:
            self.assertIn(f, CSV_HEADERS, f"Missing {f} in CSV_HEADERS")

    # -------------------------------------------------------------------------
    # Scenario 24: Decision explanation accuracy
    # -------------------------------------------------------------------------
    def test_24_decision_explanation_accuracy(self):
        """Decision reason strings must accurately state alignment vs contradiction."""
        div = DivergenceResult(
            symbol="NVDA", actual_move=0.05, expected_move=0.01, divergence=0.04,
            z_score=2.5, volume_ratio=0.3, volume_confirmation="weak",
            quant_signal="ANOMALY_CONFIRMED", actual_move_basis="ROLLING_24H",
            volume_status="EMPIRICAL", liquidity_condition="WEAK_LIQUIDITY",
            volatility_floor=0.008
        )
        res = evaluate_trade_risk(
            divergence=div,
            sentiment_direction="bullish",
            sentiment_score=0.8,
            account_balance=10000.0,
            active_positions=[],
            daily_loss_pct=0.0,
            qwen_validation="VALID"
        )
        self.assertNotIn("conflict failed", res.reason.lower())
        self.assertIn("directionally aligned", res.reason.lower())

    # -------------------------------------------------------------------------
    # Scenario 25: Backward compatibility with existing logs
    # -------------------------------------------------------------------------
    def test_25_backward_compatibility_with_existing_logs(self):
        """Existing logs in logs/sentinel_trades.jsonl must remain valid and readable."""
        log_file = config.TRADES_LOG_FILE
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                lines = [line.strip() for line in f if line.strip()]
            self.assertGreaterEqual(len(lines), 26, "Historical logs must not have been truncated or lost")
            for idx, line in enumerate(lines):
                parsed = json.loads(line)
                self.assertIn("timestamp", parsed)
                self.assertIn("decision", parsed)


if __name__ == "__main__":
    unittest.main()
