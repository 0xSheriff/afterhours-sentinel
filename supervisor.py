#!/usr/bin/env python3
"""
AfterHours Sentinel - Resilient Process Supervisor
Continuously supervises `live.py --allow-fallback` to ensure uninterrupted paper trading
through September 27, 2026.

Features:
1. Subprocess Supervision: Runs `live.py --allow-fallback` as a supervised child process.
2. Auto-Restart on Failure: Catches crashes or unexpected exits, logs full traceback/stderr
   with timestamps to `logs/crash.log`, and restarts after a 30s backoff.
3. Hourly Heartbeat: Appends a status line every hour to `logs/heartbeat.log` detailing
   process uptime, total supervisor restarts, and event decisions processed since start.
4. Clean Signal Handling: Propagates SIGINT/SIGTERM gracefully to child process for clean shutdown.
"""

import sys
import os
import time
import json
import signal
import datetime
import subprocess
import threading
import traceback
from typing import Optional, List

# Explicitly ensure .env is loaded into os.environ
try:
    import config  # loads .env via config.py
except ImportError:
    pass

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
CRASH_LOG = os.path.join(LOG_DIR, "crash.log")
HEARTBEAT_LOG = os.path.join(LOG_DIR, "heartbeat.log")
SUPERVISOR_PID_FILE = os.path.join(LOG_DIR, "supervisor.pid")
LIVE_PID_FILE = os.path.join(LOG_DIR, "live.pid")
TRADES_JSONL_LOG = os.path.join(LOG_DIR, "sentinel_trades.jsonl")

RESTART_BACKOFF_SEC = 30
HEARTBEAT_INTERVAL_SEC = 3600  # 1 hour

running = True
current_child_process: Optional[subprocess.Popen] = None
recent_stderr_lines: List[str] = []
stderr_lock = threading.Lock()


def sig_handler(signum, frame):
    """Handles termination signals gracefully."""
    global running, current_child_process
    sig_name = signal.Signals(signum).name
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    msg = f"\n[{now_str[:19]} UTC] [Supervisor] Received {sig_name}. Terminating child process..."
    print(msg, flush=True)
    running = False
    if current_child_process and current_child_process.poll() is None:
        try:
            current_child_process.terminate()
            current_child_process.wait(timeout=5)
        except Exception:
            try:
                current_child_process.kill()
            except Exception:
                pass
    if os.path.exists(LIVE_PID_FILE):
        try:
            os.remove(LIVE_PID_FILE)
        except Exception:
            pass
    if os.path.exists(SUPERVISOR_PID_FILE):
        try:
            os.remove(SUPERVISOR_PID_FILE)
        except Exception:
            pass


def stderr_reader(pipe):
    """Reads child stderr in background, prints live and keeps last 50 lines for crash log."""
    global recent_stderr_lines
    try:
        for line in iter(pipe.readline, ''):
            if not line:
                break
            sys.stderr.write(line)
            sys.stderr.flush()
            with stderr_lock:
                recent_stderr_lines.append(line)
                if len(recent_stderr_lines) > 50:
                    recent_stderr_lines.pop(0)
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def count_events_in_log() -> int:
    """Counts non-empty lines in sentinel_trades.jsonl."""
    if not os.path.exists(TRADES_JSONL_LOG):
        return 0
    try:
        count = 0
        with open(TRADES_JSONL_LOG, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
    except Exception:
        return 0


def compute_live_monitoring_span_hrs() -> float:
    """Computes duration in hours from earliest to latest mode='live' records in the trade log."""
    if not os.path.exists(TRADES_JSONL_LOG):
        return 0.0
    timestamps = []
    try:
        with open(TRADES_JSONL_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("mode") == "live":
                        ts_str = obj.get("timestamp")
                        if ts_str:
                            dt = datetime.datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                            timestamps.append(dt.timestamp())
                except Exception:
                    pass
        if len(timestamps) >= 2:
            return max(0.0, (max(timestamps) - min(timestamps)) / 3600.0)
    except Exception:
        pass
    return 0.0


def log_crash(exit_code: Optional[int], stderr_output: str, exception_msg: Optional[str] = None):
    """Appends crash incident details with UTC timestamp to logs/crash.log."""
    os.makedirs(LOG_DIR, exist_ok=True)
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry = [
        "=" * 80,
        f"CRASH TIMESTAMP: {now_str[:19]} UTC",
        f"EXIT CODE: {exit_code}",
    ]
    if exception_msg:
        entry.append(f"EXCEPTION: {exception_msg}")
    if stderr_output:
        entry.append("STDERR OUTPUT (Recent):")
        entry.append(stderr_output.strip())
    entry.append(f"ACTION: Automatically restarting live.py after {RESTART_BACKOFF_SEC}s backoff.")
    entry.append("=" * 80 + "\n")

    log_content = "\n".join(entry)
    print(f"\n[Supervisor CRASH DETECTED] Logged incident to {CRASH_LOG}", flush=True)
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(log_content)
    except Exception as e:
        print(f"[Supervisor ERROR] Failed writing to crash log: {e}", file=sys.stderr, flush=True)


def write_heartbeat(start_time: float, total_restarts: int, initial_events: int):
    """Appends an hourly heartbeat confirmation line to logs/heartbeat.log."""
    os.makedirs(LOG_DIR, exist_ok=True)
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_dt.isoformat()[:19] + " UTC"
    uptime_sec = time.time() - start_time
    uptime_hrs = uptime_sec / 3600.0
    monitoring_span_hrs = compute_live_monitoring_span_hrs()

    current_events = count_events_in_log()
    session_events = max(0, current_events - initial_events)

    child_status = "RUNNING" if (current_child_process and current_child_process.poll() is None) else "RESTARTING"
    child_pid = current_child_process.pid if (current_child_process and current_child_process.poll() is None) else "N/A"

    line = (
        f"[{now_str}] HEARTBEAT: ALIVE | Monitoring Span: {monitoring_span_hrs:.1f}h (Log-Derived) | "
        f"Process Uptime: {uptime_hrs:.1f}h | "
        f"Supervisor PID: {os.getpid()} | live.py PID: {child_pid} (Status: {child_status}) | "
        f"Restarts: {total_restarts} | Events Processed Since Start: {session_events} "
        f"(Total Logged: {current_events})\n"
    )

    print(f"[Supervisor Heartbeat] {line.strip()}", flush=True)
    try:
        with open(HEARTBEAT_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"[Supervisor ERROR] Failed writing to heartbeat log: {e}", file=sys.stderr, flush=True)


def main():
    global running, current_child_process, recent_stderr_lines

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    os.makedirs(LOG_DIR, exist_ok=True)

    with open(SUPERVISOR_PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    start_time = time.time()
    last_heartbeat_time = start_time
    total_restarts = 0
    initial_events = count_events_in_log()

    extra_args = sys.argv[1:]
    if "--allow-fallback" not in extra_args:
        extra_args.append("--allow-fallback")

    cmd = [sys.executable, "-u", os.path.join(PROJECT_ROOT, "live.py")] + extra_args

    print("=" * 80, flush=True)
    print(f" AFTERHOURS SENTINEL - PROCESS SUPERVISOR", flush=True)
    print(f" Supervisor PID:        {os.getpid()}", flush=True)
    print(f" Supervised Command:    {' '.join(cmd)}", flush=True)
    print(f" Working Directory:     {PROJECT_ROOT}", flush=True)
    print(f" Crash Log:             {CRASH_LOG}", flush=True)
    print(f" Heartbeat Log:         {HEARTBEAT_LOG}", flush=True)
    print(f" Baseline Events Count: {initial_events}", flush=True)
    print("=" * 80, flush=True)

    # Initial start flag - heartbeat is written immediately AFTER child process is spawned and verified
    initial_start = True

    while running:
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"\n[{now_str}] [Supervisor] Starting: {' '.join(cmd)}", flush=True)

        with stderr_lock:
            recent_stderr_lines = []

        try:
            current_child_process = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=None,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            # Spawn background reader for stderr
            stderr_thread = threading.Thread(target=stderr_reader, args=(current_child_process.stderr,), daemon=True)
            stderr_thread.start()

            # Record verified child PID to logs/live.pid
            with open(LIVE_PID_FILE, "w", encoding="utf-8") as f:
                f.write(str(current_child_process.pid))

            # Initial heartbeat entry AFTER verifying child process is active and PID is assigned
            if initial_start:
                time.sleep(0.2)  # Short pause to ensure initial pipe setup
                write_heartbeat(start_time, total_restarts, initial_events)
                initial_start = False
        except Exception as e:
            tb = traceback.format_exc()
            log_crash(exit_code=None, stderr_output="", exception_msg=f"{e}\n{tb}")
            total_restarts += 1
            if running:
                time.sleep(RESTART_BACKOFF_SEC)
            continue

        # Supervisor monitor loop
        while running and current_child_process.poll() is None:
            time.sleep(1)

            now_t = time.time()
            if now_t - last_heartbeat_time >= HEARTBEAT_INTERVAL_SEC:
                write_heartbeat(start_time, total_restarts, initial_events)
                last_heartbeat_time = now_t

        if not running:
            break

        exit_code = current_child_process.poll()
        total_restarts += 1

        if os.path.exists(LIVE_PID_FILE):
            try:
                os.remove(LIVE_PID_FILE)
            except Exception:
                pass

        with stderr_lock:
            captured_stderr = "".join(recent_stderr_lines)

        now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"\n[{now_str}] [Supervisor ALERT] Child process exited with code {exit_code}!", flush=True)
        log_crash(exit_code=exit_code, stderr_output=captured_stderr, exception_msg=None)

        if running:
            print(f"[Supervisor] Waiting {RESTART_BACKOFF_SEC}s backoff before restarting...", flush=True)
            for _ in range(RESTART_BACKOFF_SEC):
                if not running:
                    break
                time.sleep(1)

    if os.path.exists(LIVE_PID_FILE):
        try:
            os.remove(LIVE_PID_FILE)
        except Exception:
            pass

    if os.path.exists(SUPERVISOR_PID_FILE):
        try:
            os.remove(SUPERVISOR_PID_FILE)
        except Exception:
            pass

    print("[Supervisor] Shutdown complete.", flush=True)


if __name__ == "__main__":
    main()
