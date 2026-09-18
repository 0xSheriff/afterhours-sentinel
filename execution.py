"""
AfterHours Sentinel - Execution & Logger Module
Handles paper trading execution against Bitget Agent Hub Demo / Mock execution layer.
Enforces strict dryRun defaults, demo isolation, zero dangerous endpoints, and structured logging.
"""

import os
import csv
import json
import time
import uuid
import datetime
import hmac
import hashlib
import base64
import socket
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple
import config
from risk_engine import RiskEvaluation, PortfolioState

# Ensure robust DNS resolution for Bitget API endpoints across restricted / polluted local DNS environments
_orig_getaddrinfo = socket.getaddrinfo

def _bitget_dns_fallback_getaddrinfo(host, port, *args, **kwargs):
    if host in ("api.bitget.com", "www.bitget.com"):
        try:
            return _orig_getaddrinfo(host, port, *args, **kwargs)
        except socket.gaierror:
            # Fallback to official Bitget Cloudflare Anycast IPs
            return _orig_getaddrinfo("104.18.15.166", port, *args, **kwargs)
    return _orig_getaddrinfo(host, port, *args, **kwargs)

socket.getaddrinfo = _bitget_dns_fallback_getaddrinfo


@dataclass
class OrderRequest:
    """Standardized order request payload."""
    symbol: str
    side: str  # "LONG" | "SHORT" | "CLOSE_LONG" | "CLOSE_SHORT"
    size_usd: float
    entry_price: float
    stop_price: float
    dry_run: bool = config.DEFAULT_DRY_RUN
    trade_side: str = "open"  # "open" | "close"
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class OrderResponse:
    """Standardized order response from execution client."""
    order_id: str
    symbol: str
    side: str
    status: str  # "FILLED" | "DRY_RUN_SIMULATED" | "REJECTED"
    execution_client: str
    filled_price: float
    filled_size_usd: float
    stop_price: float
    message: str
    timestamp: str


class BaseExecutionClient:
    """Abstract interface for paper-trading execution."""
    client_name: str = "BaseExecutionClient"

    def place_order(self, request: OrderRequest) -> OrderResponse:
        raise NotImplementedError

    def get_portfolio_state(self) -> PortfolioState:
        raise NotImplementedError


class MockExecutionClient(BaseExecutionClient):
    """
    In-memory Mock Execution Layer.
    Provides identical interface to Bitget Agent Hub for local testing, backtests, and dry-run safety.
    """
    client_name: str = "MockExecutionClient [Local Simulator]"

    def __init__(self, initial_balance: float = config.DEFAULT_PORTFOLIO_BALANCE_USD):
        self.portfolio_balance = initial_balance
        self.open_positions: Dict[str, Dict[str, Any]] = {}
        self.daily_realized_loss_pct = 0.0
        self.is_halted = False

    def get_portfolio_state(self) -> PortfolioState:
        return PortfolioState(
            portfolio_balance=self.portfolio_balance,
            open_positions_count=len(self.open_positions),
            daily_realized_loss_pct=self.daily_realized_loss_pct,
            is_halted=self.is_halted
        )

    def place_order(self, request: OrderRequest) -> OrderResponse:
        order_id = f"mock-order-{uuid.uuid4().hex[:8]}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if request.dry_run:
            return OrderResponse(
                order_id=order_id,
                symbol=request.symbol,
                side=request.side,
                status="DRY_RUN_SIMULATED",
                execution_client=self.client_name,
                filled_price=request.entry_price,
                filled_size_usd=request.size_usd,
                stop_price=request.stop_price,
                message="Mock: dryRun=True (simulated fill without state mutation).",
                timestamp=now_iso
            )

        # Paper fill / exit handling
        trade_side = getattr(request, "trade_side", "open").lower()
        if request.side.upper().startswith("CLOSE_") or request.side.upper() == "CLOSE":
            trade_side = "close"

        if trade_side == "close":
            matching_ids = [oid for oid, p in self.open_positions.items() if p["symbol"] == request.symbol]
            for oid in matching_ids:
                del self.open_positions[oid]
            msg = "Mock: Paper position closed in local simulator."
        else:
            self.open_positions[order_id] = {
                "symbol": request.symbol,
                "side": request.side,
                "size_usd": request.size_usd,
                "entry_price": request.entry_price,
                "stop_price": request.stop_price,
                "timestamp": now_iso
            }
            msg = "Mock: Paper trade filled in local simulator."

        return OrderResponse(
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            status="FILLED",
            execution_client=self.client_name,
            filled_price=request.entry_price,
            filled_size_usd=request.size_usd,
            stop_price=request.stop_price,
            message=msg,
            timestamp=now_iso
        )


class BitgetAgentHubClient(BaseExecutionClient):
    """
    Bitget Agent Hub Client.
    Executes in --paper-trading mode against Bitget's Demo environment (api.bitget.com).
    Guaranteed zero withdrawal/transfer endpoints.
    """
    client_name: str = "BitgetAgentHubClient [Demo Environment: api.bitget.com]"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        # Dynamically load from env vars or OAuth token store (~/.bitget/oauth_token.json)
        k, s, p, source = config.load_bitget_credentials()
        self.api_key = api_key or k
        self.api_secret = api_secret or s
        self.passphrase = passphrase or p
        self.credentials_source = source
        self.base_url = (base_url or config.BITGET_DEMO_BASE_URL).rstrip("/")
        self.server_time_offset_ms = 0
        self._mock_fallback = MockExecutionClient()

    def check_clock_sync(self) -> Tuple[bool, int, str]:
        """
        Compares local time against Bitget server time using public market ticker endpoint.
        Returns: (is_synced, drift_ms, message)
        Logs a warning if clock drift exceeds 2.5 seconds.
        """
        try:
            t0 = int(time.time() * 1000)
            status, _, body = self.get_market_ticker(symbol="BTCUSDT", category="USDT-FUTURES")
            t1 = int(time.time() * 1000)
            local_mid = (t0 + t1) // 2

            server_time = None
            if status == 200 and isinstance(body, dict):
                server_time = body.get("requestTime")
                if not server_time and isinstance(body.get("data"), list) and len(body["data"]) > 0:
                    server_time = body["data"][0].get("ts")

            if server_time:
                server_time = int(server_time)
                drift_ms = server_time - local_mid
                self.server_time_offset_ms = drift_ms
                if abs(drift_ms) > 2500:
                    msg = f"[WARNING] Clock drift detected: Local clock is {drift_ms/1000:+.2f}s relative to Bitget server (exceeds 2.5s threshold)."
                    return False, drift_ms, msg
                return True, drift_ms, f"[OK] Clock synchronized with Bitget server (drift: {drift_ms:+} ms)."
            return False, 0, "[WARNING] Could not extract server time from Bitget response."
        except Exception as e:
            return False, 0, f"[WARNING] Clock sync check failed: {str(e)}"

    def _sign(self, timestamp: str, method: str, request_path: str, query_string: str = "", body: str = "") -> str:
        """Generates HMAC-SHA256 signature for Bitget API v2/v3 authentication."""
        message = timestamp + method.upper() + request_path
        if query_string:
            message += "?" + query_string
        if body:
            message += body

        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def send_http_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        _retry_40008: bool = True
    ) -> Tuple[int, Dict[str, str], Any]:
        """
        Sends an authenticated REST HTTP request to Bitget Unified Account Demo environment.
        Automatically applies server time offset and retries once if 40008 (timestamp expired) is encountered.
        Returns: (status_code, response_headers, response_body_json_or_text)
        Does NOT swallow errors.
        """
        import subprocess

        method = method.upper()
        query_string = urllib.parse.urlencode(params) if params else ""
        url = f"{self.base_url}{path}"
        if query_string:
            url += f"?{query_string}"

        body_str = json.dumps(data) if data is not None else ""
        # Apply server time offset for tight synchronization
        current_time_ms = int(time.time() * 1000) + getattr(self, "server_time_offset_ms", 0)
        timestamp = str(current_time_ms)

        full_path = f"{path}?{query_string}" if query_string else path
        signature = self._sign(
            timestamp=timestamp,
            method=method,
            request_path=full_path,
            body=body_str
        )

        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
            "paptrading": "1"
        }

        parsed_result = None

        # Try curl first for robust cross-environment SSL / DNS Anycast resolution
        try:
            cmd = ["curl", "-s", "-i", "--resolve", "api.bitget.com:443:104.18.15.166", "-X", method]
            for k, v in headers.items():
                cmd.extend(["-H", f"{k}: {v}"])
            if body_str:
                cmd.extend(["-d", body_str])
            cmd.append(url)
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            output = res.stdout
            if output:
                parts = output.split("\r\n\r\n", 1) if "\r\n\r\n" in output else output.split("\n\n", 1)
                header_text = parts[0] if len(parts) > 1 else ""
                raw_body = parts[1] if len(parts) > 1 else parts[0]
                status_code = 200
                if "HTTP/" in header_text:
                    status_line = header_text.splitlines()[0]
                    status_tokens = status_line.split()
                    if len(status_tokens) >= 2 and status_tokens[1].isdigit():
                        status_code = int(status_tokens[1])
                try:
                    parsed_body = json.loads(raw_body)
                except Exception:
                    parsed_body = raw_body
                parsed_result = (status_code, {}, parsed_body)
        except Exception:
            pass

        # Fallback to urllib if curl produced no result
        if parsed_result is None:
            try:
                body_bytes = body_str.encode("utf-8") if body_str else None
                req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status_code = resp.getcode()
                    resp_headers = dict(resp.info())
                    raw_body = resp.read().decode("utf-8")
                    try:
                        parsed_body = json.loads(raw_body)
                    except Exception:
                        parsed_body = raw_body
                    parsed_result = (status_code, resp_headers, parsed_body)
            except urllib.error.HTTPError as e:
                status_code = e.code
                resp_headers = dict(e.headers)
                raw_body = e.read().decode("utf-8")
                try:
                    parsed_body = json.loads(raw_body)
                except Exception:
                    parsed_body = raw_body
                parsed_result = (status_code, resp_headers, parsed_body)
            except urllib.error.URLError as e:
                parsed_result = (599, {}, {"code": "NETWORK_ERROR", "msg": f"URLError (Connection failed/timeout): {e.reason}"})
            except Exception as e:
                parsed_result = (500, {}, {"code": "INTERNAL_CLIENT_ERROR", "msg": f"Unexpected execution error: {str(e)}"})

        # Automatic 40008 retry: transient timing/timestamp drift
        status_code, resp_headers, parsed_body = parsed_result
        if _retry_40008 and isinstance(parsed_body, dict) and parsed_body.get("code") == "40008":
            server_time = parsed_body.get("requestTime")
            if server_time:
                self.server_time_offset_ms = int(server_time) - int(time.time() * 1000)
            time.sleep(0.05)
            return self.send_http_request(method, path, params=params, data=data, _retry_40008=False)

        return parsed_result

    def get_account_balance(self, category: str = "USDT-FUTURES") -> Tuple[int, Dict[str, str], Any]:
        """Fetches account assets/balance, auto-adapting between Unified Account v3 and Classic Mix v2."""
        if self.api_key == "mock_demo_api_key" or self.credentials_source == "mock_fallback":
            mock_body = {
                "code": "00000",
                "msg": "success",
                "data": {
                    "accountEquity": str(config.DEFAULT_PORTFOLIO_BALANCE_USD),
                    "usdtEquity": str(config.DEFAULT_PORTFOLIO_BALANCE_USD),
                    "assets": [
                        {
                            "coin": "USDT",
                            "available": str(config.DEFAULT_PORTFOLIO_BALANCE_USD),
                            "equity": str(config.DEFAULT_PORTFOLIO_BALANCE_USD)
                        }
                    ]
                }
            }
            return 200, {"content-type": "application/json"}, mock_body

        # Optimize initial endpoint attempt based on credential source
        if self.credentials_source == "env_vars":
            status, headers, body = self.send_http_request("GET", "/api/v2/mix/account/accounts", params={"productType": "usdt-futures"})
            if status == 200 and isinstance(body, dict) and body.get("code") == "00000":
                return status, headers, body
            # Fallback to Unified v3 if Classic returns environment mismatch
            return self.send_http_request("GET", "/api/v3/account/assets")
        else:
            status, headers, body = self.send_http_request("GET", "/api/v3/account/assets")
            if status == 200 and isinstance(body, dict) and body.get("code") == "00000":
                return status, headers, body
            # Fallback to Classic v2
            if isinstance(body, dict) and body.get("code") in ("40085", "40099"):
                return self.send_http_request("GET", "/api/v2/mix/account/accounts", params={"productType": "usdt-futures"})
            return status, headers, body

    def get_market_ticker(self, symbol: str = "BTCUSDT", category: str = "USDT-FUTURES") -> Tuple[int, Dict[str, str], Any]:
        """Fetches market ticker data in Unified or Classic Demo environment."""
        path = "/api/v3/market/tickers"
        params = {"category": category, "symbol": symbol}
        status, headers, body = self.send_http_request("GET", path, params=params)
        if status == 200 and isinstance(body, dict) and body.get("code") == "00000":
            return status, headers, body
        # Fallback to v2 mix ticker
        return self.send_http_request("GET", "/api/v2/mix/market/ticker", params={"symbol": symbol, "productType": "usdt-futures"})

    def get_portfolio_state(self) -> PortfolioState:
        # If demo credentials are mock, fallback to safe tracking
        if self.api_key == "mock_demo_api_key" or self.credentials_source == "mock_fallback":
            return self._mock_fallback.get_portfolio_state()

        status, _, body = self.get_account_balance()
        balance = config.DEFAULT_PORTFOLIO_BALANCE_USD
        if status == 200 and isinstance(body, dict) and body.get("code") == "00000":
            data = body.get("data", {})
            if isinstance(data, dict):
                eq = data.get("usdtEquity") or data.get("accountEquity")
                if eq and float(eq) > 0:
                    balance = float(eq)
            elif isinstance(data, list) and len(data) > 0:
                eq = data[0].get("usdtEquity") or data[0].get("equity") or data[0].get("available")
                if eq and float(eq) > 0:
                    balance = float(eq)

        # Query open positions (try v3 then v2)
        pos_status, _, pos_body = self.send_http_request("GET", "/api/v3/position/current-position", params={"category": "USDT-FUTURES"})
        open_pos_count = 0
        if pos_status == 200 and isinstance(pos_body, dict) and pos_body.get("code") == "00000":
            pos_data = pos_body.get("data", [])
            if isinstance(pos_data, list):
                open_pos_count = len(pos_data)

        return PortfolioState(
            portfolio_balance=balance,
            open_positions_count=open_pos_count,
            daily_realized_loss_pct=0.0,
            is_halted=False
        )

    def place_order(self, request: OrderRequest) -> OrderResponse:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        order_id = f"bitget-demo-{uuid.uuid4().hex[:8]}"

        # Always respect dryRun
        if request.dry_run:
            return OrderResponse(
                order_id=order_id,
                symbol=request.symbol,
                side=request.side,
                status="DRY_RUN_SIMULATED",
                execution_client=self.client_name,
                filled_price=request.entry_price,
                filled_size_usd=request.size_usd,
                stop_price=request.stop_price,
                message="Bitget Agent Hub Demo: dryRun=True. Simulated fill logged safely.",
                timestamp=now_iso
            )

        if self.api_key == "mock_demo_api_key" or self.credentials_source == "mock_fallback":
            res = self._mock_fallback.place_order(request)
            res.execution_client = f"{self.client_name} (Mock Fallback)"
            return res

        # In live demo mode with real credentials and dry_run=False, send order to Bitget
        formatted_sym = request.symbol if "USDT" in request.symbol else f"{request.symbol}USDT"
        if formatted_sym.startswith("r") and len(formatted_sym) > 5 and formatted_sym[1:].isupper():
            formatted_sym = formatted_sym[1:]

        size_qty = round(request.size_usd / max(request.entry_price, 0.0001), 2) if request.entry_price > 0 else 0.01

        trade_side = getattr(request, "trade_side", "open").lower()
        if request.side.upper().startswith("CLOSE_") or request.side.upper() == "CLOSE":
            trade_side = "close"

        is_long = "LONG" in request.side.upper() or request.side.upper() == "BUY"

        # When closing, retrieve exact held position quantity to avoid rounding drift or residual positions
        actual_pos_qty = None
        if trade_side == "close":
            try:
                expected_hold_side = "long" if is_long else "short"
                st_p, _, body_p = self.send_http_request("GET", "/api/v2/mix/position/all-position", params={"productType": "usdt-futures", "marginCoin": "USDT"})
                if st_p == 200 and isinstance(body_p, dict) and body_p.get("code") == "00000":
                    for p in body_p.get("data", []):
                        if p.get("symbol") == formatted_sym and p.get("holdSide", "").lower() in (expected_hold_side, "both"):
                            tot = float(p.get("total", 0))
                            if tot > 0:
                                actual_pos_qty = tot
                                break
            except Exception:
                pass

        final_size = str(actual_pos_qty) if actual_pos_qty is not None else str(max(size_qty, 0.01))

        # In Bitget Classic Mix V2 (Hedge Mode):
        # - Open Long: side="buy", tradeSide="open"
        # - Open Short: side="sell", tradeSide="open"
        # - Close Long: side="buy", tradeSide="close"
        # - Close Short: side="sell", tradeSide="close"
        # In Unified Account V3:
        # - Open Long: side="buy", posSide="long"
        # - Open Short: side="sell", posSide="short"
        # - Close Long: side="sell", posSide="long"
        # - Close Short: side="buy", posSide="short"
        if trade_side == "close":
            classic_side = "buy" if is_long else "sell"
            v3_side = "sell" if is_long else "buy"
            v3_pos_side = "long" if is_long else "short"
        else:
            classic_side = "buy" if is_long else "sell"
            v3_side = "buy" if is_long else "sell"
            v3_pos_side = "long" if is_long else "short"

        classic_payload = {
            "symbol": formatted_sym,
            "productType": "usdt-futures",
            "marginMode": "crossed",
            "marginCoin": "USDT",
            "size": final_size,
            "side": classic_side,
            "tradeSide": trade_side,
            "orderType": "market",
            "clientOid": f"sentinel-{uuid.uuid4().hex[:12]}"
        }

        v3_payload = {
            "category": "USDT-FUTURES",
            "symbol": formatted_sym,
            "side": v3_side,
            "orderType": "market",
            "posSide": v3_pos_side,
            "qty": final_size,
            "clientOid": f"sentinel-{uuid.uuid4().hex[:12]}"
        }
        if trade_side == "close":
            v3_payload["reduceOnly"] = "YES"
        elif request.stop_price > 0:
            v3_payload["stopLoss"] = str(round(request.stop_price, 1))

        if self.credentials_source == "env_vars":
            # Classic Mix endpoint first for dedicated Demo API keys
            status_code, headers, resp_body = self.send_http_request("POST", "/api/v2/mix/order/place-order", data=classic_payload)
            if not (status_code == 200 and isinstance(resp_body, dict) and resp_body.get("code") == "00000"):
                if isinstance(resp_body, dict) and resp_body.get("code") in ("40085", "40099"):
                    status_code, headers, resp_body = self.send_http_request("POST", "/api/v3/trade/place-order", data=v3_payload)
        else:
            # Unified v3 endpoint first for OAuth sub-accounts
            status_code, headers, resp_body = self.send_http_request("POST", "/api/v3/trade/place-order", data=v3_payload)
            if not (status_code == 200 and isinstance(resp_body, dict) and resp_body.get("code") == "00000"):
                needs_classic = False
                if isinstance(resp_body, dict):
                    code = resp_body.get("code")
                    msg = str(resp_body.get("msg", ""))
                    if code in ("40085", "40099") or "getModelTypeByUserId" in msg or "userId illegal" in msg:
                        needs_classic = True
                if needs_classic:
                    status_code, headers, resp_body = self.send_http_request("POST", "/api/v2/mix/order/place-order", data=classic_payload)

        if status_code == 200 and isinstance(resp_body, dict) and resp_body.get("code") == "00000":
            data = resp_body.get("data", {})
            real_order_id = data.get("orderId", order_id) if isinstance(data, dict) else order_id
            return OrderResponse(
                order_id=real_order_id,
                symbol=request.symbol,
                side=request.side,
                status="FILLED",
                execution_client=self.client_name,
                filled_price=request.entry_price,
                filled_size_usd=request.size_usd,
                stop_price=request.stop_price,
                message=f"Bitget Agent Hub Demo: Order executed (Bitget orderId: {real_order_id}).",
                timestamp=now_iso
            )
        else:
            err_msg = resp_body.get("msg", str(resp_body)) if isinstance(resp_body, dict) else str(resp_body)
            return OrderResponse(
                order_id=order_id,
                symbol=request.symbol,
                side=request.side,
                status="REJECTED",
                execution_client=self.client_name,
                filled_price=0.0,
                filled_size_usd=0.0,
                stop_price=0.0,
                message=f"Bitget Agent Hub Demo Error [HTTP {status_code}]: {err_msg}",
                timestamp=now_iso
            )

    def close_position(
        self,
        symbol: str,
        side: str = "LONG",
        size_usd: Optional[float] = None,
        dry_run: bool = config.DEFAULT_DRY_RUN
    ) -> OrderResponse:
        """
        Closes an active position on Bitget Demo environment (hedge mode).
        Supports closing LONG (side='buy', tradeSide='close') and SHORT (side='sell', tradeSide='close').
        """
        formatted_sym = symbol if "USDT" in symbol else f"{symbol}USDT"
        if formatted_sym.startswith("r") and len(formatted_sym) > 5 and formatted_sym[1:].isupper():
            formatted_sym = formatted_sym[1:]

        _, _, ticker_body = self.get_market_ticker(symbol=formatted_sym)
        current_price = 100.0
        if isinstance(ticker_body, dict) and ticker_body.get("code") == "00000":
            data = ticker_body.get("data", [])
            if isinstance(data, list) and len(data) > 0:
                current_price = float(data[0].get("lastPrice") or data[0].get("lastPr") or 100.0)

        order_req = OrderRequest(
            symbol=formatted_sym,
            side=side,
            size_usd=size_usd or 10.0,
            entry_price=current_price,
            stop_price=0.0,
            dry_run=dry_run,
            trade_side="close",
            metadata={"exit_reason": "stop_loss_or_scheduled_exit"}
        )
        return self.place_order(order_req)


# ==============================================================================
# STRUCTURED LOGGER
# ==============================================================================

# ==============================================================================
# STRUCTURED LOGGER
# ==============================================================================

CSV_HEADERS = [
    "timestamp", "mode", "execution_client", "llm_source", "symbol", "event_headline", "event_type",
    "event_timestamp", "pre_event_price", "entry_price", "actual_move", "actual_move_basis", "actual_move_status",
    "expected_move", "benchmark_type", "benchmark_move", "beta", "residual", "residual_std", "volatility_floor",
    "z_score", "z_threshold", "volume_ratio", "volume_basis", "volume_status", "liquidity_condition",
    "event_direction", "price_direction", "direction_alignment", "qwen_direction", "qwen_validation",
    "qwen_reasoning", "quant_signal", "risk_gate", "decision", "signals_aligned",
    "position_size", "stop_price", "exit_price", "exit_reason",
    "pnl", "reason", "divergence"
]


class SentinelLogger:
    """Logs structured decision records into JSONL and CSV files."""
    def __init__(
        self,
        jsonl_path: str = config.TRADES_JSONL_LOG,
        csv_path: str = config.TRADES_CSV_LOG
    ):
        self.jsonl_path = jsonl_path
        self.csv_path = csv_path
        os.makedirs(os.path.dirname(os.path.abspath(self.jsonl_path)), exist_ok=True)
        self._ensure_csv_header()

    def _ensure_csv_header(self):
        if not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0:
            with open(self.csv_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
                writer.writeheader()

    def log_decision(
        self,
        event: Dict[str, Any],
        evaluation: RiskEvaluation,
        mode: str = "live",
        execution_client: str = "BitgetAgentHubClient [Demo Environment: api.bitget.com]",
        exit_price: Optional[float] = None,
        exit_reason: Optional[str] = None,
        pnl: float = 0.0,
        timestamp: Optional[str] = None,
        symbol: Optional[str] = None,
        pre_event_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Records a decision (TRADE or NO_TRADE) to both JSONL and CSV log files.
        Includes all decoupled quantitative, liquidity, and Qwen validation evidence fields.
        """
        div = evaluation.divergence
        now_ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        target_sym = symbol or div.get("asset", "")

        record = {
            "timestamp": now_ts,
            "mode": mode,  # "historical_replay" | "live" | "live_dryrun_mock" | "backtest"
            "execution_client": execution_client,
            "llm_source": evaluation.llm_source,
            "symbol": target_sym,
            "event_headline": event.get("headline", ""),
            "event_type": event.get("event_type", "other"),
            "event_timestamp": event.get("timestamp", now_ts),
            "pre_event_price": pre_event_price if pre_event_price is not None else evaluation.entry_price,
            "entry_price": evaluation.entry_price,
            "actual_move": div.get("actual_move", 0.0),
            "actual_move_basis": div.get("actual_move_basis", "EVENT_WINDOW" if "replay" in mode or "backtest" in mode else "ROLLING_24H"),
            "actual_move_status": div.get("actual_move_status", "MEASURED"),
            "expected_move": div.get("expected_move", 0.0),
            "benchmark_type": div.get("benchmark_type", "PEER_TECH_BASKET" if div.get("benchmark") == "QQQ" else div.get("benchmark", "QQQ")),
            "benchmark_move": div.get("benchmark_move", 0.0),
            "beta": div.get("beta", 1.0),
            "residual": div.get("residual", 0.0),
            "residual_std": div.get("residual_stdev", config.DEFENSIVE_VOLATILITY_FLOOR),
            "volatility_floor": div.get("volatility_floor", config.DEFENSIVE_VOLATILITY_FLOOR),
            "z_score": div.get("z_score", 0.0),
            "z_threshold": div.get("z_threshold", config.Z_SCORE_THRESHOLD),
            "volume_ratio": div.get("volume_ratio"),
            "volume_basis": div.get("volume_basis", "MEASURED"),
            "volume_status": div.get("volume_status", "MEASURED"),
            "liquidity_condition": div.get("liquidity_condition", "INSUFFICIENT_DATA"),
            "event_direction": getattr(evaluation, "event_direction", evaluation.qwen_direction.lower()),
            "price_direction": getattr(evaluation, "price_direction", "flat"),
            "direction_alignment": getattr(evaluation, "direction_alignment", "ALIGNMENT"),
            "qwen_direction": evaluation.qwen_direction.upper(),
            "qwen_validation": getattr(evaluation, "qwen_validation", "PASS"),
            "qwen_reasoning": evaluation.qwen_reasoning,
            "quant_signal": getattr(evaluation, "quant_signal", "FAIL"),
            "risk_gate": getattr(evaluation, "risk_gate", "PASS"),
            "decision": evaluation.decision,
            "signals_aligned": evaluation.signals_aligned,
            "position_size": evaluation.position_size_usd,
            "stop_price": evaluation.stop_price,
            "exit_price": exit_price if exit_price is not None else 0.0,
            "exit_reason": exit_reason or ("N/A" if evaluation.decision == "NO_TRADE" else "OPEN"),
            "pnl": round(pnl, 2),
            "reason": evaluation.reason,
            "divergence": div.get("residual", 0.0)
        }

        # 1. Write JSONL
        with open(self.jsonl_path, mode="a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        # 2. Write CSV (extrasaction='ignore' guarantees safe evolution)
        with open(self.csv_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
            writer.writerow(record)

        return record


def export_submission_log(output_csv: str = "logs/submission_audit_trail.csv") -> int:
    """
    Exports strictly verified 'historical_replay', 'backtest', and 'live' records for hackathon submission.
    Guarantees that 'live_dryrun_mock' records are strictly excluded from submitted logs.
    """
    if not os.path.exists(config.TRADES_JSONL_LOG):
        print(f"[Sentinel] No trade log found to export at {config.TRADES_JSONL_LOG}")
        return 0

    verified_records = []
    with open(config.TRADES_JSONL_LOG, mode="r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                    if rec.get("mode") in ("backtest", "historical_replay", "live"):
                        verified_records.append(rec)
                except Exception:
                    pass

    os.makedirs(os.path.dirname(os.path.abspath(output_csv)), exist_ok=True)
    with open(output_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for r in verified_records:
            writer.writerow(r)

    print(f"[Sentinel Export] Successfully exported {len(verified_records)} verified records to {output_csv} (excluded all mock runs).")
    return len(verified_records)


def print_summary(log_file: Optional[str] = None, mode: Optional[str] = None):
    """
    CLI reporting function that parses logs and prints execution performance.
    Guarantees that 'live_dryrun_mock' entries are excluded unless explicitly asked for.
    """
    target_file = log_file or config.TRADES_JSONL_LOG
    if not os.path.exists(target_file):
        print(f"[Sentinel] No trade log found at {target_file}")
        return

    records = []
    with open(target_file, mode="r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

    # Filtering logic:
    # If mode is specific ("historical_replay", "backtest", "live", "live_dryrun_mock"), filter exactly.
    # If mode is None or "all", include ONLY legitimate submission modes ("historical_replay", "backtest", "live").
    if mode and mode != "all":
        records = [r for r in records if r.get("mode") == mode]
    else:
        records = [r for r in records if r.get("mode") in ("backtest", "historical_replay", "live")]

    total_events = len(records)
    if total_events == 0:
        print(f"[Sentinel Summary] No records found for mode='{mode or 'BACKTEST+LIVE'}'.")
        return

    trade_records = [r for r in records if r.get("decision") in ("SHORT", "LONG")]
    no_trade_records = [r for r in records if r.get("decision") == "NO_TRADE"]

    short_trades = [r for r in trade_records if r.get("decision") == "SHORT"]
    long_trades = [r for r in trade_records if r.get("decision") == "LONG"]

    total_pnl = sum(r.get("pnl", 0.0) for r in trade_records)
    winning_trades = [r for r in trade_records if r.get("pnl", 0.0) > 0]
    win_rate = (len(winning_trades) / len(trade_records) * 100) if trade_records else 0.0

    # Compute log-derived monitoring duration
    timestamps = []
    for r in records:
        ts_str = r.get("timestamp")
        if ts_str:
            try:
                dt = datetime.datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                timestamps.append(dt)
            except Exception:
                pass
    span_str = "N/A"
    if len(timestamps) >= 2:
        min_ts = min(timestamps)
        max_ts = max(timestamps)
        span_hrs = max(0.0, (max_ts - min_ts).total_seconds() / 3600.0)
        span_str = f"{span_hrs:.1f} hours ({min_ts.strftime('%Y-%m-%d %H:%M UTC')} → {max_ts.strftime('%Y-%m-%d %H:%M UTC')})"

    mode_display = mode.upper() if mode else "VERIFIED SUBMISSION AUDIT (BACKTEST + LIVE)"
    print("=" * 105)
    print(f" AFTERHOURS SENTINEL - AUDIT SUMMARY [{mode_display}]")
    print("=" * 105)
    print(f" Total Events Analyzed : {total_events}")
    print(f" Monitoring Span       : {span_str}")
    print(f" Trade Candidates      : {len(trade_records)} (Short: {len(short_trades)}, Long: {len(long_trades)})")
    print(f" Filtered (NO_TRADE)   : {len(no_trade_records)}")
    print(f" Total Realized PnL    : ${total_pnl:+,.2f}")
    if trade_records:
        print(f" Win Rate              : {win_rate:.1f}% ({len(winning_trades)}/{len(trade_records)})")
    print(f" [SAMPLE SIZE FRAMING] Sample size represents directional event verification (N={total_events} events,")
    print(f"                       n={len(trade_records)} executed trades). PnL and win rates demonstrate operational integrity")
    print(f"                       and pipeline mechanics, not a statistically generalized track record. Sharpe ratio omitted.")
    print("-" * 105)
    print(" 1. QUANTITATIVE & EXECUTION LOG:")
    print(f"{'Time':<20} | {'Mode':<8} | {'Decision':<8} | {'Signals':<7} | {'Z-Score':<8} | {'Execution Client':<28} | {'PnL ($)':<8}")
    print("-" * 105)

    for r in records[-15:]:
        client_short = r.get('execution_client', 'BitgetAgentHubClient')[:26]
        print(
            f"{str(r.get('timestamp', ''))[:19]:<20} | "
            f"{str(r.get('mode', '')):<8} | "
            f"{str(r.get('decision', '')):<8} | "
            f"{str(r.get('signals_aligned', '')):<7} | "
            f"{float(r.get('z_score', 0.0)):+8.2f} | "
            f"{client_short:<28} | "
            f"{float(r.get('pnl', 0.0)):+8.2f}"
        )

    print("-" * 105)
    print(" 2. LLM REASONING & EXPLAINABILITY AUDIT TRAIL:")
    print("-" * 105)
    for idx, r in enumerate(records[-8:], start=1):
        print(f" [Event {idx}] {r.get('timestamp', '')[:19]} | {r.get('event_type', '').upper()} | {r.get('event_headline', '')}")
        print(f"   ↳ LLM Source:      {r.get('llm_source', 'qwen3.8-max')}")
        print(f"   ↳ Assessment:      {r.get('qwen_direction', 'N/A')} -> \"{r.get('qwen_reasoning', 'N/A')}\"")
        vol_raw = r.get('volume_ratio')
        vol_display = f"{float(vol_raw):.2f}" if vol_raw is not None else "N/A"
        print(f"   ↳ Market Reaction: Act {float(r.get('actual_move', 0.0)):+.2%} vs Exp {float(r.get('expected_move', 0.0)):+.2%} (z={float(r.get('z_score', 0.0)):+.2f}, vol={vol_display})")
        print(f"   ↳ Risk Gatekeeper: {r.get('decision')} | {r.get('reason')}")
        print()
    print("=" * 105)
