from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.config import Settings

logger = logging.getLogger(__name__)

MESSENGER_SEND_API_URL = "https://graph.facebook.com/v20.0/me/messages"


def _verify_signature(raw_body: bytes, signature_header: Optional[str], app_secret: str) -> bool:
    """Validate X-Hub-Signature-256 when app secret is configured."""
    if not app_secret:
        return True
    if not signature_header:
        return False

    algo, sep, provided = signature_header.partition("=")
    if sep != "=" or algo.lower() != "sha256" or not provided:
        return False

    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def _extract_text_messages(payload: Dict[str, Any]) -> Tuple[List[Tuple[str, str]], int]:
    """Extract text messages from Messenger webhook payload.

    Returns: ([(psid, text), ...], ignored_event_count)
    """
    messages: List[Tuple[str, str]] = []
    ignored = 0

    if str(payload.get("object") or "") != "page":
        return messages, ignored

    entries = payload.get("entry")
    if not isinstance(entries, list):
        return messages, ignored

    for entry in entries:
        if not isinstance(entry, dict):
            ignored += 1
            continue

        events = entry.get("messaging")
        if not isinstance(events, list):
            continue

        for event in events:
            if not isinstance(event, dict):
                ignored += 1
                continue

            sender = event.get("sender") or {}
            if not isinstance(sender, dict):
                ignored += 1
                continue

            sender_psid = str(sender.get("id") or "").strip()
            if not sender_psid:
                ignored += 1
                continue

            message_obj = event.get("message")
            if not isinstance(message_obj, dict):
                # Unsupported event type (postback, delivery, read, etc.)
                ignored += 1
                continue

            if message_obj.get("is_echo"):
                # Skip page echoes to avoid loops.
                ignored += 1
                continue

            text = str(message_obj.get("text") or "").strip()
            if not text:
                ignored += 1
                continue

            messages.append((sender_psid, text))

    return messages, ignored


async def _send_text_reply(page_access_token: str, recipient_psid: str, text: str) -> bool:
    """Send a text message back to the user via Messenger Send API."""
    if not page_access_token:
        logger.error("FB_PAGE_ACCESS_TOKEN is missing; cannot send Messenger reply")
        return False

    clean_text = str(text or "").strip()
    if not clean_text:
        logger.warning("Skipping empty Messenger reply for psid=%s", recipient_psid)
        return False

    payload = {
        "messaging_type": "RESPONSE",
        "recipient": {"id": recipient_psid},
        "message": {"text": clean_text[:2000]},
    }
    params = {"access_token": page_access_token}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(MESSENGER_SEND_API_URL, params=params, json=payload)
        if resp.status_code >= 400:
            logger.error(
                "Messenger Send API failed: status=%s psid=%s body=%s",
                resp.status_code,
                recipient_psid,
                resp.text[:600],
            )
            return False
        return True
    except Exception:
        logger.exception("Messenger Send API request error for psid=%s", recipient_psid)
        return False


def create_messenger_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["messenger"])

    @router.get("/webhook", response_class=PlainTextResponse)
    async def verify_webhook(
        hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
        hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
        hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
    ) -> PlainTextResponse:
        """Meta webhook verification endpoint."""
        if not settings.fb_verify_token:
            raise HTTPException(status_code=503, detail="FB_VERIFY_TOKEN is not configured")

        if hub_mode != "subscribe" or not hub_verify_token:
            raise HTTPException(status_code=400, detail="Invalid webhook verification request")

        if not hmac.compare_digest(hub_verify_token, settings.fb_verify_token):
            raise HTTPException(status_code=403, detail="Invalid verify token")

        return PlainTextResponse(content=hub_challenge or "", status_code=200)

    @router.post("/webhook")
    async def receive_webhook(request: Request) -> Dict[str, Any]:
        """Receive Messenger events and route text messages to orchestrator.

        Always returns 200 for validly received webhook events so Meta does not retry.
        """
        raw_body = await request.body()
        signature_header = request.headers.get("X-Hub-Signature-256")
        if settings.fb_app_secret and not _verify_signature(raw_body, signature_header, settings.fb_app_secret):
            raise HTTPException(status_code=403, detail="Invalid X-Hub-Signature-256")

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            logger.warning("Invalid Messenger webhook JSON payload")
            return {"status": "ok", "processed_messages": 0, "ignored_events": 1}

        messages, ignored_events = _extract_text_messages(payload)
        if not messages:
            return {"status": "ok", "processed_messages": 0, "ignored_events": ignored_events}

        processed_messages = 0
        orchestrator = request.app.state.orchestrator

        for sender_psid, text in messages:
            try:
                reply = orchestrator.process_message(
                    sender_psid,
                    text,
                    channel="messenger",
                )
            except Exception:
                logger.exception("orchestrator.process_message failed for psid=%s", sender_psid)
                ignored_events += 1
                continue

            delivered = await _send_text_reply(
                page_access_token=settings.fb_page_access_token,
                recipient_psid=sender_psid,
                text=reply,
            )
            if delivered:
                processed_messages += 1
            else:
                ignored_events += 1

        return {
            "status": "ok",
            "processed_messages": processed_messages,
            "ignored_events": ignored_events,
        }

    return router

