const fs = require('fs');
const path = require('path');

const csvPath = path.resolve(__dirname, '../../logs/submission_audit_trail.csv');
const jsonlPath = path.resolve(__dirname, '../../logs/sentinel_trades.jsonl');

const publicDataDir = path.resolve(__dirname, '../public/data');
const srcDataDir = path.resolve(__dirname, '../src/data');
const distDataDir = path.resolve(__dirname, '../dist/data');

fs.mkdirSync(publicDataDir, { recursive: true });
fs.mkdirSync(srcDataDir, { recursive: true });
if (fs.existsSync(path.resolve(__dirname, '../dist'))) {
  fs.mkdirSync(distDataDir, { recursive: true });
}

// Primary: JSONL (has all records including live)
// Fallback: CSV (submission subset)
const allRecords = [];
const seen = new Set();

function dedupKey(r) {
  return `${r.timestamp}|${r.event_headline}|${r.decision}`;
}

// Read JSONL first (richer dataset)
if (fs.existsSync(jsonlPath)) {
  const lines = fs.readFileSync(jsonlPath, 'utf-8').trim().split('\n');
  for (const line of lines) {
    if (!line.trim()) continue;
    try {
      const obj = JSON.parse(line);
      const key = dedupKey(obj);
      if (!seen.has(key)) {
        seen.add(key);
        allRecords.push(obj);
      }
    } catch (e) { /* skip malformed lines */ }
  }
}

// Also read CSV for any records not in JSONL
if (fs.existsSync(csvPath)) {
  const raw = fs.readFileSync(csvPath, 'utf-8').trim();
  const lines = raw.split('\n').map(l => l.replace(/\r$/, ''));
  if (lines.length >= 2) {
    const headers = parseCSVRow(lines[0]);
    for (let i = 1; i < lines.length; i++) {
      if (!lines[i].trim()) continue;
      const vals = parseCSVRow(lines[i]);
      const obj = {};
      const numFields = ['expected_move','actual_move','divergence','z_score','volume_ratio','position_size','stop_price','entry_price','exit_price','pnl'];
      headers.forEach((h, idx) => {
        let v = vals[idx] || '';
        if (numFields.includes(h)) v = parseFloat(v) || 0;
        obj[h] = v;
      });
      const key = dedupKey(obj);
      if (!seen.has(key)) {
        seen.add(key);
        allRecords.push(obj);
      }
    }
  }
}

// Also read existing records-full.json or records.json if present (e.g. in Vercel build environment)
const existingPath = fs.existsSync(path.join(publicDataDir, 'records-full.json'))
  ? path.join(publicDataDir, 'records-full.json')
  : path.join(publicDataDir, 'records.json');

if (fs.existsSync(existingPath)) {
  try {
    const existing = JSON.parse(fs.readFileSync(existingPath, 'utf-8'));
    if (Array.isArray(existing)) {
      for (const obj of existing) {
        const key = dedupKey(obj);
        if (!seen.has(key)) {
          seen.add(key);
          allRecords.push(obj);
        }
      }
    }
  } catch (e) { /* ignore parse errors */ }
}

// Safety: If no records found but public records exist, preserve them
if (allRecords.length === 0 && fs.existsSync(path.join(publicDataDir, 'records.json'))) {
  console.warn('No records extracted from logs, preserving existing data files');
  process.exit(0);
}

// Filter out malformed records
const validRecords = allRecords.filter(r => {
  if (!r || typeof r !== 'object') return false;
  if (!r.timestamp || !r.event_headline) return false;
  if (r.null || typeof r.decision !== 'string') return false;
  return true;
});

// Sort by timestamp descending (most recent first)
validRecords.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

// Assign stable IDs across complete log
validRecords.forEach((r, i) => { r.id = i + 1; });

// ── 1. records-full.json (complete log for audit/compliance) ──
const fullJsonContent = JSON.stringify(validRecords, null, 2);
fs.writeFileSync(path.join(publicDataDir, 'records-full.json'), fullJsonContent);
fs.writeFileSync(path.join(srcDataDir, 'records-full.json'), fullJsonContent);
if (fs.existsSync(distDataDir)) {
  fs.writeFileSync(path.join(distDataDir, 'records-full.json'), fullJsonContent);
}

// ── 2. records.json (lean feed: real decisions only; excludes SKIPPED_NO_ASSET_MATCH) ──
const realDecisions = validRecords.filter(r => r.decision !== 'SKIPPED_NO_ASSET_MATCH');
const leanJsonContent = JSON.stringify(realDecisions, null, 2);
fs.writeFileSync(path.join(publicDataDir, 'records.json'), leanJsonContent);
fs.writeFileSync(path.join(srcDataDir, 'records.json'), leanJsonContent);
if (fs.existsSync(distDataDir)) {
  fs.writeFileSync(path.join(distDataDir, 'records.json'), leanJsonContent);
}

// ── 3. summary.json (precomputed KPIs and headline stats) ──
const isLiveMode = (r) => (r.mode || '').toLowerCase().includes('live');
const isBacktestMode = (r) => (r.mode || '').toLowerCase().includes('backtest') || (r.mode || '').toLowerCase().includes('historical_replay');
const isLiveCall = (r) => (r.llm_source || '').includes('[live_api]');
const isFallbackCall = (r) => (r.llm_source || '').includes('fallback') || (r.llm_source || '').includes('rule_classifier');
const isSkippedCall = (r) => (r.llm_source || '') === 'skipped' || (r.decision || '') === 'SKIPPED_NO_ASSET_MATCH';

const liveRecs = validRecords.filter(isLiveMode);
const liveTimestamps = liveRecs.map(r => new Date(r.timestamp).getTime()).filter(t => !isNaN(t));
const liveMinT = liveTimestamps.length ? Math.min(...liveTimestamps) : 0;
const liveMaxT = liveTimestamps.length ? Math.max(...liveTimestamps) : 0;
const liveDurationHrs = liveTimestamps.length ? ((liveMaxT - liveMinT) / 3600000).toFixed(1) : '0.0';

const liveTrades = liveRecs.filter(r => r.decision === 'LONG' || r.decision === 'SHORT');
const liveWins = liveTrades.filter(r => (r.pnl || 0) > 0);
const liveTotalPnl = liveTrades.reduce((s, r) => s + (r.pnl || 0), 0);

// Sharpe Ratio & Max Drawdown
const sortedLiveTrades = [...liveTrades].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
const initialBal = 100000;
let equity = initialBal;
let peakEquity = initialBal;
let maxDdUsd = 0;
let maxDdPct = 0;
const returns = [];

sortedLiveTrades.forEach(t => {
  const pnl = Number(t.pnl || 0);
  const posSize = Number(t.position_size || 150) || 150;
  returns.push(pnl / posSize);
  equity += pnl;
  if (equity > peakEquity) peakEquity = equity;
  const ddUsd = peakEquity - equity;
  const ddPct = peakEquity > 0 ? (ddUsd / peakEquity) * 100 : 0;
  if (ddUsd > maxDdUsd) maxDdUsd = ddUsd;
  if (ddPct > maxDdPct) maxDdPct = ddPct;
});

let sharpeRatio = '0.00';
if (returns.length >= 2) {
  const meanR = returns.reduce((a, b) => a + b, 0) / returns.length;
  const variance = returns.reduce((s, r) => s + Math.pow(r - meanR, 2), 0) / (returns.length - 1);
  const stdR = Math.sqrt(variance);
  if (stdR > 1e-9) {
    const sVal = (meanR / stdR) * Math.sqrt(Math.min(252, Math.max(returns.length * 12, 36)));
    sharpeRatio = sVal.toFixed(2);
  }
}

const liveCalls = liveRecs.filter(isLiveCall).length;
const fallbackCalls = liveRecs.filter(isFallbackCall).length;
const skippedCalls = liveRecs.filter(isSkippedCall).length;
const evaluatedCalls = liveCalls + fallbackCalls;
const liveCallRate = evaluatedCalls > 0 ? ((liveCalls / evaluatedCalls) * 100).toFixed(0) : '100';
const liveNoTrades = liveRecs.filter(r => r.decision === 'NO_TRADE').length;

// Backtest stats
const btRecs = validRecords.filter(isBacktestMode);
const btTrades = btRecs.filter(r => r.decision === 'LONG' || r.decision === 'SHORT');
const btWins = btTrades.filter(r => (r.pnl || 0) > 0);
const btTotalPnl = btRecs.reduce((s, r) => s + (r.pnl || 0), 0);
const btNoTrades = btRecs.filter(r => r.decision === 'NO_TRADE').length;

// Open positions
const openPositions = validRecords.filter(r => 
  (r.decision === 'LONG' || r.decision === 'SHORT') && 
  String(r.exit_reason || '').toUpperCase() === 'OPEN'
);

// Execution clients breakdown
const clientsMap = {};
validRecords.forEach(r => {
  if (r.decision === 'LONG' || r.decision === 'SHORT') {
    const c = r.execution_client || 'Unknown';
    if (!clientsMap[c]) clientsMap[c] = { trades: 0, pnl: 0 };
    clientsMap[c].trades += 1;
    clientsMap[c].pnl = Math.round((clientsMap[c].pnl + (r.pnl || 0)) * 100) / 100;
  }
});

const generatedAt = new Date().toISOString();
const version = Date.now().toString();

const summary = {
  version,
  generated_at: generatedAt,
  total_records: validRecords.length,
  skipped_count: skippedCalls,
  evaluated_count: evaluatedCalls,
  decision_counts: {
    LONG: validRecords.filter(r => r.decision === 'LONG').length,
    SHORT: validRecords.filter(r => r.decision === 'SHORT').length,
    NO_TRADE: validRecords.filter(r => r.decision === 'NO_TRADE').length,
    SKIPPED_NO_ASSET_MATCH: validRecords.filter(r => r.decision === 'SKIPPED_NO_ASSET_MATCH').length
  },
  live: {
    total: liveRecs.length,
    trades_count: liveTrades.length,
    wins_count: liveWins.length,
    win_rate: liveTrades.length > 0 ? ((liveWins.length / liveTrades.length) * 100).toFixed(1) : null,
    total_pnl: Math.round(liveTotalPnl * 100) / 100,
    sharpe_ratio: sharpeRatio,
    max_drawdown_usd: Math.round(maxDdUsd * 100) / 100,
    max_drawdown_pct: maxDdPct.toFixed(3),
    duration_hours: liveDurationHrs,
    start_time: liveMinT,
    end_time: liveMaxT,
    live_calls: liveCalls,
    fallback_calls: fallbackCalls,
    skipped_calls: skippedCalls,
    evaluated_calls: evaluatedCalls,
    live_call_rate: liveCallRate,
    no_trades: liveNoTrades,
    open_positions_count: openPositions.length
  },
  backtest: {
    total: btRecs.length,
    trades_count: btTrades.length,
    wins_count: btWins.length,
    win_rate: btTrades.length > 0 ? ((btWins.length / btTrades.length) * 100).toFixed(0) : '0',
    total_pnl: Math.round(btTotalPnl * 100) / 100,
    no_trades: btNoTrades
  },
  execution_clients: clientsMap,
  open_positions: openPositions
};

const summaryJsonContent = JSON.stringify(summary, null, 2);
fs.writeFileSync(path.join(publicDataDir, 'summary.json'), summaryJsonContent);
fs.writeFileSync(path.join(srcDataDir, 'summary.json'), summaryJsonContent);
if (fs.existsSync(distDataDir)) {
  fs.writeFileSync(path.join(distDataDir, 'summary.json'), summaryJsonContent);
}

console.log(`Successfully generated 3 data files:`);
console.log(`- records.json: ${realDecisions.length} real evaluated decisions (${(Buffer.byteLength(leanJsonContent)/1024/1024).toFixed(2)} MB)`);
console.log(`- records-full.json: ${validRecords.length} full audit records (${(Buffer.byteLength(fullJsonContent)/1024/1024).toFixed(2)} MB)`);
console.log(`- summary.json: precomputed KPIs & totals (${(Buffer.byteLength(summaryJsonContent)/1024).toFixed(2)} KB)`);

function parseCSVRow(row) {
  const result = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < row.length; i++) {
    const ch = row[i];
    if (ch === '"') {
      if (inQuotes && row[i+1] === '"') { current += '"'; i++; }
      else inQuotes = !inQuotes;
    } else if (ch === ',' && !inQuotes) {
      result.push(current); current = '';
    } else {
      current += ch;
    }
  }
  result.push(current);
  return result;
}
