#!/usr/bin/env python3
"""
AfterHours Sentinel - Real-time Git & Vercel Auto-Push Daemon
Continuously synchronizes live trade decisions from logs/sentinel_trades.jsonl
into dashboard/public/data/records.json, stages them, commits, and pushes to origin/main.
This ensures the live Vercel deployment (https://afterhours-sentinel.vercel.app/) stays updated.
"""

import os
import sys
import time
import subprocess
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, "logs", "auto_push.log")
POLL_INTERVAL_SEC = 30
MIN_PUSH_INTERVAL_SEC = 120  # Rate limit: push at most once every 2 minutes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AutoPush] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

def run_cmd(cmd, cwd=BASE_DIR):
    res = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def sync_records():
    code, out, err = run_cmd("node dashboard/scripts/convert-csv.cjs")
    if code != 0:
        logging.warning(f"convert-csv.cjs warning: {err or out}")
    return code == 0

def check_uncommitted():
    files_to_check = [
        "dashboard/public/data/records.json",
        "dashboard/src/data/records.json",
        "logs/sentinel_trades.jsonl",
        "logs/sentinel_trades.csv"
    ]
    code, out, _ = run_cmd(f"git status --porcelain {' '.join(files_to_check)}")
    return bool(out.strip())

def push_updates():
    sync_records()
    
    files_to_stage = [
        "dashboard/public/data/records.json",
        "dashboard/src/data/records.json",
        "logs/sentinel_trades.jsonl",
        "logs/sentinel_trades.csv"
    ]
    run_cmd(f"git add {' '.join(files_to_stage)}")
    
    code, _, _ = run_cmd("git diff --cached --quiet")
    if code == 0:
        return False  # No staged changes
    
    # Count records for commit message
    rec_count = "updated"
    try:
        import json
        p = os.path.join(BASE_DIR, "dashboard", "public", "data", "records.json")
        if os.path.exists(p):
            with open(p) as f:
                d = json.load(f)
                rec_count = f"{len(d)} records"
    except Exception:
        pass

    commit_msg = f"telemetry: sync live trade records ({rec_count}) [skip ci]"
    code, out, err = run_cmd(f'git commit -m "{commit_msg}"')
    if code != 0:
        logging.error(f"Git commit failed: {err or out}")
        return False

    logging.info(f"Committed: {commit_msg}")
    
    code, out, err = run_cmd("git push origin main")
    if code == 0:
        logging.info("Pushed successfully to origin/main -> Vercel will trigger deploy")
        return True
    else:
        logging.error(f"Git push failed: {err or out}")
        return False

def main():
    logging.info(f"Auto-push daemon started (poll={POLL_INTERVAL_SEC}s, min_push_interval={MIN_PUSH_INTERVAL_SEC}s)")
    last_push_time = 0
    
    # Initial sync & push check on start
    try:
        if check_uncommitted():
            if push_updates():
                last_push_time = time.time()
    except Exception as e:
        logging.error(f"Startup sync error: {e}")

    while True:
        try:
            time.sleep(POLL_INTERVAL_SEC)
            now = time.time()
            if (now - last_push_time) < MIN_PUSH_INTERVAL_SEC:
                continue
                
            if check_uncommitted():
                if push_updates():
                    last_push_time = time.time()
        except KeyboardInterrupt:
            logging.info("Auto-push daemon stopped by user")
            break
        except Exception as e:
            logging.error(f"Loop error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
