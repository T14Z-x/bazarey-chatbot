from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.config import Settings
from app.scraping.scrape_products import _format_runtime_hint
from app.tools.product_catalog import ProductCatalog


def _write_products_xlsx(path: Path, rows: list[list[object]]) -> None:
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
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_settings_defaults_to_tmp_data_dir_on_render(monkeypatch: object) -> None:
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("BAZAREY_DATA_DIR", raising=False)
    settings = Settings.from_env()
    assert str(settings.data_dir).startswith("/tmp/")


def test_catalog_uses_fallback_when_primary_is_empty(tmp_path: Path) -> None:
    primary = tmp_path / "primary_products.xlsx"
    fallback = tmp_path / "fallback_products.xlsx"

    _write_products_xlsx(primary, rows=[])
    _write_products_xlsx(
        fallback,
        rows=[
            [
                "p-1",
                "Render Fallback Product",
                "https://example.com/p1",
                "Test",
                99,
                "",
                "1pc",
                5,
                True,
                "",
                "2026-01-01",
            ]
        ],
    )

    catalog = ProductCatalog(primary, vector_index_path=None, fallback_path=fallback)
    matches = catalog.search_products("fallback product", limit=3, min_score=20)
    assert matches
    assert any(m.get("name") == "Render Fallback Product" for m in matches)


def test_playwright_missing_hint_is_actionable() -> None:
    exc = RuntimeError("Executable doesn't exist at /ms-playwright/chromium/chrome")
    hint = _format_runtime_hint(exc)
    assert "playwright install" in hint.lower()
    assert "chromium" in hint.lower()

