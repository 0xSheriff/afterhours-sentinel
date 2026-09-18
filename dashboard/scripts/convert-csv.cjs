const fs = require('fs');
const path = require('path');

const csvPath = path.resolve(__dirname, '../../logs/submission_audit_trail.csv');
const jsonlPath = path.resolve(__dirname, '../../logs/sentinel_trades.jsonl');
const publicOutPath = path.resolve(__dirname, '../public/data/records.json');
const distOutPath = path.resolve(__dirname, '../dist/data/records.json');
const srcOutPath = path.resolve(__dirname, '../src/data/records.json');

fs.mkdirSync(path.dirname(publicOutPath), { recursive: true });
fs.mkdirSync(path.dirname(srcOutPath), { recursive: true });
if (fs.existsSync(path.resolve(__dirname, '../dist'))) {
  fs.mkdirSync(path.dirname(distOutPath), { recursive: true });
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

// Sort by timestamp descending (most recent first for display)
allRecords.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

// Assign stable IDs
allRecords.forEach((r, i) => { r.id = i + 1; });

const jsonContent = JSON.stringify(allRecords, null, 2);
fs.writeFileSync(publicOutPath, jsonContent);
fs.writeFileSync(srcOutPath, jsonContent);
if (fs.existsSync(path.resolve(__dirname, '../dist'))) {
  fs.mkdirSync(path.dirname(distOutPath), { recursive: true });
  fs.writeFileSync(distOutPath, jsonContent);
}
console.log(`Converted ${allRecords.length} deduplicated records to ${publicOutPath}`);

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
