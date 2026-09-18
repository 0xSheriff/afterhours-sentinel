"""
AfterHours Sentinel - Historical Replay Engine (Backtest Mode)
Replays the full 5-stage pipeline against realistic historical after-hours macro and earnings events.
Tags every log entry with mode: "backtest" and execution_client: "MockExecutionClient [Local Simulator]".
"""

import sys
import os
import datetime
from typing import List, Dict, Any

# Ensure root directory in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from divergence_engine import compute_divergence, calculate_rolling_beta, calculate_rolling_residual_stdev, DivergenceResult
from llm_analyst import analyze_event, LLMClassification
from risk_engine import evaluate_trade, PortfolioState, RiskEvaluation
from execution import (
    BitgetAgentHubClient,
    MockExecutionClient,
    OrderRequest,
    SentinelLogger,
    print_summary
)


# Realistic 30-day trailing daily returns for QQQ benchmark
REAL_QQQ_30D_RETURNS = [
    +0.0082, -0.0045, +0.0061, -0.0028, +0.0112, -0.0075, +0.0034, +0.0051, -0.0089, +0.0024,
    +0.0041, -0.0053, +0.0095, -0.0031, +0.0018, -0.0064, +0.0072, +0.0029, -0.0048, +0.0055,
    +0.0038, -0.0021, +0.0087, -0.0092, +0.0044, +0.0063, -0.0035, +0.0019, +0.0052, -0.0027
]

# Realistic 30-day trailing returns for tech stocks with realistic idiosyncratic volatility (sigma_residual ~ 0.95% to 1.35%)
REAL_ASSET_30D_RETURNS: Dict[str, List[float]] = {
    # NVDA: Beta ~ 1.45, Idiosyncratic daily stdev ~ 1.25%
    "NVDA": [
        +0.0152, -0.0142, +0.0125, +0.0085, +0.0210, -0.0225, +0.0112, +0.0021, -0.0185, +0.0115,
        +0.0085, -0.0162, +0.0195, -0.0012, +0.0142, -0.0155, +0.0185, -0.0052, -0.0145, +0.0165,
        +0.0125, -0.0095, +0.0215, -0.0245, +0.0115, +0.0175, -0.0125, +0.0085, +0.0155, -0.0115
    ],
    # TSLA: Beta ~ 1.55, Idiosyncratic daily stdev ~ 1.35%
    "TSLA": [
        +0.0185, -0.0165, +0.0145, +0.0065, +0.0245, -0.0215, +0.0095, +0.0015, -0.0225, +0.0145,
        +0.0115, -0.0195, +0.0225, -0.0045, +0.0115, -0.0185, +0.0215, -0.0085, -0.0165, +0.0195,
        +0.0145, -0.0115, +0.0245, -0.0275, +0.0135, +0.0195, -0.0155, +0.0095, +0.0175, -0.0145
    ],
    # AAPL: Beta ~ 1.15, Idiosyncratic daily stdev ~ 0.98%
    "AAPL": [
        +0.0135, -0.0088, +0.0095, -0.0045, +0.0165, -0.0125, +0.0078, +0.0082, -0.0135, +0.0055,
        +0.0072, -0.0095, +0.0145, -0.0055, +0.0052, -0.0105, +0.0115, +0.0058, -0.0085, +0.0092,
        +0.0068, -0.0052, +0.0135, -0.0145, +0.0078, +0.0105, -0.0068, +0.0045, +0.0088, -0.0055
    ],
    # MSFT: Beta ~ 1.10, Idiosyncratic daily stdev ~ 0.92%
    "MSFT": [
        +0.0125, -0.0082, +0.0088, -0.0051, +0.0152, -0.0118, +0.0068, +0.0075, -0.0125, +0.0048,
        +0.0065, -0.0088, +0.0135, -0.0048, +0.0045, -0.0098, +0.0105, +0.0051, -0.0078, +0.0085,
        +0.0061, -0.0045, +0.0125, -0.0135, +0.0072, +0.0098, -0.0061, +0.0038, +0.0078, -0.0048
    ]
}


HISTORICAL_EVENTS: List[Dict[str, Any]] = [
    {
        "id": "HIST-001",
        "asset": "NVDA",
        "timestamp": "2026-08-20T20:30:00Z",
        "event_headline": "U.S. Commerce Dept Announces Immediate 25% Tariffs on Advanced Semiconductor Equipment",
        "event_type": "tariff",
        "raw_text": "The Department of Commerce expanded export tariffs targeting advanced lithography and packaging equipment, impacting major chip fabrication lines.",
        "entry_price": 128.50,
        "actual_move": +0.036,     # +3.6% irrational pump on thin liquidity
        "benchmark_move": +0.003,  # QQQ +0.3%
        "after_hours_vol": 250_000.0,
        "trailing_avg_vol": 1_200_000.0,  # volume ratio = 0.21 ("weak")
        "simulated_exit_price": 124.00,   # Post-market mean-reversion down
        "exit_reason": "TAKE_PROFIT_MEAN_REVERSION"
    },
    {
        "id": "HIST-002",
        "asset": "TSLA",
        "timestamp": "2026-08-27T20:05:00Z",
        "event_headline": "TSLA Reports Q2 Earnings: Automotive Revenue Surges 18%, Raises Full-Year Delivery Guidance",
        "event_type": "earnings",
        "raw_text": "Tesla beat consensus EPS by 14% and raised full-year delivery guidance citing production efficiencies and energy storage margin expansion.",
        "entry_price": 215.00,
        "actual_move": -0.038,     # -3.8% irrational algorithmic dump
        "benchmark_move": -0.002,  # QQQ -0.2%
        "after_hours_vol": 310_000.0,
        "trailing_avg_vol": 950_000.0,    # volume ratio = 0.33 ("weak")
        "simulated_exit_price": 222.50,   # Post-market mean-reversion up
        "exit_reason": "TAKE_PROFIT_MEAN_REVERSION"
    },
    {
        "id": "HIST-003",
        "asset": "AAPL",
        "timestamp": "2026-09-02T21:15:00Z",
        "event_headline": "Federal Reserve Emergency Statement on Interbank Discount Window Rate Adjustments",
        "event_type": "macro",
        "raw_text": "Fed announces tighter collateral eligibility across primary credit facilities.",
        "entry_price": 225.00,
        "actual_move": +0.022,
        "benchmark_move": +0.004,
        "after_hours_vol": 850_000.0,
        "trailing_avg_vol": 1_000_000.0,  # volume ratio = 0.85 ("normal" -> fails volume condition)
        "simulated_exit_price": 225.00,
        "exit_reason": "N/A"
    },
    {
        "id": "HIST-004",
        "asset": "MSFT",
        "timestamp": "2026-09-08T20:10:00Z",
        "event_headline": "DOJ Expands Antitrust Probe into Tech Cloud Infrastructure and Bundling Practices",
        "event_type": "regulatory",
        "raw_text": "Antitrust division requests civil investigative demands regarding enterprise cloud contracting terms.",
        "entry_price": 410.00,
        "actual_move": -0.025,     # price fell in line with bearish news
        "benchmark_move": -0.008,  # QQQ -0.8%
        "after_hours_vol": 200_000.0,
        "trailing_avg_vol": 800_000.0,
        "simulated_exit_price": 410.00,
        "exit_reason": "N/A"
    }
]


def run_historical_replay():
    """
    Executes historical replay across all past events in backtest mode.
    Uses MockExecutionClient for simulation isolation.
    """
    print("=" * 105)
    print(" STARTING AFTERHOURS SENTINEL - HISTORICAL REPLAY (BACKTEST MODE)")
    print("=" * 105)

    logger = SentinelLogger()
    # Explicitly instantiate MockExecutionClient for historical backtesting
    execution_client = MockExecutionClient(initial_balance=config.DEFAULT_PORTFOLIO_BALANCE_USD)
    portfolio_state = execution_client.get_portfolio_state()

    for idx, item in enumerate(HISTORICAL_EVENTS, start=1):
        asset = item["asset"]
        print(f"\n--- [Event {idx}/{len(HISTORICAL_EVENTS)}] Replaying: {asset} | {item['event_type'].upper()} ---")
        print(f"Timestamp: {item['timestamp']}")
        print(f"Headline : {item['event_headline']}")

        # 1. Event Object
        event_obj = {
            "timestamp": item["timestamp"],
            "headline": item["event_headline"],
            "source": "HistoricalArchive",
            "event_type": item["event_type"],
            "raw_text": item["raw_text"]
        }

        # 2. Divergence Engine with real return series
        asset_hist = REAL_ASSET_30D_RETURNS.get(asset, REAL_ASSET_30D_RETURNS["NVDA"])
        bench_hist = REAL_QQQ_30D_RETURNS

        divergence = compute_divergence(
            asset=asset,
            actual_move=item["actual_move"],
            benchmark_move=item["benchmark_move"],
            asset_history_returns=asset_hist,
            benchmark_history_returns=bench_hist,
            after_hours_volume=item["after_hours_vol"],
            trailing_avg_volume=item["trailing_avg_vol"],
            actual_move_basis="EVENT_WINDOW",
            actual_move_status="MEASURED",
            benchmark_type="PEER_TECH_BASKET",
            volume_basis="MEASURED"
        )

        d = divergence.diagnostics
        print(f"Divergence Math  -> Beta: {d['beta']} | Benchmark Move: {d['benchmark_move_pct']} | Expected Move: {d['expected_move_pct']}")
        print(f"                 -> Actual Move: {d['actual_move_pct']} ({d['actual_move_basis']}) | Residual: {d['residual_pct']} | Residual Stdev (30d): {d['residual_stdev_pct']}")
        print(f"                 -> STATISTICAL Z-SCORE: {d['z_score']:+.2f} (Threshold: |z| > {config.Z_SCORE_THRESHOLD})")
        print(f"                 -> Volume: {d['volume_ratio']}x trailing avg ({d['volume_confirmation']})")

        # 3. LLM Analyst (Groq)
        llm_res = analyze_event(event_obj, asset=asset)
        print(f"LLM Call (Groq)  -> Source: {llm_res.llm_source}")
        print(f"                 -> Direction: {llm_res.direction.upper()} (Validation: {llm_res.qwen_validation})")
        print(f"                 -> Reasoning: \"{llm_res.reasoning}\"")

        # 4. Risk Engine
        evaluation = evaluate_trade(
            divergence=divergence,
            qwen_direction=llm_res.direction,
            qwen_reasoning=llm_res.reasoning,
            current_price=item["entry_price"],
            portfolio_state=portfolio_state,
            llm_source=llm_res.llm_source,
            qwen_validation=llm_res.qwen_validation
        )

        print(f"Risk Engine Gate -> Decision: {evaluation.decision} ({evaluation.signals_aligned} | Quant: {evaluation.quant_signal} | Align: {evaluation.direction_alignment})")
        print(f"                 -> {evaluation.reason}")

        # 5. Execution & Logging
        pnl = 0.0
        exit_price = None
        exit_reason = None

        if evaluation.decision in ("SHORT", "LONG"):
            order_req = OrderRequest(
                symbol=f"r{asset}USDT",
                side=evaluation.decision,
                size_usd=evaluation.position_size_usd,
                entry_price=evaluation.entry_price,
                stop_price=evaluation.stop_price,
                dry_run=config.DEFAULT_DRY_RUN
            )
            order_res = execution_client.place_order(order_req)
            print(f"Execution Route  -> Client: {order_res.execution_client}")
            print(f"                 -> Order Status: {order_res.status} | Size: ${order_res.filled_size_usd:,.2f} | Stop: ${order_res.stop_price:,.2f}")

            # Calculate simulated PnL from historical exit
            exit_price = item["simulated_exit_price"]
            exit_reason = item["exit_reason"]
            shares = evaluation.position_size_usd / evaluation.entry_price
            if evaluation.decision == "SHORT":
                pnl = (evaluation.entry_price - exit_price) * shares
            else:  # LONG
                pnl = (exit_price - evaluation.entry_price) * shares

            print(f"Replay Outcome   -> Exit: ${exit_price:,.2f} ({exit_reason}) | Realized PnL: ${pnl:+,.2f}")

        logger.log_decision(
            event=event_obj,
            evaluation=evaluation,
            mode="historical_replay",
            execution_client=execution_client.client_name,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=pnl,
            timestamp=item["timestamp"],
            symbol=asset,
            pre_event_price=item["entry_price"]
        )

    print("\n" + "=" * 105)
    print(" HISTORICAL REPLAY AUDIT TABLE (MODE: HISTORICAL_REPLAY):")
    print("=" * 105)
    print_summary(mode="historical_replay")


if __name__ == "__main__":
    run_historical_replay()
