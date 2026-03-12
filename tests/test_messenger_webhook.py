from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.config import Settings
from app.main import create_app
from app.routers import messenger_webhook


class FakeLLM:
    def chat_json(self, messages: List[Dict[str, str]], max_retries: int = 2) -> Dict[str, Any]:
        return {"type": "final", "message": "fallback"}


class StubOrchestrator:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, str]] = []

    def process_message(self, channel_user_id: str, text: str, channel: str = "simulator") -> str:
        self.calls.append((channel_user_id, text, channel))
        return f"Bot reply: {text}"


def build_products(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "products"
    ws.append(
        [
            "product_id",
            "name",
            "url",
            "category",
            "price",
            "regular_price",
            "unit",
            "stock_qty",
            "is_active",
            "image_url",
            "updated_at",
        ]
    )
    ws.append(["p-001", "Test Product", "", "Test", 10, "", "1pc", 10, True, "", "2026-01-01"])
    wb.save(path)


def build_app(tmp_path: Path, app_secret: str = "") -> tuple[Any, StubOrchestrator]:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        base_dir=tmp_path,
        data_dir=data_dir,
        products_xlsx=data_dir / "products.xlsx",
        orders_xlsx=data_dir / "orders.xlsx",
        sessions_db=data_dir / "sessions.db",
        api_endpoints_json=data_dir / "api_endpoints.json",
        vector_index_path=data_dir / "products.index",
        llm_provider="ollama",
        groq_api_key="",
        groq_model="llama-3.1-8b-instant",
        ollama_host="http://localhost:11434",
        ollama_model="llama3.1:8b",
        fb_verify_token="verify-token-123",
        fb_page_access_token="page-token-123",
        fb_app_secret=app_secret,
    )
    build_products(settings.products_xlsx)

    app = create_app(settings=settings, llm_client=FakeLLM())
    orchestrator = StubOrchestrator()
    app.state.orchestrator = orchestrator
    return app, orchestrator


def test_webhook_verification_success(tmp_path: Path) -> None:
    app, _ = build_app(tmp_path)
    client = TestClient(app)

    res = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-token-123",
            "hub.challenge": "challenge-ok",
        },
    )
    assert res.status_code == 200
    assert res.text == "challenge-ok"


def test_webhook_verification_invalid_token(tmp_path: Path) -> None:
    app, _ = build_app(tmp_path)
    client = TestClient(app)

    res = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-ok",
        },
    )
    assert res.status_code == 403


def test_webhook_processes_text_message_and_sends_reply(tmp_path: Path, monkeypatch: Any) -> None:
    app, orchestrator = build_app(tmp_path)
    client = TestClient(app)

    sent: List[Tuple[str, str, str]] = []

    async def fake_send_text_reply(page_access_token: str, recipient_psid: str, text: str) -> bool:
        sent.append((page_access_token, recipient_psid, text))
        return True

    monkeypatch.setattr(messenger_webhook, "_send_text_reply", fake_send_text_reply)

    payload = {
        "object": "page",
        "entry": [
            {
                "messaging": [
                    {
                        "sender": {"id": "psid-1"},
                        "message": {"text": "hello from messenger"},
                    }
                ]
            }
        ],
    }
    res = client.post("/webhook", json=payload)
    body = res.json()

    assert res.status_code == 200
    assert body["status"] == "ok"
    assert body["processed_messages"] == 1
    assert orchestrator.calls == [("psid-1", "hello from messenger", "messenger")]
    assert sent == [("page-token-123", "psid-1", "Bot reply: hello from messenger")]


def test_webhook_ignores_unsupported_events(tmp_path: Path, monkeypatch: Any) -> None:
    app, orchestrator = build_app(tmp_path)
    client = TestClient(app)

    async def fake_send_text_reply(page_access_token: str, recipient_psid: str, text: str) -> bool:
        return True

    monkeypatch.setattr(messenger_webhook, "_send_text_reply", fake_send_text_reply)

    payload = {
        "object": "page",
        "entry": [
            {
                "messaging": [
                    {
                        "sender": {"id": "psid-1"},
                        "delivery": {"mids": ["mid.1"]},
                    }
                ]
            }
        ],
    }
    res = client.post("/webhook", json=payload)
    body = res.json()

    assert res.status_code == 200
    assert body["status"] == "ok"
    assert body["processed_messages"] == 0
    assert body["ignored_events"] >= 1
    assert orchestrator.calls == []


def test_webhook_signature_verification(tmp_path: Path, monkeypatch: Any) -> None:
    app, _ = build_app(tmp_path, app_secret="app-secret-123")
    client = TestClient(app)

    async def fake_send_text_reply(page_access_token: str, recipient_psid: str, text: str) -> bool:
        return True

    monkeypatch.setattr(messenger_webhook, "_send_text_reply", fake_send_text_reply)

    payload = {
        "object": "page",
        "entry": [
            {
                "messaging": [
                    {
                        "sender": {"id": "psid-2"},
                        "message": {"text": "secure hello"},
                    }
                ]
            }
        ],
    }
    raw = json.dumps(payload).encode("utf-8")
    digest = hmac.new(b"app-secret-123", raw, hashlib.sha256).hexdigest()

    ok_res = client.post(
        "/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={digest}",
        },
    )
    assert ok_res.status_code == 200

    bad_res = client.post(
        "/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=bad-signature",
        },
    )
    assert bad_res.status_code == 403
