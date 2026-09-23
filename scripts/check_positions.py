#!/usr/bin/env python3
"""
AfterHours Sentinel - Bitget Demo Position & Balance Inspector
Queries live account equity, margin status, and open positions from Bitget Demo environment.
"""

import os
import sys
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from execution import BitgetAgentHubClient

def main():
    api_key, api_secret, passphrase, source = config.load_bitget_credentials()
    
    print("=" * 80)
    print(" BITGET DEMO ACCOUNT & POSITIONS INSPECTOR")
    print(f" Credentials Source: {source}")
    print("=" * 80)
    
    client = BitgetAgentHubClient(
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase
    )
    
    # 1. Account Balance
    st_bal, _, body_bal = client.get_account_balance(category="USDT-FUTURES")
    if st_bal == 200 and isinstance(body_bal, dict) and body_bal.get("code") == "00000":
        data = body_bal.get("data", [])
        if isinstance(data, list) and len(data) > 0:
            usdt_acc = data[0]
            equity = float(usdt_acc.get("usdtEquity") or usdt_acc.get("accountEquity") or 0.0)
            available = float(usdt_acc.get("available") or 0.0)
            unrealized = float(usdt_acc.get("unrealizedPL") or 0.0)
            print(f"\n[ACCOUNT BALANCE]")
            print(f"  USDT Equity       : ${equity:,.2f} USDT")
            print(f"  Available Margin  : ${available:,.2f} USDT")
            print(f"  Unrealized PnL    : ${unrealized:+,.2f} USDT")
            
            assets = usdt_acc.get("assetList", [])
            if assets:
                asset_strs = [f"{a.get('available', 0)} {a.get('coin')}" for a in assets]
                print(f"  Other Asset Balances: {', '.join(asset_strs)}")
    else:
        print(f"\n[ACCOUNT BALANCE ERROR] HTTP {st_bal}: {body_bal}")

    # 2. Open Positions (V3 Futures API)
    st_pos, _, body_pos = client.send_http_request("GET", "/api/v3/position/current-position", params={"category": "USDT-FUTURES"})
    positions = []
    if st_pos == 200 and isinstance(body_pos, dict) and body_pos.get("code") == "00000":
        pos_data = body_pos.get("data", {})
        if isinstance(pos_data, dict):
            positions = pos_data.get("list", [])
        elif isinstance(pos_data, list):
            positions = pos_data

    # Fallback to V2 Mix if empty
    if not positions:
        st_pos2, _, body_pos2 = client.send_http_request("GET", "/api/v2/mix/position/all-position", params={"productType": "usdt-futures"})
        if st_pos2 == 200 and isinstance(body_pos2, dict) and body_pos2.get("code") == "00000":
            positions = body_pos2.get("data", [])

    print("\n[OPEN POSITIONS]")
    if not positions:
        print("  ✓ No open positions currently on Bitget Demo.")
    else:
        print(f"  Found {len(positions)} active position(s):\n")
        print(f"  {'Symbol':<12} {'Side':<8} {'Size':<12} {'Entry Price':<14} {'Mark Price':<14} {'PnL (USDT)':<14} {'ROI %':<10} {'Leverage'}")
        print("  " + "-" * 88)
        for p in positions:
            sym = p.get("symbol", "N/A")
            side = p.get("posSide", p.get("holdSide", "N/A")).upper()
            total = float(p.get("total", p.get("available", 0.0)))
            entry = float(p.get("avgPrice", p.get("openPriceAvg", 0.0)))
            mark = float(p.get("markPrice", 0.0))
            pnl = float(p.get("unrealisedPnl", p.get("unrealizedPL", 0.0)))
            roi = float(p.get("profitRate", 0.0)) * 100
            lev = f"{p.get('leverage', '1')}x ({p.get('marginMode', 'cross')})"
            
            print(f"  {sym:<12} {side:<8} {total:<12.4f} ${entry:<13,.2f} ${mark:<13,.2f} ${pnl:<+13.2f} {roi:<+9.2f}% {lev}")

    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
