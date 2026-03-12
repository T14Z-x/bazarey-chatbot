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
            "Bay Leaf (Tejpata)",
            "https://example.com/tejpata",
            "Spices",
            18,
            "",
            "50 gm",
            40,
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


def test_awaiting_qty_converts_grams_to_pack_count(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)

    r1 = orchestrator.process_message("u-unit", "tejpata price koto")
    assert "Bay Leaf (Tejpata)" in r1

    r2 = orchestrator.process_message("u-unit", "100gm")
    assert "x2" in r2
    assert "x100" not in r2

    r3 = orchestrator.process_message("u-unit", "show cart")
    assert "Bay Leaf (Tejpata) x2" in r3
    assert "= 36 টাকা" in r3


def test_direct_order_with_measurement_unit_converts_pack_count(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)

    reply = orchestrator.process_message("u-unit-2", "100gm tejpata dao")

    assert "Bay Leaf (Tejpata) x2" in reply
    assert "x100" not in reply


def test_product_inquiry_then_measured_qty_adds_correct_pack_count(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)

    r1 = orchestrator.process_message("u-unit-3", "Bay Leaf (Tejpata)")
    assert "নিতে চাইলে বলুন" in r1

    r2 = orchestrator.process_message("u-unit-3", "100gm")
    assert "Bay Leaf (Tejpata) x2" in r2
    assert "x100" not in r2
