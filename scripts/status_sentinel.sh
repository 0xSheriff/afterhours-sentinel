#!/usr/bin/env bash
# ==============================================================================
# AfterHours Sentinel - Status & Heartbeat Checker
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOGS_DIR="$PROJECT_ROOT/logs"
SUPERVISOR_PID_FILE="$LOGS_DIR/supervisor.pid"
LIVE_PID_FILE="$LOGS_DIR/live.pid"

echo "================================================================================"
echo " AFTERHOURS SENTINEL - RUNTIME SUPERVISOR & WORKER STATUS"
echo " Time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "================================================================================"

# 1. Supervisor Process Check
if [ -f "$SUPERVISOR_PID_FILE" ]; then
    SUP_PID=$(cat "$SUPERVISOR_PID_FILE")
    if kill -0 "$SUP_PID" 2>/dev/null; then
        echo "Supervisor Process: ACTIVE (PID: $SUP_PID)"
    else
        echo "Supervisor Process: STOPPED (Stale PID $SUP_PID)"
    fi
else
    echo "Supervisor Process: NOT RUNNING (No supervisor.pid)"
fi

# 2. Live Worker Process Check
if [ -f "$LIVE_PID_FILE" ]; then
    WORKER_PID=$(cat "$LIVE_PID_FILE")
    if kill -0 "$WORKER_PID" 2>/dev/null; then
        echo "Live Worker (live.py): ACTIVE (PID: $WORKER_PID)"
    else
        echo "Live Worker (live.py): STOPPED / RESTARTING (Stale PID $WORKER_PID)"
    fi
else
    echo "Live Worker (live.py): NOT RUNNING (No live.pid)"
fi

echo ""
echo "--- LATEST HEARTBEAT (Last 3 hourly ticks) ---"
if [ -f "$LOGS_DIR/heartbeat.log" ]; then
    tail -n 3 "$LOGS_DIR/heartbeat.log"
else
    echo "(No heartbeat log created yet)"
fi

echo ""
echo "--- CRASH LOG STATUS ---"
if [ -f "$LOGS_DIR/crash.log" ]; then
    CRASH_COUNT=$(grep -c "CRASH TIMESTAMP" "$LOGS_DIR/crash.log" 2>/dev/null || echo "0")
    echo "Total Recorded Incidents: $CRASH_COUNT"
    if [ "$CRASH_COUNT" -gt "0" ]; then
        echo "Most Recent Incident:"
        tail -n 6 "$LOGS_DIR/crash.log"
    fi
else
    echo "No crashes recorded (Clean run)."
fi

echo ""
echo "--- LIVE PAPER TRADING MONITORING SPAN (Log-Derived) ---"
if [ -f "$LOGS_DIR/sentinel_trades.jsonl" ]; then
    python3 -c "
import json, datetime
timestamps = []
with open('$LOGS_DIR/sentinel_trades.jsonl') as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try:
            r = json.loads(line)
            if r.get('mode') == 'live' and r.get('timestamp'):
                dt = datetime.datetime.fromisoformat(str(r['timestamp']).replace('Z', '+00:00'))
                timestamps.append(dt)
        except Exception: pass
if len(timestamps) >= 2:
    min_t, max_t = min(timestamps), max(timestamps)
    diff_hrs = (max_t - min_t).total_seconds() / 3600.0
    print(f'Live Mode Events  : {len(timestamps)} records')
    print(f'Earliest Decision : {min_t.strftime(\"%Y-%m-%d %H:%M:%S UTC\")}')
    print(f'Latest Decision   : {max_t.strftime(\"%Y-%m-%d %H:%M:%S UTC\")}')
    print(f'Monitoring Span   : {diff_hrs:.1f} hours')
elif len(timestamps) == 1:
    print(f'Live Mode Events  : 1 record ({timestamps[0].strftime(\"%Y-%m-%d %H:%M:%S UTC\")}) | Monitoring Span: 0.0 hours')
else:
    print('No mode=\"live\" records found in log.')
"
else
    echo "(No trade log file found)"
fi

echo ""
echo "--- TOTAL DECISION RECORDS IN LOG ---"
if [ -f "$LOGS_DIR/sentinel_trades.jsonl" ]; then
    COUNT=$(grep -c '^{.*}$' "$LOGS_DIR/sentinel_trades.jsonl" 2>/dev/null || wc -l < "$LOGS_DIR/sentinel_trades.jsonl")
    echo "Total Decisions in Log: $COUNT records"
    echo "Latest Decision:"
    tail -n 1 "$LOGS_DIR/sentinel_trades.jsonl" | python3 -m json.tool 2>/dev/null || tail -n 1 "$LOGS_DIR/sentinel_trades.jsonl"
else
    echo "(No trade log file found)"
fi
echo "================================================================================"
