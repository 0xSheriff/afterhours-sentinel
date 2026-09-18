"""
AfterHours Sentinel - LLM Analyst (Groq Integration)
Classifies an event's implied fundamental/sentiment direction (bullish | bearish | neutral)
for a specific rToken asset using Groq's high-speed OpenAI-compatible inference API
(default endpoint: https://api.groq.com/openai/v1/chat/completions, model: qwen/qwen3.8-27b).

Constraint: This model does not see or produce the z-score or trade decision.
It only judges the event's implied direction for the specified asset.
"""

import os
import sys
import re
import json
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
import config

GROQ_API_KEY = config.GROQ_API_KEY


@dataclass(frozen=True)
class LLMClassification:
    """Structured output from LLM Analyst."""
    direction: str  # "bullish" | "bearish" | "neutral" | "unclear" (backwards compatible alias)
    reasoning: str
    llm_source: str  # e.g. "groq_qwen3.8-27b [live_api]" | "fallback_rules [pending_groq_api_key]"
    event_type: str = "other"
    fundamental_direction: str = "neutral"
    qwen_validation: str = "PASS"  # "PASS" | "FAIL"
    raw_response: Optional[Dict[str, Any]] = None
    is_fallback: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


PROMPT_TEMPLATE = """You are an expert financial market analyst specializing in after-hours event interpretation.
Analyze the following event and determine its fundamental/macro implied directional impact on the target asset: {asset}.

Event Details:
- Initial Type: {event_type}
- Headline: {headline}
- Content: {raw_text}

Rules:
1. Classify the event_type strictly as one of: "earnings", "macro", "regulatory", "tariff", "geopolitical", "product", "corporate", "analyst", "other".
2. Classify fundamental_direction strictly as one of: "bullish", "bearish", "neutral", or "unclear".
3. Provide exactly one sentence of clear analytical reasoning.
4. Do NOT calculate z-scores, price moves, position sizes, or trades. You are an event interpretation layer only.
5. You must output ONLY a valid JSON object matching this schema:
{{
  "event_type": "earnings" | "macro" | "regulatory" | "tariff" | "geopolitical" | "product" | "corporate" | "analyst" | "other",
  "fundamental_direction": "bullish" | "bearish" | "neutral" | "unclear",
  "reasoning": "One sentence explanation."
}}
"""


def call_groq_api(
    prompt: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Calls OpenAI-compatible Groq API endpoint via standard library urllib.
    Returns (parsed_json_response, status_or_error_message).
    """
    target_key = api_key or os.getenv("GROQ_API_KEY", config.GROQ_API_KEY)
    target_url = base_url or os.getenv("GROQ_BASE_URL", config.GROQ_BASE_URL)
    target_model = model or os.getenv("GROQ_MODEL", config.GROQ_MODEL)

    url = f"{target_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {target_key}",
        "User-Agent": "AfterHoursSentinel/1.0"
    }
    payload = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": "You are a professional financial analyst. Output strictly JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            status_code = response.getcode()
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)
            content_str = res_json["choices"][0]["message"]["content"]
            parsed_content = json.loads(content_str)
            usage = res_json.get("usage", {})
            msg = f"HTTP {status_code} OK | Model: {target_model} | Tokens: prompt={usage.get('prompt_tokens', 0)}, completion={usage.get('completion_tokens', 0)}"
            return parsed_content, msg
    except urllib.error.HTTPError as e:
        err_msg = f"HTTPError {e.code}: {e.reason}"
        return None, err_msg
    except urllib.error.URLError as e:
        err_msg = f"URLError: {e.reason}"
        return None, err_msg
    except Exception as e:
        return None, str(e)

def verify_groq_connection(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None
) -> tuple[bool, str]:
    """
    Performs a single lightweight live authentication & response verification check against Groq endpoint.
    Returns (is_authenticated, status_or_error_message).
    """
    target_key = api_key or os.getenv("GROQ_API_KEY", config.GROQ_API_KEY)
    if not target_key or target_key in ("mock_groq_key", "mock_qwen_key"):
        return False, "No valid GROQ_API_KEY configured (mock key string)"

    test_prompt = "Ping test. Output valid JSON: {\"status\": \"ok\"}"
    parsed_res, msg = call_groq_api(
        prompt=test_prompt,
        api_key=target_key,
        base_url=base_url,
        model=model
    )
    if parsed_res is not None:
        return True, f"Authenticated ({msg})"
    return False, f"Authentication Check Failed ({msg})"



def fallback_rule_classifier(headline: str, raw_text: str, event_type: str, asset: str) -> LLMClassification:
    """
    Deterministic offline fallback classifier for testing and simulated replay.
    Explicitly tags llm_source as fallback to maintain 100% audit transparency.
    """
    from event_listener import classify_event_type

    text = f"{headline} {raw_text}".lower()
    resolved_type = event_type if event_type in config.EVENT_TAXONOMY else classify_event_type(headline, raw_text)

    # Bearish cues
    bearish_cues = [
        "tariff", "tariffs", "sanction", "sanctions", "miss", "misses",
        "lowers guidance", "cut guidance", "profit warning", "investigation", "probe",
        "antitrust", "ban", "slump", "loss", "losses", "subpoena", "lawsuit", "downgrade"
    ]
    # Bullish cues
    bullish_cues = [
        "beats", "beat", "beat consensus", "raises guidance", "raised guidance",
        "surges", "surge", "rate cut", "liquidity", "record revenue", "record profit",
        "soars", "approval", "stimulus", "buyback", "upgrade", "outperform"
    ]

    has_bearish = any(re.search(r'\b' + re.escape(cue) + r'\b', text) for cue in bearish_cues)
    has_bullish = any(re.search(r'\b' + re.escape(cue) + r'\b', text) for cue in bullish_cues)

    if has_bearish and not has_bullish:
        direction = "bearish"
        reasoning = f"Event introduces adverse regulatory, tariff, or fundamental pressure on {asset}."
    elif has_bullish and not has_bearish:
        direction = "bullish"
        reasoning = f"Event signals fundamental revenue/guidance upside or favorable operational growth for {asset}."
    else:
        direction = "neutral"
        reasoning = f"Event does not have a definitive directional catalyst for {asset}."

    return LLMClassification(
        direction=direction,
        fundamental_direction=direction,
        event_type=resolved_type,
        reasoning=reasoning,
        qwen_validation="PASS",
        llm_source="fallback_rules [pending_groq_api_key]"
    )


def build_analysis_prompt(headline: str, asset: str, event_type: str, raw_text: str) -> str:
    """Builds structured prompt for Qwen model."""
    return PROMPT_TEMPLATE.format(
        asset=asset,
        event_type=event_type,
        headline=headline,
        raw_text=raw_text
    )


def validate_qwen_payload(payload: Any) -> tuple[bool, Dict[str, Any]]:
    """
    Validates structured JSON output from Qwen model against required schema:
    - event_type in config.EVENT_TAXONOMY
    - fundamental_direction in ('bullish', 'bearish', 'neutral', 'unclear')
    - non-empty reasoning string
    Returns (is_valid, sanitized_dict).
    """
    if not isinstance(payload, dict):
        return False, {"qwen_validation": "FAIL", "reason": "Payload is not a dictionary"}

    ev_type = str(payload.get("event_type", "")).strip().lower()
    fund_dir = str(payload.get("fundamental_direction") or payload.get("direction", "")).strip().lower()
    reasoning = str(payload.get("reasoning", "")).strip()

    valid_dirs = ["bullish", "bearish", "neutral", "unclear"]
    if not fund_dir or fund_dir not in valid_dirs:
        return False, {"qwen_validation": "FAIL", "reason": f"Invalid fundamental_direction: {fund_dir}"}

    if not reasoning:
        return False, {"qwen_validation": "FAIL", "reason": "Missing or empty reasoning"}

    if ev_type and ev_type not in config.EVENT_TAXONOMY:
        ev_type = "other"

    return True, {
        "event_type": ev_type,
        "fundamental_direction": fund_dir,
        "reasoning": reasoning,
        "qwen_validation": "VALID"
    }


def analyze_event(
    event: Dict[str, Any],
    asset: str = "NVDA",
    api_key: Optional[str] = None,
    allow_fallback: bool = True
) -> LLMClassification:
    """
    Orchestrates LLM event analysis via Groq API (Qwen 2.5 32B / Qwen 3.8 27B).
    Validates structured response fields against strict schema:
    - event_type (9-category taxonomy)
    - fundamental_direction ('bullish' | 'bearish' | 'neutral' | 'unclear')
    - reasoning (non-empty string)

    If Qwen output is malformed or ambiguous, marks qwen_validation = 'FAIL'.
    """
    headline = event.get("headline", "")
    raw_text = event.get("raw_text", "")
    event_type = event.get("event_type", "macro")

    prompt = build_analysis_prompt(
        headline=headline,
        asset=asset,
        event_type=event_type,
        raw_text=raw_text
    )

    api_result, status_msg = call_groq_api(prompt, api_key=api_key)
    target_model = os.getenv("GROQ_MODEL", config.GROQ_MODEL)
    clean_model_tag = target_model.split("/")[-1]

    if api_result and isinstance(api_result, dict):
        is_valid, validated = validate_qwen_payload(api_result)
        if is_valid:
            print(f"[Groq Analyst LIVE API SUCCESS] {status_msg}")
            return LLMClassification(
                direction=validated["fundamental_direction"],
                fundamental_direction=validated["fundamental_direction"],
                event_type=validated["event_type"] or event_type,
                reasoning=validated["reasoning"],
                qwen_validation="VALID",
                llm_source=f"groq_{clean_model_tag} [live_api]",
                raw_response=api_result
            )
        else:
            print(f"[Groq Analyst WARNING] Malformed LLM response schema: {api_result}. Marking qwen_validation='FAIL'.")
            fb = fallback_rule_classifier(headline, raw_text, event_type, asset)
            return LLMClassification(
                direction=fb.direction,
                fundamental_direction=fb.fundamental_direction,
                event_type=fb.event_type,
                reasoning=f"Malformed Qwen response ({status_msg}). {fb.reasoning}",
                qwen_validation="FAIL",
                llm_source=f"groq_{clean_model_tag} [malformed_response]",
                raw_response=api_result,
                is_fallback=True
            )

    print(f"[Groq Analyst WARNING] Live API call failed ({status_msg}). Falling back to local classifier.")
    return fallback_rule_classifier(headline, raw_text, event_type, asset)


if __name__ == "__main__":
    # Standalone CLI test tool to test Groq key in 1 second
    print("=" * 80)
    print(" GROQ LLM ANALYST - CONNECTION TEST TOOL")
    print("=" * 80)
    current_key = os.getenv("GROQ_API_KEY", config.GROQ_API_KEY)
    print(f" Target URL   : {config.GROQ_BASE_URL}")
    print(f" Target Model : {config.GROQ_MODEL}")
    print(f" Active Key   : {current_key[:8]}... (len={len(current_key)})" if len(current_key) > 8 else f" Active Key   : {current_key}")
    print("-" * 80)

    sample_event = {
        "headline": "U.S. Commerce Dept Announces Immediate 25% Tariffs on Advanced Semiconductor Equipment",
        "raw_text": "The Department of Commerce expanded export tariffs targeting advanced lithography and packaging equipment.",
        "event_type": "macro"
    }

    result = analyze_event(sample_event, asset="NVDA")
    print("-" * 80)
    print(f" LLM Source   : {result.llm_source}")
    print(f" Direction    : {result.direction.upper()}")
    print(f" Reasoning    : \"{result.reasoning}\"")
    print("=" * 80)
