# Bazarey Bot

A local-first Python system for:
1. Scraping the Bazarey product catalog into `data/products.xlsx`
2. Running a FastAPI chat simulator that uses catalog pricing to build and confirm grocery orders

It includes a web dashboard, local session memory, order logging, and invoice CSV export.

## What It Does

- Scrapes `https://www.bazarey.store/en/product` using Playwright
- Detects JSON product endpoints when available, with DOM/detail-page fallback
- Stores product data in Excel (`products.xlsx`) with dedupe and incremental updates
- Simulates Bangla/Banglish/English ordering chat flow
- Keeps per-user session state in SQLite
- Writes confirmed orders to `orders.xlsx`
- Generates invoices in `invoices.csv` and `invoice_items.csv`
- Supports both local Ollama and cloud Groq as LLM backends

## Tech Stack

- Python 3.11+
- FastAPI + Uvicorn
- Playwright (Chromium)
- openpyxl + portalocker
- sqlite3
- httpx
- pydantic
- rapidfuzz

## Project Structure

```text
bazarey-bot/
├── app/
│   ├── bot/          # chat orchestration, normalizer, validators, channel adapters
│   ├── llm/          # Ollama/Groq clients + prompts
│   ├── scraping/     # catalog scraper + API discovery helpers
│   ├── tools/        # product catalog, order sheet, session, invoice store
│   ├── config.py
│   └── main.py       # FastAPI app + dashboard + simulation endpoints
├── data/             # local runtime data files
├── docs/             # SRS and implementation notes
├── tests/
├── requirements.txt
└── README.md
```

## Quick Start

```bash
cd bazarey-bot
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Configuration

Create a `.env` file in the project root:

```env
# LLM provider: ollama or groq
LLM_PROVIDER=ollama

# Ollama (local)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# Groq (cloud, only if LLM_PROVIDER=groq)
GROQ_API_KEY=
GROQ_MODEL=llama-3.1-8b-instant

# Optional paths
BAZAREY_BASE_DIR=.
BAZAREY_DATA_DIR=./data
BAZAREY_PRODUCTS_XLSX=./data/products.xlsx
BAZAREY_FALLBACK_PRODUCTS_XLSX=
BAZAREY_ORDERS_XLSX=./data/orders.xlsx
BAZAREY_SESSIONS_DB=./data/sessions.db
BAZAREY_API_ENDPOINTS_JSON=./data/api_endpoints.json
```

## Run the Scraper

```bash
python -m app.scraping.scrape_products --headless true
```

Useful flags:

- `--limit 100` (0 = no limit)
- `--output data/products.xlsx`
- `--slowmo 100`

## Run the API

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Render Deployment Notes

- Keep start command:
  - `uvicorn app.main:app --host 0.0.0.0 --port 10000`
- Build command must install Playwright Chromium:
  - `pip install -r requirements.txt && python -m playwright install --with-deps chromium || python -m playwright install chromium`
- Set writable runtime data directory:
  - `BAZAREY_DATA_DIR=/tmp/bazarey-data`
- Optional catalog fallback if scrape fails:
  - `BAZAREY_FALLBACK_PRODUCTS_XLSX=/path/to/last-good-products.xlsx`
- A sample `render.yaml` is included in the repo root.

Open dashboard:

- `http://127.0.0.1:8000/`

## API Endpoints

- `GET /health`
- `GET /` (dashboard UI)
- `POST /simulate/chat`
- `POST /simulate/scrape/start`
- `GET /simulate/scrape/status`

Example chat request:

```bash
curl -X POST http://127.0.0.1:8000/simulate/chat \
  -H "Content-Type: application/json" \
  -d '{"channel_user_id":"u123","text":"miniket rice 5kg price?"}'
```

Example scrape start request:

```bash
curl -X POST http://127.0.0.1:8000/simulate/scrape/start \
  -H "Content-Type: application/json" \
  -d '{"headless":true,"limit":0,"slowmo":0,"output":""}'
```

## Data Files

- `data/products.xlsx`: catalog source of truth for product lookup and pricing
- `data/orders.xlsx`: confirmed order log
- `data/sessions.db`: per-user chat/session state
- `data/api_endpoints.json`: discovered product API endpoints from scraping
- `data/invoices.csv`: invoice-level records
- `data/invoice_items.csv`: line-item invoice records

## Testing

Run from the project root:

```bash
python -m pytest -q
```

## Troubleshooting

- Playwright browser missing:
  - `python -m playwright install chromium`
- Render scraper fails before collecting products:
  - Ensure your Render build command includes Playwright install.
  - Ensure `BAZAREY_DATA_DIR` points to a writable path.
- Empty product search results:
  - Run scraper first and verify `data/products.xlsx` has rows
- Ollama connection/model issues:
  - Start Ollama and confirm model availability (`ollama list`)
- Port already in use:
  - Change `--port` or stop the process using `127.0.0.1:8000`

## Docs

- SRS: `docs/SRS.md`
- Implementation plan: `docs/IMPLEMENTATION_PLAN.md`

## Notes

- This project is local-first and currently focused on simulator flow (no live Facebook Messenger integration yet).
- Add a `LICENSE` file before publishing publicly if you want open-source reuse terms to be clear.
