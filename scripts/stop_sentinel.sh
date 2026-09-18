#!/usr/bin/env bash
# ==============================================================================
# AfterHours Sentinel - Graceful Background Stopper
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOGS_DIR="$PROJECT_ROOT/logs"
PID_FILE="$LOGS_DIR/supervisor.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "[Sentinel Info] No supervisor.pid found. Supervisor is not running."
    exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    echo "Sending SIGTERM to supervisor (PID: $PID)..."
    kill -TERM "$PID"
    for i in {1..10}; do
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "✓ Supervisor stopped cleanly."
            rm -f "$PID_FILE"
            exit 0
        fi
        sleep 1
    done
    echo "Process did not terminate within 10s, sending SIGKILL..."
    kill -9 "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "✓ Supervisor force stopped."
else
    echo "Process with PID $PID was already stopped. Cleaning up stale PID file."
    rm -f "$PID_FILE"
fi
