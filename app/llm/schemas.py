from __future__ import annotations

from typing import Any, Dict, Literal, Union

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    type: Literal["tool_call"]
    tool: Literal["search_products", "get_product", "quote_items", "browse_category", "list_categories"]
    args: Dict[str, Any] = Field(default_factory=dict)


class FinalMessage(BaseModel):
    type: Literal["final"]
    message: str


LLMAction = Union[ToolCall, FinalMessage]


def parse_action(payload: Dict[str, Any]) -> LLMAction:
    if payload.get("type") == "tool_call":
        return ToolCall.model_validate(payload)
    return FinalMessage.model_validate(payload)
