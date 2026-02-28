# Implementation Plan

## 1. Goal
Deliver a maintainable local system for catalog scraping, chat simulation, strict tool-based pricing, and order logging.

## 2. Current Status Summary
- Core backend implemented (`FastAPI`, scraper, tools, orchestrator, Ollama integration).
- Dashboard UI implemented for scraping and chat simulation.
- Automated flow test implemented and passing.

## 3. Phase Plan

### Phase 0: Environment Setup (Done)
- Define Python dependencies in `requirements.txt`.
- Install Playwright Chromium runtime.
- Prepare project structure under `app/`, `data/`, `tests/`.

### Phase 1: Data Layer (Done)
- Implement product catalog XLSX reader/search/quote tool.
- Implement order sheet upsert with file locking.
- Implement SQLite session store.

### Phase 2: Scraper (Done)
- Implement Playwright scraping with network response interception.
- Implement API payload extraction and DOM fallback parsing.
- Implement deduplication and incremental persistence.
- Add scraper CLI flags and endpoint discovery output.

### Phase 3: Bot Runtime (Done)
- Implement orchestrator for message handling and order progression.
- Implement strict JSON validation and correction retries.
- Integrate Ollama client and fallback handling.
- Enforce price/total lookups through catalog tools.

### Phase 4: API and Interface (Done)
- Expose `/health` and `/simulate/chat`.
- Expose dashboard at `/`.
- Expose scrape controls (`/simulate/scrape/start`, `/simulate/scrape/status`).
- Keep simulator channel adapter abstract for future FB adapter.

### Phase 5: Testing and Quality (Done)
- Add end-to-end simulator flow test in `tests/test_flow.py`.
- Validate order confirmation and total calculation.

## 4. Remaining Improvements (Recommended)

### Priority A (High)
1. Add scraper regression tests with recorded HTML/JSON fixtures.
2. Improve product extraction resilience for changed frontend selectors.
3. Add explicit normalization for Bangla numerals and quantity extraction.

### Priority B (Medium)
1. Add CSV export option and periodic snapshot backups of XLSX files.
2. Add order audit log table in SQLite for immutable event history.
3. Add simple admin endpoint to list recent orders and sessions.

### Priority C (Future)
1. Implement Facebook channel adapter (webhook + send API integration).
2. Add per-area delivery fee calculation and configurable tax/discount rules.
3. Add optional background scheduler for periodic scraping.

## 5. Verification Checklist
- `python3 -m pytest -q`
- `python3 -m app.scraping.scrape_products --headless true --limit 10`
- `python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- Open dashboard and verify:
  - scrape start/status updates
  - chat reply path
  - order `NEW` -> `CONFIRMED`

## 6. Risk Register
- R-001: Website structure/API changes can break extraction.
  - Mitigation: keep API discovery + DOM fallback; add fixture-based tests.
- R-002: XLSX corruption under concurrent writes.
  - Mitigation: `portalocker` lock files and single-machine operation.
- R-003: LLM output format drift.
  - Mitigation: strict JSON validator + retry correction prompt + safe fallback reply.

## 7. Definition of Done
- Non-empty `products.xlsx` generated.
- Chat flow can collect item/phone/address and confirm order.
- `orders.xlsx` reflects accurate totals from catalog tool.
- Test suite passes locally.
- README + SRS + implementation plan are present and up to date.
