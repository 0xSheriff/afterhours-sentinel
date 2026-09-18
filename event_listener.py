"""
AfterHours Sentinel - Event Listener
Polls news/macro RSS feeds and free news sources on an interval during after-hours trading windows.
Filters on keyword lists and outputs structured event objects.
"""

import datetime
import email.utils
import re
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
import config


@dataclass(frozen=True)
class MarketEvent:
    """Structured market event."""
    timestamp: str
    headline: str
    source: str
    event_type: str  # "earnings" | "macro" | "regulatory" | "tariff" | "geopolitical" | "product" | "corporate" | "analyst" | "other"
    raw_text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Free reliable RSS Feeds for Financial & Macro News
DEFAULT_RSS_FEEDS = [
    {"name": "YahooFinanceMacro", "url": "https://finance.yahoo.com/news/rssindex"},
    {"name": "InvestingNews", "url": "https://www.investing.com/rss/news.rss"},
    {"name": "MarketWatch", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"}
]


def parse_pub_date(pub_date_str: str) -> Optional[datetime.datetime]:
    """
    Robust multi-format date parser supporting:
    - ISO 8601 (e.g. '2026-09-15T13:33:00Z', '2026-09-15T13:33:00+00:00')
    - RFC 822 / 2822 / 1123 (e.g. 'Tue, 15 Sep 2026 21:34:00 GMT')
    - Standard SQL datetime (e.g. '2026-09-16 02:51:08')
    Returns timezone-aware UTC datetime or None if unparseable.
    """
    if not pub_date_str or not isinstance(pub_date_str, str):
        return None
    s = pub_date_str.strip()

    # 1. Try ISO 8601 (Yahoo)
    try:
        iso_str = s.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        pass

    # 2. Try RFC 822/2822 (MarketWatch, DowJones, standard RSS)
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(datetime.timezone.utc)
    except Exception:
        pass

    # 3. Try standard formats (Investing.com format 'YYYY-MM-DD HH:MM:SS')
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%d %b %Y %H:%M:%S",
        "%b %d, %Y %I:%M %p"
    ]
    for fmt in formats:
        try:
            dt = datetime.datetime.strptime(s, fmt)
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except Exception:
            continue

    return None


def is_event_fresh(
    pub_date_str: str,
    max_age_hours: Optional[float] = None,
    current_time: Optional[datetime.datetime] = None
) -> bool:
    """
    Freshness filter: rejects events older than max_age_hours (default: config.EVENT_FRESHNESS_WINDOW_HOURS).
    Safely rejects unparseable dates without throwing errors.
    """
    limit_hours = max_age_hours if max_age_hours is not None else config.EVENT_FRESHNESS_WINDOW_HOURS
    now_utc = current_time or datetime.datetime.now(datetime.timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)

    dt = parse_pub_date(pub_date_str)
    if dt is None:
        return False

    age_seconds = (now_utc - dt).total_seconds()
    age_hours = age_seconds / 3600.0

    # Allow slight clock skew (-6 min / -0.1h), but exclude anything older than limit_hours
    if -0.1 <= age_hours <= limit_hours:
        return True
    return False


def is_after_hours_window(dt: Optional[datetime.datetime] = None) -> bool:
    """
    Determines if given datetime (in UTC or local) falls within US market after-hours window:
    - Weekdays: 16:00 ET to 09:30 ET the next morning
    - Weekends: Entire Saturday and Sunday

    Note: 16:00 ET = 20:00 UTC (winter) / 21:00 UTC (summer).
    """
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    # Convert to approximate US Eastern Time (UTC-5 / UTC-4)
    # Using UTC-4 / UTC-5 offset estimate (-4 hours for EDT)
    et_offset = datetime.timezone(datetime.timedelta(hours=-4))
    et_time = dt.astimezone(et_offset)

    weekday = et_time.weekday()  # 0=Mon, ..., 4=Fri, 5=Sat, 6=Sun
    # Weekend
    if weekday in (5, 6):
        return True

    # Weekday after-hours check: before 09:30 or after 16:00
    hour = et_time.hour
    minute = et_time.minute
    total_minutes = hour * 60 + minute

    # Pre-market: 00:00 to 09:30 (570 min)
    # Post-market: 16:00 (960 min) to 23:59
    if total_minutes < 570 or total_minutes >= 960:
        return True

    return False


def match_keywords(text: str, keywords: Optional[List[str]] = None) -> bool:
    """Checks if text contains any target keywords."""
    if not text:
        return False
    kw_list = keywords or config.EVENT_KEYWORDS
    lower_text = text.lower()
    for kw in kw_list:
        if re.search(r'\b' + re.escape(kw) + r'\b', lower_text):
            return True
    return False


def classify_event_type(headline: str, text: str = "") -> str:
    """
    Deterministic 9-category event classifier supporting:
    - regulatory (SEC, DOJ, FDA, antitrust, probe, compliance, approval, lawsuit, milestone)
    - tariff (tariffs, trade sanctions, export curbs, import duties)
    - earnings (EPS, revenue, guidance, profit warning, quarterly results)
    - macro (Fed, FOMC, CPI, PPI, inflation, interest rate, yields, GDP, jobs)
    - geopolitical (war, military conflict, ceasefire, sanctions, election)
    - corporate (M&A, merger, acquisition, CEO resignation, restructuring, layoff)
    - product (launch, recall, robotaxi, autonomous, feature, release)
    - analyst (upgrade, downgrade, price target change, outperform)
    - other (fallback)

    Priority is enforced strictly to avoid misclassifications.
    """
    combined = f"{headline} {text}".lower()

    # Helper for regex search with word boundaries
    def has_match(patterns: List[str]) -> bool:
        for pat in patterns:
            if re.search(r'\b' + re.escape(pat) + r'\b', combined):
                return True
        return False

    # 1. Regulatory: High priority (investigations, antitrust, approval, regulatory milestones)
    regulatory_keywords = [
        "regulatory", "regulation", "regulators", "regulator", "antitrust", "investigation",
        "probe", "sec", "doj", "fda", "ftc", "subpoena", "lawsuit", "injunction", "court",
        "compliance", "approval", "patent dispute", "regulatory milestone"
    ]
    if has_match(regulatory_keywords):
        return "regulatory"

    # 2. Tariff: Trade barriers, export curbs, import duties
    tariff_keywords = [
        "tariff", "tariffs", "trade sanction", "trade sanctions", "export curb",
        "export curbs", "import duty", "import duties", "customs duty", "commerce dept"
    ]
    if has_match(tariff_keywords):
        return "tariff"

    # 3. Geopolitical: International conflict, war, military, broad sanctions
    geopolitical_keywords = [
        "war", "military", "ceasefire", "invasion", "sanctions", "embargo",
        "missile", "geopolitical", "election"
    ]
    if has_match(geopolitical_keywords):
        return "geopolitical"

    # 4. Macro: Systemic economic policy, central bank, inflation, interest rates, GDP
    macro_keywords = [
        "fed", "federal reserve", "fomc", "cpi", "ppi", "inflation", "interest rate",
        "rate hike", "rate cut", "treasury yields", "gdp", "unemployment", "jobs report",
        "central bank", "nonfarm payrolls", "discount window", "monetary policy"
    ]
    if has_match(macro_keywords):
        return "macro"

    # 5. Earnings: Company quarterly financials and forward guidance
    earnings_keywords = [
        "earnings", "eps", "revenue", "guidance", "profit", "quarterly results",
        "quarterly report", "financial results", "ebitda", "quarterly beat",
        "revenue miss", "profit warning", "raises guidance", "lowers guidance",
        "q1", "q2", "q3", "q4"
    ]
    if has_match(earnings_keywords):
        return "earnings"

    # 6. Corporate: M&A, leadership changes, restructuring
    corporate_keywords = [
        "merger", "acquisition", "acquire", "acquires", "acquired", "takeover", "buyout",
        "ceo", "cfo", "resigns", "resignation", "departure", "restructuring", "layoff",
        "layoffs", "spin-off", "spinoff", "board of directors", "share buyback", "dividend"
    ]
    if has_match(corporate_keywords):
        return "corporate"

    # 7. Analyst: Broker upgrades, downgrades, price targets
    analyst_keywords = [
        "upgrade", "upgrades", "upgraded", "downgrade", "downgrades", "downgraded",
        "price target", "outperform", "underperform", "initiates coverage",
        "overweight", "underweight", "brokerage", "wall street firm", "analyst rating"
    ]
    if has_match(analyst_keywords):
        return "analyst"

    # 8. Product: New hardware/software architecture, recalls, autonomous features
    product_keywords = [
        "product launch", "launch", "launches", "unveil", "unveils", "debut", "debuts",
        "recall", "robotaxi", "full self-driving", "autonomous", "announces new",
        "chip architecture", "software update", "feature rollout", "rollout"
    ]
    if has_match(product_keywords):
        return "product"

    # 9. Fallback
    return "other"


def parse_rss_feed(feed_url: str, source_name: str, max_age_hours: Optional[float] = None) -> List[MarketEvent]:
    """Fetches and parses standard RSS 2.0 XML feed with freshness and keyword filtering."""
    events: List[MarketEvent] = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AfterHoursSentinel/1.0)"}
    req = urllib.request.Request(feed_url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)

            channel = root.find("channel")
            if channel is None:
                return events

            for item in channel.findall("item"):
                title_elem = item.find("title")
                desc_elem = item.find("description")
                pub_elem = item.find("pubDate")

                headline = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                raw_text = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else headline
                pub_date = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else ""

                # 1. Freshness check: exclude stale articles
                if not is_event_fresh(pub_date, max_age_hours=max_age_hours):
                    continue

                # 2. Keyword check
                if match_keywords(f"{headline} {raw_text}"):
                    event_type = classify_event_type(headline, raw_text)
                    events.append(MarketEvent(
                        timestamp=pub_date,
                        headline=headline,
                        source=source_name,
                        event_type=event_type,
                        raw_text=raw_text
                    ))
    except Exception as e:
        # Feed fetch error or timeout, continue gracefully
        pass

    return events


def poll_events(feeds: Optional[List[Dict[str, str]]] = None, max_age_hours: Optional[float] = None) -> List[MarketEvent]:
    """
    Polls active feeds and returns all matched events within the freshness window.
    """
    active_feeds = feeds or DEFAULT_RSS_FEEDS
    collected_events: List[MarketEvent] = []

    for f in active_feeds:
        res = parse_rss_feed(f["url"], f["name"], max_age_hours=max_age_hours)
        collected_events.extend(res)

    return collected_events
