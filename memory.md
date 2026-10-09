# AfterHours Sentinel — Project Memory

## 1. Project Overview
- **Purpose**: Autonomous 7×24 event-driven divergence trading agent for Bitget's tokenized US equities (`rTokens` / USDT-M stock perpetual futures), built for the **Bitget AI Base Camp Hackathon S2 (Track 2: Agentic Trading · Sub-theme: Event-Driven Agent)**.
- **Core Thesis**: Exploits microstructure overreactions and catalyst continuation during the US extended/overnight session (`20:00–13:30 UTC`) when US underlying equity markets are dark or thin while Bitget rToken perpetuals trade 24/7.
- **Current Stage**: Live 24/7 competition-period paper/demo run successfully migrated to dedicated Ubuntu 24.04 VPS (`38.49.214.61`, Montreal) running unattended under PM2 (`afterhours-sentinel`) with systemd boot persistence and automated health checks (`507.9+ hours` logged, `3,926+` events); React + Tailwind Audit Dashboard deployed at `https://afterhours-sentinel.vercel.app/`; brand assets and `1:50` HyperFrames demo videos rendered and QA'd.

## 2. Architecture
1. **Stage 1 — Catalyst Ingestion (`news_stream.py` / `event_listener.py`)**: Polls Finnhub, Polygon, and news RSS feeds (`NEWS_POLL_INTERVAL_SECONDS = 30`), deduplicating headlines, checking event freshness (`4.0h`), and filtering against the 15-asset universe.
2. **Stage 2 — Deterministic Divergence Engine (`divergence_engine.py` / `divergence.py`)**: Computes 30-day rolling regression $\beta$ against benchmarks (`QQQ` 6-peer composite + `BTCUSDT` crypto-session sentiment proxy), calculates expected return $\hat{r}_i$, residual divergence $\epsilon_i = r_i - \hat{r}_i$, rolling Z-score $z = \epsilon_i / \sigma_\epsilon$ (with floor $\sigma_{\min} = 0.008$), and relative volume ratio $V_{\text{ratio}}$.
3. **Stage 3 — LLM Sentiment & Directional Analyst (`llm_analyst.py`)**: Queries Groq Cloud API (`qwen/qwen3.8-27b`) with deterministic regex/keyword fallback when API rate limits or network timeouts occur.
4. **Stage 4 — Hybrid Dual-Mode Risk Gate (`risk_engine.py`)**: Routes events by category (`earnings`, `guidance`, `analyst` $\to$ `MOMENTUM`; `macro`, `regulatory`, `corporate`, `general` $\to$ `MEAN_REVERSION`). Enforces $|z| \ge 2.0\sigma$, $V_{\text{ratio}} < 0.50$, LLM alignment/contradiction check, $5\%$ position sizing, $1.5\%$ hard stop-loss, max $3$ open positions, and $3\%$ daily loss circuit breaker.
5. **Stage 5 — Smart Hybrid Execution Router (`execution.py`)**: Routes the 8 Bitget Demo listed contracts (`NVDAUSDT`, `TSLAUSDT`, `AAPLUSDT`, `GOOGLUSDT`, `AMZNUSDT`, `METAUSDT`, `COINUSDT`, `MSTRUSDT`) to live Bitget V2 USDT-Futures Demo exchange execution (`SUSTAINED` / `SBTCUSDT` demo margin), and routes the 7 unlisted symbols (`MSFT`, `AMD`, `INTC`, `ARM`, `PLTR`, `BABA`, `NFLX`) to client-side paper simulation (`[Smart Hybrid: Paper Fallback]`).
6. **Supervisor & Background Daemons**: `supervisor.py` manages `live.py --allow-fallback` with 30s crash restart and hourly heartbeat, and spawns `scripts/auto_push_records.py` to continuously update records.
7. **Audit Dashboard (`dashboard/`)**: Vite + React + Tailwind single-page application deployed on Vercel (`https://afterhours-sentinel.vercel.app/`).

## 3. Tech Stack
- **Backend / Agent**: Python 3.12/3.11+, `requests`, `numpy`, `pandas`, `python-dotenv`, `unittest` (66 unit tests passing).
- **Process Management**: PM2 v7.0.4 + `pm2-logrotate` + systemd on Ubuntu 24.04 LTS VPS (`sheriff-vps`, 2 vCPU, 2 GB RAM, 2 GB swap).
- **Environment Management**: `uv` virtual environment in `.venv/`.
- **LLM Inference**: Groq Cloud REST API (`qwen/qwen3.8-27b`).
- **Market Data & Execution**: Bitget OpenAPI v2 (`USDT-FUTURES` Demo Trading), Finnhub REST API, Polygon.io REST API, Yahoo Finance fallback.
- **Frontend (`dashboard/`)**: React 19, Vite, Tailwind CSS v4, Framer Motion, Lucide React, deployed on Vercel.
- **Video Production**: HyperFrames CLI v0.8.142 + GSAP 3.12.5 compositions, Playwright high-DPI live browser capture.

## 4. Current State
- **VPS Host (`build` / `38.49.214.61`)**: Active and healthy.
  - PM2 service: `afterhours-sentinel` online (Supervisor PID: 4727, live.py PID: 4734, autopush PID: 4737).
  - Memory consumption: Total system used 553 MB, 1.4 GB available RAM, 0 B swap used.
  - Start timestamp: `2026-10-08 23:47:39 UTC`.
  - Telemetry logs restored: 3,926 records in `sentinel_trades.jsonl`.
- **Unit Tests**: 66/66 passing on the VPS virtual environment (`.venv/bin/python3 -m unittest discover -s tests -v`).
- **Maintenance & Runbook**:
  - `~/apps/scripts/healthcheck.sh` (scheduled every 15 min via cron).
  - `~/apps/scripts/backup_weekly.sh` (scheduled weekly via cron, rotates 4 weeks).
  - `~/apps/SERVER.md` operational runbook written on the VPS.

## 5. Recent Changes
- **2026-10-09**: Wired official AfterHours Sentinel brand assets, favicon suite, manifest, and responsive header logo into live Vercel web app (`https://afterhours-sentinel.vercel.app/`).
  - Generated and placed complete favicon suite in `dashboard/public/` and root `public/`: `favicon.svg`, multi-res `favicon.ico` (16, 32, 48), `favicon-16.png`, `favicon-32.png`, `favicon-192.png`, `favicon-512.png`, `apple-touch-icon.png` (180×180), `og-image.png` (1200×630), and `site.webmanifest`.
  - Declared full metadata in `dashboard/index.html`: theme colors (`#0D0F12` dark, `#D4FF3F` light), SVG-first icon hierarchy, manifest, and absolute Open Graph / Twitter image tags.
  - Replaced temporary `AH` text block in `dashboard/src/App.jsx` with responsive header brand lockup (desktop wordmark + mark, mobile square mark only, zero CLS), loading state spinner mark, and footer marks.
  - Deployed to Vercel production and verified all 9 asset endpoints return HTTP 200 with matching Content-Type. Verified live responsive layouts at 375px, 768px, and 1440px via headless browser screenshots.
- **2026-10-09**: Migrated AfterHours Sentinel onto dedicated Ubuntu 24.04 VPS (`build`, `38.49.214.61`).
  - Cloned repository into `/home/sheriff/apps/afterhours-sentinel`.
  - Built Python virtual environment via `uv` and verified 66/66 unit tests passed.
  - Copied `.env` and secured with `chmod 600`.
  - Restored complete historical logs (`sentinel_trades.jsonl`, `heartbeat.log`, `submission_audit_trail.csv`) without overwriting.
  - Verified read-only reachability to Bitget Demo API (200 OK), Groq API (200 OK), and news streams.
  - Launched supervisor under PM2 (`ecosystem.config.cjs`) with `pm2-logrotate` and systemd boot enablement.
  - Verified 10-minute memory stability (~145 MB total RSS across all processes, 0 swap used).
  - Installed 15-minute automated health check and weekly backup rotation.
  - Documented server procedures in `~/apps/SERVER.md`.
  - Executed Step 11 Reboot Test (`sudo reboot`): systemd automatically resurrected PM2 (`afterhours-sentinel`), bringing supervisor (PID 1073), live engine (PID 1105), and autopush (PID 1108) back online with verified heartbeat (`509.2h` span, `3,944` records restored, 1,490 MB RAM available).

## 6. Important Decisions
- **Smart Hybrid Execution Transparency**: Always distinguish live Bitget Demo exchange fills from client-side paper fallback fills.
- **Dual-Mode Risk Routing**: `earnings`, `guidance`, and `analyst` events route to `MOMENTUM`; `macro`, `regulatory`, `corporate`, and `general` events route to `MEAN_REVERSION`.
- **VPS Architecture**: Run `supervisor.py --allow-fallback` under PM2 as user `sheriff` to preserve the built-in 30s crash recovery, hourly heartbeat, and autopush daemon, backed by systemd boot resurrection (`pm2-sheriff.service`).
- **Brand Consistency**: Live Vercel SPA renders official vector mark (`brand/favicon.svg`) and typography lockup across dark/light themes without layout shifts, serving standard PWA manifests and social preview cards.

## 7. Known Issues
- Bitget Demo `USDT-FUTURES` environment lists 8 of the 15 tracked US equities (the remaining 7 use the Smart Hybrid Router's client-side paper simulation fallback).
- Auto-push to GitHub from the VPS is fully resolved: authenticates using a dedicated ed25519 deploy key (`~/.ssh/github_sentinel`) over SSH with verified write permissions.

## 8. Current Task
- Completed brand asset wiring and live Vercel deployment verification. All favicons, manifest, head metadata, and responsive header/footer logos are live and verified.

## 9. Next Steps
1. Final submission of Hackathon S2 deliverables (Google Form answers, live Vercel dashboard URL, rendered demo videos, and verified VPS run records).

## 10. Important Files
- VPS Repository: `/home/sheriff/apps/afterhours-sentinel`
- VPS Server Runbook: `/home/sheriff/apps/SERVER.md`
- VPS Health Check Script: `/home/sheriff/apps/scripts/healthcheck.sh`
- VPS Backup Script: `/home/sheriff/apps/scripts/backup_weekly.sh`
- Config & Strategy: `config.py`, `live.py`, `supervisor.py`, `divergence_engine.py`, `risk_engine.py`, `execution.py`
- Local Rendered Videos: `afterhours-sentinel-demo-16x9.mp4`, `afterhours-sentinel-demo-9x16.mp4`

## 11. Environment & Configuration
- Python in `.venv/` on VPS (`/home/sheriff/apps/afterhours-sentinel/.venv/bin/python3`).
- PM2 configuration: `/home/sheriff/apps/afterhours-sentinel/ecosystem.config.cjs`.
- Crontab on VPS: `crontab -l` manages health check and backup schedules.
- Secrets: `/home/sheriff/apps/afterhours-sentinel/.env` (`chmod 600`). Never commit or display.

## 12. Development Rules
- Never expose `.env` or private credentials.
- Never conflate live exchange demo fills, client-side paper fallback fills, and historical backtest calibration records.
- Always update `memory.md` after meaningful codebase changes.

