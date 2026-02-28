from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Tuple


class ChannelAdapter(ABC):
    name: str

    @abstractmethod
    def normalize_inbound(self, payload: Any) -> Tuple[str, str]:
        """Return (channel_user_id, text)."""


class SimulatorChannelAdapter(ChannelAdapter):
    name = "simulator"

    def normalize_inbound(self, payload: Any) -> Tuple[str, str]:
        user_id = str(payload.channel_user_id).strip()
        text = str(payload.text).strip()
        return user_id, text
