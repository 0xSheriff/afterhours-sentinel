# AfterHours Sentinel

> **Autonomous Event-Driven Trading Agent for Tokenized U.S. Stocks (rTokens) on Bitget**  
> *Bitget AI Base Camp Hackathon S2 — Agentic Trading Track (Event-Driven Agent Sub-Theme)*

---

## 1. Overview & Core Thesis

**AfterHours Sentinel** is an autonomous trading agent engineered to exploit after-hours price dislocations in tokenized U.S. equities (rTokens) on Bitget. 

During after-hours sessions (post-market 16:00–09:30 ET and weekends), liquidity thins significantly. When a high-impact macroeconomic announcement (tariffs, Fed statements) or earnings release occurs, price action often exhibits irrational, knee-jerk moves driven by algorithmic stops or thin orderbooks.

AfterHours Sentinel detects when an rToken's price reaction **diverges fundamentally and statistically** from what the event and correlated benchmarks imply. When statistically anomalous divergence ($|z| > 2.0$, typically $z \approx 2.5 - 4.5$) occurs on **weak volume** against the fundamental direction of the news, Sentinel executes a mean-reverting paper trade with strict risk controls.

---

## 2. Non-Negotiable Safety Constraints

To guarantee account security and zero unintended exposure:
1. **Paper-Trading Only**: All execution targets Bitget Agent Hub in `--paper-trading` mode against Bitget's Demo environment (`DEMO_MODE=True`). It never touches live/mainnet accounts.
2. **`dryRun=True` by Default**: Every order-placing function enforces `dryRun=True` unless explicitly toggled in `config.py` (`DEFAULT_DRY_RUN = False`).
3. **Zero Dangerous Operations**: Zero withdrawal, transfer, or `cancelAll`-type calls exist anywhere in the codebase.
4. **Transparent Execution Layer**: Explicitly tracks routing via `BitgetAgentHubClient` against `api.bitget.com` demo endpoints with fallback to `MockExecutionClient`.

---

## 3. Architecture (Strict 5-Component Pipeline)

```mermaid
graph TD
    A[1. Event Listener] -->|Structured Market Event| B[2. Divergence Engine]
    B -->|Deterministic Z-Score & Volume Ratio| C[3. LLM Analyst (Groq)]
    C -->|Implied Event Direction: Bullish/Bearish/Neutral| D[4. Risk Engine]
    D -->|3/3 Signals Verified + Risk Checks| E[5. Bitget Execution & Logger]
    E -->|Structured Log JSONL / CSV| F[Backtest / Live Audit Logs]
```

### Component Breakdown & Mathematical Rigor

1. **Event Listener (`event_listener.py`)**:
   - Polls free macro & earnings news feeds on an interval during after-hours sessions.
   - Filters on target keywords: `tariff`, `fed`, `rate decision`, `earnings`, `guidance`, `cpi`, `sanctions`, `geopolitics`.
   - Produces structured event: `{timestamp, headline, source, event_type: "macro" | "earnings", raw_text}`.

2. **Divergence Engine (`divergence_engine.py`)**:
   - Pure, deterministic mathematics with zero LLM dependencies.
   - Dynamic benchmark mapping: **QQQ** for tech/semiconductor rTokens (`NVDA`, `TSLA`, `AAPL`, `MSFT`, `AMD`), **BTC** for others.
   - Computes:
     $$\beta = \frac{\text{Cov}(R_{\text{asset}}, R_{\text{bench}})}{\text{Var}(R_{\text{bench}})} \quad (\text{30-day rolling window})$$
     $$\text{expected\_move} = \beta \times \Delta_{\text{bench}}$$
     $$\text{residual} = \Delta_{\text{actual}} - \text{expected\_move}$$
     $$z = \frac{\text{residual}}{\sigma_{\text{residual}}} \quad (\text{with realistic volatility floor } \sigma_{\min} = 80\text{ bps})$$
     $$\text{volume\_ratio} = \frac{\text{Volume}_{\text{after\_hours}}}{\overline{\text{Volume}}_{\text{timeslot}}}$$
     $$\text{volume\_confirmation} = \begin{cases} \text{"weak"} & \text{if } \text{volume\_ratio} < 0.5 \\ \text{"normal"} & \text{otherwise} \end{cases}$$

3. **LLM Analyst (`llm_analyst.py`)**:
   - Calls Groq OpenAI-compatible API (`https://api.groq.com/openai/v1`, default model `qwen/qwen3.8-27b` / `llama-3.3-70b-versatile`).
   - Prompt strictly requests JSON: `{"direction": "bullish" | "bearish" | "neutral", "reasoning": "..."}`.
   - **Explainability & Isolation Guarantee**: The LLM does *not* see or produce the z-score or trade decision. It solely evaluates fundamental directional impact and provides one sentence of reasoning that is surfaced directly in the audit log.
   - **Provenance Transparency**: If `GROQ_API_KEY` is not present, emits a loud warning and tags records with `llm_source: "fallback_rules [pending_groq_api_key]"`. When live, logs explicit model provenance e.g. `llm_source: "groq_qwen3.8-27b [live_api]"`.

4. **Risk Engine (`risk_engine.py`)**:
   - Pure rule-based gatekeeper (no LLM).
   - Generates trade candidates only if **ALL 3 signals align**:
     1. $|z| > 2.0$ (Significant statistical divergence)
     2. Event direction from LLM conflicts with price move (e.g. LLM says `bearish` and price pumped $\rightarrow$ `SHORT`; LLM says `bullish` and price dumped $\rightarrow$ `LONG`)
     3. Volume confirmation is `"weak"` (indicates thin liquidity dislocation rather than broad institutional consensus)
   - Risk management constraints:
     - Fixed **3% of portfolio** per trade.
     - Hard stop loss at **1.5% from entry**.
     - Maximum **2 simultaneous open positions**.
     - Daily loss limit **2% of portfolio** (halts trading for the day if breached).
     - Reports exact signal count as `"N/3 signals aligned"`.

5. **Bitget Execution & Logger (`execution.py`)**:
   - Dispatches orders to Bitget Agent Hub Paper Trading in Demo environment.
   - Records every decision (`TRADE` or `NO_TRADE`) to `logs/sentinel_trades.jsonl` and `logs/sentinel_trades.csv`.
   - Log schema: `{timestamp, mode, execution_client, llm_source, event_headline, event_type, expected_move, actual_move, divergence, z_score, volume_ratio, qwen_direction, qwen_reasoning, decision, signals_aligned, position_size, stop_price, entry_price, exit_price, exit_reason, pnl, reason}`.

---

## 4. Key Proof Point: Near-Miss Gating (AAPL $z=1.93$)

A key test of any quantitative trading thesis is whether the gatekeeper rejects near-misses rather than rubber-stamping every event.

In our backtest suite, **Event 3 (Federal Reserve Interbank Statement on AAPL)** illustrates this exact principle:
* Price moved $+2.20\%$ against expected $+0.66\%$ (residual $+1.54\%$).
* Resulting $z$-score was **$+1.93$** (just below the $2.0$ threshold) and volume was **$0.85\text{x}$** (normal institutional volume).
* **Gatekeeper Decision**: Correctly rejected with `NO_TRADE (1/3 signals aligned)` because the statistical threshold was not breached and volume indicated legitimate institutional participation rather than thin-liquidity dislocation.

---

## 5. Quick Start & Usage

### 1. Run Unit Tests (100% pure standard library)
```bash
python3 -m unittest discover -s tests -v
```

### 2. Run Historical Replay (Backtest Mode)
Replays realistic after-hours macro & earnings events, verifying that trade candidates trigger cleanly on divergences ($z \in [2.0, 4.5]$) and filter correctly on near-misses and directional agreement:
```bash
python3 historical_replay.py
```

### 3. Test Groq Connection
```bash
export GROQ_API_KEY="gsk-your-groq-key"
python3 llm_analyst.py
```

### 4. Run Live Agent (Live Paper-Trading Mode)
Runs continuous monitoring loop during after-hours sessions with `dryRun` safety enabled:
```bash
# Continuous live runner (pauses safely if key is not yet set)
python3 live.py --interval 30 --asset NVDA

# Export clean verified submission log (excludes all mock runs)
python3 live.py --export-submission
```

### 5. Resilient Background Supervisor
For unattended long-running execution, run `supervisor.py` or use the management scripts:
```bash
# Start supervisor in background (auto-restarts worker on crash with backoff, hourly heartbeat)
./scripts/start_sentinel.sh

# Inspect supervisor, worker PID, heartbeat, and log-derived monitoring span
./scripts/status_sentinel.sh

# Stop supervisor and worker gracefully
./scripts/stop_sentinel.sh
```

### 6. Interactive Audit Dashboard
A React + Vite audit interface providing visual inspection of the live paper trading log, decision feed, and risk parameters:
```bash
cd dashboard
npm install
npm run build   # Production bundle to dist/
npm run dev     # Local development server (default port 5180)
```

### 7. Query Audit Summaries via CLI
```bash
# View Backtest summary
python3 live.py --summary --mode backtest

# View Live summary
python3 live.py --summary --mode live

# View Verified Submission Audit (strictly backtest + live)
python3 live.py --summary --mode all
```

---

## 6. Audit Trail & Verification Data

The canonical record of all autonomous decisions is maintained in `logs/`:
* **`logs/sentinel_trades.jsonl`**: Complete JSON Lines log containing each event, benchmark move, beta, residual z-score, volume ratio, Qwen classification, risk gate outcome, and paper execution status.
* **`logs/sentinel_trades.csv`**: Tabular export of all logged decisions.
* **`logs/submission_audit_trail.csv`**: Verified competition dataset (excludes all mock calibration runs).
* **`logs/heartbeat.log`**: Hourly supervisor heartbeats recording process health and cumulative log-derived monitoring span.
