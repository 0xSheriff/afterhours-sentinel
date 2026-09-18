"""
Unit tests for Event Listener module.
Verifies keyword matching, case-insensitivity, position invariance (start vs mid-sentence),
boundary safety, event classification (macro vs earnings), and after-hours window detection.
"""

import unittest
import sys
import os
import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from event_listener import (
    match_keywords,
    classify_event_type,
    is_after_hours_window,
    parse_pub_date,
    is_event_fresh,
    MarketEvent
)
import config


class TestEventListener(unittest.TestCase):
    def test_matching_target_keywords(self):
        """Headlines with explicit target keywords must match."""
        matching_headlines = [
            "White House announces new 25% tariff on imported semiconductor chips",
            "Fed signals potential 50bps rate cut at upcoming FOMC meeting",
            "NVIDIA reports Q2 earnings beat and raises full-year guidance",
            "Producer Price Index (PPI) inflation surges above consensus expectations",
            "SEC investigation opened into executive stock transactions",
            "Antitrust regulators file formal complaint against tech conglomerate",
            "Escalating trade war threatens global automotive supply chains",
            "Oil spikes 6% as new Middle East war fears emerge"
        ]
        for h in matching_headlines:
            with self.subTest(headline=h):
                self.assertTrue(match_keywords(h), f"Failed to match keyword in: '{h}'")

    def test_non_matching_headlines(self):
        """Headlines with no market-moving catalyst keywords must not match."""
        unrelated_headlines = [
            "How a Costco partner's bankruptcy could benefit its biggest rival",
            "Walmart Delivery Push Gains Momentum with Papa John's Partnership",
            "Half of Gen X expects to outlive their savings",
            "Coffee Prices Fall as Production Spikes and Consumption Chills",
            "Top 5 best credit cards for travel points this summer",
            "Local weather forecast shows sunny skies for the weekend"
        ]
        for h in unrelated_headlines:
            with self.subTest(headline=h):
                self.assertFalse(match_keywords(h), f"Should NOT match keyword in: '{h}'")

    def test_case_insensitivity(self):
        """Keyword matching must be case-insensitive (UPPERCASE, lowercase, MixedCase)."""
        cases = [
            ("FED ANNOUNCES SURPRISE RATE HIKE", True),
            ("fed announces surprise rate hike", True),
            ("Fed Announces Surprise Rate Hike", True),
            ("NEW TARIFFS IMPOSED ON EXPORTS", True),
            ("new tariffs imposed on exports", True),
            ("New Tariffs Imposed On Exports", True),
            ("INFLATION RISES SHARPLY ACROSS SECTORS", True),
            ("inflation rises sharply across sectors", True)
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(match_keywords(text), expected)

    def test_keyword_position_start_vs_mid_sentence(self):
        """Keywords must match whether located at the start, middle, or end of a headline."""
        start_pos = "Tariff increases scheduled to take effect immediately"
        mid_pos = "Commerce Department announces aggressive tariff increases on foreign solar panels"
        end_pos = "International trade strained by impending tariff"

        self.assertTrue(match_keywords(start_pos), "Failed matching keyword at start of sentence")
        self.assertTrue(match_keywords(mid_pos), "Failed matching keyword in middle of sentence")
        self.assertTrue(match_keywords(end_pos), "Failed matching keyword at end of sentence")

    def test_word_boundary_safety(self):
        """Substrings within other words must not trigger false positive matches."""
        # e.g., 'fed' in 'federated', 'buffed', 'feathered'
        false_positives = [
            "Company adopts a federated cloud architecture for data analytics",
            "The product was buffed and polished to perfection",
            "The software update is buffered in memory"
        ]
        for fp in false_positives:
            with self.subTest(text=fp):
                self.assertFalse(match_keywords(fp), f"False positive triggered on substring in: '{fp}'")

    def test_event_type_classification(self):
        """Earnings keywords must classify as 'earnings', macro keywords as 'macro'."""
        earnings_samples = [
            "NVIDIA beats Q2 earnings expectations and raises revenue guidance",
            "Tesla reports quarterly results with EPS beat",
            "Company issues profit warning following supply disruptions"
        ]
        macro_samples = [
            "Federal Reserve holds interest rates steady following FOMC rate decision",
            "CPI inflation reading rises 0.4% month-over-month",
            "US GDP grows at 2.8% annualized rate in Q3"
        ]
        tariff_samples = [
            "White House announces comprehensive tariff policy on European imports",
            "New tariffs imposed on imported semiconductor components"
        ]
        regulatory_samples = [
            "Tesla achieves regulatory milestone for Full Self-Driving rollout in Europe",
            "DOJ antitrust division files antitrust lawsuit against tech conglomerate",
            "FDA grants accelerated approval for new drug application"
        ]
        geopolitical_samples = [
            "Escalation in sanctions announced against foreign entities",
            "Military conflict prompts closure of international shipping route"
        ]
        corporate_samples = [
            "CEO announces sudden departure amid board restructuring",
            "Company agrees to acquire key competitor for $12 billion in cash"
        ]
        product_samples = [
            "Company unveils next-generation chip architecture at annual developer summit",
            "New flagship model debut scheduled for commercial release next month"
        ]
        analyst_samples = [
            "Wall Street firm upgrades stock rating to overweight with higher price target",
            "Brokerage downgrades tech giant to sell citing valuation concerns"
        ]

        for s in earnings_samples:
            with self.subTest(sample=s):
                self.assertEqual(classify_event_type(s, ""), "earnings")

        for s in macro_samples:
            with self.subTest(sample=s):
                self.assertEqual(classify_event_type(s, ""), "macro")

        for s in tariff_samples:
            with self.subTest(sample=s):
                self.assertEqual(classify_event_type(s, ""), "tariff")

        for s in regulatory_samples:
            with self.subTest(sample=s):
                self.assertEqual(classify_event_type(s, ""), "regulatory")

        for s in geopolitical_samples:
            with self.subTest(sample=s):
                self.assertEqual(classify_event_type(s, ""), "geopolitical")

        for s in corporate_samples:
            with self.subTest(sample=s):
                self.assertEqual(classify_event_type(s, ""), "corporate")

        for s in product_samples:
            with self.subTest(sample=s):
                self.assertEqual(classify_event_type(s, ""), "product")

        for s in analyst_samples:
            with self.subTest(sample=s):
                self.assertEqual(classify_event_type(s, ""), "analyst")

        self.assertEqual(classify_event_type("Random community discussion thread", ""), "other")

    def test_after_hours_window_detection(self):
        """Verifies US after-hours window logic (weekends and weekday 16:00-09:30 ET)."""
        # Saturday in UTC -> True
        saturday = datetime.datetime(2026, 9, 19, 14, 0, tzinfo=datetime.timezone.utc)
        self.assertTrue(is_after_hours_window(saturday))

        # Sunday in UTC -> True
        sunday = datetime.datetime(2026, 9, 20, 14, 0, tzinfo=datetime.timezone.utc)
        self.assertTrue(is_after_hours_window(sunday))

        # Monday 18:00 ET (22:00 UTC EDT) -> After-hours (True)
        mon_after_hours = datetime.datetime(2026, 9, 14, 22, 0, tzinfo=datetime.timezone.utc)
        self.assertTrue(is_after_hours_window(mon_after_hours))

        # Monday 12:00 ET (16:00 UTC EDT) -> Regular trading hours (False)
        mon_regular_hours = datetime.datetime(2026, 9, 14, 16, 0, tzinfo=datetime.timezone.utc)
        self.assertFalse(is_after_hours_window(mon_regular_hours))

    def test_freshness_within_window_passes(self):
        """An event published within the 4-hour window must pass freshness check."""
        now = datetime.datetime(2026, 9, 16, 3, 30, 0, tzinfo=datetime.timezone.utc)
        recent_iso = "2026-09-16T02:45:00Z"  # 45 minutes old
        recent_rfc = "Wed, 16 Sep 2026 02:30:00 GMT"  # 60 minutes old
        recent_sql = "2026-09-16 02:00:00"  # 90 minutes old

        self.assertTrue(is_event_fresh(recent_iso, max_age_hours=4.0, current_time=now))
        self.assertTrue(is_event_fresh(recent_rfc, max_age_hours=4.0, current_time=now))
        self.assertTrue(is_event_fresh(recent_sql, max_age_hours=4.0, current_time=now))

    def test_freshness_stale_articles_excluded(self):
        """Events older than the freshness window (e.g. 2024 or 12h ago) must be excluded."""
        now = datetime.datetime(2026, 9, 16, 3, 30, 0, tzinfo=datetime.timezone.utc)
        stale_2024_iso = "2024-06-06T15:07:09Z"  # Over 2 years old
        stale_yesterday_rfc = "Mon, 14 Sep 2026 10:00:00 GMT"  # ~41 hours old
        stale_hours_ago = "2026-09-15 18:00:00"  # 9.5 hours old (> 4h threshold)

        self.assertFalse(is_event_fresh(stale_2024_iso, max_age_hours=4.0, current_time=now))
        self.assertFalse(is_event_fresh(stale_yesterday_rfc, max_age_hours=4.0, current_time=now))
        self.assertFalse(is_event_fresh(stale_hours_ago, max_age_hours=4.0, current_time=now))

    def test_unparseable_pub_date_safely_excluded(self):
        """Invalid date strings must return False and never crash the process."""
        invalid_dates = [
            "not-a-date",
            "",
            "invalid 2026",
            "99-99-9999 99:99:99",
            None
        ]
        for inv in invalid_dates:
            with self.subTest(invalid_date=inv):
                self.assertFalse(is_event_fresh(inv, max_age_hours=4.0))

    def test_parse_pub_date_formats(self):
        """Verifies correct parsing and UTC conversion across date standards."""
        iso_dt = parse_pub_date("2026-09-16T02:45:00Z")
        self.assertIsNotNone(iso_dt)
        self.assertEqual(iso_dt.year, 2026)
        self.assertEqual(iso_dt.hour, 2)
        self.assertEqual(iso_dt.minute, 45)

        rfc_dt = parse_pub_date("Tue, 15 Sep 2026 21:34:00 GMT")
        self.assertIsNotNone(rfc_dt)
        self.assertEqual(rfc_dt.year, 2026)
        self.assertEqual(rfc_dt.day, 15)
        self.assertEqual(rfc_dt.hour, 21)

        sql_dt = parse_pub_date("2026-09-16 02:51:08")
        self.assertIsNotNone(sql_dt)
        self.assertEqual(sql_dt.year, 2026)
        self.assertEqual(sql_dt.minute, 51)


if __name__ == "__main__":
    unittest.main()
