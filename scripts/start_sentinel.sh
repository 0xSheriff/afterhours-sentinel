#!/usr/bin/env bash
# ==============================================================================
# AfterHours Sentinel - Background Process Launcher
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOGS_DIR="$PROJECT_ROOT/logs"

mkdir -p "$LOGS_DIR"

PID_FILE="$LOGS_DIR/supervisor.pid"
OUTPUT_LOG="$LOGS_DIR/supervisor_stdout.log"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "[Sentinel Warning] Supervisor is already running with PID $PID."
        echo "Check status with: ./scripts/status_sentinel.sh"
        exit 0
    else
        echo "[Sentinel Info] Removing stale PID file from previous run."
        rm -f "$PID_FILE"
    fi
fi

echo "================================================================================"
echo " Starting AfterHours Sentinel Resilient Supervisor in Background..."
echo " Project Directory: $PROJECT_ROOT"
echo " Console Output:    $OUTPUT_LOG"
echo " Crash Log:         $LOGS_DIR/crash.log"
echo " Heartbeat Log:     $LOGS_DIR/heartbeat.log"
echo "================================================================================"

# Load and export environment variables from .env if present
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

cd "$PROJECT_ROOT"
nohup python3 -u supervisor.py --allow-fallback "$@" >> "$OUTPUT_LOG" 2>&1 &
SUPERVISOR_PID=$!
echo "$SUPERVISOR_PID" > "$PID_FILE"

sleep 2

if kill -0 "$SUPERVISOR_PID" 2>/dev/null; then
    echo "✓ Sentinel Supervisor successfully started in background (PID: $SUPERVISOR_PID)!"
    echo "Check status at any time with: ./scripts/status_sentinel.sh"
else
    echo "✗ Failed to launch supervisor. Check $OUTPUT_LOG for errors."
    exit 1
fi
