from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.bot.validators import InvalidLLMOutput, validate_llm_json
from app.llm.prompts import CORRECTION_PROMPT

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, host: str, model: str, timeout_sec: int = 30) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self._resolved_model: Optional[str] = None
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        """Reuse a persistent connection for faster consecutive requests."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self.timeout_sec)
        return self._client

    @staticmethod
    def _messages_to_prompt(messages: List[Dict[str, str]]) -> str:
        parts = []
        for msg in messages:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
        parts.append("ASSISTANT:")
        return "\n\n".join(parts)

    def _resolve_model(self, client: httpx.Client) -> str:
        if self._resolved_model:
            return self._resolved_model
        try:
            response = client.get(f"{self.host}/api/tags")
            response.raise_for_status()
            tags = response.json().get("models", [])
            installed = [str(m.get("name") or "") for m in tags if m.get("name")]
            if self.model in installed:
                self._resolved_model = self.model
                return self._resolved_model
            if installed:
                self._resolved_model = installed[0]
                logger.warning(
                    "Configured model '%s' not found in Ollama. Falling back to '%s'.",
                    self.model,
                    self._resolved_model,
                )
                return self._resolved_model
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not resolve Ollama model list: %s", exc)
        self._resolved_model = self.model
        return self._resolved_model

    def _request(self, messages: List[Dict[str, str]]) -> str:
        client = self._get_client()
        model = self._resolve_model(client)
        payload_chat = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_predict": 300,
            },
        }
        response = client.post(f"{self.host}/api/chat", json=payload_chat)
        if response.status_code == 404:
            logger.warning("Ollama /api/chat unavailable. Falling back to /api/generate.")
            payload_generate = {
                "model": model,
                "prompt": self._messages_to_prompt(messages),
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0,
                    "num_predict": 300,
                },
            }
            fallback = client.post(f"{self.host}/api/generate", json=payload_generate)
            fallback.raise_for_status()
            data = fallback.json()
            return str(data.get("response") or "")
        response.raise_for_status()
        data = response.json()
        return str(data.get("message", {}).get("content", ""))

    def chat_json(self, messages: List[Dict[str, str]], max_retries: int = 1) -> Dict[str, Any]:
        local_messages = list(messages)
        last_error = None

        for _ in range(max_retries + 1):
            content = self._request(local_messages)
            try:
                return validate_llm_json(content)
            except InvalidLLMOutput as exc:
                last_error = str(exc)
                logger.warning("Invalid LLM JSON: %s", exc)
                local_messages.append({"role": "user", "content": CORRECTION_PROMPT})

        raise RuntimeError(f"LLM failed strict JSON after retries: {last_error}")
