"""
AfterHours Sentinel - Risk Engine
Pure rule-based deterministic trade gatekeeper, position sizer, and risk manager.
Zero LLM dependencies.
"""

from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional
import config
from divergence_engine import DivergenceResult


@dataclass
class PortfolioState:
    """Current snapshot of the paper portfolio state for risk validation."""
    portfolio_balance: float = config.DEFAULT_PORTFOLIO_BALANCE_USD
    open_positions_count: int = 0
    daily_realized_loss_pct: float = 0.0  # Cumulative daily loss as positive decimal (e.g. 0.015 for 1.5%)
    is_halted: bool = False
    total_balance: Optional[float] = None
    available_balance: Optional[float] = None
    open_positions: Optional[List[str]] = None

    def __post_init__(self):
        if self.total_balance is not None:
            self.portfolio_balance = self.total_balance
        elif self.available_balance is not None:
            self.portfolio_balance = self.available_balance
        if self.open_positions is not None:
            self.open_positions_count = len(self.open_positions)


@dataclass(frozen=True)
class RiskEvaluation:
    """Structured output of the Risk Engine evaluation."""
    decision: str = "NO_TRADE"  # "SHORT" | "LONG" | "NO_TRADE"
    signals_aligned: str = "0/3 signals aligned"
    aligned_count: int = 0
    failed_conditions: List[str] = field(default_factory=list)
    position_size_usd: float = 0.0
    entry_price: float = 0.0
    stop_price: float = 0.0
    reason: str = ""
    divergence: Dict[str, Any] = field(default_factory=dict)
    qwen_direction: str = "neutral"
    qwen_reasoning: str = ""
    quant_signal: str = "FAIL"  # "PASS" | "FAIL"
    z_score: float = 0.0
    z_threshold: float = config.Z_SCORE_THRESHOLD
    event_direction: str = "neutral"
    price_direction: str = "flat"
    direction_alignment: str = "ALIGNMENT"  # "ALIGNMENT" | "CONTRADICTION" | "NEUTRAL"
    volume_ratio: Optional[float] = None
    volume_status: str = "MEASURED"
    liquidity_condition: str = "INSUFFICIENT_DATA"
    qwen_validation: str = "PASS"  # "PASS" | "FAIL"
    risk_gate: str = "PASS"  # "PASS" | "BLOCK"
    llm_source: str = "fallback_rules [pending_qwen_api_key]"
    action: str = ""
    side: str = ""
    stop_loss_pct: float = config.STOP_LOSS_PCT
    take_profit_pct: float = config.TAKE_PROFIT_PCT
    strategy_mode: str = "MEAN_REVERSION"  # "MEAN_REVERSION" | "MOMENTUM"

    def __post_init__(self):
        if self.action and self.decision == "NO_TRADE":
            if self.action == "PAPER_TRADE" and self.side in ("SHORT", "LONG"):
                object.__setattr__(self, "decision", self.side)
        if not self.action:
            object.__setattr__(self, "action", "PAPER_TRADE" if self.decision in ("SHORT", "LONG") else "NO_TRADE")
        if not self.side:
            object.__setattr__(self, "side", self.decision if self.decision in ("SHORT", "LONG") else "NONE")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


RiskEvaluationResult = RiskEvaluation


def determine_direction_alignment(event_dir: str, actual_move: float) -> str:
    """Determines whether fundamental event direction aligns or contradicts price move."""
    dir_clean = str(event_dir).strip().lower()
    price_dir = "bullish" if actual_move > 0.0001 else ("bearish" if actual_move < -0.0001 else "flat")
    if dir_clean in ("neutral", "unclear") or price_dir == "flat":
        return "NEUTRAL"
    if (dir_clean == "bullish" and price_dir == "bullish") or (dir_clean == "bearish" and price_dir == "bearish"):
        return "ALIGNMENT"
    if (dir_clean == "bearish" and price_dir == "bullish") or (dir_clean == "bullish" and price_dir == "bearish"):
        return "CONTRADICTION"
    return "NEUTRAL"


def evaluate_trade_risk(
    divergence: DivergenceResult,
    sentiment_direction: str = "neutral",
    sentiment_score: float = 0.0,
    account_balance: float = config.DEFAULT_PORTFOLIO_BALANCE_USD,
    active_positions: Optional[List[str]] = None,
    daily_loss_pct: float = 0.0,
    qwen_validation: str = "PASS",
    current_price: float = 100.0,
    event_type: str = "other",
    strategy_mode: Optional[str] = None,
    **kwargs
) -> RiskEvaluation:
    """Wrapper entrypoint for trade risk evaluation supporting alternative parameter conventions."""
    state = PortfolioState(
        portfolio_balance=account_balance,
        open_positions=active_positions or [],
        daily_realized_loss_pct=daily_loss_pct
    )
    ev_type = kwargs.get("event_type", event_type)
    strat_mode = kwargs.get("strategy_mode", strategy_mode)
    return evaluate_trade(
        divergence=divergence,
        qwen_direction=sentiment_direction,
        qwen_reasoning="Risk evaluation model analysis",
        current_price=current_price,
        portfolio_state=state,
        qwen_validation=qwen_validation,
        event_type=ev_type,
        strategy_mode=strat_mode
    )


def evaluate_trade(
    divergence: DivergenceResult,
    qwen_direction: str,
    qwen_reasoning: str,
    current_price: float,
    portfolio_state: Optional[PortfolioState] = None,
    llm_source: str = "fallback_rules [pending_qwen_api_key]",
    qwen_validation: str = "PASS",
    event_type: str = "other",
    strategy_mode: Optional[str] = None
) -> RiskEvaluation:
    """
    Evaluates whether an observed divergence and event direction qualify for a trade.
    Decouples Quantitative Anomaly Signal from Qwen Event Validation.

    Event-Type-Differentiated Strategies:
      1. MOMENTUM / PEAD (Post-Earnings Announcement Drift):
         Applied to event_type in ("earnings", "product").
         - Seeks fundamental price discovery continuation with institutional volume confirmation.
         - Requires DIRECTIONAL ALIGNMENT (Bullish event + positive price move -> LONG; Bearish event + negative price move -> SHORT).
         - Requires CONFIRMING_VOLUME (volume_ratio >= 0.8) and |z| >= 2.0.
      2. MEAN_REVERSION / FADE:
         Applied to all other event types ("macro", "tariff", "geopolitical", "regulatory", "other").
         - Seeks transitory dislocations where information and price disagree on weak liquidity.
         - Requires DIRECTIONAL CONTRADICTION (Bearish event + price pumped -> SHORT; Bullish event + price dumped -> LONG).
         - Requires WEAK_LIQUIDITY (volume_ratio < 0.5) and |z| >= 2.0.

    Deterministic Risk Bounds:
      - Fixed 3% of paper portfolio per trade.
      - Hard stop at 1.5% from entry.
      - Max 2 simultaneous open positions.
      - Daily loss limit 2% of portfolio — halts new trades for the day.
    """
    state = portfolio_state or PortfolioState()
    failed_conditions: List[str] = []
    aligned_count = 0
    dir_clean = qwen_direction.strip().lower()

    # Determine strategy mode from event_type if not explicitly provided
    if strategy_mode is None:
        clean_type = str(event_type).strip().lower()
        mode = "MOMENTUM" if clean_type in ("earnings", "product") else "MEAN_REVERSION"
    else:
        mode = strategy_mode.strip().upper()

    # 1. Price Direction & Event Direction Analysis
    price_dir = "bullish" if divergence.actual_move > 0.0001 else ("bearish" if divergence.actual_move < -0.0001 else "flat")
    event_dir = dir_clean if dir_clean in ("bullish", "bearish", "neutral", "unclear") else "neutral"

    # 2. Direction Alignment Classification
    if event_dir == "neutral" or event_dir == "unclear" or price_dir == "flat":
        direction_alignment = "NEUTRAL"
    elif (event_dir == "bullish" and price_dir == "bullish") or (event_dir == "bearish" and price_dir == "bearish"):
        direction_alignment = "ALIGNMENT"
    elif (event_dir == "bearish" and price_dir == "bullish") or (event_dir == "bullish" and price_dir == "bearish"):
        direction_alignment = "CONTRADICTION"
    else:
        direction_alignment = "NEUTRAL"

    # Check Signal 1: Z-score threshold (Identical bar for both modes)
    z_score_pass = abs(divergence.z_score) >= config.Z_SCORE_THRESHOLD
    if z_score_pass:
        aligned_count += 1
    else:
        failed_conditions.append(
            f"Z-score threshold failed: abs({divergence.z_score:.2f}) <= {config.Z_SCORE_THRESHOLD}"
        )

    # Check Signal 2: Directional Condition & Tentative Side
    tentative_side: Optional[str] = None
    if mode == "MOMENTUM":
        # Momentum (PEAD) requires fundamental ALIGNMENT
        if direction_alignment == "ALIGNMENT":
            aligned_count += 1
            if event_dir == "bullish" and price_dir == "bullish":
                tentative_side = "LONG"
            elif event_dir == "bearish" and price_dir == "bearish":
                tentative_side = "SHORT"
        elif direction_alignment == "CONTRADICTION":
            failed_conditions.append(
                f"Direction contradiction rejected in momentum mode: Qwen ({dir_clean}) contradicts price move ({divergence.actual_move:+.2%})"
            )
        else:
            failed_conditions.append(
                f"Direction neutral/unclear: Qwen classified event as '{dir_clean}'"
            )
    else:
        # MEAN_REVERSION requires fundamental CONTRADICTION (fade candidate)
        if direction_alignment == "CONTRADICTION":
            aligned_count += 1
            if event_dir == "bearish" and price_dir == "bullish":
                tentative_side = "SHORT"
            elif event_dir == "bullish" and price_dir == "bearish":
                tentative_side = "LONG"
        elif direction_alignment == "ALIGNMENT":
            failed_conditions.append(
                f"Direction alignment confirmed: Qwen ({dir_clean}) agrees with price move ({divergence.actual_move:+.2%})"
            )
        else:
            failed_conditions.append(
                f"Direction neutral/unclear: Qwen classified event as '{dir_clean}'"
            )

    # Check Signal 3: Liquidity Condition
    if mode == "MOMENTUM":
        # Momentum requires confirming volume (volume_ratio >= 0.8)
        vol_confirming = (
            divergence.liquidity_condition in ("CONFIRMING_VOLUME", "HIGH_VOLUME_CONFIRMED")
            or (divergence.volume_ratio is not None and divergence.volume_ratio >= config.VOLUME_RATIO_CONFIRMING_THRESHOLD)
        )
        if vol_confirming and divergence.liquidity_condition != "INSUFFICIENT_DATA":
            vol_pass = True
            aligned_count += 1
        else:
            vol_pass = False
            if divergence.liquidity_condition == "INSUFFICIENT_DATA" or divergence.volume_ratio is None:
                failed_conditions.append(
                    "Volume confirmation failed: Insufficient volume history to verify institutional participation"
                )
            else:
                v_ratio_str = f"{divergence.volume_ratio:.2f}"
                failed_conditions.append(
                    f"Volume confirmation failed: Volume ratio is {v_ratio_str} (expected confirming >= {config.VOLUME_RATIO_CONFIRMING_THRESHOLD})"
                )
    else:
        # MEAN_REVERSION requires weak liquidity (volume_ratio < 0.5)
        vol_pass = (divergence.liquidity_condition == "WEAK_LIQUIDITY")
        if vol_pass:
            aligned_count += 1
        else:
            if divergence.liquidity_condition == "INSUFFICIENT_DATA":
                failed_conditions.append(
                    "Volume confirmation failed: Insufficient volume history to verify liquidity vacuum"
                )
            else:
                v_ratio_str = f"{divergence.volume_ratio:.2f}" if divergence.volume_ratio is not None else "N/A"
                failed_conditions.append(
                    f"Volume confirmation failed: Volume ratio is {v_ratio_str} (expected weak < {config.VOLUME_RATIO_WEAK_THRESHOLD})"
                )

    # Quantitative Anomaly Signal (Pure Math + Liquidity)
    quant_signal = "PASS" if (z_score_pass and vol_pass) else "FAIL"

    # Qwen Event Validation Check
    qwen_pass = (qwen_validation in ("PASS", "VALID")) and (event_dir in ("bullish", "bearish"))
    if not qwen_pass:
        if qwen_validation == "FAIL":
            failed_conditions.append("Qwen validation failed: Malformed or unparseable LLM output")
        elif event_dir not in ("bullish", "bearish"):
            failed_conditions.append(f"Qwen validation neutral: Event direction '{event_dir}' does not support directional edge")

    # Risk Engine Gates (Deterministic Portfolio Bounds)
    risk_gate = "PASS"
    if state.is_halted or state.daily_realized_loss_pct >= config.DAILY_LOSS_LIMIT_PCT:
        failed_conditions.append(
            f"Daily loss limit reached: {state.daily_realized_loss_pct:.2%} >= {config.DAILY_LOSS_LIMIT_PCT:.2%}. Trading halted for the day."
        )
        risk_gate = "BLOCK"

    if state.open_positions_count >= config.MAX_OPEN_POSITIONS:
        failed_conditions.append(
            f"Max open positions reached: {state.open_positions_count} >= {config.MAX_OPEN_POSITIONS} active trades."
        )
        risk_gate = "BLOCK"

    # Final Decision Formulation
    signals_aligned_str = f"{aligned_count}/3 signals aligned"
    required_alignment = "ALIGNMENT" if mode == "MOMENTUM" else "CONTRADICTION"

    if (
        quant_signal == "PASS"
        and direction_alignment == required_alignment
        and qwen_pass
        and risk_gate == "PASS"
        and tentative_side is not None
    ):
        decision = tentative_side
        position_size_usd = round(state.portfolio_balance * config.POSITION_SIZE_PCT, 2)
        vol_ratio_str = f"{divergence.volume_ratio:.2f}" if divergence.volume_ratio is not None else "measured"

        if mode == "MOMENTUM":
            if decision == "LONG":
                stop_price = round(current_price * (1.0 - config.STOP_LOSS_PCT), 4)
                reason = (
                    f"LONG signal approved (MOMENTUM/PEAD): Bullish earnings drift with confirming volume "
                    f"({vol_ratio_str} >= {config.VOLUME_RATIO_CONFIRMING_THRESHOLD}) and statistical significance (z={divergence.z_score:+.2f})."
                )
            else:  # SHORT
                stop_price = round(current_price * (1.0 + config.STOP_LOSS_PCT), 4)
                reason = (
                    f"SHORT signal approved (MOMENTUM/PEAD): Bearish earnings breakdown with confirming volume "
                    f"({vol_ratio_str} >= {config.VOLUME_RATIO_CONFIRMING_THRESHOLD}) and statistical significance (z={divergence.z_score:+.2f})."
                )
        else:  # MEAN_REVERSION
            if decision == "SHORT":
                stop_price = round(current_price * (1.0 + config.STOP_LOSS_PCT), 4)
                reason = (
                    f"SHORT signal approved: Price pumped {divergence.actual_move:+.2%} on bearish event "
                    f"with weak volume ({vol_ratio_str}) and high divergence (z={divergence.z_score:+.2f})."
                )
            else:  # LONG
                stop_price = round(current_price * (1.0 - config.STOP_LOSS_PCT), 4)
                reason = (
                    f"LONG signal approved: Price dumped {divergence.actual_move:+.2%} on bullish event "
                    f"with weak volume ({vol_ratio_str}) and high divergence (z={divergence.z_score:+.2f})."
                )
    else:
        decision = "NO_TRADE"
        position_size_usd = 0.0
        stop_price = 0.0

        # Construct clear institutional explanation
        if mode == "MOMENTUM":
            if direction_alignment == "CONTRADICTION":
                reason = (
                    f"NO_TRADE: Price move ({divergence.actual_move:+.2%}) contradicts {event_dir} fundamental direction "
                    f"in momentum mode. Post-Earnings Announcement Drift requires fundamental alignment."
                )
            elif not z_score_pass:
                reason = (
                    f"NO_TRADE: Insufficient divergence (|z|={abs(divergence.z_score):.2f} <= {config.Z_SCORE_THRESHOLD:.1f}) "
                    f"— price move ({divergence.actual_move:+.2%}) is within normal rolling beta-adjusted volatility."
                )
            elif not vol_pass:
                v_ratio_str = f"{divergence.volume_ratio:.2f}" if divergence.volume_ratio is not None else "N/A"
                reason = (
                    f"NO_TRADE: Momentum confirmation failed: Volume ratio {v_ratio_str} < {config.VOLUME_RATIO_CONFIRMING_THRESHOLD}. "
                    f"Institutional momentum drift requires confirming volume."
                )
            elif not qwen_pass:
                reason = f"NO_TRADE: Qwen validation failed or event direction is neutral ('{event_dir}'); no directional edge to trade against."
            elif risk_gate == "BLOCK":
                reason = f"NO_TRADE: Risk limit block: {'; '.join(failed_conditions)}"
            else:
                reason = f"NO_TRADE: {'; '.join(failed_conditions)}"
        else:
            # Existing MEAN_REVERSION explanation logic (unchanged)
            if direction_alignment == "ALIGNMENT":
                reason = (
                    f"NO_TRADE: Quantitative divergence did not exceed the configured threshold. "
                    f"Fundamental direction is {event_dir} and price direction is {price_dir}, "
                    f"so the event reaction is directionally aligned. No statistically significant "
                    f"mean-reversion opportunity was detected."
                )
            elif not z_score_pass:
                reason = (
                    f"NO_TRADE: Insufficient divergence (|z|={abs(divergence.z_score):.2f} <= {config.Z_SCORE_THRESHOLD:.1f}) "
                    f"— price move ({divergence.actual_move:+.2%}) is within normal rolling beta-adjusted volatility."
                )
            elif divergence.liquidity_condition in ("HIGH_VOLUME_CONFIRMED", "CONFIRMING_VOLUME"):
                v_ratio_str = f"{divergence.volume_ratio:.2f}" if divergence.volume_ratio is not None else ">=0.5"
                reason = (
                    f"NO_TRADE: High volume confirmation (volume_ratio={v_ratio_str} >= {config.VOLUME_RATIO_WEAK_THRESHOLD}) "
                    f"indicates institutional conviction; do not fade high-volume moves."
                )
            elif divergence.liquidity_condition == "INSUFFICIENT_DATA":
                reason = "NO_TRADE: Insufficient volume history to verify liquidity vacuum; risk engine blocks trade on unverified liquidity."
            elif not qwen_pass:
                reason = f"NO_TRADE: Qwen validation failed or event direction is neutral ('{event_dir}'); no directional edge to trade against."
            elif risk_gate == "BLOCK":
                reason = f"NO_TRADE: Risk limit block: {'; '.join(failed_conditions)}"
            else:
                reason = f"NO_TRADE: {'; '.join(failed_conditions)}"

    return RiskEvaluation(
        decision=decision,
        signals_aligned=signals_aligned_str,
        aligned_count=aligned_count,
        failed_conditions=failed_conditions,
        position_size_usd=position_size_usd,
        entry_price=round(current_price, 4),
        stop_price=stop_price,
        reason=reason,
        divergence=divergence.to_dict(),
        qwen_direction=dir_clean,
        qwen_reasoning=qwen_reasoning,
        quant_signal=quant_signal,
        z_score=round(divergence.z_score, 2),
        z_threshold=config.Z_SCORE_THRESHOLD,
        event_direction=event_dir,
        price_direction=price_dir,
        direction_alignment=direction_alignment,
        volume_ratio=divergence.volume_ratio,
        volume_status=divergence.volume_status,
        liquidity_condition=divergence.liquidity_condition,
        qwen_validation="PASS" if qwen_pass else "FAIL",
        risk_gate=risk_gate,
        llm_source=llm_source,
        strategy_mode=mode
    )

