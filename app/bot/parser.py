from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

from app.bot.normalizer import normalize_query


_BN_DIGIT_TABLE = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

_WORD_TO_NUMBER = {
    # English
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    # Banglish
    "ek": 1,
    "ekti": 1,
    "ekta": 1,
    "akta": 1,
    "aek": 1,
    "dui": 2,
    "doi": 2,
    "duita": 2,
    "doita": 2,
    "tin": 3,
    "teen": 3,
    "teenta": 3,
    "char": 4,
    "charta": 4,
    "pach": 5,
    "paanch": 5,
    "choy": 6,
    "sat": 7,
    "aat": 8,
    "noy": 9,
    "dosh": 10,
    # Bangla script
    "এক": 1,
    "একটা": 1,
    "একটি": 1,
    "দুই": 2,
    "দুইটা": 2,
    "দুইটি": 2,
    "তিন": 3,
    "তিনটা": 3,
    "তিনটি": 3,
    "চার": 4,
    "চারটা": 4,
    "চারটি": 4,
    "পাঁচ": 5,
    "ছয়": 6,
    "ছয়": 6,
    "সাত": 7,
    "আট": 8,
    "নয়": 9,
    "নয়": 9,
    "দশ": 10,
}

_QTY_HINT_WORDS = {
    "nibo",
    "nib",
    "nite",
    "lagbe",
    "kinbo",
    "debo",
    "dibo",
    "dite",
    "dao",
    "din",
    "den",
    "add",
    "order",
    "pcs",
    "pc",
    "piece",
    "pack",
    "packet",
    "ta",
    "ti",
    "টা",
    "টি",
}

_INTENT_KEYWORDS = {
    "greeting": [
        "hello",
        "hi",
        "hey",
        "salam",
        "assalamualaikum",
        "হ্যালো",
        "হাই",
        "আসসালামু আলাইকুম",
    ],
    "price_query": [
        "price",
        "dam",
        "daam",
        "koto",
        "how much",
        "দাম",
        "কত",
    ],
    "order_intent": [
        "nibo",
        "lagbe",
        "add",
        "dao",
        "din",
        "debo",
        "order",
        "buy",
        "want",
        "চাই",
        "নিব",
        "নিবো",
        "লাগবে",
        "দাও",
        "দিন",
    ],
    "checkout": [
        "checkout",
        "confirm",
        "order confirm",
        "finalize",
        "পাঠাও",
        "কনফার্ম",
        "অর্ডার",
    ],
    "show_cart": [
        "show cart",
        "my cart",
        "cart dekhao",
        "amar cart",
        "কার্ট",
    ],
    "remove_cart": [
        "remove",
        "delete",
        "drop",
        "clear cart",
        "বাদ দাও",
    ],
    "category_query": [
        "category",
        "ki ache",
        "ki ki ache",
        "available",
        "show",
        "list",
        "কী আছে",
        "কি আছে",
        "ক্যাটাগরি",
    ],
}

_BANGLISH_HINTS = {
    "peyaj",
    "piyaj",
    "aloo",
    "alu",
    "dim",
    "dimer",
    "maach",
    "mach",
    "murgi",
    "chal",
    "dal",
    "chini",
    "dudh",
    "rosun",
    "ada",
    "shobji",
    "fol",
    "moshla",
    "dam",
    "koto",
    "nibo",
    "lagbe",
    "dao",
    "pathao",
    "kinbo",
}


@dataclass
class ParsedUserMessage:
    text: str
    normalized_text: str
    language_mix: str
    intent: str
    intent_confidence: float
    product_query: str
    product_confidence: float
    quantity: Optional[int]
    quantity_confidence: float
    unit_hint: str


def _normalize_digits(text: str) -> str:
    return text.translate(_BN_DIGIT_TABLE)


def _safe_lower(text: str) -> str:
    return _normalize_digits(text or "").strip().lower()


def normalize_spelled_numbers(text: str) -> str:
    out = _safe_lower(text)
    for token, value in sorted(_WORD_TO_NUMBER.items(), key=lambda kv: len(kv[0]), reverse=True):
        pattern = rf"(?<![\w\u0980-\u09FF]){re.escape(token)}(?![\w\u0980-\u09FF])"
        out = re.sub(pattern, str(value), out)
    return out


def detect_language_mix(text: str) -> str:
    raw = text or ""
    bn_count = len(re.findall(r"[\u0980-\u09FF]", raw))
    en_count = len(re.findall(r"[A-Za-z]", raw))
    lowered = raw.lower()
    has_banglish_hint = any(
        re.search(rf"(?<![\w\u0980-\u09FF]){re.escape(tok)}(?![\w\u0980-\u09FF])", lowered)
        for tok in _BANGLISH_HINTS
    )
    if bn_count > 0 and en_count > 0:
        return "mixed"
    if en_count > 0 and has_banglish_hint:
        return "mixed"
    if bn_count > 0:
        return "bangla"
    if en_count > 0:
        return "english"
    return "unknown"


def _detect_intent(text: str) -> Tuple[str, float]:
    t = _safe_lower(text)
    best_intent = "unknown"
    best_score = 0.35

    for intent, words in _INTENT_KEYWORDS.items():
        hits = sum(1 for w in words if w in t)
        if hits <= 0:
            continue
        score = min(0.96, 0.52 + (0.16 * hits))
        if score > best_score:
            best_score = score
            best_intent = intent

    return best_intent, round(best_score, 2)


def extract_quantity(text: str, allow_bare: bool = False) -> Tuple[Optional[int], float, str]:
    t = normalize_spelled_numbers(text)
    unit_hint = ""

    unit_match = re.search(
        r"\b(kg|kilo|g|gm|gram|ml|l|liter|litre|pcs?|pc|piece|packet|pack|ta|ti|টা|টি)\b",
        t,
    )
    if unit_match:
        unit_hint = unit_match.group(1)

    # x2, 2x, x 2
    x_match = re.search(r"(?:\bx\s*(?<!\d)(\d{1,3})(?!\d)\b)|(?:(?<!\d)(\d{1,3})(?!\d)\s*x\b)", t)
    if x_match:
        qty = int(x_match.group(1) or x_match.group(2) or 0)
        if qty > 0:
            return qty, 0.92, unit_hint

    num_match = re.search(r"(?<!\d)(\d{1,3})(?!\d)", t)
    if not num_match:
        return None, 0.0, unit_hint

    qty = int(num_match.group(1))
    has_qty_hint = any(k in t for k in _QTY_HINT_WORDS)
    has_suffix = bool(
        re.search(
            r"(?<!\d)\d{1,3}(?!\d)\s*(ta|ti|টা|টি|pcs?|pc|piece|packet|pack|kg|kilo|g|gm|gram|l|ml|liter|litre)(?![\w\u0980-\u09FF])",
            t,
        )
    )

    if has_suffix:
        return qty, 0.95, unit_hint
    if has_qty_hint:
        return qty, 0.82, unit_hint
    if allow_bare and re.fullmatch(r"[\s\.,!?\-]*(?<!\d)\d{1,3}(?!\d)[\s\.,!?\-]*", t):
        return qty, 0.8, unit_hint
    return None, 0.0, unit_hint


def _extract_product_query(text: str) -> Tuple[str, float]:
    normalized = normalize_query(text or "")
    q = normalized.lower()
    q = re.sub(
        r"\b(price|how much|order|need|want|buy|pcs|x|nibo|nib|nite|nitesi|niteci|nichi|nimu|lagbe|kinbo|debo|dibo|dite|pathao|add|cart|koto|dam|daam|ki|ache|show|list)\b",
        " ",
        q,
    )
    q = re.sub(r"\s+", " ", q).strip(" ?!.,")
    if not q:
        return "", 0.0
    meaningful = len(re.findall(r"[a-z\u0980-\u09FF]", q))
    confidence = 0.5 if meaningful >= 2 else 0.3
    if meaningful >= 5:
        confidence = 0.72
    if meaningful >= 9:
        confidence = 0.84
    return q, round(confidence, 2)


def parse_user_message(text: str, allow_bare_qty: bool = False) -> ParsedUserMessage:
    intent, intent_conf = _detect_intent(text)
    qty, qty_conf, unit_hint = extract_quantity(text, allow_bare=allow_bare_qty)
    product_query, product_conf = _extract_product_query(text)
    normalized = normalize_query(text or "")
    return ParsedUserMessage(
        text=text,
        normalized_text=normalized,
        language_mix=detect_language_mix(text),
        intent=intent,
        intent_confidence=intent_conf,
        product_query=product_query,
        product_confidence=product_conf,
        quantity=qty,
        quantity_confidence=qty_conf,
        unit_hint=unit_hint,
    )
