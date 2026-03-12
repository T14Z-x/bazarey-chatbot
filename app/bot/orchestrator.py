from __future__ import annotations

import json
import logging
import math
import re
import time
from typing import Any, Dict, List, Optional

from app.bot.normalizer import normalize_query
from app.bot.parser import extract_quantity, normalize_spelled_numbers, parse_user_message
from app.llm.prompts import SYSTEM_PROMPT
from app.tools.order_sheet import OrderSheet
from app.tools.product_catalog import ProductCatalog
from app.tools.recommendation_engine import RecommendationEngine
from app.tools.session_store import SessionStore

logger = logging.getLogger(__name__)


class ChatOrchestrator:
    _BN_DIGIT_TABLE = str.maketrans("\u09e6\u09e7\u09e8\u09e9\u09ea\u09eb\u09ec\u09ed\u09ee\u09ef", "0123456789")

    def __init__(
        self,
        product_catalog: ProductCatalog,
        order_sheet: OrderSheet,
        session_store: SessionStore,
        llm_client: Any,
        invoice_store: Any = None,
    ) -> None:
        self.catalog = product_catalog
        self.orders = order_sheet
        self.sessions = session_store
        self.llm = llm_client
        self.invoice_store = invoice_store
        self.recommendations = RecommendationEngine(invoice_store, product_catalog) if invoice_store else None

    # ── Static helpers ──────────────────────────────────────────────────

    @staticmethod
    def _is_yes(text: str) -> bool:
        t = text.strip().lower()
        yes_words = {"yes", "y", "ok", "confirm", "confirmed", "haa", "ha", "hae", "ji",
                     "hmm", "jee", "hyan", "ofc", "okay", "sure",
                     "\u099c\u09bf", "\u09b9\u09cd\u09af\u09be\u0981", "\u09b9\u09be"}
        if t in yes_words:
            return True
        first = re.split(r"\s+", t)[0] if t else ""
        return first in yes_words

    @staticmethod
    def _normalize_digits(text: str) -> str:
        return text.translate(ChatOrchestrator._BN_DIGIT_TABLE)

    @staticmethod
    def _is_take_intent(text: str) -> bool:
        t = text.strip().lower()
        keywords = [
            "nibo", "nib", "nite", "nitesi", "niteci", "nichi", "nimu",
            "lagbe", "kinbo", "debo", "dibo", "dite", "dao", "din", "den",
            "add", "pathao",
            "\u09a8\u09bf\u09ac", "\u09a8\u09bf\u09ac\u09cb", "\u09a8\u09c7\u09ac", "\u09a8\u09c7\u09ac\u09cb",
            "\u09a8\u09bf\u09a4\u09c7", "\u09a8\u09bf\u09a4\u09c7 \u099a\u09be\u0987", "\u09b2\u09be\u0997\u09ac\u09c7",
            "\u0995\u09bf\u09a8\u09ac", "\u0995\u09bf\u09a8\u09ac\u09cb",
            "\u09a6\u09be\u0993", "\u09a6\u09bf\u09a8", "\u09a6\u09c7\u09a8",
            "\u09aa\u09be\u09a0\u09be\u0993",
        ]
        return any(k in t for k in keywords)

    @staticmethod
    def _is_intent_only_add_request(text: str) -> bool:
        t = ChatOrchestrator._normalize_digits(text.lower())
        t = re.sub(r"[^\w\s\u0980-\u09FF]", " ", t)
        tokens = [tok for tok in t.split() if tok]
        if not tokens:
            return False

        # "chai" alone can mean tea, so avoid treating it as confirmation.
        if len(tokens) == 1 and tokens[0] in {"chai", "cha", "\u099a\u09be\u0987"}:
            return False

        action_tokens = {
            "nibo", "nib", "nite", "nitesi", "niteci", "nichi", "nimu",
            "lagbe", "kinbo", "debo", "dibo", "dite", "dao", "din", "den",
            "add", "pathao", "order",
            "\u09a8\u09bf\u09ac", "\u09a8\u09bf\u09ac\u09cb", "\u09a8\u09c7\u09ac", "\u09a8\u09c7\u09ac\u09cb",
            "\u09a8\u09bf\u09a4\u09c7", "\u09b2\u09be\u0997\u09ac\u09c7",
            "\u0995\u09bf\u09a8\u09ac", "\u0995\u09bf\u09a8\u09ac\u09cb",
            "\u09a6\u09be\u0993", "\u09a6\u09bf\u09a8", "\u09a6\u09c7\u09a8",
            "\u09aa\u09be\u09a0\u09be\u0993", "\u0985\u09b0\u09cd\u09a1\u09be\u09b0",
        }
        filler_tokens = {
            "chai", "please", "pls", "plz", "cart", "e", "te", "to", "bhai", "vai",
            "\u099a\u09be\u0987", "\u0995\u09be\u09b0\u09cd\u099f", "\u09ad\u09be\u0987",
        }

        if any(tok.isdigit() for tok in tokens):
            return False
        if not any(tok in action_tokens for tok in tokens):
            return False
        return all(tok in action_tokens or tok in filler_tokens for tok in tokens)

    @staticmethod
    def _is_no(text: str) -> bool:
        t = text.strip().lower()
        return t in {"no", "n", "na", "nah", "cancel", "noi", "bad",
                      "\u09a8\u09be", "\u09a8\u09be\u09b9", "\u09ac\u09be\u09a6 \u09a6\u09be\u0993"}

    @staticmethod
    def _is_greeting(text: str) -> bool:
        t = text.strip().lower().rstrip("!?.")
        return t in {
            "hi", "hello", "hey", "assalamualaikum", "salam",
            "salaam", "good morning", "good evening", "sup",
            "\u09b9\u09cd\u09af\u09be\u09b2\u09cb", "\u09b9\u09be\u0987",
            "\u0986\u09b8\u09b8\u09be\u09b2\u09be\u09ae\u09c1 \u0986\u09b2\u09be\u0987\u0995\u09c1\u09ae",
            "oi", "bhai", "\u09ad\u09be\u0987", "vai",
        }

    @staticmethod
    def _is_checkout_intent(text: str) -> bool:
        t = text.strip().lower()
        keywords = [
            "order", "checkout", "confirm", "done", "finalize",
            "pathao", "order dibo", "order korbo", "confirm koro",
            "order confirm", "hoishe", "order dao", "bas eto i",
            "\u0985\u09b0\u09cd\u09a1\u09be\u09b0", "\u099a\u09c7\u0995\u0986\u0989\u099f",
            "\u0995\u09a8\u09ab\u09be\u09b0\u09cd\u09ae", "\u09aa\u09be\u09a0\u09be\u0993",
            "\u09b9\u09df\u09c7\u099b\u09c7",
        ]
        return any(k in t for k in keywords)

    @staticmethod
    def _extract_phone(text: str) -> Optional[str]:
        match = re.search(r"\b01\d{9}\b", text)
        return match.group(0) if match else None

    @staticmethod
    def _has_invalid_phone_candidate(text: str) -> bool:
        digits = re.sub(r"\D", "", text)
        if not digits:
            return False
        if len(digits) == 11 and digits.startswith("01"):
            return False
        return len(digits) >= 10

    @staticmethod
    def _extract_name(text: str) -> str:
        """Return cleaned name. Accept Bangla, English, or mixed."""
        t = text.strip()
        # Remove common prefixes
        t = re.sub(r"^(my name is|ami|nama|naam|name)\s*:?\s*", "", t, flags=re.IGNORECASE)
        # Limit to reasonable length
        if len(t) > 80:
            t = t[:80]
        return t.strip()

    @staticmethod
    def _format_price(price: Any, unit: str) -> str:
        if price is None:
            return "\u09a6\u09be\u09ae \u099c\u09be\u09a8\u09be \u09a8\u09c7\u0987"
        price_val = float(price)
        if abs(price_val - round(price_val)) < 1e-9:
            price_text = str(int(round(price_val)))
        else:
            price_text = f"{price_val:.2f}".rstrip("0").rstrip(".")
        if unit:
            return f"{price_text} \u099f\u09be\u0995\u09be \u09aa\u09cd\u09b0\u09a4\u09bf {unit}"
        return f"{price_text} \u099f\u09be\u0995\u09be"

    @staticmethod
    def _extract_qty_only(text: str, allow_bare: bool = False) -> Optional[int]:
        qty, confidence, _ = extract_quantity(text, allow_bare=allow_bare)
        if qty is None or confidence <= 0:
            return None
        return qty

    @staticmethod
    def _unit_to_base(unit: str) -> Optional[tuple[str, float]]:
        u = (unit or "").strip().lower()
        if u in {"g", "gm", "gram", "grams"}:
            return "g", 1.0
        if u in {"kg", "kilo", "kilogram", "kilograms"}:
            return "g", 1000.0
        if u in {"ml"}:
            return "ml", 1.0
        if u in {"l", "lit", "liter", "litre"}:
            return "ml", 1000.0
        return None

    @classmethod
    def _extract_amount_with_unit(cls, text: str) -> Optional[tuple[float, str, str]]:
        t = cls._normalize_digits(str(text or "").lower())
        match = re.search(
            r"(?<!\d)(\d+(?:\.\d+)?)\s*(kg|kilo|kilogram|g|gm|gram|ml|l|lit|liter|litre)\b",
            t,
        )
        if not match:
            return None
        qty_raw = float(match.group(1))
        unit_raw = match.group(2)
        mapped = cls._unit_to_base(unit_raw)
        if not mapped:
            return None
        base_unit, factor = mapped
        amount_base = qty_raw * factor
        display = f"{match.group(1)} {unit_raw}".strip()
        return amount_base, base_unit, display

    @classmethod
    def _extract_pack_size_base(cls, unit_text: str) -> Optional[tuple[float, str]]:
        t = cls._normalize_digits(str(unit_text or "").lower())
        match = re.search(
            r"(?<!\d)(\d+(?:\.\d+)?)\s*(kg|kilo|kilogram|g|gm|gram|ml|l|lit|liter|litre)\b",
            t,
        )
        if not match:
            return None
        qty_raw = float(match.group(1))
        mapped = cls._unit_to_base(match.group(2))
        if not mapped:
            return None
        base_unit, factor = mapped
        pack_amount = qty_raw * factor
        if pack_amount <= 0:
            return None
        return pack_amount, base_unit

    def _resolve_qty_for_product(self, qty: int, qty_text: str, product: Dict[str, Any]) -> tuple[int, str]:
        final_qty = max(1, int(qty))
        requested = self._extract_amount_with_unit(qty_text)
        if not requested:
            return final_qty, ""

        pack = self._extract_pack_size_base(str(product.get("unit") or ""))
        if not pack:
            return final_qty, ""

        req_amount, req_base, req_label = requested
        pack_amount, pack_base = pack
        if req_base != pack_base:
            return final_qty, ""

        computed_qty = max(1, int(math.ceil((req_amount / pack_amount) - 1e-9)))
        if computed_qty == final_qty:
            return computed_qty, ""

        unit_label = str(product.get("unit") or "").strip()
        note = f"{req_label} হিসেবে {computed_qty} প্যাক ধরা হয়েছে"
        if unit_label:
            note = f"{note} (প্রতি {unit_label})"
        return computed_qty, note

    @staticmethod
    def _is_ambiguous_match(matches: List[Dict[str, Any]]) -> bool:
        """If top matches are close, ask the user to disambiguate."""
        if len(matches) < 2:
            return False
        try:
            top = float(matches[0].get("_score") or 0)
            second = float(matches[1].get("_score") or 0)
        except Exception:
            return False
        return top >= 55 and second >= 50 and (top - second) < 8

    def _build_disambiguation_reply(self, matches: List[Dict[str, Any]], prompt: str) -> str:
        choices = matches[:3]
        lines = [prompt]
        for idx, item in enumerate(choices, start=1):
            price_str = self._format_price(item.get("price"), item.get("unit", ""))
            lines.append(f"{idx}) {item.get('name', '')} — {price_str}")
        lines.append("\u09a8\u09be\u09ae \u09ac\u09be 1/2/3 \u09b2\u09bf\u0996\u09c7 \u09b8\u09bf\u09b2\u09c7\u0995\u09cd\u099f \u0995\u09b0\u09c1\u09a8\u0964")
        return "\n".join(lines)

    @staticmethod
    def _extract_choice_index(text: str, max_options: int) -> Optional[int]:
        t = ChatOrchestrator._normalize_digits(text.strip().lower())
        words = {
            "first": 1, "1st": 1, "prothom": 1, "\u09aa\u09cd\u09b0\u09a5\u09ae": 1,
            "second": 2, "2nd": 2, "ditio": 2, "\u09a6\u09cd\u09ac\u09bf\u09a4\u09c0\u09df": 2, "\u09a6\u09cd\u09ac\u09bf\u09a4\u09c0\u09af\u09bc": 2,
            "third": 3, "3rd": 3, "tritio": 3, "\u09a4\u09c3\u09a4\u09c0\u09df": 3, "\u09a4\u09c3\u09a4\u09c0\u09af\u09bc": 3,
        }
        for token, value in words.items():
            if token in t and 1 <= value <= max_options:
                return value

        match = re.search(r"(?<!\d)([1-9])(?!\d)", t)
        if not match:
            return None
        idx = int(match.group(1))
        if 1 <= idx <= max_options:
            return idx
        return None

    def _handle_pending_choice(self, text: str, state: Dict[str, Any]) -> Optional[str]:
        if not state.get("awaiting_choice"):
            return None

        candidates = state.get("pending_choice_candidates") or []
        if not candidates:
            state["awaiting_choice"] = False
            state["pending_choice_candidates"] = []
            state["choice_context"] = ""
            state["choice_qty"] = 1
            state["choice_qty_text"] = ""
            return None

        if self._is_no(text):
            state["awaiting_choice"] = False
            state["pending_choice_candidates"] = []
            state["choice_context"] = ""
            state["choice_qty"] = 1
            state["choice_qty_text"] = ""
            return "\u09a0\u09bf\u0995 \u0986\u099b\u09c7, \u098f\u0987\u099f\u09be \u09ac\u09be\u09a6 \u09a6\u09bf\u09b2\u09be\u09ae\u0964 \u099a\u09be\u0987\u09b2\u09c7 \u0985\u09a8\u09cd\u09af \u09aa\u09a3\u09cd\u09af\u09c7\u09b0 \u09a8\u09be\u09ae \u09ac\u09b2\u09c1\u09a8\u0964"

        choice_idx = self._extract_choice_index(text, len(candidates))
        if choice_idx is None:
            query = self._clean_query(text)
            if query:
                best_idx = -1
                best_score = 0.0
                for idx, item in enumerate(candidates):
                    score = self.catalog._score(query, str(item.get("name") or ""))
                    if score > best_score:
                        best_score = score
                        best_idx = idx
                # Only auto-pick from free-text when the lexical signal is very strong.
                if best_idx >= 0 and best_score >= 78:
                    choice_idx = best_idx + 1

        if choice_idx is None:
            return self._build_disambiguation_reply(candidates, "\u098f\u0995\u099f\u09be \u0985\u09aa\u09b6\u09a8 \u09b8\u09bf\u09b2\u09c7\u0995\u09cd\u099f \u0995\u09b0\u09c1\u09a8:")

        chosen = candidates[choice_idx - 1]
        state["awaiting_choice"] = False
        state["pending_choice_candidates"] = []
        state["last_product_candidates"] = [chosen]
        context = str(state.get("choice_context") or "")
        qty = int(state.get("choice_qty") or 1)
        qty_text = str(state.get("choice_qty_text") or str(qty))
        state["choice_context"] = ""
        state["choice_qty"] = 1
        state["choice_qty_text"] = ""

        price_str = self._format_price(chosen.get("price"), chosen.get("unit", ""))
        if context == "price":
            state["awaiting_qty"] = True
            return f"{chosen.get('name', '')}: {price_str}\n\u0995\u09a4\u099f\u09c1\u0995\u09c1 \u09a6\u09bf\u09ac\u09cb?"

        if context == "order":
            state["awaiting_qty"] = False
            qty_final, qty_note = self._resolve_qty_for_product(max(1, qty), qty_text, chosen)
            self._add_or_update_pending_item(state, str(chosen.get("product_id") or ""), qty_final)
            pending = state.get("pending_items", [])
            note_line = f"\n{qty_note}" if qty_note else ""
            return (
                f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09af\u09cb\u0997 \u09b9\u09df\u09c7\u099b\u09c7: {chosen.get('name', '')} x{qty_final} ({price_str}){note_line}\n"
                f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09ae\u09cb\u099f {len(pending)}\u099f\u09bf \u09aa\u09a3\u09cd\u09af\u0964\n"
                "\u0986\u09b0 \u0995\u09bf\u099b\u09c1 \u09b2\u09be\u0997\u09ac\u09c7? \u09a8\u09be\u0995\u09bf 'order' \u09b2\u09bf\u0996\u09c1\u09a8 \u2705"
            )

        return f"{chosen.get('name', '')}: {price_str}\n\u09a8\u09bf\u09a4\u09c7 \u099a\u09be\u0987\u09b2\u09c7 \u09ac\u09b2\u09c1\u09a8!"

    def _handle_affirmative_followup(self, text: str, state: Dict[str, Any]) -> Optional[str]:
        """Handle messages like 'yes 5 ti' after a product suggestion."""
        candidates = state.get("last_product_candidates") or []
        if not candidates:
            return None

        awaiting_qty = bool(state.get("awaiting_qty"))
        parsed_msg = parse_user_message(text, allow_bare_qty=awaiting_qty)
        qty = parsed_msg.quantity if parsed_msg.quantity_confidence >= 0.75 else self._extract_qty_only(text, allow_bare=awaiting_qty)
        is_affirmative = self._is_yes(text) or self._is_take_intent(text)
        has_measured_amount = self._extract_amount_with_unit(text) is not None
        qty_followup = (awaiting_qty and qty is not None) or (has_measured_amount and qty is not None)
        if not is_affirmative and not qty_followup:
            return None

        if qty is None:
            # Track that we are waiting for the user to reply with a quantity
            state["awaiting_qty"] = True
            return "\u0995\u09a4\u099f\u09bf \u09a6\u09bf\u09ac\u09cb \u09ad\u09be\u0987?"

        best = candidates[0]
        qty_final, qty_note = self._resolve_qty_for_product(qty, text, best)
        state["awaiting_qty"] = False
        self._add_or_update_pending_item(state, str(best.get("product_id") or ""), qty_final)
        pending = state.get("pending_items", [])
        price_str = self._format_price(best.get("price"), best.get("unit", ""))
        note_line = f"\n{qty_note}" if qty_note else ""
        return (
            f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09af\u09cb\u0997 \u09b9\u09df\u09c7\u099b\u09c7: {best.get('name', '')} x{qty_final} ({price_str}){note_line}\n"
            f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09ae\u09cb\u099f {len(pending)}\u099f\u09bf \u09aa\u09a3\u09cd\u09af\u0964\n"
            "\u0986\u09b0 \u0995\u09bf\u099b\u09c1 \u09b2\u09be\u0997\u09ac\u09c7? \u09a8\u09be\u0995\u09bf 'order' \u09b2\u09bf\u0996\u09c1\u09a8 \u2705"
        )

    @staticmethod
    def _is_price_query(text: str) -> bool:
        t = text.lower()
        keywords = [
            "price", "dam", "daam", "koto", "how much", "kemon",
            "\u09a6\u09be\u09ae", "\u0995\u09a4", "\u09a6\u09be\u09ae \u0995\u09a4",
            "\u0995\u09a4 \u099f\u09be\u0995\u09be",
        ]
        return any(k in t for k in keywords)

    @staticmethod
    def _is_order_intent(text: str) -> bool:
        t = text.lower()
        keywords = [
            "order", "nibo", "nib", "nite", "nitesi", "niteci", "nichi",
            "need", "lagbe", "want", "buy", "kinbo", "debo", "dibo", "dite",
            "dao", "din", "den",
            "\u09a8\u09bf\u09ac", "\u099a\u09be\u0987", "\u09b2\u09be\u0997\u09ac\u09c7",
            "\u0995\u09bf\u09a8\u09ac", "\u09a6\u09be\u0993", "\u09a6\u09bf\u09a8", "\u09a6\u09c7\u09a8",
            "\u09aa\u09be\u09a0\u09be\u0993", "\u09a8\u09bf\u09a4\u09c7 \u099a\u09be\u0987",
            "add", "pathao",
        ]
        return any(k in t for k in keywords)

    @staticmethod
    def _is_show_cart_request(text: str) -> bool:
        t = text.lower().strip()
        phrases = {
            "show my cart", "show cart", "my cart", "cart dekhaw", "cart dekhao",
            "amar cart", "cart ta dekhaw", "cart ta dekhao", "\u0995\u09be\u09b0\u09cd\u099f \u09a6\u09c7\u0996\u09be\u0993",
            "\u0986\u09ae\u09be\u09b0 \u0995\u09be\u09b0\u09cd\u099f", "\u0995\u09be\u09b0\u09cd\u099f",
        }
        if t in phrases:
            return True
        return bool(re.search(r"\b(show|view|see)\b.{0,12}\bcart\b", t))

    @staticmethod
    def _is_remove_from_cart_request(text: str) -> bool:
        t = text.lower().strip()
        remove_words = [
            "remove", "delete", "drop", "clear cart", "cart theke remove", "cart থেকে remove",
            "\u09ac\u09be\u09a6 \u09a6\u09be\u0993", "\u09b0\u09bf\u09ae\u09c1\u09ad", "\u09ae\u09c1\u099b\u09c7 \u09a6\u09be\u0993",
            "\u0995\u09be\u09b0\u09cd\u099f \u09a5\u09c7\u0995\u09c7 \u09ac\u09be\u09a6", "remove koro",
        ]
        return any(w in t for w in remove_words)

    def _remove_from_cart(self, text: str, state: Dict[str, Any]) -> str:
        pending = state.get("pending_items", [])
        if not pending:
            return "\u0986\u09aa\u09a8\u09be\u09b0 \u0995\u09be\u09b0\u09cd\u099f \u098f\u0996\u09a8 \u0996\u09be\u09b2\u09bf\u0964"

        t = text.lower()
        if any(k in t for k in ["all", "sob", "\u09b8\u09ac", "clear"]):
            state["pending_items"] = []
            return "\u09a0\u09bf\u0995 \u0986\u099b\u09c7, \u0995\u09be\u09b0\u09cd\u099f\u09c7\u09b0 \u09b8\u09ac \u0986\u0987\u099f\u09c7\u09ae \u09ac\u09be\u09a6 \u09a6\u09c7\u09df\u09be \u09b9\u09df\u09c7\u099b\u09c7\u0964"

        cleaned = normalize_query(text).lower()
        cleaned = re.sub(
            r"\b(remove|delete|drop|cart|theke|from|my|amar|koro|koren|koren|bad|dao|\u09ac\u09be\u09a6|\u09a6\u09be\u0993|\u0995\u09be\u09b0\u09cd\u099f|\u09a5\u09c7\u0995\u09c7)\b",
            " ",
            cleaned,
        )
        query = re.sub(r"\s+", " ", cleaned).strip()

        if query:
            best_idx = -1
            best_score = 0.0
            for idx, item in enumerate(pending):
                product = self.catalog.get_product(str(item.get("product_id") or ""))
                if not product:
                    continue
                score = self.catalog._score(query, str(product.get("name") or ""))
                if score > best_score:
                    best_score = score
                    best_idx = idx
            if best_idx >= 0 and best_score >= 45:
                removed = pending.pop(best_idx)
                state["pending_items"] = pending
                product = self.catalog.get_product(str(removed.get("product_id") or ""))
                name = str(product.get("name") or "\u0986\u0987\u099f\u09c7\u09ae") if product else "\u0986\u0987\u099f\u09c7\u09ae"
                return f"\u0995\u09be\u09b0\u09cd\u099f \u09a5\u09c7\u0995\u09c7 \u09ac\u09be\u09a6 \u09a6\u09c7\u09df\u09be \u09b9\u09df\u09c7\u099b\u09c7: {name}\n{self._format_cart_summary(state)}"

        removed = pending.pop()
        state["pending_items"] = pending
        product = self.catalog.get_product(str(removed.get("product_id") or ""))
        name = str(product.get("name") or "\u09b6\u09c7\u09b7 \u0986\u0987\u099f\u09c7\u09ae") if product else "\u09b6\u09c7\u09b7 \u0986\u0987\u099f\u09c7\u09ae"
        return f"\u0995\u09be\u09b0\u09cd\u099f \u09a5\u09c7\u0995\u09c7 \u09ac\u09be\u09a6 \u09a6\u09c7\u09df\u09be \u09b9\u09df\u09c7\u099b\u09c7: {name}\n{self._format_cart_summary(state)}"

    @staticmethod
    def _is_update_cart_qty_request(text: str) -> bool:
        t = normalize_query(text).lower()
        keywords = [
            "update", "set", "change", "quantity", "qty", "increase", "decrease", "reduce",
            "barao", "barao", "komao", "কমাও", "বাড়াও", "বাড়াও",
            "কার্ট আপডেট", "cart update",
        ]
        has_keyword = any(k in t for k in keywords)
        has_numeric = bool(re.search(r"\d", ChatOrchestrator._normalize_digits(t)))
        return has_keyword and has_numeric

    @staticmethod
    def _is_cart_edit_help_request(text: str) -> bool:
        t = normalize_query(text).lower().strip()
        phrases = {
            "edit cart",
            "cart edit",
            "update cart",
            "change cart",
            "how to edit cart",
            "কার্ট এডিট",
            "কার্ট আপডেট",
            "কার্ট পরিবর্তন",
        }
        return t in phrases

    @staticmethod
    def _detect_qty_update_mode(text: str) -> str:
        t = normalize_query(text).lower()
        if any(k in t for k in ["increase", "inc", "barao", "barao", "বাড়াও", "বাড়াও", "plus", "আরও"]):
            return "increase"
        if any(k in t for k in ["decrease", "dec", "reduce", "komao", "কমাও", "কমান", "minus"]):
            return "decrease"
        return "set"

    @staticmethod
    def _extract_cart_update_query(text: str) -> str:
        t = normalize_query(text).lower()
        t = re.sub(
            r"\b(update|set|change|quantity|qty|increase|decrease|reduce|barao|barao|komao|cart|amar|my|to|the|koro|koren|koren|korun)\b",
            " ",
            t,
        )
        t = re.sub(r"(?<!\d)\d+(?:\.\d+)?\s*(kg|kilo|g|gm|gram|ml|l|lit|liter|litre|pcs?|pc|piece|ta|ti|টা|টি)?", " ", t)
        t = re.sub(r"\s+", " ", t).strip(" .,-")
        return t

    def _cart_edit_help_text(self) -> str:
        return (
            "\u0995\u09be\u09b0\u09cd\u099f \u098f\u09a1\u09bf\u099f \u0995\u09b0\u09a4\u09c7 \u098f\u09ad\u09be\u09ac\u09c7 \u09b2\u09bf\u0996\u09c1\u09a8:\n"
            "1) update <\u09aa\u09a3\u09cd\u09af\u09c7\u09b0 \u09a8\u09be\u09ae> <qty>\n"
            "2) increase <\u09aa\u09a3\u09cd\u09af\u09c7\u09b0 \u09a8\u09be\u09ae> <qty>\n"
            "3) decrease <\u09aa\u09a3\u09cd\u09af\u09c7\u09b0 \u09a8\u09be\u09ae> <qty>\n"
            "4) remove <\u09aa\u09a3\u09cd\u09af\u09c7\u09b0 \u09a8\u09be\u09ae>"
        )

    def _update_cart_qty(self, text: str, state: Dict[str, Any]) -> str:
        pending = state.get("pending_items", [])
        if not pending:
            return "\u0986\u09aa\u09a8\u09be\u09b0 \u0995\u09be\u09b0\u09cd\u099f \u0996\u09be\u09b2\u09bf \u0986\u099b\u09c7\u0964"

        parsed = parse_user_message(text, allow_bare_qty=False)
        qty = parsed.quantity if parsed.quantity_confidence >= 0.7 else self._extract_qty_only(text, allow_bare=False)
        if qty is None:
            num_match = re.search(r"(?<!\d)(\d{1,3})(?!\d)", self._normalize_digits(text.lower()))
            if num_match:
                qty = int(num_match.group(1))
        if qty is None:
            return (
                "\u0995\u09a4 \u0995\u09b0\u09a4\u09c7 \u099a\u09be\u09a8 \u09ac\u09b2\u09c1\u09a8\u0964\n"
                "উদাহরণ: update miniket rice 2"
            )

        query = self._extract_cart_update_query(text)
        target_idx = -1
        if query:
            best_score = 0.0
            for idx, item in enumerate(pending):
                product = self.catalog.get_product(str(item.get("product_id") or ""))
                if not product:
                    continue
                score = self.catalog._score(query, str(product.get("name") or ""))
                if score > best_score:
                    best_score = score
                    target_idx = idx
            if target_idx < 0 or best_score < 45:
                return (
                    "\u0995\u09cb\u09a8 \u09aa\u09a3\u09cd\u09af\u099f\u09be \u0986\u09aa\u09a1\u09c7\u099f \u0995\u09b0\u09ac\u09c7\u09a8 \u09ac\u09b2\u09c1\u09a8\u0964\n"
                    f"{self._format_cart_summary(state)}"
                )
        elif len(pending) == 1:
            target_idx = 0
        else:
            return (
                "\u0995\u09cb\u09a8 \u09aa\u09a3\u09cd\u09af\u099f\u09be \u0986\u09aa\u09a1\u09c7\u099f \u0995\u09b0\u09ac\u09c7\u09a8 \u09ac\u09b2\u09c1\u09a8\u0964\n"
                f"{self._format_cart_summary(state)}"
            )

        target = pending[target_idx]
        product = self.catalog.get_product(str(target.get("product_id") or ""))
        if not product:
            return "\u09a6\u09c1\u0983\u0996\u09bf\u09a4, \u0986\u0987\u099f\u09c7\u09ae\u099f\u09be \u0986\u09b0 \u0995\u09cd\u09af\u09be\u099f\u09be\u09b2\u0997\u09c7 \u09aa\u09be\u0993\u09df\u09be \u09af\u09be\u099a\u09cd\u099b\u09c7 \u09a8\u09be\u0964"

        qty_final, qty_note = self._resolve_qty_for_product(int(qty), text, product)
        mode = self._detect_qty_update_mode(text)
        current_qty = int(target.get("qty") or 0)
        if mode == "increase":
            new_qty = current_qty + qty_final
        elif mode == "decrease":
            new_qty = max(0, current_qty - qty_final)
        else:
            new_qty = qty_final

        name = str(product.get("name") or "\u0986\u0987\u099f\u09c7\u09ae")
        if new_qty <= 0:
            pending.pop(target_idx)
            state["pending_items"] = pending
            if not pending:
                return f"\u0995\u09be\u09b0\u09cd\u099f \u0986\u09aa\u09a1\u09c7\u099f \u09b9\u09df\u09c7\u099b\u09c7: {name} \u09ac\u09be\u09a6 \u09a6\u09c7\u09df\u09be \u09b9\u09df\u09c7\u099b\u09c7\u0964\n\u098f\u0996\u09a8 \u0995\u09be\u09b0\u09cd\u099f \u0996\u09be\u09b2\u09bf\u0964"
            return f"\u0995\u09be\u09b0\u09cd\u099f \u0986\u09aa\u09a1\u09c7\u099f: {name} \u09ac\u09be\u09a6 \u09a6\u09c7\u09df\u09be \u09b9\u09df\u09c7\u099b\u09c7\u0964\n{self._format_cart_summary(state)}"

        target["qty"] = new_qty
        state["pending_items"] = pending
        price_str = self._format_price(product.get("price"), product.get("unit", ""))
        note_line = f"\n{qty_note}" if qty_note else ""
        return (
            f"\u0995\u09be\u09b0\u09cd\u099f \u0986\u09aa\u09a1\u09c7\u099f: {name} x{new_qty} ({price_str}){note_line}\n"
            f"{self._format_cart_summary(state)}"
        )

    @staticmethod
    def _is_recommendation_request(text: str) -> bool:
        t = normalize_query(text).lower()
        keywords = [
            "recommend", "suggest", "bundle", "also buy", "what else", "আর কি", "আরকি",
            "সাজেশন", "সাজেস্ট", "recommendation",
        ]
        return any(k in t for k in keywords)

    def _format_recommendation_block(self, items: List[Dict[str, Any]], heading: str = "") -> str:
        if not items:
            return ""
        lines = [heading or "\u09b8\u09be\u09a5\u09c7 \u0986\u09b0\u09cb \u09a8\u09bf\u09a4\u09c7 \u09aa\u09be\u09b0\u09c7\u09a8:"]
        for item in items:
            lines.append(f"  \u2022 {item.get('name', '')} \u2014 {self._format_price(item.get('price'), str(item.get('unit') or ''))}")
        return "\n".join(lines)

    def _get_cart_recommendations(self, state: Dict[str, Any], limit: int = 2) -> List[Dict[str, Any]]:
        if not self.recommendations:
            return []
        pending = state.get("pending_items", [])
        pids = [str(x.get("product_id") or "") for x in pending if str(x.get("product_id") or "")]
        if not pids:
            return []
        return self.recommendations.recommend_for_cart(pids, limit=limit)

    def _maybe_answer_recommendation(self, text: str, state: Dict[str, Any]) -> Optional[str]:
        if not self._is_recommendation_request(text):
            return None
        if not self.recommendations:
            return "\u098f\u0987 \u09ae\u09c1\u09b9\u09c2\u09b0\u09cd\u09a4\u09c7 \u09b8\u09be\u099c\u09c7\u09b6\u09a8 \u09a1\u09c7\u099f\u09be \u09a8\u09c7\u0987\u0964 \u09a4\u09ac\u09c7 \u099a\u09be\u0987\u09b2\u09c7 \u0995\u09cd\u09af\u09be\u099f\u09be\u0997\u09b0\u09bf \u09a6\u09c7\u0996\u09be\u09a4\u09c7 \u09aa\u09be\u09b0\u09bf\u0964"

        pending = state.get("pending_items", [])
        if pending:
            recs = self._get_cart_recommendations(state, limit=3)
            if recs:
                return self._format_recommendation_block(recs)

        query = self._clean_query(text)
        if query:
            matches = self.catalog.search_products(query, limit=1, min_score=55)
            if matches:
                recs = self.recommendations.recommend_for_product(
                    str(matches[0].get("product_id") or ""),
                    limit=3,
                )
                if recs:
                    return self._format_recommendation_block(recs, "\u098f\u0987 \u09aa\u09a3\u09cd\u09af\u09c7\u09b0 \u09b8\u09be\u09a5\u09c7 \u0986\u09b0\u09cb \u09af\u09be \u09a8\u09c7\u09df\u09be \u09b9\u09df:")

        popular = self.recommendations.popular_products(limit=3)
        if popular:
            return self._format_recommendation_block(popular, "\u09aa\u09aa\u09c1\u09b2\u09be\u09b0 \u09aa\u09be\u09a3\u09cd\u09af:")
        return "\u098f\u0996\u09a8\u09cb \u09af\u09a5\u09c7\u09b7\u09cd\u099f \u09aa\u09be\u09b8\u09cd\u099f \u0985\u09b0\u09cd\u09a1\u09be\u09b0 \u09a1\u09c7\u099f\u09be \u09a8\u09c7\u0987, \u09a4\u09ac\u09c7 \u099a\u09be\u0987\u09b2\u09c7 \u0995\u09cd\u09af\u09be\u099f\u09be\u0997\u09b0\u09bf \u09a6\u09c7\u0996\u09be\u09a4\u09c7 \u09aa\u09be\u09b0\u09bf\u0964"

    @staticmethod
    def _checkout_resume_prompt(flow: str) -> str:
        if flow == "awaiting_phone":
            return "\u099a\u09be\u09b2\u09bf\u09df\u09c7 \u09af\u09c7\u09a4\u09c7 \u0986\u09aa\u09a8\u09be\u09b0 \u09ab\u09cb\u09a8 \u09a8\u09ae\u09cd\u09ac\u09b0 \u09a6\u09bf\u09a8 (01XXXXXXXXX):"
        if flow == "awaiting_address":
            return "\u099a\u09be\u09b2\u09bf\u09df\u09c7 \u09af\u09c7\u09a4\u09c7 \u09a0\u09bf\u0995\u09be\u09a8\u09be \u09a6\u09bf\u09a8:"
        if flow == "awaiting_confirm":
            return "YES \u09b2\u09bf\u0996\u09c7 \u0995\u09a8\u09ab\u09be\u09b0\u09cd\u09ae \u0995\u09b0\u09c1\u09a8, \u09ac\u09be \u09ad\u09c1\u09b2 \u09a5\u09be\u0995\u09b2\u09c7 \u09b8\u0982\u09b6\u09cb\u09a7\u09a8 \u09ac\u09b2\u09c1\u09a8\u0964"
        return "\u0985\u09b0\u09cd\u09a1\u09be\u09b0 \u0995\u09a8\u09ab\u09be\u09b0\u09cd\u09ae \u0995\u09b0\u09a4\u09c7 \u0986\u09aa\u09a8\u09be\u09b0 \u09a8\u09be\u09ae \u09b2\u09bf\u0996\u09c1\u09a8:"

    @staticmethod
    def _is_category_query(text: str) -> bool:
        t = text.lower()
        keywords = [
            "category", "ki ache", "ki ki ache", "available", "dekhao",
            "show", "list", "\u0995\u09bf \u0986\u099b\u09c7",
            "\u09a6\u09c7\u0996\u09be\u0993", "\u09b8\u09ac", "all",
            "what do you have", "what's available", "ki ki", "kon kon",
            "\u0995\u09cd\u09af\u09be\u099f\u09be\u0997\u09b0\u09bf", "ki pawa jai",
            "what products",
            "maach ache", "mach ache", "maach list", "mach list",
            "fish list", "fish ache", "kon maach", "kono maach",
            "\u0995\u09cb\u09a8 \u09ae\u09be\u099b", "\u09b8\u09ac \u09ae\u09be\u099b",
            "\u0995\u09bf \u09ae\u09be\u099b",
        ]
        if any(k in t for k in keywords):
            return True
        if re.search(r"\b(ki|kon|kono|\u0995\u09bf|\u0995\u09cb\u09a8)\b.{1,20}\b(ache|acche|\u0986\u099b\u09c7)\b", t):
            return True
        return False

    @staticmethod
    def _is_generic_catalog_request(text: str) -> bool:
        t = text.lower().strip()
        generic_phrases = [
            "ki ki ache",
            "ki ache",
            "what products do we have",
            "what products do you have",
            "what do you have",
            "what's available",
            "available products",
            "show all categories",
            "list categories",
            "categories",
            "\u0995\u09bf \u0995\u09bf \u0986\u099b\u09c7",
            "\u0995\u09bf \u0986\u099b\u09c7",
            "\u0995\u09cd\u09af\u09be\u099f\u09be\u0997\u09b0\u09bf",
            "\u09b8\u09ac \u0995\u09bf\u099b\u09c1",
            "\u09b8\u09ac \u09a6\u09c7\u0996\u09be\u0993",
        ]
        if any(p in t for p in generic_phrases):
            return True
        if re.search(r"\bwhat\b.{0,30}\b(products|items|available|categories)\b", t):
            return True
        if re.search(r"\b(ki|\u0995\u09bf)\b.{0,20}\b(ache|\u0986\u099b\u09c7)\b", t):
            return True
        return False

    def _match_explicit_category_name(self, text: str) -> Optional[str]:
        """Return category name if text looks like a direct category mention."""
        q = self._clean_query(text)
        if not q:
            return None

        # Avoid stealing obvious non-category intents
        if any(ch.isdigit() for ch in q):
            return None
        if self._is_order_intent(text) or self._is_price_query(text) or self._is_checkout_intent(text):
            return None

        q_tokens = q.split()
        if len(q_tokens) > 4:
            return None

        qn = normalize_query(q).lower().strip()
        if not qn:
            return None
        if len(qn) < 3:
            return None

        best_cat = ""
        best_score = 0.0

        for row in self.catalog.list_categories():
            cat = str(row.get("category") or "").strip()
            if not cat:
                continue
            cn = normalize_query(cat).lower().strip()
            if not cn:
                continue
            if qn == cn:
                return cat
            score = max(
                self.catalog._score(qn, cn),
                self.catalog._score(q, cat),
            )
            if score > best_score:
                best_score = score
                best_cat = cat

        # Only accept fuzzy category resolution when confidence is high.
        if best_cat and best_score >= 78:
            return best_cat

        return None

    @staticmethod
    def _extract_order_items(text: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        t = normalize_spelled_numbers(ChatOrchestrator._normalize_digits(text.lower().strip()))
        segments = re.split(r"\s*(?:,| and | ar | \+ |&|\n)\s*", t)
        noise = {
            "nibo", "lagbe", "kinbo", "debo", "order", "want", "need",
            "buy", "dite", "den", "din", "dao", "diyo", "pathao", "send",
            "chai", "add", "cart", "nite", "please", "pls", "and", "ar",
            "ta", "kg", "kilo", "gm", "gram", "litre", "liter", "packet",
            "pack", "pcs", "piece", "er",
            "\u099a\u09be\u0987", "\u09b2\u09be\u0997\u09ac\u09c7", "\u09a6\u09bf\u09a8",
            "\u09a6\u09be\u0993", "\u09aa\u09be\u09a0\u09be\u0993", "\u09a8\u09bf\u09ac",
            "\u09a8\u09bf\u09ac\u09cb", "\u0995\u09bf\u09a8\u09ac", "\u0995\u09bf\u09a8\u09ac\u09cb",
        }

        for seg in segments:
            s = seg.strip()
            if not s:
                continue

            m1 = re.search(
                r"(?<!\d)(\d{1,3})(?!\d)\s*(?:kg|kilo|gm|gram|litre|liter|packet|pack|pcs|pc|ta|ti|\u099f\u09be|\u099f\u09bf|piece)?\s+(.+)$",
                s,
            )
            m2 = re.search(
                r"^(.+?)\s+(?<!\d)(\d{1,3})(?!\d)\s*(?:kg|kilo|gm|gram|litre|liter|packet|pack|pcs|pc|ta|ti|\u099f\u09be|\u099f\u09bf|piece)?$",
                s,
            )

            qty = 0
            raw_product = ""
            if m1:
                qty = int(m1.group(1))
                raw_product = m1.group(2)
            elif m2:
                raw_product = m2.group(1)
                qty = int(m2.group(2))
            else:
                continue

            raw_product = re.sub(
                r"\b(nibo|lagbe|kinbo|debo|dibo|dite|order|want|need|buy|den|din|dao|pathao|send|add|cart|nite|please|pls|kg|kilo|gm|gram|litre|liter|packet|pack|pcs|pc|piece|ta|ti)\b",
                " ",
                raw_product,
            )
            raw_product = re.sub(r"\s+", " ", raw_product).strip(" .,-")
            if not raw_product:
                continue
            if raw_product.lower() in noise:
                continue
            if qty <= 0:
                continue
            items.append({"raw_product": raw_product, "qty": qty, "source_text": s})
        return items

    @staticmethod
    def _clean_query(text: str) -> str:
        normalized = normalize_query(text)
        t = normalized.lower()
        t = re.sub(
            r"\b(price|how much|order|need|want|buy|pcs|x|nibo|nib|nite|nitesi|niteci|nichi|nimu|lagbe|kinbo|debo|dibo|dite|pathao|add|cart)\b",
            " ",
            t,
        )
        t = re.sub(r"\s+", " ", t).strip(" ?!.,")
        return t

    @staticmethod
    def _looks_like_address(text: str) -> bool:
        t = text.strip()
        if len(t) < 8:
            return False
        if re.search(r"\b01\d{9}\b", t):
            return False
        return True

    @staticmethod
    def _stringify_items(line_items: List[Dict[str, Any]]) -> str:
        chunks = []
        for li in line_items:
            unit = f" {li['unit']}" if li.get("unit") else ""
            chunks.append(f"{li['name']}{unit} x{li['qty']}")
        return ", ".join(chunks)

    # ── Checkout flow helpers ───────────────────────────────────────────

    def _format_cart_summary(self, state: Dict[str, Any]) -> str:
        """Build a Bangla cart summary with prices."""
        pending = state.get("pending_items", [])
        if not pending:
            return "\u0986\u09aa\u09a8\u09be\u09b0 \u0995\u09be\u09b0\u09cd\u099f \u0996\u09be\u09b2\u09bf \u0986\u099b\u09c7\u0964"  # "Your cart is empty."
        quote = self.catalog.quote_items(pending)
        lines = ["\U0001f6d2 \u0986\u09aa\u09a8\u09be\u09b0 \u0995\u09be\u09b0\u09cd\u099f:"]
        total_units = 0
        for idx, li in enumerate(quote.get("line_items", []), start=1):
            total_units += int(li.get("qty") or 0)
            unit_price_str = self._format_price(li.get("unit_price"), li.get("unit", ""))
            line_total_str = self._format_price(li.get("line_total"), "")
            lines.append(f"  {idx}) {li['name']} x{li['qty']} ({unit_price_str}) = {line_total_str}")
        lines.append(f"\n\u09ae\u09cb\u099f \u09aa\u09a3\u09cd\u09af \u0987\u0989\u09a8\u09bf\u099f: {total_units}")
        lines.append(f"\u09b8\u09be\u09ac\u099f\u09cb\u099f\u09be\u09b2: {self._format_price(quote.get('subtotal', 0), '')}")
        lines.append("\u098f\u09a1\u09bf\u099f: update <\u09aa\u09a3\u09cd\u09af> <qty> / remove <\u09aa\u09a3\u09cd\u09af>")

        recs = self._get_cart_recommendations(state, limit=2)
        if recs:
            lines.append("")
            lines.append(self._format_recommendation_block(recs))
        return "\n".join(lines)

    def _format_order_confirmation(self, state: Dict[str, Any], invoice_no: str = "") -> str:
        """Build final order confirmation message."""
        pending = state.get("pending_items", [])
        quote = self.catalog.quote_items(pending)
        lines = ["\u2705 \u0985\u09b0\u09cd\u09a1\u09be\u09b0 \u0995\u09a8\u09ab\u09be\u09b0\u09cd\u09ae \u09b9\u09df\u09c7\u099b\u09c7!"]
        if invoice_no:
            lines.append(f"\u0987\u09a8\u09ad\u09df\u09c7\u09b8: {invoice_no}")
        lines.append(f"\u09a8\u09be\u09ae: {state.get('name', '-')}")
        lines.append(f"\u09ab\u09cb\u09a8: {state.get('phone', '-')}")
        lines.append(f"\u09a0\u09bf\u0995\u09be\u09a8\u09be: {state.get('address', '-')}")
        lines.append("")
        for li in quote.get("line_items", []):
            lines.append(f"  \u2022 {li['name']} x{li['qty']} = {int(round(float(li.get('line_total', 0))))} \u099f\u09be\u0995\u09be")
        lines.append(f"\n\u09ae\u09cb\u099f: {int(round(float(quote.get('subtotal', 0))))} \u099f\u09be\u0995\u09be")
        lines.append("\n\u0986\u09ae\u09b0\u09be \u09b6\u09bf\u0998\u09cd\u09b0\u0987 \u09a1\u09c7\u09b2\u09bf\u09ad\u09be\u09b0\u09bf \u09a6\u09c7\u09ac\u09cb\u0964 \u09a7\u09a8\u09cd\u09af\u09ac\u09be\u09a6! \U0001f64f")
        return "\n".join(lines)

    def _start_checkout(self, state: Dict[str, Any]) -> str:
        """Begin checkout flow. Returns first prompt."""
        pending = state.get("pending_items", [])
        if not pending:
            return "\u0986\u09aa\u09a8\u09be\u09b0 \u0995\u09be\u09b0\u09cd\u099f\u09c7 \u0995\u09bf\u099b\u09c1 \u09a8\u09c7\u0987\u0964 \u0986\u0997\u09c7 \u09aa\u09a3\u09cd\u09af \u09af\u09cb\u0997 \u0995\u09b0\u09c1\u09a8!"  # "Cart empty, add products first!"
        summary = self._format_cart_summary(state)
        state["awaiting_qty"] = False
        state["checkout_flow"] = "awaiting_name"
        return (
            f"{summary}\n\n"
            "\u099a\u09c7\u0995\u0986\u0989\u099f \u09b6\u09c1\u09b0\u09c1 \u09b9\u099a\u09cd\u099b\u09c7\u0964 \u0995\u09be\u09b0\u09cd\u099f \u098f\u09a1\u09bf\u099f \u0995\u09b0\u09a4\u09c7 \u099a\u09be\u0987\u09b2\u09c7 \u098f\u0996\u09a8\u0987 update/remove \u09ac\u09b2\u09c1\u09a8\u0964\n"
            "\u0985\u09b0\u09cd\u09a1\u09be\u09b0 \u0995\u09a8\u09ab\u09be\u09b0\u09cd\u09ae \u0995\u09b0\u09a4\u09c7 \u0986\u09aa\u09a8\u09be\u09b0 \u09a8\u09be\u09ae \u09b2\u09bf\u0996\u09c1\u09a8:"
        )

    def _handle_checkout_flow(self, text: str, state: Dict[str, Any],
                               channel: str, channel_user_id: str) -> Optional[str]:
        """Handle checkout state machine. Returns reply or None if not in checkout."""
        flow = state.get("checkout_flow", "")
        if not flow:
            return None

        # Allow cancel at any point
        if self._is_no(text) or text.strip().lower() in {"cancel", "বাতিল"}:
            state["awaiting_qty"] = False
            state["checkout_flow"] = ""
            return "\u0985\u09b0\u09cd\u09a1\u09be\u09b0 \u09ac\u09be\u09a4\u09bf\u09b2 \u0995\u09b0\u09be \u09b9\u09df\u09c7\u099b\u09c7\u0964 \u0986\u09aa\u09a8\u09be\u09b0 \u0995\u09be\u09b0\u09cd\u099f\u09c7\u09b0 \u09aa\u09a3\u09cd\u09af \u098f\u0996\u09a8\u09cb \u0986\u099b\u09c7\u0964 \u0986\u09b0 \u0995\u09bf\u099b\u09c1 \u09b2\u09be\u0997\u09b2\u09c7 \u09ac\u09b2\u09c1\u09a8!"

        # Allow cart operations while checkout is active.
        if self._is_show_cart_request(text):
            return f"{self._format_cart_summary(state)}\n\n{self._checkout_resume_prompt(flow)}"
        if self._is_cart_edit_help_request(text):
            return f"{self._cart_edit_help_text()}\n\n{self._checkout_resume_prompt(flow)}"
        if self._is_update_cart_qty_request(text):
            reply = self._update_cart_qty(text, state)
            if not state.get("pending_items"):
                state["checkout_flow"] = ""
                return f"{reply}\n\n\u0995\u09be\u09b0\u09cd\u099f \u0996\u09be\u09b2\u09bf \u09b9\u09df\u09c7 \u0997\u09c7\u099b\u09c7\u0964 \u09a8\u09a4\u09c1\u09a8 \u09aa\u09a3\u09cd\u09af \u09af\u09cb\u0997 \u0995\u09b0\u09c1\u09a8\u0964"
            return f"{reply}\n\n{self._checkout_resume_prompt(flow)}"
        if self._is_remove_from_cart_request(text):
            reply = self._remove_from_cart(text, state)
            if not state.get("pending_items"):
                state["checkout_flow"] = ""
                return f"{reply}\n\n\u0995\u09be\u09b0\u09cd\u099f \u0996\u09be\u09b2\u09bf \u09b9\u09df\u09c7 \u0997\u09c7\u099b\u09c7\u0964 \u09a8\u09a4\u09c1\u09a8 \u09aa\u09a3\u09cd\u09af \u09af\u09cb\u0997 \u0995\u09b0\u09c1\u09a8\u0964"
            return f"{reply}\n\n{self._checkout_resume_prompt(flow)}"
        reco_reply = self._maybe_answer_recommendation(text, state)
        if reco_reply:
            return f"{reco_reply}\n\n{self._checkout_resume_prompt(flow)}"

        if flow == "awaiting_name":
            name = self._extract_name(text)
            if len(name) < 2:
                return "\u09a6\u09df\u09be \u0995\u09b0\u09c7 \u0986\u09aa\u09a8\u09be\u09b0 \u09a8\u09be\u09ae \u09b2\u09bf\u0996\u09c1\u09a8:"
            state["name"] = name
            state["checkout_flow"] = "awaiting_phone"
            return f"\u09a7\u09a8\u09cd\u09af\u09ac\u09be\u09a6 {name}! \u098f\u0996\u09a8 \u0986\u09aa\u09a8\u09be\u09b0 \u09ab\u09cb\u09a8 \u09a8\u09ae\u09cd\u09ac\u09b0 \u09a6\u09bf\u09a8 (01XXXXXXXXX):"

        if flow == "awaiting_phone":
            phone = self._extract_phone(text)
            if not phone:
                if self._has_invalid_phone_candidate(text):
                    return "\u09a8\u09ae\u09cd\u09ac\u09b0\u099f\u09bf \u09b8\u09b9\u09bf \u09a8\u09df\u0964 01 \u09a6\u09bf\u09df\u09c7 \u09b6\u09c1\u09b0\u09c1 \u09b9\u0993\u09df\u09be 11 \u09a1\u09bf\u099c\u09bf\u099f\u09c7\u09b0 \u09a8\u09ae\u09cd\u09ac\u09b0 \u09a6\u09bf\u09a8:"
                return "\u09a6\u09df\u09be \u0995\u09b0\u09c7 \u0986\u09aa\u09a8\u09be\u09b0 \u09ab\u09cb\u09a8 \u09a8\u09ae\u09cd\u09ac\u09b0 \u09a6\u09bf\u09a8 (01XXXXXXXXX):"
            state["phone"] = phone
            state["checkout_flow"] = "awaiting_address"
            return "\u09a7\u09a8\u09cd\u09af\u09ac\u09be\u09a6! \u098f\u0996\u09a8 \u0986\u09aa\u09a8\u09be\u09b0 \u09a1\u09c7\u09b2\u09bf\u09ad\u09be\u09b0\u09bf \u09a0\u09bf\u0995\u09be\u09a8\u09be \u09b2\u09bf\u0996\u09c1\u09a8:"

        if flow == "awaiting_address":
            addr = text.strip()
            if len(addr) < 5:
                return "\u09a6\u09df\u09be \u0995\u09b0\u09c7 \u09aa\u09c1\u09b0\u09cb \u09a0\u09bf\u0995\u09be\u09a8\u09be \u09b2\u09bf\u0996\u09c1\u09a8 (\u098f\u09b0\u09bf\u09df\u09be, \u09b0\u09cb\u09a1, \u09ac\u09be\u09b8\u09be \u09a8\u09ae\u09cd\u09ac\u09b0):"
            state["address"] = addr
            state["checkout_flow"] = "awaiting_confirm"
            summary = self._format_cart_summary(state)
            return (
                f"{summary}\n\n"
                f"\u09a8\u09be\u09ae: {state.get('name', '-')}\n"
                f"\u09ab\u09cb\u09a8: {state.get('phone', '-')}\n"
                f"\u09a0\u09bf\u0995\u09be\u09a8\u09be: {addr}\n\n"
                "\u09b8\u09ac \u09a0\u09bf\u0995 \u0986\u099b\u09c7? \u0995\u09a8\u09ab\u09be\u09b0\u09cd\u09ae \u0995\u09b0\u09a4\u09c7 YES \u09b2\u09bf\u0996\u09c1\u09a8, \u09ac\u09be \u09aa\u09b0\u09bf\u09ac\u09b0\u09cd\u09a4\u09a8 \u0995\u09b0\u09a4\u09c7 \u09ac\u09b2\u09c1\u09a8\u0964"
            )

        if flow == "awaiting_confirm":
            if self._is_yes(text):
                return self._finalize_order(state, channel, channel_user_id)
            # Not yes — let them correct
            state["checkout_flow"] = "awaiting_name"
            return "\u09a0\u09bf\u0995 \u0986\u099b\u09c7, \u0986\u09ac\u09be\u09b0 \u09b6\u09c1\u09b0\u09c1 \u0995\u09b0\u09bf\u0964 \u0986\u09aa\u09a8\u09be\u09b0 \u09a8\u09be\u09ae \u09b2\u09bf\u0996\u09c1\u09a8:"

        # Unknown flow state — reset
        state["checkout_flow"] = ""
        return None

    def _finalize_order(self, state: Dict[str, Any],
                         channel: str, channel_user_id: str) -> str:
        """Save order to OrderSheet + InvoiceStore, return confirmation."""
        pending = state.get("pending_items", [])
        quote = self.catalog.quote_items(pending)
        if not quote.get("line_items"):
            state["checkout_flow"] = ""
            return "\u0995\u09be\u09b0\u09cd\u099f\u09c7\u09b0 \u09aa\u09a3\u09cd\u09af \u09ad\u09c7\u09b0\u09bf\u09ab\u09be\u0987 \u0995\u09b0\u09be \u09af\u09be\u09df\u09a8\u09bf\u0964 \u09a6\u09df\u09be \u0995\u09b0\u09c7 \u0986\u09ac\u09be\u09b0 \u09aa\u09a3\u09cd\u09af \u09af\u09cb\u0997 \u0995\u09b0\u09c1\u09a8\u0964"

        # Save to order sheet (xlsx)
        payload = {
            "channel": channel,
            "channel_user_id": channel_user_id,
            "customer_name": state.get("name", ""),
            "phone": state.get("phone", ""),
            "address": state.get("address", ""),
            "area": state.get("area", ""),
            "items": self._stringify_items(quote["line_items"]),
            "total": quote["subtotal"],
            "notes": state.get("notes", ""),
            "last_message": "confirmed",
        }
        try:
            order = self.orders.upsert_active_order(channel_user_id, payload, status="CONFIRMED")
        except Exception as exc:
            logger.error("order_finalize_failed user=%s err=%s", channel_user_id, exc)
            return (
                "দুঃখিত, অর্ডার কনফার্ম করতে সাময়িক সমস্যা হচ্ছে। "
                "আবার YES লিখে চেষ্টা করুন।"
            )

        # Save to invoice CSV
        invoice_no = ""
        if self.invoice_store:
            try:
                inv = self.invoice_store.create_invoice(
                    customer_name=state.get("name", ""),
                    phone=state.get("phone", ""),
                    address=state.get("address", ""),
                    area=state.get("area", ""),
                    channel=channel,
                    line_items=quote["line_items"],
                    subtotal=quote["subtotal"],
                    delivery_charge=0,
                    payment_method="COD",
                    notes=state.get("notes", ""),
                    order_id=str(order.get("order_id", "")),
                )
                invoice_no = inv.get("invoice_no", "")
                logger.info("invoice_created invoice=%s user=%s", invoice_no, channel_user_id)
            except Exception as exc:
                logger.error("invoice_creation_failed: %s", exc)

        confirmation = self._format_order_confirmation(state, invoice_no)

        # Clear cart and checkout state
        state["pending_items"] = []
        state["awaiting_qty"] = False
        state["checkout_flow"] = ""

        return confirmation

    # ── Tool execution ──────────────────────────────────────────────────

    def _execute_tool(self, tool: str, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("tool_call tool=%s args=%s", tool, args)
        if tool == "search_products":
            query = str(args.get("query") or "")
            limit = int(args.get("limit") or 5)
            result = self.catalog.search_products(query, limit=limit)
            state["last_product_candidates"] = result
            return {"matches": result}
        if tool == "get_product":
            product_id = str(args.get("product_id") or "")
            result = self.catalog.get_product(product_id)
            return {"product": result}
        if tool == "quote_items":
            items = args.get("items") or []
            return self.catalog.quote_items(items)
        if tool == "browse_category":
            query = str(args.get("query") or args.get("category") or "")
            limit = int(args.get("limit") or 10)
            return self.catalog.browse_category(query, limit=limit)
        if tool == "list_categories":
            return {"categories": self.catalog.list_categories()}
        return {"error": f"Unknown tool: {tool}"}

    # ── LLM loop ────────────────────────────────────────────────────────

    def _run_llm_loop(self, text: str, state: Dict[str, Any]) -> str:
        t0 = time.monotonic()
        normalized = normalize_query(text)
        pre_results = []
        if normalized and len(normalized.strip()) >= 2:
            pre_results = self.catalog.search_products(normalized, limit=5)

        if pre_results:
            short = [
                {"name": r["name"], "price": r["price"], "unit": r["unit"],
                 "product_id": r["product_id"]}
                for r in pre_results
            ]
            state["last_product_candidates"] = pre_results
            hint = (
                f"\n[Pre-searched catalog for \"{normalized}\": "
                f"{json.dumps(short, ensure_ascii=False)}]\n"
                "You already have the search results above. "
                "Reply with a final message directly \u2014 do NOT call search_products again."
            )
        elif normalized.strip() and normalized != text:
            hint = f"\n[Hint: normalized product query = \"{normalized}\"]"
        else:
            hint = ""

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Session state JSON:\n"
                    f"{json.dumps(state, ensure_ascii=False)}\n\n"
                    f"Customer message: {text}{hint}"
                ),
            },
        ]

        fallback = "\u09a7\u09a8\u09cd\u09af\u09ac\u09be\u09a6! \u0995\u09bf \u09aa\u09a3\u09cd\u09af \u09b2\u09be\u0997\u09ac\u09c7 \u09ac\u09b2\u09c1\u09a8\u0964"

        for i in range(3):
            try:
                action = self.llm.chat_json(messages)
            except Exception as exc:
                logger.warning("LLM call failed: %s", exc)
                break

            if action.get("type") == "tool_call":
                tool_result = self._execute_tool(action["tool"], action.get("args", {}), state)
                messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(
                            {"tool": action["tool"], "result": tool_result},
                            ensure_ascii=False,
                        ),
                    }
                )
                continue

            if action.get("type") == "final":
                elapsed = time.monotonic() - t0
                logger.info("llm_loop_done elapsed=%.1fs iterations=%d", elapsed, i + 1)
                return str(action.get("message") or fallback)

        return fallback

    # ── Cart helpers ────────────────────────────────────────────────────

    def _add_or_update_pending_item(self, state: Dict[str, Any], product_id: str, qty: int) -> None:
        if qty <= 0:
            return
        pending = state.get("pending_items", [])
        for item in pending:
            if item.get("product_id") == product_id:
                item["qty"] = int(item.get("qty", 0)) + qty
                break
        else:
            pending.append({"product_id": product_id, "qty": qty})
        state["pending_items"] = pending

    def _handle_item_capture(self, text: str, state: Dict[str, Any]) -> Optional[str]:
        if not self._is_order_intent(text):
            return None

        awaiting_qty = bool(state.get("awaiting_qty"))
        parsed_msg = parse_user_message(text, allow_bare_qty=awaiting_qty)
        parsed = self._extract_order_items(text)
        if parsed:
            added = []
            unresolved = []
            conversion_notes = []
            for item in parsed:
                normalized_product = normalize_query(item["raw_product"])
                matches = self.catalog.search_products(normalized_product, limit=3, min_score=45)
                if matches:
                    top_score = float(matches[0].get("_score") or 0)
                    if top_score < 55:
                        unresolved.append(item["raw_product"])
                        state["last_product_candidates"] = matches
                        continue
                    if self._is_ambiguous_match(matches):
                        state["awaiting_choice"] = True
                        state["pending_choice_candidates"] = matches[:3]
                        state["choice_context"] = "order"
                        state["choice_qty"] = int(item["qty"])
                        state["choice_qty_text"] = str(item.get("source_text") or "")
                        state["last_product_candidates"] = matches
                        return self._build_disambiguation_reply(
                            matches,
                            f"\"{item['raw_product']}\" \u09a6\u09bf\u09df\u09c7 \u098f\u0995\u09be\u09a7\u09bf\u0995 \u09aa\u09a3\u09cd\u09af \u09ae\u09bf\u09b2\u09c7\u099b\u09c7, \u0995\u09cb\u09a8\u099f\u09be \u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09a8\u09bf\u09ac?",
                        )
                    qty_final, qty_note = self._resolve_qty_for_product(
                        int(item["qty"]),
                        str(item.get("source_text") or text),
                        matches[0],
                    )
                    self._add_or_update_pending_item(state, matches[0]["product_id"], qty_final)
                    price_str = self._format_price(matches[0].get("price"), matches[0].get("unit", ""))
                    added.append(f"{matches[0]['name']} x{qty_final} ({price_str})")
                    if qty_note:
                        conversion_notes.append(f"{matches[0]['name']}: {qty_note}")
                    state["last_product_candidates"] = matches
                else:
                    unresolved.append(item["raw_product"])
            if added:
                state["awaiting_qty"] = False
                pending = state.get("pending_items", [])
                note_block = ""
                if conversion_notes:
                    note_block = "\n" + "\n".join(conversion_notes)
                return (
                    f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09af\u09cb\u0997 \u09b9\u09df\u09c7\u099b\u09c7: {', '.join(added)}{note_block}\n"
                    f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09ae\u09cb\u099f {len(pending)}\u099f\u09bf \u09aa\u09a3\u09cd\u09af\u0964\n"
                    "\u0986\u09b0 \u0995\u09bf\u099b\u09c1 \u09b2\u09be\u0997\u09ac\u09c7? \u09a8\u09be\u0995\u09bf 'order' \u09b2\u09bf\u0996\u09c1\u09a8 \u2705"
                )
            if unresolved:
                return (
                    f"\"{unresolved[0]}\" \u098f\u0995\u099f\u09c1 \u09b8\u09cd\u09aa\u09b7\u09cd\u099f \u0995\u09b0\u09c7 \u09ac\u09b2\u09ac\u09c7\u09a8? "
                    "\u09aa\u09be\u0995\u09c7\u099f/\u0993\u099c\u09a8 \u09a5\u09be\u0995\u09b2\u09c7 \u09a6\u09bf\u09a8\u0964"
                )

        qty = parsed_msg.quantity if parsed_msg.quantity_confidence >= 0.75 else self._extract_qty_only(text, allow_bare=awaiting_qty)
        if qty and state.get("last_product_candidates"):
            best = state["last_product_candidates"][0]
            best_score = float(best.get("_score") or 100)
            if best_score < 55:
                return "\u0995\u09cb\u09a8 \u09aa\u09a3\u09cd\u09af\u099f\u09be \u09a8\u09bf\u09ac\u09c7\u09a8, \u09a8\u09be\u09ae\u099f\u09be \u0986\u09b0\u0995\u099f\u09c1 \u09b8\u09cd\u09aa\u09b7\u09cd\u099f \u0995\u09b0\u09c7 \u09ac\u09b2\u09c1\u09a8\u0964"
            qty_final, qty_note = self._resolve_qty_for_product(int(qty), text, best)
            state["awaiting_qty"] = False
            self._add_or_update_pending_item(state, best["product_id"], qty_final)
            pending = state.get("pending_items", [])
            price_str = self._format_price(best.get("price"), best.get("unit", ""))
            note_line = f"\n{qty_note}" if qty_note else ""
            return (
                f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09af\u09cb\u0997 \u09b9\u09df\u09c7\u099b\u09c7: {best['name']} x{qty_final} ({price_str}){note_line}\n"
                f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09ae\u09cb\u099f {len(pending)}\u099f\u09bf \u09aa\u09a3\u09cd\u09af\u0964\n"
                "\u0986\u09b0 \u0995\u09bf\u099b\u09c1 \u09b2\u09be\u0997\u09ac\u09c7? \u09a8\u09be\u0995\u09bf 'order' \u09b2\u09bf\u0996\u09c1\u09a8 \u2705"
            )

        if state.get("last_product_candidates") and self._is_intent_only_add_request(text):
            state["awaiting_qty"] = True
            return "\u0995\u09a4\u099f\u09bf \u09a6\u09bf\u09ac\u09cb \u09ad\u09be\u0987?"

        query = parsed_msg.product_query or self._clean_query(text)
        if not query or parsed_msg.product_confidence < 0.2:
            return None
        matches = self.catalog.search_products(query, limit=3, min_score=45)
        state["last_product_candidates"] = matches
        if matches:
            top_score = float(matches[0].get("_score") or 0)
            if top_score < 55:
                return (
                    f"\"{query}\" \u09a8\u09be\u09ae\u099f\u09be \u098f\u0995\u099f\u09c1 \u09b8\u09cd\u09aa\u09b7\u09cd\u099f \u0995\u09b0\u09c7 \u09ac\u09b2\u09c1\u09a8। "
                    "\u09a6\u09b0\u0995\u09be\u09b0 \u09b9\u09b2\u09c7 \u09aa\u09be\u0995\u09c7\u099f/\u0993\u099c\u09a8 \u09af\u09cb\u0997 \u0995\u09b0\u09c1\u09a8\u0964"
                )
            if self._is_ambiguous_match(matches):
                state["awaiting_choice"] = True
                state["pending_choice_candidates"] = matches[:3]
                state["choice_context"] = "order"
                state["choice_qty"] = int(qty or 1)
                state["choice_qty_text"] = text
                return self._build_disambiguation_reply(
                    matches,
                    "\u098f\u0995\u09be\u09a7\u09bf\u0995 \u09aa\u09a3\u09cd\u09af \u09ae\u09bf\u09b2\u09c7\u099b\u09c7, \u0995\u09cb\u09a8\u099f\u09be \u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09a8\u09bf\u09ac?",
                )
            qty_final, qty_note = self._resolve_qty_for_product(int(qty or 1), text, matches[0])
            state["awaiting_qty"] = False
            self._add_or_update_pending_item(state, matches[0]["product_id"], qty_final)
            pending = state.get("pending_items", [])
            price_str = self._format_price(matches[0].get("price"), matches[0].get("unit", ""))
            note_line = f"\n{qty_note}" if qty_note else ""
            return (
                f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09af\u09cb\u0997 \u09b9\u09df\u09c7\u099b\u09c7: {matches[0]['name']} x{qty_final} ({price_str}){note_line}\n"
                f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09ae\u09cb\u099f {len(pending)}\u099f\u09bf \u09aa\u09a3\u09cd\u09af\u0964\n"
                "\u0986\u09b0 \u0995\u09bf\u099b\u09c1 \u09b2\u09be\u0997\u09ac\u09c7? \u09a8\u09be\u0995\u09bf 'order' \u09b2\u09bf\u0996\u09c1\u09a8 \u2705"
            )
        return None

    def _maybe_answer_price(self, text: str, state: Dict[str, Any]) -> Optional[str]:
        if not self._is_price_query(text):
            return None
        parsed = parse_user_message(text, allow_bare_qty=False)
        query = parsed.product_query or self._clean_query(text)
        if not query or parsed.product_confidence < 0.25:
            return "\u09aa\u09a3\u09cd\u09af\u09c7\u09b0 \u09a8\u09be\u09ae \u09ac\u09b2\u09c1\u09a8, \u09a6\u09be\u09ae \u099c\u09be\u09a8\u09bf\u09df\u09c7 \u09a6\u09bf\u099a\u09cd\u099b\u09bf\u0964"
        matches = self.catalog.search_products(query, limit=3)
        state["last_product_candidates"] = matches
        if not matches:
            return f"\"{query}\" \u09aa\u09be\u0993\u09df\u09be \u09af\u09be\u09df\u09a8\u09bf\u0964 \u0986\u09b0\u09c7\u0995\u099f\u09c1 \u09ad\u09bf\u09a8\u09cd\u09a8\u09ad\u09be\u09ac\u09c7 \u09b2\u09bf\u0996\u09c7 \u09a6\u09c7\u0996\u09c1\u09a8?"
        top_score = float(matches[0].get("_score") or 0)
        if top_score < 50:
            return f"\"{query}\" \u09aa\u09be\u09a3\u09cd\u09af\u099f\u09be \u09b8\u09cd\u09aa\u09b7\u09cd\u099f \u09aa\u09be\u0993\u09df\u09be \u09af\u09be\u099a\u09cd\u099b\u09c7 \u09a8\u09be\u0964 \u09a8\u09be\u09ae \u0986\u09b0\u09c7\u0995\u099f\u09c1 \u09a1\u09bf\u099f\u09c7\u0987\u09b2\u09c7 \u09ac\u09b2\u09c1\u09a8?"
        query_tokens = re.findall(r"[a-z0-9\u0980-\u09FF]{2,}", query.lower())
        top_lexical = self.catalog._score(query, str(matches[0].get("name") or ""))
        # For short random queries (e.g., two unrelated words), avoid returning accidental item prices.
        if len(query_tokens) >= 2 and top_lexical < 65 and top_score < 78:
            return f"\"{query}\" \u098f\u09b0 \u09b8\u09be\u09a5\u09c7 \u09a0\u09bf\u0995 \u09aa\u09a3\u09cd\u09af \u09ae\u09bf\u09b2\u099b\u09c7 \u09a8\u09be\u0964 \u09a6\u09df\u09be \u0995\u09b0\u09c7 \u09aa\u09a3\u09cd\u09af\u09c7\u09b0 \u09a0\u09bf\u0995 \u09a8\u09be\u09ae \u09b2\u09bf\u0996\u09c1\u09a8\u0964"
        if self._is_ambiguous_match(matches):
            state["awaiting_choice"] = True
            state["pending_choice_candidates"] = matches[:3]
            state["choice_context"] = "price"
            state["choice_qty"] = 1
            state["choice_qty_text"] = ""
            return self._build_disambiguation_reply(
                matches,
                "\u098f\u0987 \u09a8\u09be\u09ae\u09c7 \u098f\u0995\u09be\u09a7\u09bf\u0995 \u09aa\u09a3\u09cd\u09af \u0986\u099b\u09c7, \u0995\u09cb\u09a8\u099f\u09be\u09b0 \u09a6\u09be\u09ae \u099c\u09be\u09a8\u09a4\u09c7 \u099a\u09be\u09a8?",
            )
        top = matches[0]
        score = top.get("_score", 0)
        prefix = "\u0995\u09be\u099b\u09be\u0995\u09be\u099b\u09bf \u09aa\u09a3\u09cd\u09af \u2014 " if score < 55 else ""
        price_str = self._format_price(top.get("price"), top.get("unit", ""))
        state["awaiting_qty"] = True
        return f"{prefix}{top['name']}: {price_str}\n\u0995\u09a4\u099f\u09c1\u0995\u09c1 \u09a6\u09bf\u09ac\u09cb?"

    def _maybe_answer_product_inquiry(self, text: str, state: Dict[str, Any]) -> Optional[str]:
        parsed = parse_user_message(text, allow_bare_qty=False)
        query = parsed.product_query or self._clean_query(text)
        if not query or len(query) < 2 or parsed.product_confidence < 0.3:
            return None
        matches = self.catalog.search_products(query, limit=3, min_score=55)
        if not matches:
            return None
        top = matches[0]
        top_hybrid = float(top.get("_score") or 0)
        top_lexical = self.catalog._score(query, str(top.get("name") or ""))
        query_tokens = re.findall(r"[a-z0-9\u0980-\u09FF]{2,}", query.lower())
        # Guard against random semantic matches for unrelated short queries.
        if top_hybrid < 70 and top_lexical < 45:
            return None
        # Extra guard: unknown short text needs stronger lexical evidence.
        if parsed.intent == "unknown" and parsed.intent_confidence < 0.55:
            if len(query_tokens) >= 2 and top_lexical < 70:
                return None
            if len(query_tokens) == 1 and top_lexical < 58 and top_hybrid < 85:
                return None
        if self._is_ambiguous_match(matches):
            state["awaiting_choice"] = True
            state["pending_choice_candidates"] = matches[:3]
            state["choice_context"] = "inquiry"
            state["choice_qty"] = 1
            state["choice_qty_text"] = ""
            return self._build_disambiguation_reply(
                matches,
                "\u09a8\u09be\u09ae\u099f\u09be \u098f\u0995\u099f\u09c1 \u0985\u09cd\u09af\u09be\u09ae\u09cd\u09ac\u09bf\u0997\u09c1\u09df\u09be\u09b8 \u09b2\u09be\u0997\u099b\u09c7, \u0995\u09cb\u09a8\u099f\u09be \u09a8\u09bf\u09ac\u09c7\u09a8?",
            )
        state["last_product_candidates"] = matches
        price_str = self._format_price(top.get("price"), top.get("unit", ""))
        return f"{top['name']}: {price_str}\n\u09a8\u09bf\u09a4\u09c7 \u099a\u09be\u0987\u09b2\u09c7 \u09ac\u09b2\u09c1\u09a8!"

    # ── Main entry point ────────────────────────────────────────────────

    def process_message(self, channel_user_id: str, text: str, channel: str = "simulator") -> str:
        t0 = time.monotonic()
        logger.info("incoming_message user=%s text=%s", channel_user_id, text)
        state = self.sessions.get_state(channel_user_id)
        parsed = parse_user_message(text, allow_bare_qty=bool(state.get("awaiting_qty")))
        state["last_parse_meta"] = {
            "intent": parsed.intent,
            "intent_confidence": parsed.intent_confidence,
            "language_mix": parsed.language_mix,
            "product_confidence": parsed.product_confidence,
        }

        # ── Priority 0: Candidate disambiguation follow-up ────────────────
        choice_reply = self._handle_pending_choice(text, state)
        if choice_reply:
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_choice_select user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return choice_reply

        # ── Priority 0.5: Awaiting quantity reply ────────────────────────
        # When bot asked "কতটি দিবো ভাই?" the awaiting_qty flag is set.
        # ANY next message that contains a number is treated as the qty.
        if state.get("awaiting_qty") and state.get("last_product_candidates"):
            qty = parsed.quantity if parsed.quantity_confidence >= 0.75 else self._extract_qty_only(text, allow_bare=True)
            if qty is not None:
                state["awaiting_qty"] = False
                best = state["last_product_candidates"][0]
                best_score = float(best.get("_score") or 100)
                if best_score < 55:
                    self.sessions.save_state(channel_user_id, state)
                    return "\u0995\u09cb\u09a8 \u09aa\u09a3\u09cd\u09af\u099f\u09be \u09a8\u09bf\u09ac\u09c7\u09a8, \u09a8\u09be\u09ae\u099f\u09be \u0986\u09b0\u0995\u099f\u09c1 \u09b8\u09cd\u09aa\u09b7\u09cd\u099f \u0995\u09b0\u09c7 \u09ac\u09b2\u09c1\u09a8\u0964"
                qty_final, qty_note = self._resolve_qty_for_product(int(qty), text, best)
                self._add_or_update_pending_item(state, str(best.get("product_id") or ""), qty_final)
                pending = state.get("pending_items", [])
                price_str = self._format_price(best.get("price"), best.get("unit", ""))
                note_line = f"\n{qty_note}" if qty_note else ""
                reply = (
                    f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09af\u09cb\u0997 \u09b9\u09df\u09c7\u099b\u09c7: {best.get('name', '')} x{qty_final} ({price_str}){note_line}\n"
                    f"\u0995\u09be\u09b0\u09cd\u099f\u09c7 \u09ae\u09cb\u099f {len(pending)}\u099f\u09bf \u09aa\u09a3\u09cd\u09af\u0964\n"
                    "\u0986\u09b0 \u0995\u09bf\u099b\u09c1 \u09b2\u09be\u0997\u09ac\u09c7? \u09a8\u09be\u0995\u09bf 'order' \u09b2\u09bf\u0996\u09c1\u09a8 \u2705"
                )
                self.sessions.save_state(channel_user_id, state)
                logger.info("fast_awaiting_qty user=%s qty=%d elapsed=%.3fs", channel_user_id, qty_final, time.monotonic() - t0)
                return reply

        # ── Priority 1: Active checkout flow ─────────────────────────────
        checkout_reply = self._handle_checkout_flow(text, state, channel, channel_user_id)
        if checkout_reply:
            self.sessions.save_state(channel_user_id, state)
            logger.info("checkout_flow user=%s step=%s elapsed=%.3fs",
                        channel_user_id, state.get("checkout_flow", "done"), time.monotonic() - t0)
            return checkout_reply

        # ── Priority 2: Greeting ─────────────────────────────────────────
        if self._is_greeting(text):
            cart_count = len(state.get("pending_items", []))
            if cart_count:
                reply = f"\u0986\u09b8\u09b8\u09be\u09b2\u09be\u09ae\u09c1 \u0986\u09b2\u09be\u0987\u0995\u09c1\u09ae! Bazarey \u09a4\u09c7 \u09b8\u09cd\u09ac\u09be\u0997\u09a4\u09ae \U0001f6d2\n\u0986\u09aa\u09a8\u09be\u09b0 \u0995\u09be\u09b0\u09cd\u099f\u09c7 {cart_count}\u099f\u09bf \u09aa\u09a3\u09cd\u09af \u0986\u099b\u09c7\u0964 \u0986\u09b0 \u0995\u09bf\u099b\u09c1 \u09b2\u09be\u0997\u09ac\u09c7?"
            else:
                reply = "\u0986\u09b8\u09b8\u09be\u09b2\u09be\u09ae\u09c1 \u0986\u09b2\u09be\u0987\u0995\u09c1\u09ae! Bazarey \u09a4\u09c7 \u09b8\u09cd\u09ac\u09be\u0997\u09a4\u09ae \U0001f6d2\n\u0995\u09bf \u09aa\u09a3\u09cd\u09af \u0996\u09c1\u0981\u099c\u099b\u09c7\u09a8? \u09ac\u09b2\u09c1\u09a8!"
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_greeting user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return reply

        # ── Priority 3: Checkout intent (start flow) ─────────────────────
        if self._is_checkout_intent(text):
            reply = self._start_checkout(state)
            self.sessions.save_state(channel_user_id, state)
            logger.info("checkout_start user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return reply

        # ── Priority 4: Price query ──────────────────────────────────────
        price_reply = self._maybe_answer_price(text, state)
        if price_reply:
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_price user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return price_reply

        # ── Priority 4.5: Cart commands ─────────────────────────────────
        if self._is_show_cart_request(text):
            reply = self._format_cart_summary(state)
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_show_cart user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return reply

        if self._is_cart_edit_help_request(text):
            reply = self._cart_edit_help_text()
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_cart_edit_help user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return reply

        if self._is_update_cart_qty_request(text):
            reply = self._update_cart_qty(text, state)
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_update_cart user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return reply

        if self._is_remove_from_cart_request(text):
            reply = self._remove_from_cart(text, state)
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_remove_cart user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return reply

        reco_reply = self._maybe_answer_recommendation(text, state)
        if reco_reply:
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_recommend user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return reco_reply

        if self._is_no(text):
            state["awaiting_qty"] = False
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_no_ack user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return "\u09a0\u09bf\u0995 \u0986\u099b\u09c7 \u09ad\u09be\u0987\u0964 \u0986\u09b0 \u0995\u09bf\u099b\u09c1 \u09b2\u09be\u0997\u09b2\u09c7 \u09ac\u09b2\u09c1\u09a8\u0964"

        affirmative_reply = self._handle_affirmative_followup(text, state)
        if affirmative_reply:
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_affirm_qty user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return affirmative_reply

        # ── Priority 5: Category browsing ────────────────────────────────
        explicit_category = self._match_explicit_category_name(text)
        if self._is_category_query(text) or explicit_category:
            if self._is_generic_catalog_request(text):
                cats = self.catalog.list_categories()
                if cats:
                    lines = ["\U0001f4cb \u0986\u09ae\u09be\u09a6\u09c7\u09b0 \u0995\u09cd\u09af\u09be\u099f\u09be\u0997\u09b0\u09bf:"]
                    for c in cats[:20]:
                        lines.append(f"  \u2022 {c['category']} ({c['count']})")
                    if len(cats) > 20:
                        lines.append(f"  ... \u0986\u09b0\u09cb {len(cats) - 20}\u099f\u09bf")
                    reply = "\n".join(lines)
                    self.sessions.save_state(channel_user_id, state)
                    logger.info("fast_catlist_generic user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
                    return reply

            query = explicit_category or self._clean_query(text)
            if query and len(query) >= 2:
                result = self.catalog.browse_category(query, limit=0)
                if result.get("category") and result.get("products"):
                    cat = result["category"]
                    prods = result["products"]
                    lines = [f"\U0001f4c2 {cat} \u2014 {result['count']}\u099f\u09bf \u09aa\u09a3\u09cd\u09af \u0986\u099b\u09c7:"]
                    for p in prods:
                        price_str = self._format_price(p.get("price"), p.get("unit", ""))
                        lines.append(f"  \u2022 {p['name']} \u2014 {price_str}")
                    lines.append("\n\u09af\u09c7\u0995\u09cb\u09a8\u09cb \u09aa\u09a3\u09cd\u09af\u09c7\u09b0 \u09a8\u09be\u09ae \u09ac\u09b2\u09c1\u09a8 \u0985\u09a5\u09ac\u09be 'order' \u09b2\u09bf\u0996\u09c1\u09a8 \U0001f6d2")
                    reply = "\n".join(lines)
                    self.sessions.save_state(channel_user_id, state)
                    logger.info("fast_category user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
                    return reply
            cats = self.catalog.list_categories()
            if cats:
                lines = ["\U0001f4cb \u0986\u09ae\u09be\u09a6\u09c7\u09b0 \u0995\u09cd\u09af\u09be\u099f\u09be\u0997\u09b0\u09bf:"]
                for c in cats[:20]:
                    lines.append(f"  \u2022 {c['category']} ({c['count']})")
                if len(cats) > 20:
                    lines.append(f"  ... \u0986\u09b0\u09cb {len(cats) - 20}\u099f\u09bf")
                lines.append("\n\u09af\u09c7\u0995\u09cb\u09a8\u09cb \u0995\u09cd\u09af\u09be\u099f\u09be\u0997\u09b0\u09bf\u09b0 \u09a8\u09be\u09ae \u09ac\u09b2\u09c1\u09a8!")
                reply = "\n".join(lines)
                self.sessions.save_state(channel_user_id, state)
                logger.info("fast_catlist user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
                return reply

        # ── Priority 6: Order intent (add to cart) ───────────────────────
        order_reply = self._handle_item_capture(text, state)
        if order_reply:
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_order user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return order_reply

        # ── Priority 7: Product inquiry ──────────────────────────────────
        product_reply = self._maybe_answer_product_inquiry(text, state)
        if product_reply:
            self.sessions.save_state(channel_user_id, state)
            logger.info("fast_product user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
            return product_reply

        # ── Priority 7.5: Low-confidence guard ───────────────────────────
        # Avoid random product/category hallucinations for unrelated short text.
        normalized_msg = str(parsed.normalized_text or "").strip()
        if parsed.intent == "unknown" and parsed.intent_confidence < 0.55:
            if len(normalized_msg) <= 24 and not re.search(r"\d", normalized_msg):
                reply = (
                    "\u09a6\u09c1\u0983\u0996\u09bf\u09a4, \u09a0\u09bf\u0995\u09ae\u09a4\u09cb \u09ac\u09c1\u099d\u09a4\u09c7 \u09aa\u09be\u09b0\u09bf\u09a8\u09bf\u0964 "
                    "\u09aa\u09a3\u09cd\u09af\u09c7\u09b0 \u09a8\u09be\u09ae/\u09a6\u09be\u09ae \u09a6\u09bf\u09df\u09c7 \u0986\u09b0\u09c7\u0995\u09ac\u09be\u09b0 \u09b2\u09bf\u0996\u09c1\u09a8\u0964 "
                    "(I couldn't understand. Please share product name or price query.)"
                )
                self.sessions.save_state(channel_user_id, state)
                logger.info("fast_low_confidence user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
                return reply

        # ── Fallback: LLM ────────────────────────────────────────────────
        llm_reply = self._run_llm_loop(text, state)
        self.sessions.save_state(channel_user_id, state)
        logger.info("final_reply user=%s elapsed=%.3fs", channel_user_id, time.monotonic() - t0)
        return llm_reply
