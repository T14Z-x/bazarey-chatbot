from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from openpyxl import Workbook

from app.bot.orchestrator import ChatOrchestrator
from app.tools.order_sheet import OrderSheet
from app.tools.product_catalog import ProductCatalog
from app.tools.session_store import SessionStore


class FakeLLM:
    def chat_json(self, messages: List[Dict[str, str]], max_retries: int = 2) -> Dict[str, Any]:
        return {"type": "final", "message": "Fallback reply"}


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
    ws.append(
        [
            "p-001",
            "Wheel Washing Bar",
            "https://example.com/wheel-bar",
            "Home Care",
            50,
            "",
            "pc",
            20,
            True,
            "",
            "2026-01-01T00:00:00+00:00",
        ]
    )
    ws.append(
        [
            "p-002",
            "Sunsilk Shampoo Black Shine",
            "https://example.com/sunsilk",
            "Hair Care",
            290,
            "",
            "650ml",
            10,
            True,
            "",
            "2026-01-01T00:00:00+00:00",
        ]
    )
    wb.save(path)


def build_orchestrator(tmp_path: Path) -> ChatOrchestrator:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    products_xlsx = data_dir / "products.xlsx"
    orders_xlsx = data_dir / "orders.xlsx"
    sessions_db = data_dir / "sessions.db"

    build_products(products_xlsx)

    catalog = ProductCatalog(products_xlsx, vector_index_path=None)
    orders = OrderSheet(orders_xlsx)
    sessions = SessionStore(sessions_db)
    return ChatOrchestrator(catalog, orders, sessions, FakeLLM())


def test_random_two_words_returns_not_understood(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)

    reply = orchestrator.process_message("u-random", "foo bar")

    assert "couldn't understand" in reply.lower() or "বুঝতে পারিনি" in reply


def test_random_price_query_does_not_return_unrelated_product(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)

    reply = orchestrator.process_message("u-price", "foo bar price?")

    assert "ঠিক পণ্য মিলছে না" in reply or "ঠিক নাম" in reply


def test_valid_product_query_still_returns_product(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)

    reply = orchestrator.process_message("u-valid", "sunsilk shampoo")

    assert "Sunsilk Shampoo Black Shine" in reply
