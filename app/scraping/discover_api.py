from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List

PRODUCT_KEYS = {
    "product", "products", "name", "price", "slug", "stock", "category",
    "image", "title", "sku", "unit", "weight", "isActive", "is_active",
    "selling_price", "sale_price", "regular_price", "mrp",
}


def looks_like_product_endpoint(url: str) -> bool:
    u = url.lower()
    return any(k in u for k in ["product", "catalog", "item", "graphql", "search", "api"])


def _to_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            cleaned = re.sub(r"[^\d.,-]", "", value).replace(",", "")
            if not cleaned:
                return None
            return float(cleaned)
        return float(value)
    except Exception:
        return None


def _flatten_dicts(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _flatten_dicts(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _flatten_dicts(item)


def extract_products_from_payload(payload: Any, source_url: str = "") -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []
    for obj in _flatten_dicts(payload):
        keys = {str(k).lower() for k in obj.keys()}
        if len(keys & PRODUCT_KEYS) < 2:
            continue

        name = obj.get("name") or obj.get("title") or obj.get("product_name") or obj.get("productName")
        price = (
            _to_number(obj.get("price"))
            or _to_number(obj.get("sale_price"))
            or _to_number(obj.get("selling_price"))
            or _to_number(obj.get("salePrice"))
            or _to_number(obj.get("sellingPrice"))
            or _to_number(obj.get("amount"))
        )
        url = obj.get("url") or obj.get("link") or obj.get("permalink") or obj.get("slug") or source_url
        if not name or price is None:
            continue

        # Extract category: handle both string and dict (e.g. {"name": "Rice"})
        raw_category = obj.get("category") or obj.get("category_name") or obj.get("categoryName") or ""
        if isinstance(raw_category, dict):
            raw_category = raw_category.get("name") or raw_category.get("title") or ""

        # Extract product ID
        pid = str(obj.get("_id") or obj.get("id") or obj.get("product_id") or obj.get("productId") or "").strip()

        # Build proper product URL from slug or ID
        raw_url = str(url or "").strip()
        slug = obj.get("slug") or ""
        if slug and (not raw_url or "api/" in raw_url):
            raw_url = f"https://www.bazarey.store/en/product/{pid}" if pid else raw_url
        elif pid and (not raw_url or "api/" in raw_url):
            raw_url = f"https://www.bazarey.store/en/product/{pid}"

        # Build unit string: combine weight value and unit label
        unit_label = str(obj.get("unit") or obj.get("size") or "").strip()
        weight_val = obj.get("weight") or obj.get("netWeight") or obj.get("net_weight") or ""
        if weight_val and unit_label:
            unit_str = f"{weight_val} {unit_label}".strip()
        elif unit_label:
            unit_str = unit_label
        elif weight_val:
            unit_str = str(weight_val)
        else:
            unit_str = ""

        # Extract image URL, handling both string and list/dict formats
        raw_image = obj.get("image") or obj.get("image_url") or obj.get("imageUrl") or obj.get("thumbnail") or ""
        if isinstance(raw_image, list) and raw_image:
            raw_image = raw_image[0] if isinstance(raw_image[0], str) else (raw_image[0].get("url") or "")
        elif isinstance(raw_image, dict):
            raw_image = raw_image.get("url") or raw_image.get("src") or ""

        products.append(
            {
                "product_id": pid,
                "name": str(name).strip(),
                "url": raw_url,
                "category": str(raw_category).strip(),
                "price": price,
                "regular_price": _to_number(obj.get("regular_price") or obj.get("regularPrice") or obj.get("mrp")),
                "unit": unit_str,
                "stock_qty": obj.get("stock_qty") or obj.get("stock") or obj.get("quantity") or "",
                "is_active": bool(obj.get("is_active") or obj.get("isActive", True)),
                "image_url": str(raw_image or "").strip(),
            }
        )
    return products


def decode_response_json(text: str) -> Any:
    return json.loads(text)
