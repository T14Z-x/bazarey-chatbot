from __future__ import annotations

import json
import re
from typing import Any, Dict

from pydantic import ValidationError

from app.llm.schemas import parse_action


class InvalidLLMOutput(ValueError):
    """Raised when the LLM output is not valid strict JSON."""


def _extract_json_block(text: str) -> str:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        return match.group(0)
    raise InvalidLLMOutput("No JSON object found in output")


def validate_llm_json(raw_content: str) -> Dict[str, Any]:
    try:
        payload = json.loads(_extract_json_block(raw_content))
    except json.JSONDecodeError as exc:
        raise InvalidLLMOutput(f"Invalid JSON: {exc}") from exc

    try:
        action = parse_action(payload)
    except ValidationError as exc:
        raise InvalidLLMOutput(f"Schema validation error: {exc}") from exc
    return action.model_dump()
