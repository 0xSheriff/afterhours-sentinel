#!/usr/bin/env python3
"""
AfterHours Sentinel - Event Listener Live Source Verification Script
Polls live RSS feeds, outputs all raw headlines unfiltered,
and tests them against the keyword filter with match explanation.
"""

import sys
import re
import urllib.request
import xml.etree.ElementTree as ET
import config
from event_listener import DEFAULT_RSS_FEEDS, match_keywords, classify_event_type


def get_matching_keywords(text: str, keywords=None):
    """Finds all specific keywords that matched in text."""
    kw_list = keywords or config.EVENT_KEYWORDS
    lower_text = text.lower()
    matched = []
    for kw in kw_list:
        if re.search(r'\b' + re.escape(kw) + r'\b', lower_text):
            matched.append(kw)
    return matched


def main():
    print("=" * 90)
    print(" AFTERHOURS SENTINEL - EVENT LISTENER LIVE SOURCE VERIFICATION")
    print("=" * 90)
    print("Configured Feeds:")
    for f in DEFAULT_RSS_FEEDS:
        print(f"  - {f['name']:<18} : {f['url']}")
    print(f"\nActive Keyword Filter List ({len(config.EVENT_KEYWORDS)} keywords):")
    print("  " + ", ".join(config.EVENT_KEYWORDS))
    print("=" * 90)

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    all_raw_items = []
    feed_errors = []

    for feed in DEFAULT_RSS_FEEDS:
        name = feed["name"]
        url = feed["url"]
        print(f"\n[Polling Feed] {name} ({url})...")

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                status_code = response.getcode()
                raw_xml = response.read()
                root = ET.fromstring(raw_xml)
                channel = root.find("channel")

                if channel is None:
                    print(f"  ↳ Warning: No <channel> found in XML from {name}")
                    continue

                items = channel.findall("item")
                print(f"  ↳ HTTP {status_code} OK - Received {len(items)} items from {name}")

                for item in items:
                    title_elem = item.find("title")
                    desc_elem = item.find("description")
                    pub_elem = item.find("pubDate")

                    headline = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
                    pub_date = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else "N/A"

                    all_raw_items.append({
                        "source": name,
                        "headline": headline,
                        "description": desc,
                        "pubDate": pub_date
                    })

        except Exception as e:
            print(f"  ↳ Error fetching {name}: {e}")
            feed_errors.append((name, str(e)))

    print("\n" + "=" * 90)
    print(f" 1. UNFILTERED RAW HEADLINES (Total: {len(all_raw_items)})")
    print("=" * 90)

    for idx, item in enumerate(all_raw_items, start=1):
        print(f"[{idx:02d}] [{item['source']}] {item['headline']}")
        if item['pubDate'] != "N/A":
            print(f"     PubDate: {item['pubDate']}")

    print("\n" + "=" * 90)
    print(" 2. FILTER EVALUATION: FRESHNESS (<= 4.0h) + KEYWORD MATCHING")
    print("=" * 90)

    from event_listener import is_event_fresh, parse_pub_date
    import datetime

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    fresh_matched_events = []
    stale_keyword_matches = []

    for idx, item in enumerate(all_raw_items, start=1):
        full_text = f"{item['headline']} {item['description']}"
        matches = get_matching_keywords(full_text)
        if matches:
            dt = parse_pub_date(item['pubDate'])
            age_hours = (now_utc - dt).total_seconds() / 3600.0 if dt else None
            is_fresh = is_event_fresh(item['pubDate'])
            event_type = classify_event_type(item['headline'], item['description'])

            ev_info = {
                "raw_idx": idx,
                "source": item['source'],
                "headline": item['headline'],
                "matched_keywords": matches,
                "event_type": event_type,
                "pubDate": item['pubDate'],
                "age_hours": age_hours
            }

            if is_fresh:
                fresh_matched_events.append(ev_info)
            else:
                stale_keyword_matches.append(ev_info)

    print(f"Total Raw Headlines Analyzed       : {len(all_raw_items)}")
    print(f"Total Keyword Matches              : {len(fresh_matched_events) + len(stale_keyword_matches)}")
    print(f"Stale Items Rejected (> 4h window) : {len(stale_keyword_matches)}")
    print(f"Fresh Candidates Passed (<= 4h)    : {len(fresh_matched_events)}")
    pass_rate = (len(fresh_matched_events) / len(all_raw_items) * 100) if all_raw_items else 0
    print(f"Final Pipeline Selectivity Rate    : {pass_rate:.1f}%\n")

    print("--- [SECTION A] STALE ITEMS REJECTED BY FRESHNESS FILTER ---")
    if stale_keyword_matches:
        for idx, ev in enumerate(stale_keyword_matches, start=1):
            age_str = f"{ev['age_hours']:.1f}h ago" if ev['age_hours'] is not None else "Unparseable"
            print(f"[Rejected {idx}] (Raw #{ev['raw_idx']}) [{ev['source']}] Age: {age_str}")
            print(f"  Headline        : \"{ev['headline']}\"")
            print(f"  Matched Keywords: {ev['matched_keywords']}")
            print(f"  PubDate         : {ev['pubDate']}")
            print("-" * 90)
    else:
        print("None.")

    print("\n--- [SECTION B] QUALIFIED FRESH EVENT CANDIDATES (PASSED ALL FILTERS) ---")
    if fresh_matched_events:
        for idx, ev in enumerate(fresh_matched_events, start=1):
            age_str = f"{ev['age_hours']:.1f}h ago" if ev['age_hours'] is not None else "Recent"
            print(f"[Event {idx}] (Raw #{ev['raw_idx']}) [{ev['source']}] Age: {age_str}")
            print(f"  Headline        : \"{ev['headline']}\"")
            print(f"  Matched Keywords: {ev['matched_keywords']}")
            print(f"  Event Type      : {ev['event_type'].upper()}")
            print(f"  PubDate         : {ev['pubDate']}")
            print("-" * 90)
    else:
        print("No fresh events matched within the current 4-hour window.")

    print("\n" + "=" * 90)


if __name__ == "__main__":
    main()
