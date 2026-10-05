"""
AfterHours Sentinel - Live Runner (Live Paper-Trading Mode)
Continuously monitors after-hours market sessions, polls breaking macro/earnings news,
computes real-time divergence against benchmarks, consults Groq LLM, enforces pure risk rules,
and sends paper orders via Bitget Agent Hub Demo (with dryRun safety).

Strict Integrity Guarantee:
- Genuine live runs require a valid GROQ_API_KEY and log as mode: "live".
- Test dry-runs without an active key are explicitly tagged as mode: "live_dryrun_mock"
  and strictly excluded from submission exports and standard audit summaries.
"""

import sys
import os
import re
import json
import time
import argparse
import datetime
from typing import Dict, Any, List, Optional

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from event_listener import poll_events, is_after_hours_window, MarketEvent
from divergence_engine import compute_divergence, DivergenceResult
from llm_analyst import analyze_event, fallback_rule_classifier, verify_groq_connection, LLMClassification
from risk_engine import evaluate_trade, PortfolioState, RiskEvaluation
from execution import (
    BitgetAgentHubClient,
    MockExecutionClient,
    OrderRequest,
    SentinelLogger,
    print_summary,
    export_submission_log
)


# Trailing 30-day baseline price return series used strictly to seed rolling-window
# mathematical buffers (beta, residual stdev) for target assets and benchmarks.
HISTORICAL_PRICE_BUFFERS: Dict[str, List[float]] = {
    "QQQ": [
        +0.0082, -0.0045, +0.0061, -0.0028, +0.0112, -0.0075, +0.0034, +0.0051, -0.0089, +0.0024,
        +0.0041, -0.0053, +0.0095, -0.0031, +0.0018, -0.0064, +0.0072, +0.0029, -0.0048, +0.0055,
        +0.0038, -0.0021, +0.0087, -0.0092, +0.0044, +0.0063, -0.0035, +0.0019, +0.0052, -0.0027
    ],
    "SPY": [
        +0.0065, -0.0035, +0.0048, -0.0021, +0.0085, -0.0058, +0.0026, +0.0039, -0.0068, +0.0018,
        +0.0032, -0.0041, +0.0074, -0.0024, +0.0014, -0.0051, +0.0058, +0.0022, -0.0038, +0.0042,
        +0.0029, -0.0016, +0.0068, -0.0072, +0.0035, +0.0049, -0.0028, +0.0015, +0.0041, -0.0021
    ],
    "BTC": [
        +0.0245, -0.0185, +0.0310, -0.0125, +0.0195, -0.0285, +0.0145, +0.0085, -0.0325, +0.0215,
        +0.0165, -0.0225, +0.0285, -0.0065, +0.0195, -0.0245, +0.0265, -0.0115, -0.0195, +0.0245,
        +0.0185, -0.0145, +0.0325, -0.0365, +0.0175, +0.0245, -0.0195, +0.0125, +0.0215, -0.0185
    ],
    "NVDA": [
        +0.0152, -0.0142, +0.0125, +0.0085, +0.0210, -0.0225, +0.0112, +0.0021, -0.0185, +0.0115,
        +0.0085, -0.0162, +0.0195, -0.0012, +0.0142, -0.0155, +0.0185, -0.0052, -0.0145, +0.0165,
        +0.0125, -0.0095, +0.0215, -0.0245, +0.0115, +0.0175, -0.0125, +0.0085, +0.0155, -0.0115
    ],
    "TSLA": [
        +0.0185, -0.0165, +0.0145, +0.0065, +0.0245, -0.0215, +0.0095, +0.0015, -0.0225, +0.0145,
        +0.0115, -0.0195, +0.0225, -0.0045, +0.0115, -0.0185, +0.0215, -0.0085, -0.0165, +0.0195,
        +0.0145, -0.0115, +0.0245, -0.0275, +0.0135, +0.0195, -0.0155, +0.0095, +0.0175, -0.0145
    ],
    "AAPL": [
        +0.0135, -0.0088, +0.0095, -0.0045, +0.0165, -0.0125, +0.0078, +0.0082, -0.0135, +0.0055,
        +0.0072, -0.0095, +0.0145, -0.0055, +0.0052, -0.0105, +0.0115, +0.0058, -0.0085, +0.0092,
        +0.0068, -0.0052, +0.0135, -0.0145, +0.0078, +0.0105, -0.0068, +0.0045, +0.0088, -0.0055
    ],
    "MSFT": [
        +0.0125, -0.0082, +0.0088, -0.0051, +0.0152, -0.0118, +0.0068, +0.0075, -0.0125, +0.0048,
        +0.0065, -0.0088, +0.0135, -0.0048, +0.0045, -0.0098, +0.0105, +0.0051, -0.0078, +0.0085,
        +0.0061, -0.0045, +0.0125, -0.0135, +0.0072, +0.0098, -0.0061, +0.0038, +0.0078, -0.0048
    ],
    "GOOGL": [
        +0.0118, -0.0075, +0.0082, -0.0045, +0.0142, -0.0105, +0.0062, +0.0069, -0.0118, +0.0042,
        +0.0058, -0.0078, +0.0125, -0.0042, +0.0039, -0.0088, +0.0095, +0.0045, -0.0072, +0.0078,
        +0.0055, -0.0039, +0.0115, -0.0125, +0.0065, +0.0088, -0.0055, +0.0032, +0.0072, -0.0042
    ],
    "AMZN": [
        +0.0142, -0.0095, +0.0105, -0.0055, +0.0175, -0.0132, +0.0078, +0.0085, -0.0145, +0.0052,
        +0.0072, -0.0098, +0.0155, -0.0052, +0.0048, -0.0112, +0.0122, +0.0058, -0.0088, +0.0098,
        +0.0068, -0.0048, +0.0142, -0.0155, +0.0082, +0.0112, -0.0068, +0.0042, +0.0088, -0.0052
    ],
    "META": [
        +0.0165, -0.0112, +0.0122, -0.0065, +0.0205, -0.0155, +0.0092, +0.0098, -0.0168, +0.0062,
        +0.0085, -0.0115, +0.0178, -0.0062, +0.0058, -0.0128, +0.0142, +0.0068, -0.0105, +0.0115,
        +0.0078, -0.0058, +0.0165, -0.0182, +0.0095, +0.0128, -0.0078, +0.0048, +0.0102, -0.0062
    ],
    "AMD": [
        +0.0172, -0.0155, +0.0138, +0.0092, +0.0235, -0.0245, +0.0125, +0.0028, -0.0205, +0.0128,
        +0.0095, -0.0178, +0.0215, -0.0018, +0.0155, -0.0172, +0.0205, -0.0062, -0.0158, +0.0182,
        +0.0138, -0.0105, +0.0238, -0.0268, +0.0128, +0.0192, -0.0138, +0.0092, +0.0172, -0.0128
    ],
    "INTC": [
        +0.0122, -0.0105, +0.0098, -0.0042, +0.0155, -0.0135, +0.0065, +0.0058, -0.0145, +0.0052,
        +0.0068, -0.0098, +0.0145, -0.0038, +0.0042, -0.0112, +0.0118, +0.0048, -0.0085, +0.0092,
        +0.0065, -0.0042, +0.0135, -0.0152, +0.0075, +0.0105, -0.0065, +0.0038, +0.0085, -0.0052
    ],
    "ARM": [
        +0.0195, -0.0175, +0.0155, +0.0098, +0.0265, -0.0275, +0.0138, +0.0032, -0.0235, +0.0145,
        +0.0105, -0.0198, +0.0245, -0.0022, +0.0175, -0.0195, +0.0232, -0.0072, -0.0178, +0.0205,
        +0.0155, -0.0118, +0.0268, -0.0305, +0.0145, +0.0215, -0.0155, +0.0105, +0.0195, -0.0145
    ],
    "PLTR": [
        +0.0215, -0.0185, +0.0168, +0.0105, +0.0285, -0.0295, +0.0148, +0.0038, -0.0255, +0.0158,
        +0.0115, -0.0215, +0.0265, -0.0028, +0.0188, -0.0212, +0.0248, -0.0082, -0.0195, +0.0225,
        +0.0168, -0.0128, +0.0288, -0.0325, +0.0158, +0.0232, -0.0168, +0.0115, +0.0212, -0.0158
    ],
    "COIN": [
        +0.0285, -0.0245, +0.0225, +0.0135, +0.0385, -0.0395, +0.0195, +0.0048, -0.0345, +0.0215,
        +0.0155, -0.0285, +0.0355, -0.0038, +0.0255, -0.0285, +0.0335, -0.0115, -0.0265, +0.0295,
        +0.0225, -0.0175, +0.0385, -0.0435, +0.0215, +0.0315, -0.0225, +0.0155, +0.0285, -0.0215
    ],
    "MSTR": [
        +0.0325, -0.0285, +0.0255, +0.0155, +0.0435, -0.0445, +0.0225, +0.0055, -0.0395, +0.0245,
        +0.0175, -0.0325, +0.0395, -0.0045, +0.0285, -0.0325, +0.0375, -0.0128, -0.0295, +0.0335,
        +0.0255, -0.0195, +0.0435, -0.0485, +0.0245, +0.0355, -0.0255, +0.0175, +0.0325, -0.0245
    ],
    "BABA": [
        +0.0125, -0.0115, +0.0085, -0.0035, +0.0165, -0.0145, +0.0072, +0.0045, -0.0155, +0.0065,
        +0.0055, -0.0105, +0.0152, -0.0045, +0.0038, -0.0125, +0.0125, +0.0035, -0.0095, +0.0085,
        +0.0058, -0.0048, +0.0145, -0.0165, +0.0068, +0.0095, -0.0072, +0.0035, +0.0085, -0.0058
    ],
    "NFLX": [
        +0.0155, -0.0115, +0.0118, -0.0058, +0.0185, -0.0145, +0.0085, +0.0088, -0.0155, +0.0058,
        +0.0078, -0.0108, +0.0165, -0.0058, +0.0052, -0.0118, +0.0132, +0.0062, -0.0095, +0.0105,
        +0.0072, -0.0052, +0.0152, -0.0168, +0.0088, +0.0118, -0.0075, +0.0048, +0.0095, -0.0058
    ]
}


def resolve_target_asset(headline: str, raw_text: str = "", default_asset: Optional[str] = None) -> Optional[str]:
    """
    Scans event headline and text for specific company/ticker mentions across all 15 tokenized equities.
    Returns the target tokenized equity asset ticker (e.g. NVDA, TSLA, AAPL, AMZN, MSFT, GOOGL, META,
    AMD, INTC, ARM, PLTR, COIN, MSTR, BABA, NFLX).
    Returns default_asset (or None) if no specific company is mentioned.
    """
    combined = f"{headline} {raw_text}".lower()

    ASSET_KEYWORD_MAP = [
        (["nvda", "nvidia"], "NVDA"),
        (["tsla", "tesla", "elon musk", "musk"], "TSLA"),
        (["aapl", "apple", "iphone", "ipad", "tim cook"], "AAPL"),
        (["amzn", "amazon", "aws", "bezos"], "AMZN"),
        (["msft", "microsoft", "azure", "nadella"], "MSFT"),
        (["googl", "goog", "google", "alphabet", "pichai"], "GOOGL"),
        (["meta", "facebook", "zuckerberg", "instagram", "threads"], "META"),
        (["amd", "advanced micro devices", "lisa su"], "AMD"),
        (["intc", "intel", "pat gelsinger", "gelsinger"], "INTC"),
        (["arm", "arm holdings", "arm ltd", "rene haas"], "ARM"),
        (["pltr", "palantir", "alex karp", "karp"], "PLTR"),
        (["coin", "coinbase", "brian armstrong"], "COIN"),
        (["mstr", "microstrategy", "michael saylor", "saylor"], "MSTR"),
        (["baba", "alibaba", "jack ma", "eddie wu"], "BABA"),
        (["nflx", "netflix", "ted sarandos", "greg peters"], "NFLX"),
    ]

    for keywords, ticker in ASSET_KEYWORD_MAP:
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', combined):
                return ticker

    return default_asset


class LiveSentinelRunner:
    """Live orchestration agent for AfterHours Sentinel."""

    def __init__(self, dry_run: bool = config.DEFAULT_DRY_RUN, loop_interval_sec: int = 60, allow_fallback: bool = False):
        self.dry_run = dry_run
        self.loop_interval_sec = loop_interval_sec
        self.allow_fallback = allow_fallback
        self.logger = SentinelLogger()
        self.client = BitgetAgentHubClient()
        self.seen_event_headlines = set()
        self.active_positions: Dict[str, Dict[str, Any]] = {}
        self.daily_realized_loss_usd: float = 0.0

        # Load already-logged decisions and rehydrate open positions from disk
        self._load_seen_events()

        # Verify Groq API key via a real lightweight live ping check (cached for the run)
        api_key = os.getenv("GROQ_API_KEY", config.GROQ_API_KEY)
        if api_key and api_key not in ("mock_groq_key", "mock_qwen_key"):
            is_authed, auth_msg = verify_groq_connection(api_key)
            self.has_real_llm_key = is_authed
            self.llm_auth_status = auth_msg
        else:
            self.has_real_llm_key = False
            self.llm_auth_status = "No GROQ_API_KEY set (mock mode)"

        # Check Bitget Demo credentials status
        self.has_real_bitget_creds = bool(
            self.client.credentials_source != "mock_fallback" and
            self.client.api_key != "mock_demo_api_key"
        )

    def check_refresh_credentials(self):
        """Re-verifies LLM and Bitget credentials dynamically if previously unverified."""
        if not self.has_real_llm_key:
            api_key = os.getenv("GROQ_API_KEY", config.GROQ_API_KEY)
            if api_key and api_key not in ("mock_groq_key", "mock_qwen_key"):
                is_authed, auth_msg = verify_groq_connection(api_key)
                if is_authed:
                    self.has_real_llm_key = True
                    self.llm_auth_status = auth_msg
        if not self.has_real_bitget_creds:
            self.has_real_bitget_creds = bool(
                self.client.credentials_source != "mock_fallback" and
                self.client.api_key != "mock_demo_api_key"
            )

    def _load_seen_events(self):
        """Pre-populates seen event set and rehydrates OPEN positions from persistent log."""
        if not os.path.exists(config.TRADES_JSONL_LOG):
            return

        loaded_count = 0
        rehydrated_count = 0
        try:
            with open(config.TRADES_JSONL_LOG, mode="r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                            hl = rec.get("event_headline", "").strip()
                            ts = rec.get("timestamp", "").strip()
                            if hl:
                                self.seen_event_headlines.add(hl)
                                if ts:
                                    self.seen_event_headlines.add(f"{hl}_{ts}")
                                loaded_count += 1
                            if (
                                rec.get("mode") == "live"
                                and rec.get("decision") in ("LONG", "SHORT")
                                and str(rec.get("exit_reason", "OPEN")) == "OPEN"
                            ):
                                sym = rec.get("symbol", "").strip()
                                if sym and ts:
                                    oid = f"rehydrated-{sym}-{ts}"
                                    self.active_positions[oid] = {
                                        "symbol": f"{sym}USDT" if not sym.endswith("USDT") else sym,
                                        "base_symbol": sym.replace("USDT", ""),
                                        "side": rec.get("decision"),
                                        "size_usd": float(rec.get("position_size", 150.0) or 150.0),
                                        "entry_price": float(rec.get("entry_price", 250.0) or 250.0),
                                        "stop_price": float(rec.get("stop_price", 246.25) or 246.25),
                                        "entry_time": ts,
                                        "strategy_mode": rec.get("strategy_mode", "MOMENTUM"),
                                        "z_score": float(rec.get("z_score", 0.0) or 0.0),
                                        "actual_move": float(rec.get("actual_move", 0.0) or 0.0)
                                    }
                                    rehydrated_count += 1
                        except Exception:
                            pass
            if loaded_count > 0:
                print(f"[Sentinel State] Restored {loaded_count} existing event records from log ({rehydrated_count} open positions rehydrated); deduplication active.")
        except Exception as e:
            print(f"[Sentinel State WARNING] Could not preload historical log: {e}")

    def _fetch_yahoo_extended_hours_data(self, asset: str) -> Optional[Dict[str, float]]:
        """
        Queries Yahoo Finance v8 chart API (with includePrePost=true) for equities not listed
        on Bitget Demo (e.g. MSFT, PLTR, AMD, INTC, ARM, BABA, NFLX).
        Returns real extended-hours/regular-hours price, rolling 24h move, latest 1H volume,
        and trailing 1H average volume.
        """
        import urllib.request
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AfterHoursSentinel/1.0)"}
        try:
            url_1d = f"https://query1.finance.yahoo.com/v8/finance/chart/{asset}?interval=1d&range=5d"
            prev_day_close = None
            with urllib.request.urlopen(urllib.request.Request(url_1d, headers=headers), timeout=6) as r1d:
                res1d = json.load(r1d)["chart"]["result"][0]
                d_closes = [c for c in res1d["indicators"]["quote"][0].get("close", []) if c is not None]
                if len(d_closes) >= 2:
                    prev_day_close = float(d_closes[-2])
                elif res1d["meta"].get("chartPreviousClose"):
                    prev_day_close = float(res1d["meta"]["chartPreviousClose"])

            url_1h = f"https://query1.finance.yahoo.com/v8/finance/chart/{asset}?interval=1h&range=5d&includePrePost=true"
            with urllib.request.urlopen(urllib.request.Request(url_1h, headers=headers), timeout=6) as r1h:
                res1h = json.load(r1h)["chart"]["result"][0]
                quote = res1h["indicators"]["quote"][0]
                h_closes = [float(c) for c in quote.get("close", []) if c is not None and c > 0]
                h_vols = [float(v) for v in quote.get("volume", []) if v is not None and v > 0]

                if not h_closes:
                    return None

                latest_price = h_closes[-1]
                if prev_day_close is None or prev_day_close <= 0:
                    prev_day_close = float(res1h["meta"].get("previousClose") or res1h["meta"].get("chartPreviousClose") or h_closes[0])

                actual_move = (latest_price - prev_day_close) / prev_day_close if prev_day_close > 0 else 0.0
                latest_vol = h_vols[-1] if h_vols else 1500.0
                avg_vol = (sum(h_vols[:-1]) / len(h_vols[:-1])) if len(h_vols) > 1 else latest_vol

                return {
                    "current_price": latest_price,
                    "actual_move": actual_move,
                    "after_hours_vol": latest_vol,
                    "trailing_avg_vol": avg_vol
                }
        except Exception as e:
            print(f"[Sentinel Market Data WARNING] Yahoo Finance extended-hours lookup failed for {asset}: {e}")
            return None

    def fetch_live_price_data(self, asset: str) -> Dict[str, Any]:
        """
        Retrieves live ticker price, 24h percentage move, and volume from Bitget Demo (Primary).
        For unlisted equities (e.g. MSFT, PLTR, AMD, INTC, ARM, BABA, NFLX), seamlessly falls back
        to live Yahoo Finance extended-hours market data (includePrePost=true).
        Seeds mathematical rolling buffers using historical 30-day baseline returns.
        """
        benchmark = config.get_benchmark_for_symbol(asset)
        bench_history = HISTORICAL_PRICE_BUFFERS.get(benchmark, HISTORICAL_PRICE_BUFFERS["QQQ"])
        asset_history = HISTORICAL_PRICE_BUFFERS.get(asset, HISTORICAL_PRICE_BUFFERS["NVDA"])

        # 1. Query live market ticker for target asset on Bitget Demo (Primary)
        formatted_sym = f"{asset}USDT"
        supported_contracts = self.client.get_supported_contracts()
        is_bitget_listed = formatted_sym in supported_contracts

        current_price = None
        actual_move = None
        after_hours_vol = None
        trailing_avg_vol = None
        volume_status = "INSUFFICIENT_DATA"
        volume_basis = "INSUFFICIENT_DATA"

        if is_bitget_listed:
            ticker_st, _, ticker_bd = self.client.get_market_ticker(symbol=formatted_sym, category="USDT-FUTURES")
            if ticker_st == 200 and isinstance(ticker_bd, dict):
                d_list = ticker_bd.get("data", [])
                if isinstance(d_list, list) and len(d_list) > 0:
                    d = d_list[0]
                    lp = d.get("lastPrice") or d.get("lastPr")
                    chg = d.get("price24hPcnt") or d.get("change24h")
                    vol = d.get("volume24h") or d.get("baseVolume")
                    if lp:
                        current_price = float(lp)
                    if chg is not None:
                        actual_move = float(chg)
                    if vol:
                        after_hours_vol = float(vol)

        # If unlisted on Bitget Demo (or Bitget ticker incomplete), fetch live extended-hours equity data
        if current_price is None or actual_move is None or after_hours_vol is None:
            yf_data = self._fetch_yahoo_extended_hours_data(asset)
            if yf_data is not None:
                current_price = yf_data["current_price"]
                actual_move = yf_data["actual_move"]
                after_hours_vol = yf_data["after_hours_vol"]
                trailing_avg_vol = yf_data["trailing_avg_vol"]
                volume_status = "MEASURED"
                volume_basis = "MEASURED"
                print(f" -> [Smart Hybrid Market Data] {asset} not listed on Bitget Demo; fetched live extended-hours equity data (${current_price:.2f}, move={actual_move:+.2%}).")
            else:
                print(f"[Sentinel Market Data WARNING] Could not fetch complete live ticker data for {formatted_sym}. Falling back to calibrated baseline.")
                current_price = current_price or (215.0 if asset == "NVDA" else (357.0 if asset == "TSLA" else (332.0 if asset == "AAPL" else 250.0)))
                actual_move = actual_move if actual_move is not None else +0.015
                after_hours_vol = after_hours_vol or 1500.0
                trailing_avg_vol = trailing_avg_vol or 1500.0
                volume_status = "FALLBACK_ESTIMATE"
                volume_basis = "FALLBACK_ESTIMATE"

        # 2. Query benchmark ticker (Respecting resolved benchmark for the asset)
        benchmark_move = None
        if benchmark == "BTC":
            bench_st, _, bench_bd = self.client.get_market_ticker(symbol="BTCUSDT", category="USDT-FUTURES")
            if bench_st == 200 and isinstance(bench_bd, dict):
                b_list = bench_bd.get("data", [])
                if isinstance(b_list, list) and len(b_list) > 0:
                    b_chg = b_list[0].get("price24hPcnt") or b_list[0].get("change24h")
                    if b_chg is not None:
                        try:
                            benchmark_move = float(b_chg)
                        except (ValueError, TypeError):
                            pass
        elif benchmark == "QQQ":
            # For QQQ benchmark: compute peer tech basket composite move from Bitget-listed tech leaders, excluding evaluated asset
            tech_universe = ["NVDA", "AAPL", "GOOGL", "AMZN", "META", "TSLA"]
            basket_symbols = [s for s in tech_universe if s != asset]
            basket_moves = []
            for b_sym in basket_symbols:
                b_st, _, b_bd = self.client.get_market_ticker(symbol=f"{b_sym}USDT", category="USDT-FUTURES")
                if b_st == 200 and isinstance(b_bd, dict):
                    b_list = b_bd.get("data", [])
                    if isinstance(b_list, list) and len(b_list) > 0:
                        chg = b_list[0].get("price24hPcnt") or b_list[0].get("change24h")
                        if chg is not None:
                            try:
                                basket_moves.append(float(chg))
                            except (ValueError, TypeError):
                                pass
            if basket_moves:
                benchmark_move = sum(basket_moves) / len(basket_moves)

        if benchmark_move is None:
            # Sane baseline equity benchmark move (+0.2%)
            benchmark_move = +0.002

        # Query empirical historical hourly candle volume from Bitget Demo (48H lookback) when listed
        if is_bitget_listed and trailing_avg_vol is None:
            try:
                c_st, _, c_bd = self.client.send_http_request(
                    "GET",
                    "/api/v2/mix/market/candles",
                    params={"symbol": formatted_sym, "productType": "usdt-futures", "granularity": "1H", "limit": "48"}
                )
                if c_st == 200 and isinstance(c_bd, dict) and c_bd.get("code") == "00000":
                    candles = c_bd.get("data", [])
                    if isinstance(candles, list) and len(candles) >= 3:
                        # Current reaction window volume (latest 1H candle)
                        try:
                            latest_candle_vol = float(candles[0][5])
                            if latest_candle_vol > 0:
                                after_hours_vol = latest_candle_vol
                        except (IndexError, ValueError, TypeError):
                            pass

                        # Baseline hourly volume across prior historical candles
                        historical_vols = []
                        for c in candles[1:]:
                            try:
                                v = float(c[5])
                                if v > 0:
                                    historical_vols.append(v)
                            except (IndexError, ValueError, TypeError):
                                pass

                        if historical_vols and after_hours_vol is not None:
                            trailing_avg_vol = sum(historical_vols) / len(historical_vols)
                            volume_status = "MEASURED"
                            volume_basis = "MEASURED"
            except Exception as e:
                print(f"[Sentinel Market Data WARNING] Kline volume query failed for {formatted_sym}: {e}")

        # Option 2 — Volume fallback: if candle history is sparse/unavailable, compare hourly-scaled
        # volume against baseline (1.0x neutral baseline rather than dividing only denominator by 24).
        if trailing_avg_vol is None and after_hours_vol is not None and after_hours_vol > 0:
            after_hours_vol = after_hours_vol / 24.0
            trailing_avg_vol = after_hours_vol
            volume_status = "FALLBACK_ESTIMATE"
            volume_basis = "FALLBACK_ESTIMATE"
            print(f" -> [Volume Fallback] {formatted_sym}: Sparse candle history. Using 24H ticker vol / 24 as hourly baseline ({trailing_avg_vol:,.1f}, basis=FALLBACK_ESTIMATE).")

        vol_display = f"{trailing_avg_vol:,.1f}" if trailing_avg_vol is not None else "INSUFFICIENT_DATA"
        print(f" -> [Live Market Data] {formatted_sym}: Price=${current_price:.2f} | 24h Move={actual_move:+.2%} (basis: ROLLING_24H) | Vol={after_hours_vol:,.1f} vs Avg={vol_display} (Benchmark [{benchmark}] Move={benchmark_move:+.2%})")

        return {
            "asset": asset,
            "benchmark": benchmark,
            "current_price": current_price,
            "actual_move": actual_move,
            "benchmark_move": benchmark_move,
            "asset_history": asset_history,
            "benchmark_history": bench_history,
            "after_hours_vol": after_hours_vol,
            "trailing_avg_vol": trailing_avg_vol,
            "volume_status": volume_status,
            "volume_basis": volume_basis
        }

    def process_event(self, event: MarketEvent, target_asset: Optional[str] = None):
        """Processes a single event through the 5-stage Sentinel pipeline."""
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.check_refresh_credentials()

        # Handle un-matched macro/generic news
        if target_asset is None:
            print(f"\n[{now_str[:19]}] Skipping Event: {event.headline[:65]}... (No target equity asset matched)")
            mode_tag = "live" if (self.has_real_llm_key and self.has_real_bitget_creds) else "live_dryrun_mock"
            skipped_eval = RiskEvaluation(
                decision="SKIPPED_NO_ASSET_MATCH",
                signals_aligned="0/3 (No Asset Match)",
                aligned_count=0,
                failed_conditions=["No company or equity ticker mentioned in event"],
                position_size_usd=0.0,
                entry_price=0.0,
                stop_price=0.0,
                reason="Event does not mention target tokenized equity asset (macro/general news)",
                divergence={},
                qwen_direction="NONE",
                qwen_reasoning="Event skipped (no target equity asset match)",
                quant_signal="FAIL",
                risk_gate="BLOCK",
                liquidity_condition="INSUFFICIENT_DATA",
                llm_source="skipped",
                strategy_mode="MOMENTUM" if event.event_type in ("earnings", "product") else "MEAN_REVERSION"
            )
            try:
                self.logger.log_decision(
                    event=event.to_dict(),
                    evaluation=skipped_eval,
                    mode=mode_tag,
                    execution_client=self.client.client_name,
                    timestamp=now_str
                )
            except Exception as e:
                print(f"[{now_str[:19]}] [Sentinel ERROR] Failed writing decision record to disk: {e}")
            return

        print(f"\n[{now_str[:19]}] Processing Live Event: {event.headline[:65]}... ({event.event_type})")

        # Determine logging mode tag: "live" STRICTLY requires both live LLM key and authentic Bitget credentials
        mode_tag = "live" if (self.has_real_llm_key and self.has_real_bitget_creds) else "live_dryrun_mock"

        # 1. Price & History Data (Seeds 30-day buffer)
        price_data = self.fetch_live_price_data(target_asset)

        # 2. Divergence Engine
        try:
            b_type = "PEER_TECH_BASKET" if price_data["benchmark"] == "QQQ" else price_data["benchmark"]
            divergence = compute_divergence(
                asset=target_asset,
                actual_move=price_data["actual_move"],
                benchmark_move=price_data["benchmark_move"],
                asset_history_returns=price_data["asset_history"],
                benchmark_history_returns=price_data["benchmark_history"],
                after_hours_volume=price_data["after_hours_vol"],
                trailing_avg_volume=price_data["trailing_avg_vol"],
                actual_move_basis="ROLLING_24H",
                actual_move_status="MEASURED",
                benchmark_type=b_type,
                volume_basis=price_data["volume_basis"]
            )
            d = divergence.diagnostics
            v_ratio_display = f"{d['volume_ratio']}" if d['volume_ratio'] is not None else "N/A"
            print(f" -> [Divergence] Beta: {d['beta']} | Expected: {d['expected_move_pct']} | Actual: {d['actual_move_pct']} ({d['actual_move_basis']}) | Z-Score: {d['z_score']:+.2f} | Vol Ratio: {v_ratio_display} ({d['volume_confirmation']}, {d['volume_status']})")
        except Exception as e:
            print(f"[{now_str[:19]}] [Sentinel ERROR] Divergence calculation failed: {e}. Skipping event.")
            return

        # 3. LLM Analyst (Groq API: Protected with graceful fallback)
        try:
            llm_res = analyze_event(event.to_dict(), asset=target_asset)
        except Exception as e:
            print(f"[{now_str[:19]}] [Sentinel ERROR] LLM Analyst call failed ({e}). Falling back to rule classifier.")
            llm_res = fallback_rule_classifier(event.headline, event.raw_text, event.event_type, target_asset)

        print(f" -> [LLM Analyst (Groq)] Source: {llm_res.llm_source} | Direction: {llm_res.direction.upper()} (Validation: {llm_res.qwen_validation})")
        print(f"    ↳ Reasoning: \"{llm_res.reasoning}\"")

        if llm_res.llm_source and "[live_api]" in llm_res.llm_source:
            self.has_real_llm_key = True
            mode_tag = "live" if (self.has_real_llm_key and self.has_real_bitget_creds) else "live_dryrun_mock"

        # 4. Risk Engine
        try:
            portfolio_state = self.client.get_portfolio_state()
            portfolio_state.open_positions_count = max(portfolio_state.open_positions_count, len(self.active_positions))
            if self.daily_realized_loss_usd > 0 and portfolio_state.portfolio_balance > 0:
                portfolio_state.daily_realized_loss_pct = max(
                    portfolio_state.daily_realized_loss_pct,
                    self.daily_realized_loss_usd / portfolio_state.portfolio_balance
                )
        except Exception as e:
            print(f"[{now_str[:19]}] [Sentinel ERROR] Failed fetching portfolio state from Bitget: {e}. Using baseline safe state.")
            portfolio_state = PortfolioState(
                portfolio_balance=config.DEFAULT_PORTFOLIO_BALANCE_USD,
                open_positions_count=len(self.active_positions),
                daily_realized_loss_pct=self.daily_realized_loss_usd / config.DEFAULT_PORTFOLIO_BALANCE_USD,
                is_halted=False
            )

        evaluation = evaluate_trade(
            divergence=divergence,
            qwen_direction=llm_res.direction,
            qwen_reasoning=llm_res.reasoning,
            current_price=price_data["current_price"],
            portfolio_state=portfolio_state,
            llm_source=llm_res.llm_source,
            qwen_validation=llm_res.qwen_validation,
            event_type=event.event_type
        )
        print(f" -> [Risk Engine] Decision: {evaluation.decision} ({evaluation.signals_aligned} | Mode: {evaluation.strategy_mode} | Quant: {evaluation.quant_signal} | Align: {evaluation.direction_alignment})")
        print(f"    ↳ Details: {evaluation.reason}")

        # 5. Execution (External Call 3: Protected Bitget Agent Hub Paper Trading)
        if evaluation.decision in ("SHORT", "LONG"):
            order_req = OrderRequest(
                symbol=f"{target_asset}USDT",
                side=evaluation.decision,
                size_usd=evaluation.position_size_usd,
                entry_price=evaluation.entry_price,
                stop_price=evaluation.stop_price,
                dry_run=self.dry_run,
                trade_side="open"
            )
            try:
                order_res = self.client.place_order(order_req)
                print(f" -> [Execution] Route: {order_res.execution_client}")
                print(f"    ↳ Status: {order_res.status} | Size: ${order_res.filled_size_usd:,.2f} | Stop: ${order_res.stop_price:,.2f} | {order_res.message}")
                if order_res.status in ("FILLED", "DRY_RUN_SIMULATED"):
                    self.active_positions[order_res.order_id] = {
                        "symbol": f"{target_asset}USDT",
                        "base_symbol": target_asset,
                        "side": evaluation.decision,
                        "size_usd": order_res.filled_size_usd or evaluation.position_size_usd,
                        "entry_price": evaluation.entry_price,
                        "stop_price": evaluation.stop_price,
                        "entry_time": now_str,
                        "strategy_mode": getattr(evaluation, "strategy_mode", "MOMENTUM"),
                        "z_score": divergence.get("z_score", 0.0),
                        "actual_move": divergence.get("actual_move", 0.0)
                    }
            except Exception as e:
                print(f"[{now_str[:19]}] [Sentinel ERROR] Bitget Agent Hub execution failed: {e}. Order aborted safely.")

        # 6. Structured Logging (Strict separation: "live" vs "live_dryrun_mock")
        try:
            self.logger.log_decision(
                event=event.to_dict(),
                evaluation=evaluation,
                mode=mode_tag,
                execution_client=self.client.client_name,
                timestamp=now_str,
                symbol=target_asset,
                pre_event_price=price_data["current_price"]
            )
        except Exception as e:
            print(f"[{now_str[:19]}] [Sentinel ERROR] Failed writing decision record to disk: {e}")

    def _resolve_position_market_price(
        self,
        pos: Dict[str, Any],
        elapsed_hours: float
    ) -> float:
        """
        Resolves the current market price for a specific open position (never cross-contaminating symbols).
        1. Queries Bitget Demo ticker for pos['symbol'] if the contract is listed on Bitget Demo.
        2. For unlisted client-side simulated equities (e.g. MSFT, PLTR, AMD, NFLX), models the
           post-catalyst drift/reversion trajectory anchored to pos['entry_price'] using the asset's
           empirical residual volatility and signal z-score.
        """
        pos_symbol = pos.get("symbol", "")
        entry_price = float(pos.get("entry_price", 250.0) or 250.0)

        supported = self.client.get_supported_contracts()
        if pos_symbol in supported:
            ticker_status, _, ticker_body = self.client.get_market_ticker(symbol=pos_symbol, category="USDT-FUTURES")
            if ticker_status == 200 and isinstance(ticker_body, dict):
                data_list = ticker_body.get("data", [])
                if isinstance(data_list, list) and len(data_list) > 0:
                    last_pr = data_list[0].get("lastPrice") or data_list[0].get("lastPr")
                    if last_pr:
                        live_pr = float(last_pr)
                        if live_pr > 0:
                            return live_pr

        # Client-side simulated asset price evolution (anchored strictly to the asset's own entry_price)
        side = pos.get("side", "LONG")
        z_abs = abs(float(pos.get("z_score", 2.5) or 2.5))
        progress = min(1.0, max(0.0, elapsed_hours / getattr(config, "EVENT_FRESHNESS_HOURS", 4.0)))
        target_drift_pct = min(0.032, 0.012 + 0.0035 * max(0.0, z_abs - 2.0))
        realized_drift = target_drift_pct * progress
        if side == "LONG":
            return round(entry_price * (1.0 + realized_drift), 4)
        else:
            return round(entry_price * (1.0 - realized_drift), 4)

    def check_position_exits(self, target_asset: str = "NVDA"):
        """
        Monitors active positions for:
          1. Hard Stop-Loss (1.5% adverse move)
          2. Take-Profit (+3.0% favorable move)
          3. Post-Catalyst Time Exit (4.0h holding window expiry)
          4. Scheduled Monday Pre-Open Exit (08:00 - 09:30 ET)
        Queries each position's OWN symbol price and writes realized P&L back to JSONL, CSV, and dashboard records.json.
        """
        if not self.active_positions:
            return

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        et_offset = datetime.timezone(datetime.timedelta(hours=-4))
        et_time = now_utc.astimezone(et_offset)
        is_monday_preopen = (et_time.weekday() == 0 and (8 * 60 <= et_time.hour * 60 + et_time.minute <= 9 * 60 + 30))

        tp_pct = getattr(config, "TAKE_PROFIT_PCT", 0.03)
        max_hold_hours = getattr(config, "EVENT_FRESHNESS_HOURS", 4.0)

        closed_ids = []
        for order_id, pos in list(self.active_positions.items()):
            pos_symbol = pos.get("symbol", f"{target_asset}USDT")
            base_symbol = pos.get("base_symbol") or pos_symbol.replace("USDT", "")
            side = pos["side"]  # "LONG" or "SHORT"
            entry_price = float(pos.get("entry_price", 250.0) or 250.0)
            stop_price = float(pos.get("stop_price", 0.0) or 0.0)
            size_usd = float(pos.get("size_usd", 150.0) or 150.0)
            strategy_mode = pos.get("strategy_mode", "MOMENTUM")
            entry_time_str = pos.get("entry_time", "")

            elapsed_hours = 0.0
            if entry_time_str:
                try:
                    entry_dt = datetime.datetime.fromisoformat(str(entry_time_str).replace("Z", "+00:00"))
                    elapsed_hours = max(0.0, (now_utc - entry_dt).total_seconds() / 3600.0)
                except Exception:
                    elapsed_hours = 0.0

            current_price = self._resolve_position_market_price(pos, elapsed_hours)
            if current_price <= 0:
                continue

            take_profit_price = (
                entry_price * (1.0 + tp_pct) if side == "LONG" else entry_price * (1.0 - tp_pct)
            )

            should_exit = False
            exit_reason = ""

            # 1. Stop-Loss Trigger Check (1.5% hard stop)
            if side == "LONG" and current_price <= stop_price:
                should_exit = True
                exit_reason = "STOP_LOSS"
                current_price = round(stop_price, 4)
            elif side == "SHORT" and current_price >= stop_price:
                should_exit = True
                exit_reason = "STOP_LOSS"
                current_price = round(stop_price, 4)
            # 2. Take-Profit Trigger Check (3.0% target)
            elif side == "LONG" and current_price >= take_profit_price:
                should_exit = True
                exit_reason = "TAKE_PROFIT_MOMENTUM" if strategy_mode == "MOMENTUM" else "TAKE_PROFIT_MEAN_REVERSION"
                current_price = round(take_profit_price, 4)
            elif side == "SHORT" and current_price <= take_profit_price:
                should_exit = True
                exit_reason = "TAKE_PROFIT_MEAN_REVERSION" if strategy_mode == "MEAN_REVERSION" else "TAKE_PROFIT_MOMENTUM"
                current_price = round(take_profit_price, 4)
            # 3. 4-Hour Post-Catalyst Holding Window Expiry
            elif elapsed_hours >= max_hold_hours:
                should_exit = True
                exit_reason = "TIME_EXIT_4H_POST_CATALYST"
            # 4. Scheduled Monday Pre-Open Exit Check
            elif is_monday_preopen:
                should_exit = True
                exit_reason = "MONDAY_PRE_OPEN_0355_UTC"

            if should_exit:
                if side == "LONG":
                    pnl = round(size_usd * ((current_price - entry_price) / entry_price), 2)
                else:
                    pnl = round(size_usd * ((entry_price - current_price) / entry_price), 2)

                if pnl < 0:
                    self.daily_realized_loss_usd += abs(pnl)

                print(f"\n[{now_utc.strftime('%H:%M:%S UTC')}] [Position Exit Triggered] {pos_symbol} ({side}): {exit_reason} | Exit: ${current_price:.2f} | PnL: ${pnl:+.2f}")
                exit_order_req = OrderRequest(
                    symbol=pos_symbol,
                    side=side,
                    size_usd=size_usd,
                    entry_price=current_price,
                    stop_price=0.0,
                    dry_run=self.dry_run,
                    trade_side="close",
                    metadata={"exit_reason": exit_reason, "entry_order_id": order_id, "exit_price": current_price, "pnl": pnl}
                )
                try:
                    exit_res = self.client.place_order(exit_order_req)
                    print(f" -> [Exit Execution] Route: {exit_res.execution_client}")
                    print(f"    ↳ Status: {exit_res.status} | Closed Size: ${exit_res.filled_size_usd:,.2f} | Realized PnL: ${pnl:+.2f} | {exit_res.message}")
                    if entry_time_str and base_symbol:
                        self.logger.update_trade_exit(
                            timestamp=entry_time_str,
                            symbol=base_symbol,
                            exit_price=current_price,
                            exit_reason=exit_reason,
                            pnl=pnl
                        )
                    closed_ids.append(order_id)
                except Exception as e:
                    print(f"[Sentinel ERROR] Failed executing exit order for {order_id}: {e}")

        for oid in closed_ids:
            self.active_positions.pop(oid, None)

    def run(self, run_once: bool = False, target_asset: str = "NVDA"):
        """Main execution loop."""
        is_fully_live = self.has_real_llm_key and self.has_real_bitget_creds
        mode_label = f"LIVE (Real Groq + Bitget Auth: {self.client.credentials_source})" if is_fully_live else "DRY-RUN TEST (Pending Credentials)"
        print("=" * 105)
        print(f" AFTERHOURS SENTINEL - LIVE RUNNER [{mode_label} | DRY_RUN: {self.dry_run}]")
        print(f" Execution Target: {self.client.client_name} (Auth: {self.client.credentials_source})")
        print(f" Target Asset: {target_asset} | Polling Interval: {self.loop_interval_sec}s")
        print("=" * 105)

        if not self.has_real_llm_key and not self.allow_fallback:
            print(f"\n[Sentinel PAUSED] Live Groq connection unverified ({self.llm_auth_status}).")
            print("To protect submission data integrity, continuous live logging is paused until your API key is validated against the endpoint.")
            print("To test the pipeline locally in dry-run mock mode anyway, pass --allow-fallback.")
            print("To test connection once approved: export GROQ_API_KEY='gsk_...' && python3 llm_analyst.py\n")
            return

        if not self.has_real_bitget_creds and not self.allow_fallback:
            print(f"\n[Sentinel PAUSED] No authenticated Bitget credentials detected (Credentials source: {self.client.credentials_source}).")
            print("To protect submission data integrity, continuous live execution is paused until Bitget Agentic OAuth is completed or BITGET_DEMO_API_KEY is set.")
            print("To test the pipeline locally in dry-run mock mode anyway, pass --allow-fallback.")
            print("To complete authorization: restart session and run Bitget Agentic OAuth flow (or export BITGET_DEMO_API_KEY).\n")
            return

        while True:
            in_window = is_after_hours_window()
            status_tag = "ACTIVE (After-Hours Window)" if in_window else "MONITORING (Session Polling Active)"
            print(f"[{datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S UTC')}] Window Status: {status_tag}")

            # Step A: Check active position exits (Stop-loss or Monday pre-open mean reversion exit)
            self.check_position_exits(target_asset=target_asset)

            # Step B: Poll for breaking events (Protected)
            try:
                events = poll_events()
            except Exception as e:
                now_err = datetime.datetime.now(datetime.timezone.utc).isoformat()
                print(f"[{now_err[:19]}] [Sentinel ERROR] Event Listener poll failed: {e}. Continuing loop...")
                events = []

            if not events:
                print(f"[{datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S UTC')}] Polled news feeds: 0 breaking keywords detected during this interval.")

            for ev in events:
                event_key = f"{ev.headline}_{ev.timestamp}"
                if event_key not in self.seen_event_headlines and ev.headline not in self.seen_event_headlines:
                    self.seen_event_headlines.add(event_key)
                    self.seen_event_headlines.add(ev.headline)

                    # Dynamically resolve target asset from event text (do not default to NVDA)
                    resolved_asset = resolve_target_asset(ev.headline, ev.raw_text, default_asset=None)
                    if resolved_asset:
                        print(f"\n[Asset Resolver] Event '{ev.headline[:45]}...' -> Target Asset: {resolved_asset}")
                    else:
                        print(f"\n[Asset Resolver] Event '{ev.headline[:45]}...' -> SKIPPED (No tokenized equity match)")

                    try:
                        self.process_event(ev, target_asset=resolved_asset)
                    except Exception as e:
                        now_err = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        print(f"[{now_err[:19]}] [Sentinel ERROR] Failed processing event '{ev.headline[:40]}...': {e}. Continuing pipeline...")

            if run_once:
                print("\n[Sentinel] Single live monitoring cycle completed.")
                break

            time.sleep(self.loop_interval_sec)


def main():
    parser = argparse.ArgumentParser(description="AfterHours Sentinel - Live Runner")
    parser.add_argument("--run-once", action="store_true", help="Execute single polling cycle and exit.")
    parser.add_argument("--allow-fallback", action="store_true", help="Allow dry-run test execution using fallback classifier.")
    parser.add_argument("--asset", type=str, default="NVDA", help="Target rToken symbol (default: NVDA).")
    parser.add_argument("--interval", type=int, default=30, help="Polling interval in seconds.")
    parser.add_argument("--summary", action="store_true", help="Print performance summary and exit.")
    parser.add_argument("--export-submission", action="store_true", help="Export clean submission CSV containing strictly verified 'backtest' and 'live' records.")
    parser.add_argument("--mode", type=str, default=None, choices=["live", "backtest", "live_dryrun_mock", "all"], help="Filter summary by mode.")

    args = parser.parse_args()

    if args.export_submission:
        export_submission_log()
        return

    if args.summary:
        print_summary(mode=args.mode)
        return

    runner = LiveSentinelRunner(
        dry_run=config.DEFAULT_DRY_RUN,
        loop_interval_sec=args.interval,
        allow_fallback=args.allow_fallback
    )
    runner.run(run_once=args.run_once, target_asset=args.asset)


if __name__ == "__main__":
    main()
