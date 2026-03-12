from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass  # python-dotenv not installed; rely on real env vars


@dataclass
class Settings:
    base_dir: Path
    data_dir: Path
    products_xlsx: Path
    orders_xlsx: Path
    sessions_db: Path
    api_endpoints_json: Path
    vector_index_path: Path
    # LLM provider selection
    llm_provider: str  # "groq" or "ollama"
    # Groq (cloud)
    groq_api_key: str
    groq_model: str
    # Ollama (local)
    ollama_host: str
    ollama_model: str
    # Facebook Messenger integration
    fb_verify_token: str = ""
    fb_page_access_token: str = ""
    fb_app_secret: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(os.getenv("BAZAREY_BASE_DIR", Path(__file__).resolve().parents[1]))
        data_dir = Path(os.getenv("BAZAREY_DATA_DIR", base_dir / "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            base_dir=base_dir,
            data_dir=data_dir,
            products_xlsx=Path(os.getenv("BAZAREY_PRODUCTS_XLSX", data_dir / "products.xlsx")),
            orders_xlsx=Path(os.getenv("BAZAREY_ORDERS_XLSX", data_dir / "orders.xlsx")),
            sessions_db=Path(os.getenv("BAZAREY_SESSIONS_DB", data_dir / "sessions.db")),
            api_endpoints_json=Path(os.getenv("BAZAREY_API_ENDPOINTS_JSON", data_dir / "api_endpoints.json")),
            vector_index_path=Path(os.getenv("BAZAREY_VECTOR_INDEX", data_dir / "products.index")),
            llm_provider=os.getenv("LLM_PROVIDER", "ollama").lower(),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
            fb_verify_token=os.getenv("FB_VERIFY_TOKEN", ""),
            fb_page_access_token=os.getenv("FB_PAGE_ACCESS_TOKEN", ""),
            fb_app_secret=os.getenv("FB_APP_SECRET", ""),
        )
