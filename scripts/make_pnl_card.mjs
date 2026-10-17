#!/usr/bin/env node
/**
 * scripts/make_pnl_card.mjs
 *
 * Standalone, re-runnable P&L card generator for AfterHours Sentinel.
 * Reads logs/sentinel_trades.jsonl (and dashboard/public/data/pnl.json if present),
 * renders a dark liquid glass trader-stats card in self-contained HTML,
 * and captures 2x retina screenshots via headless Chrome.
 *
 * Outputs:
 *  - brand/cards/pnl-card-4x3.png  (2048 x 1536)
 *  - brand/cards/pnl-card-16x9.png (1600 x 900)
 */

import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

// ── 1. Data Ingestion & Deduplication ──
const pnlJsonPath = path.join(rootDir, 'dashboard', 'public', 'data', 'pnl.json');
const jsonlPath = path.join(rootDir, 'logs', 'sentinel_trades.jsonl');

let trades = [];

if (fs.existsSync(pnlJsonPath)) {
  try {
    trades = JSON.parse(fs.readFileSync(pnlJsonPath, 'utf8'));
  } catch (err) {
    trades = [];
  }
}

// Fallback or verify with logs/sentinel_trades.jsonl
if (trades.length === 0 && fs.existsSync(jsonlPath)) {
  const seen = new Set();
  const rawLines = fs.readFileSync(jsonlPath, 'utf8').trim().split('\n');
  for (const line of rawLines) {
    if (!line.trim()) continue;
    try {
      const r = JSON.parse(line);
      const key = `${r.timestamp}|${r.event_headline}|${r.decision}`;
      if (!seen.has(key)) {
        seen.add(key);
        if (r.decision === 'LONG' || r.decision === 'SHORT') {
          const isOpen = String(r.exit_reason || '').toUpperCase() === 'OPEN';
          trades.push({
            id: r.id || trades.length + 1,
            timestamp: r.timestamp,
            symbol: r.symbol || 'ASSET',
            side: r.decision,
            entry_time: r.timestamp,
            exit_time: isOpen ? null : (r.exit_timestamp || r.timestamp),
            entry_price: parseFloat(r.entry_price) || 0,
            exit_price: parseFloat(r.exit_price) || 0,
            pnl: isOpen ? 0.0 : Math.round((parseFloat(r.pnl) || 0.0) * 100) / 100,
            exit_reason: r.exit_reason || (isOpen ? 'OPEN' : 'N/A'),
            status: isOpen ? 'OPEN' : 'CLOSED',
          });
        }
      }
    } catch (e) {}
  }
}

if (trades.length === 0) {
  console.error('Error: No trade records found in pnl.json or logs/sentinel_trades.jsonl');
  process.exit(1);
}

// ── 2. Metric Computation ──
const totalTradesCount = trades.length;
const closedTrades = trades
  .filter(t => t.status === 'CLOSED' || (t.exit_reason && t.exit_reason !== 'OPEN' && t.exit_reason !== 'N/A'))
  .sort((a, b) => new Date(a.exit_time || a.timestamp) - new Date(b.exit_time || b.timestamp));

const openTrades = trades.filter(t => t.status === 'OPEN' || t.exit_reason === 'OPEN');
const closedTradesCount = closedTrades.length;
const openTradesCount = openTrades.length;

const wins = closedTrades.filter(t => (t.pnl || 0) > 0);
const losses = closedTrades.filter(t => (t.pnl || 0) < 0);
const breakeven = closedTrades.filter(t => (t.pnl || 0) === 0);

const winsCount = wins.length;
const lossesCount = losses.length;
const breakevenCount = breakeven.length;

const totalRealizedPnl = closedTrades.reduce((acc, t) => acc + (t.pnl || 0), 0);
const winRate = closedTradesCount > 0 ? (winsCount / closedTradesCount) * 100 : 0;

// Formatters
const fmtUSD = (n) => {
  const abs = Math.abs(n);
  const str = abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n >= 0 ? `+$${str}` : `-$${str}`;
};

const fmtPnlColor = (n) => (n >= 0 ? '#22C55E' : '#EF4444');

// Latest closed trade with non-zero, profitable W trades (no loss) and P&L > $20
const qualifyingTrades = closedTrades.filter(t => (t.pnl || 0) > 20);
const latestTradeToFeature = qualifyingTrades.length > 0
  ? qualifyingTrades[qualifyingTrades.length - 1]
  : (closedTrades.filter(t => (t.pnl || 0) > 0).slice(-1)[0] || (closedTrades.length > 0 ? closedTrades[closedTrades.length - 1] : null));

let latestPillText = 'No closed trades yet';
if (latestTradeToFeature) {
  const sym = latestTradeToFeature.symbol || 'ASSET';
  const side = latestTradeToFeature.side || 'TRADE';
  const pnlStr = fmtUSD(latestTradeToFeature.pnl || 0);
  latestPillText = `Latest: ${sym} ${side} closed ${pnlStr}`;
}

// ── 3. Stepped Sparkline Path Generation ──
function generateSteppedSparkline(tradesList, width = 280, height = 74, margin = 8) {
  if (tradesList.length === 0) return '';
  let running = 0;
  const series = [running];
  for (const t of tradesList) {
    running += (t.pnl || 0);
    series.push(running);
  }

  const minVal = Math.min(...series);
  const maxVal = Math.max(...series);
  const valRange = maxVal - minVal === 0 ? 1 : maxVal - minVal;

  const w = width - margin * 2;
  const h = height - margin * 2;

  const points = series.map((val, idx) => {
    const x = margin + (idx / (series.length - 1)) * w;
    const y = margin + (1 - (val - minVal) / valRange) * h;
    return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 };
  });

  // Stepped path: M x0 y0 H x1 V y1 H x2 V y2 ...
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i++) {
    d += ` H ${points[i].x} V ${points[i].y}`;
  }
  return d;
}

// ── 4. Sentinel Star Mark SVG Path (exact vector from brand/favicon.svg) ──
const starMarkSvg = `
<svg viewBox="0 0 256 256" width="30" height="30" fill="none" xmlns="http://www.w3.org/2000/svg">
  <g fill="#D4FF3F">
    <path d="M 132 30 C 132 24, 144 24, 146 31 C 158 76, 180 98, 225 110 C 232 112, 232 124, 226 124 C 166 116, 140 90, 132 30 Z" />
    <path d="M 132 30 C 132 24, 144 24, 146 31 C 158 76, 180 98, 225 110 C 232 112, 232 124, 226 124 C 166 116, 140 90, 132 30 Z" transform="rotate(90 128 128)" />
    <path d="M 132 30 C 132 24, 144 24, 146 31 C 158 76, 180 98, 225 110 C 232 112, 232 124, 226 124 C 166 116, 140 90, 132 30 Z" transform="rotate(180 128 128)" />
    <path d="M 132 30 C 132 24, 144 24, 146 31 C 158 76, 180 98, 225 110 C 232 112, 232 124, 226 124 C 166 116, 140 90, 132 30 Z" transform="rotate(270 128 128)" />
    <path d="M 128 84 Q 135 121 172 128 Q 135 135 128 172 Q 121 135 84 128 Q 121 121 128 84 Z" />
  </g>
</svg>
`;

// ── 5. HTML Template Builder ──
function buildHtmlCard({ format = '4x3' }) {
  const is4x3 = format === '4x3';
  const canvasWidth = is4x3 ? 1024 : 800;
  const canvasHeight = is4x3 ? 768 : 450;
  const cardWidth = is4x3 ? 730 : 660;
  const cardPadding = is4x3 ? '38px 42px' : '26px 32px';
  const heroFontSize = is4x3 ? '52px' : '42px';
  const sparkWidth = is4x3 ? 300 : 250;
  const sparkHeight = is4x3 ? 78 : 64;
  const dividerMargin = is4x3 ? '26px 0' : '18px 0';
  const bottomPillMargin = is4x3 ? '26px' : '18px';
  const footnoteMargin = is4x3 ? '22px' : '14px';

  const sparklineD = generateSteppedSparkline(closedTrades, sparkWidth, sparkHeight, 6);

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>AfterHours Sentinel — P&L Card</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@700;800;900&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600;700;800&display=swap" rel="stylesheet">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
      width: ${canvasWidth}px;
      height: ${canvasHeight}px;
      overflow: hidden;
      background-color: #0D0F12;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      color: #F3F4F6;
      -webkit-font-smoothing: antialiased;
    }

    /* Ambient Canvas Lighting & Grain */
    .canvas-root {
      position: relative;
      width: 100%;
      height: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: 
        radial-gradient(circle at 50% -15%, rgba(212, 255, 63, 0.08) 0%, transparent 55%),
        radial-gradient(circle at 10% 20%, rgba(56, 189, 248, 0.04) 0%, transparent 40%),
        linear-gradient(135deg, rgba(255, 255, 255, 0.02) 0%, transparent 60%),
        #0D0F12;
    }

    /* Grain Overlay via SVG feTurbulence */
    .grain-overlay {
      position: absolute;
      inset: 0;
      opacity: 0.025;
      pointer-events: none;
      background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
    }

    /* Restrained Liquid Glass Card */
    .glass-card {
      position: relative;
      width: ${cardWidth}px;
      padding: ${cardPadding};
      background: rgba(18, 21, 28, 0.82);
      border-radius: 28px;
      border: 1px solid rgba(255, 255, 255, 0.10);
      box-shadow: 
        inset 1px 1px 0 rgba(255, 255, 255, 0.20),
        inset -1px -1px 0 rgba(0, 0, 0, 0.50),
        0 35px 70px -15px rgba(0, 0, 0, 0.85);
      z-index: 1;
    }

    /* Header */
    .header-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .profile-group {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .avatar-circle {
      width: 48px;
      height: 48px;
      border-radius: 50%;
      background: #161922;
      border: 1px solid rgba(212, 255, 63, 0.35);
      box-shadow: inset 0 0 12px rgba(212, 255, 63, 0.12), 0 4px 12px rgba(0, 0, 0, 0.4);
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .name-title {
      font-family: 'Plus Jakarta Sans', sans-serif;
      font-weight: 800;
      font-size: 19px;
      letter-spacing: -0.03em;
      color: #FFFFFF;
      line-height: 1.2;
    }

    .name-subtitle {
      font-size: 13px;
      color: #9CA3AF;
      font-weight: 500;
      letter-spacing: -0.01em;
      margin-top: 1px;
    }

    .live-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      border-radius: 9999px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.10);
      font-size: 12px;
      font-weight: 700;
      color: #F3F4F6;
      letter-spacing: 0.06em;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }

    .pulsing-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #D4FF3F;
      box-shadow: 0 0 10px #D4FF3F, 0 0 2px #D4FF3F;
    }

    /* Hero Stat + Sparkline */
    .hero-section {
      margin-top: ${is4x3 ? '30px' : '20px'};
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
    }

    .hero-stat-block {
      display: flex;
      flex-direction: column;
    }

    .hero-label {
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #9CA3AF;
      margin-bottom: 6px;
    }

    .hero-number {
      font-family: 'JetBrains Mono', monospace;
      font-feature-settings: 'tnum' 1, 'zero' 1;
      font-weight: 800;
      font-size: ${heroFontSize};
      color: ${fmtPnlColor(totalRealizedPnl)};
      line-height: 1;
      letter-spacing: -0.03em;
    }

    .sparkline-wrapper {
      position: relative;
      width: ${sparkWidth}px;
      height: ${sparkHeight}px;
      display: flex;
      align-items: center;
      justify-content: flex-end;
    }

    .sparkline-svg {
      width: 100%;
      height: 100%;
      overflow: visible;
    }

    /* Hairline Divider */
    .hairline-divider {
      height: 1px;
      background: rgba(255, 255, 255, 0.08);
      margin: ${dividerMargin};
    }

    /* 3 Metrics Row */
    .stats-row {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 16px;
    }

    .stat-item {
      display: flex;
      flex-direction: column;
    }

    .stat-label {
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #9CA3AF;
      margin-bottom: 4px;
    }

    .stat-val {
      font-family: 'JetBrains Mono', monospace;
      font-feature-settings: 'tnum' 1;
      font-weight: 700;
      font-size: ${is4x3 ? '22px' : '18px'};
      color: #F3F4F6;
      letter-spacing: -0.02em;
    }

    .stat-val-pnl {
      color: ${fmtPnlColor(totalRealizedPnl)};
    }

    /* Bottom Pill */
    .bottom-pill {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: ${is4x3 ? '13px 18px' : '10px 16px'};
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.07);
      margin-top: ${bottomPillMargin};
      font-size: ${is4x3 ? '13px' : '12px'};
      color: #E5E7EB;
      font-weight: 500;
    }

    .bottom-pill-content {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .bottom-pill-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: ${latestTradeToFeature && latestTradeToFeature.pnl > 0 ? '#22C55E' : '#9CA3AF'};
      box-shadow: ${latestTradeToFeature && latestTradeToFeature.pnl > 0 ? '0 0 6px rgba(34, 197, 94, 0.5)' : 'none'};
    }

    .bottom-pill-chevron {
      color: #6B7280;
      font-size: 16px;
      line-height: 1;
      font-weight: 600;
    }

    /* Footnote */
    .footnote-text {
      text-align: center;
      margin-top: ${footnoteMargin};
      font-size: ${is4x3 ? '13px' : '11px'};
      color: #6B7280;
      letter-spacing: 0.01em;
      font-weight: 500;
      z-index: 1;
    }
  </style>
</head>
<body>
  <div class="canvas-root">
    <div class="grain-overlay"></div>

    <div class="glass-card">
      <!-- Header Row -->
      <div class="header-row">
        <div class="profile-group">
          <div class="avatar-circle">
            ${starMarkSvg}
          </div>
          <div>
            <div class="name-title">AfterHours Sentinel</div>
            <div class="name-subtitle">Event-driven trading agent</div>
          </div>
        </div>
        <div class="live-pill">
          <span class="pulsing-dot"></span>
          <span>LIVE</span>
        </div>
      </div>

      <!-- Hero Stat + Stepped Sparkline -->
      <div class="hero-section">
        <div class="hero-stat-block">
          <div class="hero-label">Total P&amp;L</div>
          <div class="hero-number">${fmtUSD(totalRealizedPnl)}</div>
        </div>
        <div class="sparkline-wrapper">
          <svg class="sparkline-svg" viewBox="0 0 ${sparkWidth} ${sparkHeight}">
            <!-- Glow stroke behind -->
            <path d="${sparklineD}" fill="none" stroke="rgba(34, 197, 94, 0.35)" stroke-width="6" stroke-linecap="square" />
            <!-- Main solid stroke -->
            <path d="${sparklineD}" fill="none" stroke="#22C55E" stroke-width="2.5" stroke-linecap="square" />
          </svg>
        </div>
      </div>

      <!-- Hairline Divider -->
      <div class="hairline-divider"></div>

      <!-- 3 Metrics in Row -->
      <div class="stats-row">
        <div class="stat-item">
          <div class="stat-label">Total P&amp;L</div>
          <div class="stat-val stat-val-pnl">${fmtUSD(totalRealizedPnl)}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">Trades</div>
          <div class="stat-val">${totalTradesCount}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">Win Rate</div>
          <div class="stat-val">${winRate.toFixed(1)}%</div>
        </div>
      </div>

      <!-- Bottom Pill -->
      <div class="bottom-pill">
        <div class="bottom-pill-content">
          <span class="bottom-pill-dot"></span>
          <span>${latestPillText}</span>
        </div>
        <span class="bottom-pill-chevron">›</span>
      </div>
    </div>

    <!-- Footnote below card -->
    <div class="footnote-text">Bitget Demo + simulated fills · realized P&amp;L</div>
  </div>
</body>
</html>`;
}

// ── 6. Screenshot Engine via Headless Chrome ──
const cardsDir = path.join(rootDir, 'brand', 'cards');
if (!fs.existsSync(cardsDir)) {
  fs.mkdirSync(cardsDir, { recursive: true });
}

const chromeBin = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
if (!fs.existsSync(chromeBin)) {
  console.error(`Chrome binary not found at ${chromeBin}`);
  process.exit(1);
}

const targets = [
  {
    format: '4x3',
    file: 'pnl-card-4x3.png',
    viewport: '1024,768',
    targetPx: '2048x1536'
  },
  {
    format: '16x9',
    file: 'pnl-card-16x9.png',
    viewport: '800,450',
    targetPx: '1600x900'
  }
];

console.log('───────────────────────────────────────────────────────');
console.log('AfterHours Sentinel — P&L Card Image Generator');
console.log('───────────────────────────────────────────────────────');
console.log(`Input Source:       ${fs.existsSync(pnlJsonPath) ? 'pnl.json' : 'sentinel_trades.jsonl'}`);
console.log(`Total Trades:       ${totalTradesCount} (Closed: ${closedTradesCount}, Open: ${openTradesCount})`);
console.log(`W / L / Breakeven:  ${winsCount}W / ${lossesCount}L / ${breakevenCount}BE`);
console.log(`Win Rate:           ${winRate.toFixed(1)}% (wins / closed)`);
console.log(`Total Realized PnL: ${fmtUSD(totalRealizedPnl)}`);
console.log(`Latest Trade:       ${latestPillText}`);
console.log('───────────────────────────────────────────────────────\n');

for (const t of targets) {
  const htmlContent = buildHtmlCard({ format: t.format });
  const tmpHtmlPath = path.join(cardsDir, `_temp_${t.format}.html`);
  const outPngPath = path.join(cardsDir, t.file);

  fs.writeFileSync(tmpHtmlPath, htmlContent, 'utf8');
  const cmd = `"${chromeBin}" --headless --disable-gpu --no-sandbox --disable-background-networking --disable-default-apps --disable-sync --disable-extensions --hide-scrollbars --force-device-scale-factor=2 --window-size=${t.viewport} --virtual-time-budget=1200 --screenshot="${outPngPath}" "file://${tmpHtmlPath}"`;
  
  try {
    execSync(cmd, { stdio: 'pipe' });
    fs.unlinkSync(tmpHtmlPath);

    // Verify image dimensions with sips
    const sipsOut = execSync(`sips -g pixelWidth -g pixelHeight "${outPngPath}"`, { encoding: 'utf8' });
    const w = sipsOut.match(/pixelWidth:\s*(\d+)/)?.[1];
    const h = sipsOut.match(/pixelHeight:\s*(\d+)/)?.[1];
    const stats = fs.statSync(outPngPath);

    console.log(`✓ Generated ${t.file}:`);
    console.log(`  Path:       ${outPngPath}`);
    console.log(`  Resolution: ${w}x${h} (expected ${t.targetPx})`);
    console.log(`  File Size:  ${Math.round(stats.size / 1024)} KB\n`);
  } catch (err) {
    if (fs.existsSync(tmpHtmlPath)) fs.unlinkSync(tmpHtmlPath);
    console.error(`Failed to generate ${t.file}:`, err.message);
    process.exit(1);
  }
}

console.log('All P&L cards successfully generated in brand/cards/ !');
