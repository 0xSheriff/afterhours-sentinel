"""
Unit tests for LLM Analyst (Groq Integration & Fallback Classifier).
"""

import unittest
from unittest.mock import patch, MagicMock
import io
import json
import urllib.error

from llm_analyst import (
    call_groq_api,
    verify_groq_connection,
    fallback_rule_classifier,
    analyze_event,
    LLMClassification
)


class TestLLMAnalyst(unittest.TestCase):

    def test_fallback_classifier_bearish(self):
        res = fallback_rule_classifier(
            headline="U.S. Announces 25% Tariffs on Semiconductor Imports",
            raw_text="New trade sanctions and tariff expansion.",
            event_type="macro",
            asset="NVDA"
        )
        self.assertEqual(res.direction, "bearish")
        self.assertIn("fallback_rules [pending_groq_api_key]", res.llm_source)
        self.assertIn("adverse regulatory", res.reasoning)

    def test_fallback_classifier_bullish(self):
        res = fallback_rule_classifier(
            headline="TSLA Reports Record Revenue and Raises Guidance",
            raw_text="Automotive gross margins beat consensus.",
            event_type="earnings",
            asset="TSLA"
        )
        self.assertEqual(res.direction, "bullish")
        self.assertIn("fallback_rules [pending_groq_api_key]", res.llm_source)
        self.assertIn("fundamental revenue/guidance upside", res.reasoning)

    def test_fallback_classifier_neutral(self):
        res = fallback_rule_classifier(
            headline="Global Treasury Yields Steady Ahead of Central Bank Meetings",
            raw_text="Bond yields unchanged across tenors.",
            event_type="macro",
            asset="AAPL"
        )
        self.assertEqual(res.direction, "neutral")
        self.assertIn("fallback_rules [pending_groq_api_key]", res.llm_source)

    def test_verify_groq_connection_rejects_mock_key(self):
        is_authed, msg = verify_groq_connection(api_key="mock_groq_key")
        self.assertFalse(is_authed)
        self.assertIn("No valid GROQ_API_KEY", msg)

    @patch("urllib.request.urlopen")
    def test_call_groq_api_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "direction": "bearish",
                        "reasoning": "Tariffs directly compress hardware margins."
                    })
                }
            }],
            "usage": {"prompt_tokens": 150, "completion_tokens": 30}
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        parsed, status = call_groq_api("Test prompt", api_key="gsk_test_valid_key")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("direction"), "bearish")
        self.assertIn("HTTP 200 OK", status)

    @patch("urllib.request.urlopen")
    def test_analyze_event_live_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "direction": "bullish",
                        "reasoning": "Strong earnings guidance beat."
                    })
                }
            }],
            "usage": {"prompt_tokens": 120, "completion_tokens": 25}
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with patch.dict("os.environ", {"GROQ_API_KEY": "gsk_mock_valid"}):
            event = {
                "headline": "NVIDIA Earnings Surge 150% YoY",
                "raw_text": "Data center revenue hit all time high.",
                "event_type": "earnings"
            }
            res = analyze_event(event, asset="NVDA")
            self.assertEqual(res.direction, "bullish")
            self.assertIn("live_api", res.llm_source)
            self.assertEqual(res.reasoning, "Strong earnings guidance beat.")

    def test_llm_classification_is_dataclass(self):
        """Verify LLMClassification is the actual class (not an alias)."""
        obj = LLMClassification(
            direction="neutral",
            reasoning="test",
            llm_source="test"
        )
        self.assertIsInstance(obj, LLMClassification)
        d = obj.to_dict()
        self.assertEqual(d["direction"], "neutral")


if __name__ == "__main__":
    unittest.main()
