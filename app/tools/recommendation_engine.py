from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


class RecommendationEngine:
    """Simple co-occurrence recommender built from confirmed invoice items."""

    def __init__(self, invoice_store: Any, catalog: Any) -> None:
        self.invoice_store = invoice_store
        self.catalog = catalog
        self._cache_key: Optional[Tuple[float, int]] = None
        self._item_counts: Counter[str] = Counter()
        self._pair_counts: Dict[str, Counter[str]] = {}

    def _items_path(self) -> Optional[Path]:
        path = getattr(self.invoice_store, "items_path", None)
        if not path:
            return None
        return Path(path)

    @staticmethod
    def _path_key(path: Path) -> Tuple[float, int]:
        st = path.stat()
        return (st.st_mtime, st.st_size)

    def _is_active_product(self, product_id: str) -> bool:
        p = self.catalog.get_product(product_id)
        if not p:
            return False
        return bool(p.get("is_active", True))

    def _reload_if_needed(self) -> None:
        path = self._items_path()
        if not path or not path.exists():
            self._cache_key = None
            self._item_counts = Counter()
            self._pair_counts = {}
            return

        key = self._path_key(path)
        if self._cache_key == key:
            return

        invoice_to_products: Dict[str, Set[str]] = defaultdict(set)
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                invoice_no = str(row.get("invoice_no") or "").strip()
                product_id = str(row.get("product_id") or "").strip()
                if not invoice_no or not product_id:
                    continue
                invoice_to_products[invoice_no].add(product_id)

        item_counts: Counter[str] = Counter()
        pair_counts: Dict[str, Counter[str]] = defaultdict(Counter)

        for product_ids in invoice_to_products.values():
            active_ids = sorted(pid for pid in product_ids if self._is_active_product(pid))
            if not active_ids:
                continue
            for pid in active_ids:
                item_counts[pid] += 1
            for i, a in enumerate(active_ids):
                for b in active_ids[i + 1 :]:
                    pair_counts[a][b] += 1
                    pair_counts[b][a] += 1

        self._cache_key = key
        self._item_counts = item_counts
        self._pair_counts = dict(pair_counts)

    def _build_result(self, product_id: str, score: float) -> Optional[Dict[str, Any]]:
        p = self.catalog.get_product(product_id)
        if not p or not p.get("is_active", True):
            return None
        return {
            "product_id": product_id,
            "name": str(p.get("name") or ""),
            "price": p.get("price"),
            "unit": str(p.get("unit") or ""),
            "score": float(score),
        }

    def recommend_for_product(
        self, product_id: str, limit: int = 3, exclude: Optional[Set[str]] = None
    ) -> List[Dict[str, Any]]:
        if not product_id:
            return []
        self._reload_if_needed()

        block = set(exclude or set())
        block.add(product_id)

        related = self._pair_counts.get(product_id, Counter())
        ranked = sorted(
            related.items(),
            key=lambda kv: (kv[1], self._item_counts.get(kv[0], 0)),
            reverse=True,
        )

        out: List[Dict[str, Any]] = []
        for pid, score in ranked:
            if pid in block:
                continue
            item = self._build_result(pid, float(score))
            if item:
                out.append(item)
            if len(out) >= limit:
                break
        return out

    def recommend_for_cart(self, product_ids: List[str], limit: int = 3) -> List[Dict[str, Any]]:
        self._reload_if_needed()
        seeds = [str(pid) for pid in product_ids if str(pid)]
        if not seeds:
            return self.popular_products(limit=limit)

        block = set(seeds)
        aggregate: Counter[str] = Counter()
        for pid in seeds:
            for candidate, score in self._pair_counts.get(pid, Counter()).items():
                if candidate in block:
                    continue
                aggregate[candidate] += score

        ranked = sorted(
            aggregate.items(),
            key=lambda kv: (kv[1], self._item_counts.get(kv[0], 0)),
            reverse=True,
        )

        out: List[Dict[str, Any]] = []
        for pid, score in ranked:
            item = self._build_result(pid, float(score))
            if item:
                out.append(item)
            if len(out) >= limit:
                break

        if out:
            return out
        return self.popular_products(limit=limit, exclude=block)

    def popular_products(self, limit: int = 3, exclude: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        self._reload_if_needed()
        block = set(exclude or set())
        ranked = sorted(self._item_counts.items(), key=lambda kv: kv[1], reverse=True)
        out: List[Dict[str, Any]] = []
        for pid, score in ranked:
            if pid in block:
                continue
            item = self._build_result(pid, float(score))
            if item:
                out.append(item)
            if len(out) >= limit:
                break
        return out

