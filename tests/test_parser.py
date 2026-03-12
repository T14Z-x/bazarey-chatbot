from __future__ import annotations

from app.bot.parser import extract_quantity, parse_user_message
from app.bot.orchestrator import ChatOrchestrator


def test_extract_quantity_bangla_digits_and_suffix() -> None:
    qty, conf, unit = extract_quantity("৫টা ডিম লাগবে", allow_bare=False)
    assert qty == 5
    assert conf >= 0.9
    assert unit in {"ta", "ti", "টা", "টি", ""}


def test_extract_quantity_banglish_word_number() -> None:
    qty, conf, _ = extract_quantity("duita dim dao", allow_bare=False)
    assert qty == 2
    assert conf >= 0.8


def test_extract_quantity_bare_reply() -> None:
    qty, conf, _ = extract_quantity(" 3 ", allow_bare=True)
    assert qty == 3
    assert conf >= 0.75


def test_parse_user_message_mixed_language() -> None:
    parsed = parse_user_message("Bhai peyaj er price koto?")
    assert parsed.language_mix == "mixed"
    assert parsed.intent in {"price_query", "order_intent"}
    assert parsed.intent_confidence >= 0.5
    assert "onion" in parsed.normalized_text


def test_ambiguity_detection() -> None:
    matches = [
        {"name": "Rui Fish 1kg", "_score": 61.0},
        {"name": "Rui Fish 800g", "_score": 58.5},
        {"name": "Katla Fish 1kg", "_score": 47.0},
    ]
    assert ChatOrchestrator._is_ambiguous_match(matches)
