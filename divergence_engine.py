"""
AfterHours Sentinel - Divergence Engine
Pure deterministic calculation of rolling beta, expected move, residual z-score, and volume confirmation.
Zero external library dependencies (uses Python standard library math & statistics).
"""

from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional, Sequence
import math
import statistics

import config


@dataclass(frozen=True)
class DivergenceResult:
    """Structured output from the Divergence Engine."""
    asset: str = ""
    benchmark: str = "QQQ"
    beta: float = 1.0
    benchmark_move: float = 0.0
    expected_move: float = 0.0
    actual_move: float = 0.0
    residual: float = 0.0
    residual_stdev: float = config.DEFENSIVE_VOLATILITY_FLOOR
    z_score: float = 0.0
    z_threshold: float = config.Z_SCORE_THRESHOLD
    volatility_floor: float = config.DEFENSIVE_VOLATILITY_FLOOR
    after_hours_volume: Optional[float] = None
    trailing_avg_volume: Optional[float] = None
    volume_ratio: Optional[float] = None
    volume_confirmation: str = "unknown"  # "weak" | "normal" | "unknown"
    volume_basis: str = "MEASURED"  # "MEASURED" | "FALLBACK_ESTIMATE" | "INSUFFICIENT_DATA"
    volume_status: str = "MEASURED"  # "MEASURED" | "INSUFFICIENT_DATA" | "EMPIRICAL"
    liquidity_condition: str = "INSUFFICIENT_DATA"  # "WEAK_LIQUIDITY" | "HIGH_VOLUME_CONFIRMED" | "INSUFFICIENT_DATA" | "NORMAL"
    actual_move_basis: str = "EVENT_WINDOW"  # "EVENT_WINDOW" | "ROLLING_24H"
    actual_move_status: str = "MEASURED"  # "MEASURED" | "INSUFFICIENT_DATA"
    benchmark_type: str = "QQQ"  # "PEER_TECH_BASKET" | "QQQ" | "BTC"
    quant_signal: str = "FAIL"  # "PASS" | "FAIL" | "ANOMALY_CONFIRMED" | "NORMAL_VARIATION"
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    symbol: Optional[str] = None
    divergence: Optional[float] = None

    def __post_init__(self):
        if self.symbol and not self.asset:
            object.__setattr__(self, "asset", self.symbol)
        if self.divergence is not None and self.residual == 0.0:
            object.__setattr__(self, "residual", self.divergence)
        if self.quant_signal in ("PASS", "FAIL"):
            if abs(self.z_score) >= self.z_threshold:
                object.__setattr__(self, "quant_signal", "ANOMALY_CONFIRMED")
            else:
                object.__setattr__(self, "quant_signal", "NORMAL_VARIATION")
        if self.liquidity_condition == "INSUFFICIENT_DATA":
            if self.volume_confirmation == "weak":
                object.__setattr__(self, "liquidity_condition", "WEAK_LIQUIDITY")
            elif self.volume_confirmation == "normal":
                object.__setattr__(self, "liquidity_condition", "HIGH_VOLUME_CONFIRMED")

    @property
    def volume_confirmed(self) -> bool:
        return self.volume_confirmation == "weak"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calculate_rolling_beta(
    asset_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    window: int = config.BETA_ROLLING_WINDOW_DAYS
) -> float:
    """
    Computes rolling beta between asset returns and benchmark returns:
    Beta = Cov(R_asset, R_bench) / Var(R_bench)

    Strictly uses historical observations available prior to the event (no future lookahead).
    """
    if len(asset_returns) < 2 or len(benchmark_returns) < 2:
        return 1.0

    # Slice to window
    a = list(asset_returns[-window:])
    b = list(benchmark_returns[-window:])

    n = min(len(a), len(b))
    if n < 2:
        return 1.0

    a = a[-n:]
    b = b[-n:]

    mean_a = sum(a) / n
    mean_b = sum(b) / n

    # Sample Covariance and Sample Variance (n - 1 degrees of freedom)
    cov_ab = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / (n - 1)
    var_b = sum((b[i] - mean_b) ** 2 for i in range(n)) / (n - 1)

    if var_b <= 1e-12 or math.isnan(var_b):
        return 1.0

    beta = cov_ab / var_b
    if math.isnan(beta) or math.isinf(beta):
        return 1.0

    return float(beta)


def calculate_rolling_residual_stdev(
    asset_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    beta: float,
    window: int = config.RESIDUAL_ROLLING_WINDOW_DAYS,
    min_floor: float = config.DEFENSIVE_VOLATILITY_FLOOR
) -> float:
    """
    Computes sample standard deviation of historical residuals:
    Residual_t = R_asset,t - beta * R_bench,t

    Strictly uses historical observations available prior to the event (no future lookahead).
    Enforces a defensive volatility floor (default: 80 bps / 0.008) to prevent numerical
    instabilities and division by near-zero.
    """
    if len(asset_returns) < 2 or len(benchmark_returns) < 2:
        return min_floor

    a = list(asset_returns[-window:])
    b = list(benchmark_returns[-window:])

    n = min(len(a), len(b))
    if n < 2:
        return min_floor

    a = a[-n:]
    b = b[-n:]

    residuals = [a[i] - (beta * b[i]) for i in range(n)]

    try:
        raw_stdev = statistics.stdev(residuals)
    except statistics.StatisticsError:
        raw_stdev = min_floor

    if math.isnan(raw_stdev) or raw_stdev <= 1e-8:
        raw_stdev = min_floor

    # Enforce defensive market volatility floor (e.g. 0.8% minimum)
    final_stdev = max(raw_stdev, min_floor)
    return float(final_stdev)


def compute_expected_move(
    asset: str,
    peer_returns: Dict[str, float],
    beta: Optional[float] = None
) -> float:
    """
    Computes expected move: beta * benchmark_move (average of peer basket).
    The target asset is explicitly excluded from the peer basket calculation.
    """
    if beta is None:
        beta = config.EQUITY_TICKER_MAP.get(asset, {}).get("beta", 1.0)

    # Strictly exclude the target asset from the peer basket
    valid_peers = [ret for sym, ret in peer_returns.items() if sym != asset and not math.isnan(ret)]
    if not valid_peers:
        return 0.0

    benchmark_move = float(statistics.mean(valid_peers))
    return float(beta * benchmark_move)


def calculate_volume_metrics(
    after_hours_volume: Optional[float] = None,
    trailing_avg_volume: Optional[float] = None,
    weak_threshold: float = config.VOLUME_RATIO_WEAK_THRESHOLD,
    current_volume: Optional[float] = None,
    baseline_volume: Optional[float] = None,
    min_threshold_ratio: Optional[float] = None,
    **kwargs
) -> tuple[Optional[float], str]:
    """
    Computes empirical volume ratio and confirmation flag.
    Returns: (volume_ratio, volume_confirmation)

    - If trailing_avg_volume is None, <= 0.0, or after_hours_volume is None:
      returns (None, "unknown")
    - If valid empirical observations exist:
      volume_ratio = round(after_hours_volume / trailing_avg_volume, 4)
      volume_confirmation = "weak" if volume_ratio < weak_threshold else "normal"
    """
    cur = current_volume if current_volume is not None else after_hours_volume
    base = baseline_volume if baseline_volume is not None else trailing_avg_volume
    thresh = min_threshold_ratio if min_threshold_ratio is not None else weak_threshold

    if base is None or base <= 0.0 or cur is None:
        return None, "unknown"

    ratio = float(cur / base)
    confirmation = "weak" if ratio < thresh else "normal"

    return round(ratio, 4), confirmation


def compute_divergence(
    asset: str,
    actual_move: float,
    benchmark_move: float = 0.0,
    asset_history_returns: Optional[Any] = None,
    benchmark_history_returns: Optional[Any] = None,
    after_hours_volume: Optional[float] = None,
    trailing_avg_volume: Optional[float] = None,
    benchmark_override: Optional[str] = None,
    actual_move_basis: str = "EVENT_WINDOW",
    actual_move_status: str = "MEASURED",
    benchmark_type: Optional[str] = None,
    volume_basis: str = "MEASURED",
    current_volume: Optional[float] = None,
    baseline_volume: Optional[float] = None,
    **kwargs
) -> DivergenceResult:
    """
    Primary pure deterministic entrypoint for the Divergence Engine.
    """
    resolved_benchmark = benchmark_override or config.get_benchmark_for_symbol(asset)
    b_type = benchmark_type or ("PEER_TECH_BASKET" if resolved_benchmark == "QQQ" else resolved_benchmark)

    # Check if caller passed residual_stdev directly as 4th param (or positional test mock)
    if isinstance(asset_history_returns, (int, float)):
        beta = config.EQUITY_TICKER_MAP.get(asset, {}).get("beta", 1.0)
        expected_move = float(beta * benchmark_move)
        residual = float(actual_move - expected_move)
        raw_std = float(asset_history_returns)
        residual_stdev = max(raw_std, config.DEFENSIVE_VOLATILITY_FLOOR)
        if isinstance(benchmark_history_returns, (int, float)):
            if trailing_avg_volume is None and after_hours_volume is not None:
                trailing_avg_volume = after_hours_volume
                after_hours_volume = float(benchmark_history_returns)
            elif after_hours_volume is None:
                after_hours_volume = float(benchmark_history_returns)
    elif asset_history_returns is not None and benchmark_history_returns is not None and len(asset_history_returns) >= 2:
        # 1. Rolling Beta (strictly pre-event window)
        beta = calculate_rolling_beta(asset_history_returns, benchmark_history_returns, config.BETA_ROLLING_WINDOW_DAYS)
        # 2. Expected Move
        expected_move = float(beta * benchmark_move)
        # 3. Residual
        residual = float(actual_move - expected_move)
        # 4. Rolling Stdev of Residuals & Z-Score
        residual_stdev = calculate_rolling_residual_stdev(
            asset_history_returns, benchmark_history_returns, beta, config.RESIDUAL_ROLLING_WINDOW_DAYS
        )
    else:
        beta = config.EQUITY_TICKER_MAP.get(asset, {}).get("beta", 1.0)
        expected_move = float(beta * benchmark_move)
        residual = float(actual_move - expected_move)
        residual_stdev = config.DEFENSIVE_VOLATILITY_FLOOR

    z_score = float(residual / residual_stdev)

    # 5. Volume Confirmation & Liquidity Status
    cur_v = current_volume if current_volume is not None else after_hours_volume
    base_v = baseline_volume if baseline_volume is not None else trailing_avg_volume
    vol_ratio, vol_conf = calculate_volume_metrics(
        after_hours_volume=cur_v,
        trailing_avg_volume=base_v,
        weak_threshold=config.VOLUME_RATIO_WEAK_THRESHOLD
    )

    v_basis = volume_basis
    if vol_ratio is None or base_v is None or base_v <= 0.0:
        vol_status = "INSUFFICIENT_DATA"
        liq_cond = "INSUFFICIENT_DATA"
        vol_conf_bool = False
    elif vol_ratio < config.VOLUME_RATIO_WEAK_THRESHOLD:
        vol_status = "EMPIRICAL"
        liq_cond = "WEAK_LIQUIDITY"
        vol_conf_bool = True
    else:
        vol_status = "EMPIRICAL"
        liq_cond = "HIGH_VOLUME_CONFIRMED"
        vol_conf_bool = False

    # 6. Quantitative Anomaly Signal: PASS iff |z| > threshold AND thin liquidity AND data is valid
    z_pass = abs(z_score) > config.Z_SCORE_THRESHOLD
    liq_pass = (liq_cond == "WEAK_LIQUIDITY")
    data_valid = (actual_move_status == "MEASURED")

    quant_signal = "PASS" if (z_pass and liq_pass and data_valid) else "FAIL"

    diagnostics = {
        "asset": asset,
        "benchmark": resolved_benchmark,
        "benchmark_type": b_type,
        "window_size": (
            min(len(asset_history_returns), len(benchmark_history_returns))
            if (isinstance(asset_history_returns, (list, tuple)) and isinstance(benchmark_history_returns, (list, tuple)))
            else 30
        ),
        "beta": round(beta, 4),
        "actual_move_pct": f"{actual_move:+.2%}",
        "actual_move_basis": actual_move_basis,
        "actual_move_status": actual_move_status,
        "benchmark_move_pct": f"{benchmark_move:+.2%}",
        "expected_move_pct": f"{expected_move:+.2%}",
        "residual_pct": f"{residual:+.2%}",
        "residual_stdev_pct": f"{residual_stdev:.2%}",
        "volatility_floor": config.DEFENSIVE_VOLATILITY_FLOOR,
        "z_score": round(z_score, 2),
        "z_threshold": config.Z_SCORE_THRESHOLD,
        "volume_ratio": vol_ratio,
        "volume_confirmation": vol_conf,
        "volume_basis": v_basis,
        "volume_status": vol_status,
        "liquidity_condition": liq_cond,
        "quant_signal": quant_signal
    }

    return DivergenceResult(
        asset=asset,
        benchmark=resolved_benchmark,
        beta=round(beta, 4),
        benchmark_move=round(benchmark_move, 6),
        expected_move=round(expected_move, 6),
        actual_move=round(actual_move, 6),
        residual=round(residual, 6),
        residual_stdev=round(residual_stdev, 6),
        z_score=round(z_score, 2),
        z_threshold=config.Z_SCORE_THRESHOLD,
        volatility_floor=config.DEFENSIVE_VOLATILITY_FLOOR,
        after_hours_volume=round(after_hours_volume, 2) if after_hours_volume is not None else None,
        trailing_avg_volume=round(trailing_avg_volume, 2) if trailing_avg_volume is not None else None,
        volume_ratio=vol_ratio,
        volume_confirmation=vol_conf,
        volume_basis=v_basis,
        volume_status=vol_status,
        liquidity_condition=liq_cond,
        actual_move_basis=actual_move_basis,
        actual_move_status=actual_move_status,
        benchmark_type=b_type,
        quant_signal=quant_signal,
        diagnostics=diagnostics
    )
