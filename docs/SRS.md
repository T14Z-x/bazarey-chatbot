# Software Requirements Specification (SRS)

## 1. Purpose
This document defines requirements for the Bazarey Local Bot system:
1. Scrape Bazarey catalog data into `data/products.xlsx`.
2. Provide a local chat simulator API/UI that uses a local Ollama model, always reads catalog price/stock from XLSX, and logs orders to `data/orders.xlsx`.

## 2. Scope
The system runs on one local machine and excludes live Facebook API integration. The architecture must keep channel adapters abstract so Facebook can be added later.

## 3. Stakeholders
- Operator/Admin: runs scraper and API locally.
- Customer Support User: uses simulator UI/API to reply and create orders.
- Developer: maintains scraper, orchestration logic, and storage tools.

## 4. System Context
Inputs:
- Public catalog webpage: `https://www.bazarey.store/en/product`
- User chat messages from simulator endpoint/UI

Outputs:
- `data/products.xlsx`
- `data/orders.xlsx`
- `data/sessions.db`
- API responses from FastAPI endpoints

## 5. Functional Requirements

### 5.1 Scraper
- FR-SCR-001: System shall support Playwright-based scraping for JS-rendered catalog pages.
- FR-SCR-002: System shall observe network responses and attempt API discovery for product JSON payloads.
- FR-SCR-003: If API payloads/endpoints are available, system shall prefer API-derived extraction.
- FR-SCR-004: If API extraction is unavailable/insufficient, system shall parse rendered DOM and product detail pages.
- FR-SCR-005: Scraper output shall be written to XLSX with columns:
  - `product_id`, `name`, `url`, `category`, `price`, `regular_price`, `unit`, `stock_qty`, `is_active`, `image_url`, `updated_at`
- FR-SCR-006: If source product id is missing, system shall generate stable id from URL hash.
- FR-SCR-007: Scraper CLI shall support `--headless`, `--limit`, `--output`, and `--slowmo`.
- FR-SCR-008: Scraper shall deduplicate by `product_id` and fallback to URL.
- FR-SCR-009: Scraper shall perform incremental saves to reduce progress loss risk.
- FR-SCR-010: Discovered endpoints shall be stored at `data/api_endpoints.json`.

### 5.2 Catalog Tooling
- FR-CAT-001: System shall provide `search_products(query, limit)` with case-insensitive matching.
- FR-CAT-002: System shall use fuzzy matching (`rapidfuzz` when available; fallback token overlap otherwise).
- FR-CAT-003: System shall provide `get_product(product_id)`.
- FR-CAT-004: System shall provide `quote_items([{product_id, qty}])` and return line items + subtotal from XLSX prices only.

### 5.3 Order Logging
- FR-ORD-001: Orders shall be stored in `data/orders.xlsx` with columns:
  - `order_id`, `created_at`, `channel`, `channel_user_id`, `customer_name`, `phone`, `address`, `area`, `items`, `total`, `notes`, `status`, `last_message`
- FR-ORD-002: Order ids shall follow `BZ-000001` format and increment.
- FR-ORD-003: System shall keep one active row per `channel_user_id` unless status is `CONFIRMED` or `CANCELLED`.
- FR-ORD-004: Missing fields supplied later shall update the same active row.
- FR-ORD-005: XLSX writes shall use file lock protection.

### 5.4 Session Memory
- FR-SES-001: Session state shall persist in SQLite (`data/sessions.db`) keyed by `channel_user_id`.
- FR-SES-002: Session JSON shall retain at least `name`, `phone`, `address`, `area`, `pending_items`, `notes`, `last_product_candidates`.
- FR-SES-003: State shall update on each user message and bot action.

### 5.5 Bot Flow
- FR-BOT-001: Bot shall never output price/stock/total unless sourced from products tool results.
- FR-BOT-002: Required fields to finalize order are `items + phone + address`.
- FR-BOT-003: Bot shall validate Bangladesh phone format: exactly 11 digits, starts with `01`.
- FR-BOT-004: On valid items + phone + address, bot shall create/update order with status `NEW` and ask for confirmation (`YES`).
- FR-BOT-005: On `YES`, bot shall set status to `CONFIRMED` and return order id.

### 5.6 LLM Integration
- FR-LLM-001: LLM backend shall use local Ollama HTTP.
- FR-LLM-002: LLM output shall be strict JSON with one of:
  - `{"type":"tool_call","tool":"search_products|get_product|quote_items","args":{...}}`
  - `{"type":"final","message":"..."}`
- FR-LLM-003: Invalid JSON shall trigger correction retries up to 2 times, then fallback message.
- FR-LLM-004: System shall support configuration by `OLLAMA_HOST` and `OLLAMA_MODEL`.

### 5.7 API and UI
- FR-API-001: API shall expose `GET /health`.
- FR-API-002: API shall expose `POST /simulate/chat` with body `{channel_user_id, text}`.
- FR-API-003: API shall expose dashboard at `GET /` for scraper/chat operations.
- FR-API-004: API shall expose scrape control endpoints:
  - `POST /simulate/scrape/start`
  - `GET /simulate/scrape/status`

## 6. Non-Functional Requirements
- NFR-001: Runs locally on Python 3.11+ target runtime.
- NFR-002: No paid cloud LLM API dependency.
- NFR-003: Local-only storage in XLSX and SQLite.
- NFR-004: Basic console logging for incoming message, tool calls, and final reply.
- NFR-005: Recoverability via incremental scraper writes and dedup merge behavior.

## 7. Constraints
- Single-machine execution.
- Playwright browser installation is required before scraping.
- Product/API schema can change externally and may require extractor updates.

## 8. Out of Scope
- Facebook Messenger Graph API integration.
- Production-grade authentication/authorization.
- Multi-node concurrency and distributed storage.

## 9. Acceptance Criteria
- AC-001: Running scraper creates non-empty `data/products.xlsx` with required columns.
- AC-002: Price query returns value from XLSX (not fabricated).
- AC-003: Full chat order flow reaches `CONFIRMED` status and writes correct total/items into `orders.xlsx`.
- AC-004: `pytest` flow test passes.
