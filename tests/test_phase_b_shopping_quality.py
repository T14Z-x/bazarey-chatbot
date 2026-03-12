from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from openpyxl import Workbook

from app.bot.orchestrator import ChatOrchestrator
from app.tools.invoice_store import InvoiceStore
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
    ws.append(["p-rice", "Miniket Rice 5kg", "", "Rice", 450, "", "5kg", 20, True, "", "2026-01-01"]) 
    ws.append(["p-dal", "Masoor Dal 1kg", "", "Lentil", 170, "", "1kg", 20, True, "", "2026-01-01"]) 
    ws.append(["p-oil", "Soybean Oil 1L", "", "Oil", 220, "", "1L", 20, True, "", "2026-01-01"]) 
    wb.save(path)


def seed_invoice_history(invoice_store: InvoiceStore) -> None:
    invoice_store.create_invoice(
        order_id="o-1",
        customer_name="A",
        phone="01700000001",
        address="Dhaka",
        area="Dhaka",
        channel="sim",
        line_items=[
            {"product_id": "p-rice", "name": "Miniket Rice 5kg", "qty": 1, "unit": "5kg", "unit_price": 450, "line_total": 450},
            {"product_id": "p-dal", "name": "Masoor Dal 1kg", "qty": 1, "unit": "1kg", "unit_price": 170, "line_total": 170},
        ],
        subtotal=620,
    )
    invoice_store.create_invoice(
        order_id="o-2",
        customer_name="B",
        phone="01700000002",
        address="Dhaka",
        area="Dhaka",
        channel="sim",
        line_items=[
            {"product_id": "p-rice", "name": "Miniket Rice 5kg", "qty": 1, "unit": "5kg", "unit_price": 450, "line_total": 450},
            {"product_id": "p-oil", "name": "Soybean Oil 1L", "qty": 1, "unit": "1L", "unit_price": 220, "line_total": 220},
        ],
        subtotal=670,
    )
    invoice_store.create_invoice(
        order_id="o-3",
        customer_name="C",
        phone="01700000003",
        address="Dhaka",
        area="Dhaka",
        channel="sim",
        line_items=[
            {"product_id": "p-rice", "name": "Miniket Rice 5kg", "qty": 1, "unit": "5kg", "unit_price": 450, "line_total": 450},
            {"product_id": "p-dal", "name": "Masoor Dal 1kg", "qty": 1, "unit": "1kg", "unit_price": 170, "line_total": 170},
        ],
        subtotal=620,
    )


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
    invoice_store = InvoiceStore(data_dir)
    seed_invoice_history(invoice_store)
    return ChatOrchestrator(catalog, orders, sessions, FakeLLM(), invoice_store=invoice_store)


def test_update_cart_quantity_set_mode(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)
    state = orchestrator.sessions.get_state("u-edit")
    state["pending_items"] = [{"product_id": "p-rice", "qty": 1}]
    orchestrator.sessions.save_state("u-edit", state)

    reply = orchestrator.process_message("u-edit", "update miniket rice 3")
    assert "কার্ট আপডেট" in reply
    assert "x3" in reply

    cart = orchestrator.process_message("u-edit", "show cart")
    assert "Miniket Rice 5kg x3" in cart


def test_update_cart_quantity_decrease_removes_item(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)
    state = orchestrator.sessions.get_state("u-edit-2")
    state["pending_items"] = [{"product_id": "p-rice", "qty": 1}]
    orchestrator.sessions.save_state("u-edit-2", state)

    reply = orchestrator.process_message("u-edit-2", "decrease miniket rice 1")
    assert "বাদ" in reply

    cart = orchestrator.process_message("u-edit-2", "show cart")
    assert "খালি" in cart


def test_recommendation_from_order_history(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)
    state = orchestrator.sessions.get_state("u-rec")
    state["pending_items"] = [{"product_id": "p-rice", "qty": 1}]
    orchestrator.sessions.save_state("u-rec", state)

    reply = orchestrator.process_message("u-rec", "suggest something")
    assert "সাথে" in reply or "পপুলার" in reply
    assert ("Masoor Dal 1kg" in reply) or ("Soybean Oil 1L" in reply)
