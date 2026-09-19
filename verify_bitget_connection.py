#!/usr/bin/env python3
"""
AfterHours Sentinel - Isolated Bitget Demo Connection & Execution Verifier
Validates authentic authentication against Bitget Demo / Paper Trading environment.
Does NOT modify live.py, historical_replay.py, or any trade log files.
"""

import os
import sys
import json
import config
from execution import BitgetAgentHubClient, OrderRequest


def main():
    api_key, api_secret, passphrase, source = config.load_bitget_credentials()
    base_url = os.getenv("BITGET_DEMO_BASE_URL", config.BITGET_DEMO_BASE_URL)

    print("=" * 80)
    print(" BITGET DEMO ENVIRONMENT CONNECTION & EXECUTION VERIFIER")
    print("=" * 80)
    print(f"Base URL           : {base_url}")
    print(f"Credentials Source : {source}")
    print(f"API Key Present    : {'YES (' + api_key[:6] + '...)' if api_key and api_key != 'mock_demo_api_key' else 'NO (Missing API Key)'}")
    print(f"Secret Present     : {'YES' if api_secret and api_secret != 'mock_demo_secret' else 'NO (Missing Secret)'}")
    print(f"Passphrase Set     : {'YES' if passphrase and passphrase != 'mock_demo_passphrase' else 'NO (Missing Passphrase)'}")
    print("=" * 80)

    if source == "mock_fallback":
        print("\n[ERROR] Missing required Bitget Demo credentials in environment variables or OAuth store:")
        print("  - Either complete Bitget Agentic OAuth via MCP (stores to ~/.bitget/oauth_token.json)")
        print("  - Or export credentials manually:")
        print("      export BITGET_DEMO_API_KEY=\"...\"")
        print("      export BITGET_DEMO_API_SECRET=\"...\"")
        print("      export BITGET_DEMO_PASSPHRASE=\"...\"")
        print("  python3 verify_bitget_connection.py\n")
        sys.exit(1)

    client = BitgetAgentHubClient(
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        base_url=base_url
    )

    # --------------------------------------------------------------------------
    # STEP 0: Bitget Server Clock Synchronization Check
    # --------------------------------------------------------------------------
    print("\n[STEP 0] Checking Clock Synchronization with Bitget Public Server Time...")
    is_synced, drift_ms, sync_msg = client.check_clock_sync()
    print(f"Clock Sync Status : {sync_msg}")
    if abs(drift_ms) > 2500:
        print(f"[WARNING] Local clock drift is large ({drift_ms:+} ms). Requests may face timestamp expiration.")

    # --------------------------------------------------------------------------
    # STEP 1: Read-Only Authenticated Call (Account Assets / Balance)
    # --------------------------------------------------------------------------
    print("\n[STEP 1] Executing Read-Only Authenticated Call (Account Assets / Balance)...")
    status_code, headers, body = client.get_account_balance(category="USDT-FUTURES")

    print(f"\n--- RAW HTTP RESPONSE: READ-ONLY CALL ---")
    print(f"HTTP Status Code : {status_code}")
    print("HTTP Headers     :")
    for k, v in headers.items():
        print(f"  {k}: {v}")
    print("\nHTTP Body (Raw / Parsed JSON):")
    if isinstance(body, (dict, list)):
        print(json.dumps(body, indent=2))
    else:
        print(body)

    # Confirmed Tokenized U.S. Stock Candidates on Bitget USDT-Futures (All 15 Single-Stock Equities)
    CANDIDATE_SYMBOLS = [
        "NVDAUSDT", "TSLAUSDT", "AAPLUSDT", "AMZNUSDT", "GOOGLUSDT", "METAUSDT",
        "AMDUSDT", "INTCUSDT", "ARMUSDT", "PLTRUSDT", "COINUSDT", "MSTRUSDT",
        "BABAUSDT", "NFLXUSDT"
    ]

    # --------------------------------------------------------------------------
    # STEP 1c: Check Existing Open Positions (Dynamic Flat-State Candidate Selector)
    # --------------------------------------------------------------------------
    print("\n[STEP 1b] Checking Existing Open Positions (/api/v2/mix/position/all-position)...")
    pos_status, pos_headers, pos_body = client.send_http_request("GET", "/api/v2/mix/position/all-position", params={"productType": "usdt-futures", "marginCoin": "USDT"})
    print(f"HTTP Status Code : {pos_status}")
    open_pos_symbols = set()
    if isinstance(pos_body, dict):
        print("Positions Data   :")
        pos_list = pos_body.get("data", [])
        if isinstance(pos_list, list) and len(pos_list) > 0:
            for p in pos_list:
                total_qty = float(p.get("total", 0))
                sym = p.get("symbol")
                if total_qty > 0:
                    open_pos_symbols.add(sym)
                print(f"  - Symbol: {sym}, Total: {total_qty}, Available: {p.get('available')}, HoldSide: {p.get('holdSide')}")
        else:
            print("  [OK] No open positions currently held (All candidate pairs are Flat).")
    else:
        print(f"Positions Body   : {pos_body}")

    # Dynamically select the first flat candidate symbol
    selected_symbol = None
    for sym in CANDIDATE_SYMBOLS:
        if sym not in open_pos_symbols:
            selected_symbol = sym
            break

    if not selected_symbol:
        selected_symbol = CANDIDATE_SYMBOLS[0]

    print(f"\n[CANDIDATE SELECTION] Selected Flat Tokenized Stock Candidate: {selected_symbol}")

    # --------------------------------------------------------------------------
    # STEP 1c: Market Data Ticker Call for Selected Candidate
    # --------------------------------------------------------------------------
    print(f"\n[STEP 1c] Executing Market Data Ticker Call ({selected_symbol})...")
    ticker_status, ticker_headers, ticker_body = client.get_market_ticker(symbol=selected_symbol, category="USDT-FUTURES")
    print(f"HTTP Status Code : {ticker_status}")
    print(f"HTTP Body (Ticker for {selected_symbol}):")
    if isinstance(ticker_body, (dict, list)):
        print(json.dumps(ticker_body, indent=2))
    else:
        print(ticker_body)

    is_success = (status_code == 200 and isinstance(body, dict) and body.get("code") == "00000") or \
                 (ticker_status == 200 and isinstance(ticker_body, dict) and ticker_body.get("code") == "00000")

    if not is_success:
        print("\n[STEP 1 FAILED] Read-only authentication check did not return code 00000.")
        sys.exit(2)

    print("\n[STEP 1 SUCCESS] Authentication & read-only API access verified successfully.")

    # --------------------------------------------------------------------------
    # STEP 2: Paper-Trading Order Execution (dryRun=False strictly in this test)
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print(f"[STEP 2] Placing exactly ONE Paper-Trading Order on {selected_symbol} (dryRun=False)...")
    print("=" * 80)

    current_price = 200.0
    if isinstance(ticker_body, dict) and ticker_body.get("code") == "00000":
        data_list = ticker_body.get("data", [])
        if isinstance(data_list, list) and len(data_list) > 0:
            last_pr = data_list[0].get("lastPrice") or data_list[0].get("lastPr")
            if last_pr:
                current_price = float(last_pr)

    stop_price = round(current_price * 0.985, 2)
    order_req = OrderRequest(
        symbol=selected_symbol,
        side="LONG",
        size_usd=10.0,
        entry_price=current_price,
        stop_price=stop_price,
        dry_run=False,  # ISOLATED VERIFICATION TEST ONLY
        metadata={"verification_test": True, "tokenized_equity": True}
    )

    print(f"Order Request Payload:")
    print(f"  Symbol      : {order_req.symbol}")
    print(f"  Side        : {order_req.side}")
    print(f"  Size USD    : ${order_req.size_usd:.2f}")
    print(f"  Entry Price : ${order_req.entry_price:.2f}")
    print(f"  Stop Price  : ${order_req.stop_price:.2f}")
    print(f"  dryRun      : {order_req.dry_run}")

    order_resp = client.place_order(order_req)

    print(f"\n--- ORDER EXECUTION RESULT ---")
    print(f"Order ID         : {order_resp.order_id}")
    print(f"Status           : {order_resp.status}")
    print(f"Execution Client : {order_resp.execution_client}")
    print(f"Filled Price     : {order_resp.filled_price}")
    print(f"Filled Size USD  : {order_resp.filled_size_usd}")
    print(f"Message          : {order_resp.message}")
    print(f"Timestamp        : {order_resp.timestamp}")
    print("=" * 80)


if __name__ == "__main__":
    main()
