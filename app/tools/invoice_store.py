"""
CSV-based invoice storage for confirmed orders.

Each confirmed order gets a row in `data/invoices.csv` with:
- Invoice number (INV-YYYYMMDD-NNNN)
- Date & time
- Customer name, phone, address, area
- Itemized product list with qty, unit, unit_price, line_total
- Subtotal, delivery charge, grand total
- Payment method, order status, notes, channel
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

INVOICE_HEADERS = [
    "invoice_no",
    "date",
    "time",
    "customer_name",
    "phone",
    "address",
    "area",
    "channel",
    "items_summary",
    "item_count",
    "subtotal",
    "delivery_charge",
    "grand_total",
    "payment_method",
    "status",
    "notes",
    "order_id",
]

# Itemized detail file (one row per line-item)
INVOICE_ITEMS_HEADERS = [
    "invoice_no",
    "product_id",
    "product_name",
    "qty",
    "unit",
    "unit_price",
    "line_total",
]


def _bd_now() -> datetime:
    """Return current Bangladesh Standard Time (UTC+6)."""
    from datetime import timedelta
    return datetime.now(timezone(timedelta(hours=6)))


class InvoiceStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.invoices_path = self.data_dir / "invoices.csv"
        self.items_path = self.data_dir / "invoice_items.csv"
        self._ensure_files()

    def _ensure_files(self) -> None:
        if not self.invoices_path.exists():
            with open(self.invoices_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=INVOICE_HEADERS)
                writer.writeheader()
        if not self.items_path.exists():
            with open(self.items_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=INVOICE_ITEMS_HEADERS)
                writer.writeheader()

    def _next_invoice_no(self) -> str:
        """Generate INV-YYYYMMDD-NNNN, auto-incrementing within the day."""
        now = _bd_now()
        date_str = now.strftime("%Y%m%d")
        prefix = f"INV-{date_str}-"

        max_seq = 0
        if self.invoices_path.exists():
            with open(self.invoices_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    inv = row.get("invoice_no", "")
                    if inv.startswith(prefix):
                        try:
                            seq = int(inv[len(prefix):])
                            max_seq = max(max_seq, seq)
                        except ValueError:
                            continue
        return f"{prefix}{max_seq + 1:04d}"

    def create_invoice(
        self,
        order_id: str,
        customer_name: str,
        phone: str,
        address: str,
        area: str,
        channel: str,
        line_items: List[Dict[str, Any]],
        subtotal: float,
        delivery_charge: float = 0.0,
        payment_method: str = "Cash on Delivery",
        notes: str = "",
    ) -> Dict[str, Any]:
        """Create a new invoice and append to both CSV files. Returns the invoice dict."""
        now = _bd_now()
        invoice_no = self._next_invoice_no()
        grand_total = subtotal + delivery_charge

        # Human-readable items summary
        items_parts = []
        for li in line_items:
            unit = f" {li.get('unit', '')}" if li.get("unit") else ""
            items_parts.append(f"{li['name']}{unit} x{li['qty']} = {li.get('line_total', 0):.0f} টাকা")
        items_summary = " | ".join(items_parts)

        invoice_row = {
            "invoice_no": invoice_no,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%I:%M %p"),
            "customer_name": customer_name,
            "phone": phone,
            "address": address,
            "area": area,
            "channel": channel,
            "items_summary": items_summary,
            "item_count": len(line_items),
            "subtotal": f"{subtotal:.2f}",
            "delivery_charge": f"{delivery_charge:.2f}",
            "grand_total": f"{grand_total:.2f}",
            "payment_method": payment_method,
            "status": "CONFIRMED",
            "notes": notes,
            "order_id": order_id,
        }

        # Append to invoices.csv
        with open(self.invoices_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=INVOICE_HEADERS)
            writer.writerow(invoice_row)

        # Append item rows to invoice_items.csv
        with open(self.items_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=INVOICE_ITEMS_HEADERS)
            for li in line_items:
                writer.writerow({
                    "invoice_no": invoice_no,
                    "product_id": li.get("product_id", ""),
                    "product_name": li.get("name", ""),
                    "qty": li.get("qty", 0),
                    "unit": li.get("unit", ""),
                    "unit_price": f"{li.get('unit_price', 0):.2f}",
                    "line_total": f"{li.get('line_total', 0):.2f}",
                })

        return invoice_row

    def get_invoice(self, invoice_no: str) -> Optional[Dict[str, Any]]:
        """Look up a single invoice by number."""
        if not self.invoices_path.exists():
            return None
        with open(self.invoices_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("invoice_no") == invoice_no:
                    return dict(row)
        return None

    def get_invoice_items(self, invoice_no: str) -> List[Dict[str, Any]]:
        """Get all line-items for an invoice."""
        items: List[Dict[str, Any]] = []
        if not self.items_path.exists():
            return items
        with open(self.items_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("invoice_no") == invoice_no:
                    items.append(dict(row))
        return items
