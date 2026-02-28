from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.bot.validators import InvalidLLMOutput, validate_llm_json
from app.llm.prompts import CORRECTION_PROMPT

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqClient:
    """Drop-in replacement for OllamaClient that uses the Groq cloud API."""

    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant", timeout_sec: int = 30) -> None:
        if not api_key:
            raise ValueError("GROQ_API_KEY is required. Set it in .env or as an environment variable.")
        self.api_key = api_key
        self.model = model
        self.timeout_sec = timeout_sec
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=self.timeout_sec,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def _request(self, messages: List[Dict[str, str]]) -> str:
        client = self._get_client()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
        }
        response = client.post(GROQ_CHAT_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])

    def chat_json(self, messages: List[Dict[str, str]], max_retries: int = 1) -> Dict[str, Any]:
        local_messages = list(messages)
        last_error = None

        for _ in range(max_retries + 1):
            content = self._request(local_messages)
            try:
                return validate_llm_json(content)
            except InvalidLLMOutput as exc:
                last_error = str(exc)
                logger.warning("Invalid LLM JSON from Groq: %s", exc)
                local_messages.append({"role": "user", "content": CORRECTION_PROMPT})

        raise RuntimeError(f"Groq LLM failed strict JSON after retries: {last_error}")
