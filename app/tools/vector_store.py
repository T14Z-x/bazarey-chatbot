from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import faiss
    from sentence_transformers import SentenceTransformer
    HAS_RAG_LIBS = True
except ImportError:
    HAS_RAG_LIBS = False
    logger.warning("faiss or sentence_transformers not installed. RAG features will be disabled.")


class VectorStore:
    def __init__(
        self, 
        index_path: Path, 
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"
    ) -> None:
        self.index_path = Path(index_path)
        self.index: Optional[faiss.Index] = None
        self.product_ids: List[str] = []
        self.model_name = model_name
        self._model: Optional[SentenceTransformer] = None

    @property
    def model(self) -> Optional[SentenceTransformer]:
        if not HAS_RAG_LIBS:
            return None
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def build_index(self, products: List[Dict[str, Any]]) -> bool:
        if not HAS_RAG_LIBS or self.model is None:
            return False

        try:
            logger.info(f"Building vector index for {len(products)} products...")
            # Combine name and category for better semantic matching
            texts = []
            valid_ids = []
            for p in products:
                name = (p.get("name") or "").strip()
                cat = (p.get("category") or "").strip()
                if not name:
                    continue
                texts.append(f"{name} [{cat}]")
                valid_ids.append(str(p.get("product_id")))

            if not texts:
                return False

            self.product_ids = valid_ids
            embeddings = self.model.encode(texts, show_progress_bar=False)
            
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatL2(dimension)
            self.index.add(embeddings.astype("float32"))
            
            self.save()
            return True
        except Exception as e:
            logger.error(f"Failed to build vector index: {e}")
            return False

    def save(self) -> None:
        if self.index is None or not HAS_RAG_LIBS:
            return
        
        try:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self.index, str(self.index_path))
            
            ids_path = self.index_path.with_suffix(".ids")
            with open(ids_path, "wb") as f:
                pickle.dump(self.product_ids, f)
            logger.info(f"Vector index saved to {self.index_path}")
        except Exception as e:
            logger.error(f"Failed to save vector index: {e}")

    def load(self) -> bool:
        if not HAS_RAG_LIBS:
            return False
            
        ids_path = self.index_path.with_suffix(".ids")
        if not self.index_path.exists() or not ids_path.exists():
            return False

        try:
            self.index = faiss.read_index(str(self.index_path))
            with open(ids_path, "rb") as f:
                self.product_ids = pickle.load(f)
            logger.info(f"Vector index loaded with {len(self.product_ids)} items.")
            return True
        except Exception as e:
            logger.error(f"Failed to load vector index: {e}")
            return False

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not HAS_RAG_LIBS or self.index is None or self.model is None:
            return []

        try:
            query_vector = self.model.encode([query])
            distances, indices = self.index.search(query_vector.astype("float32"), top_k)
            
            results = []
            for i, idx in enumerate(indices[0]):
                if idx != -1 and idx < len(self.product_ids):
                    # In L2 distance, smaller is better. Convert to a "score" for consistency.
                    # This is a heuristic conversion.
                    dist = float(distances[0][i])
                    score = max(0, 100 - (dist * 10)) 
                    results.append({
                        "product_id": self.product_ids[idx],
                        "score": round(score, 1)
                    })
            return results
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []
