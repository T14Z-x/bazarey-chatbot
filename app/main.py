from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.bot.channels import SimulatorChannelAdapter
from app.bot.orchestrator import ChatOrchestrator
from app.config import Settings
from app.llm.groq_client import GroqClient
from app.llm.ollama_client import OllamaClient
from app.tools.order_sheet import OrderSheet
from app.tools.product_catalog import ProductCatalog
from app.tools.session_store import SessionStore
from app.tools.invoice_store import InvoiceStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class ChatRequest(BaseModel):
    channel_user_id: str
    text: str


class ChatResponse(BaseModel):
    reply: str


class ScrapeStartRequest(BaseModel):
    headless: bool = True
    limit: int = Field(default=0, ge=0)
    slowmo: int = Field(default=0, ge=0)
    output: str = ""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def dashboard_html() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Bazarey Local Console</title>
  <style>
    :root {
      --bg0: #fef9ef;
      --bg1: #f8e6c4;
      --card: #fffdf8;
      --ink: #202125;
      --muted: #6a6f76;
      --accent: #0b8d8c;
      --accent2: #eb5e28;
      --line: #e9dcc5;
      --ok: #107a42;
      --warn: #af5b00;
      --err: #b30f2f;
      --font-head: "Avenir Next", "Futura", "Trebuchet MS", sans-serif;
      --font-body: "Gill Sans", "Segoe UI", sans-serif;
      --font-mono: "Courier Prime", "Menlo", monospace;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: var(--font-body);
      color: var(--ink);
      background:
        radial-gradient(1200px 500px at 110% -10%, rgba(11,141,140,.2), transparent 55%),
        radial-gradient(900px 420px at -10% 110%, rgba(235,94,40,.16), transparent 52%),
        linear-gradient(135deg, var(--bg0), var(--bg1));
      display: grid;
      place-items: center;
      padding: 24px;
    }

    .shell {
      width: min(1160px, 100%);
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      animation: rise .28s ease-out;
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .card {
      background: linear-gradient(180deg, rgba(255,255,255,.94), rgba(255,253,248,.9));
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 8px 28px rgba(0,0,0,.08);
      padding: 18px;
      backdrop-filter: blur(4px);
    }

    h1 {
      margin: 0 0 14px;
      font-family: var(--font-head);
      letter-spacing: .2px;
      font-size: clamp(1.3rem, 2vw, 1.8rem);
      line-height: 1.15;
    }
    h2 {
      margin: 0 0 10px;
      font-family: var(--font-head);
      font-size: 1.05rem;
    }
    .muted { color: var(--muted); font-size: .93rem; }

    .grid2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    label { font-size: .84rem; color: var(--muted); display: block; margin-bottom: 5px; }
    input, textarea {
      width: 100%;
      border: 1px solid #dccfb5;
      border-radius: 10px;
      padding: 10px 11px;
      font: inherit;
      background: #fffefb;
      color: var(--ink);
    }
    textarea { resize: vertical; min-height: 72px; }

    .actions {
      margin-top: 10px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    button {
      border: 0;
      border-radius: 11px;
      padding: 10px 13px;
      font: 600 .9rem var(--font-head);
      cursor: pointer;
      transition: transform .08s ease, opacity .12s ease;
    }
    button:active { transform: translateY(1px); }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-secondary { background: #212121; color: #fff; }
    .btn-warm { background: var(--accent2); color: #fff; }

    .badge {
      display: inline-block;
      margin: 6px 0 10px;
      border-radius: 999px;
      padding: 6px 10px;
      font: 600 .8rem var(--font-mono);
      background: #fff5dc;
      border: 1px solid #f4d89b;
      color: var(--warn);
    }
    .badge.ok { background: #edf9f2; border-color: #cfe9da; color: var(--ok); }
    .badge.err { background: #fff1f4; border-color: #efc7d1; color: var(--err); }

    .chat-box {
      margin-top: 10px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fffefb;
      height: 360px;
      overflow: auto;
      padding: 10px;
    }
    .msg {
      margin: 0 0 8px;
      padding: 8px 10px;
      border-radius: 10px;
      width: fit-content;
      max-width: 92%;
      white-space: pre-wrap;
      line-height: 1.4;
    }
    .me { margin-left: auto; background: #e8f4fb; border: 1px solid #cce4f3; }
    .bot { background: #fff5df; border: 1px solid #f0dfb7; }

    pre {
      margin: 6px 0 0;
      border: 1px dashed #dbcbb0;
      border-radius: 8px;
      background: #fffdf8;
      padding: 10px;
      font: .8rem var(--font-mono);
      overflow-x: auto;
    }

    @media (max-width: 960px) {
      .shell { grid-template-columns: 1fr; }
      .chat-box { height: 300px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="card">
      <h1>Bazarey Scraper Console</h1>
      <p class="muted">Run catalog scrape into <code>data/products.xlsx</code> with live status.</p>
      <div class="grid2">
        <div>
          <label for="headless">Headless</label>
          <input id="headless" value="true" />
        </div>
        <div>
          <label for="limit">Limit (0 = all)</label>
          <input id="limit" type="number" value="0" min="0" />
        </div>
        <div>
          <label for="slowmo">Slowmo (ms)</label>
          <input id="slowmo" type="number" value="0" min="0" />
        </div>
        <div>
          <label for="output">Output path (optional)</label>
          <input id="output" value="" placeholder="data/products.xlsx" />
        </div>
      </div>
      <div class="actions">
        <button class="btn-primary" id="startScrapeBtn">Start Scrape</button>
        <button class="btn-secondary" id="refreshStatusBtn">Refresh Status</button>
      </div>
      <div id="scrapeBadge" class="badge">Idle</div>
      <pre id="scrapeStatus">No scrape started yet.</pre>
    </section>

    <section class="card">
      <h1>Chat Simulator</h1>
      <p class="muted">Local order assistant using Ollama + products.xlsx pricing.</p>
      <div class="grid2">
        <div>
          <label for="userId">Channel User ID</label>
          <input id="userId" value="u123" />
        </div>
        <div>
          <label for="quickMsg">Quick Prompt</label>
          <input id="quickMsg" value="miniket rice 5kg price?" />
        </div>
      </div>
      <div class="actions">
        <button class="btn-warm" id="sendQuickBtn">Send Quick Prompt</button>
        <button class="btn-secondary" id="clearChatBtn">Clear Chat</button>
      </div>
      <div class="chat-box" id="chatBox"></div>
      <label for="chatInput">Message</label>
      <textarea id="chatInput" placeholder="Type message..."></textarea>
      <div class="actions">
        <button class="btn-primary" id="sendBtn">Send</button>
      </div>
    </section>
  </div>

  <script>
    const scrapeStatusEl = document.getElementById("scrapeStatus");
    const scrapeBadgeEl = document.getElementById("scrapeBadge");
    const chatBoxEl = document.getElementById("chatBox");

    function setBadge(kind, text) {
      scrapeBadgeEl.className = "badge" + (kind ? " " + kind : "");
      scrapeBadgeEl.textContent = text;
    }

    function addMsg(kind, text) {
      const p = document.createElement("p");
      p.className = "msg " + kind;
      p.textContent = text;
      chatBoxEl.appendChild(p);
      chatBoxEl.scrollTop = chatBoxEl.scrollHeight;
    }

    async function refreshStatus() {
      const res = await fetch("/simulate/scrape/status");
      const data = await res.json();
      scrapeStatusEl.textContent = JSON.stringify(data, null, 2);
      if (data.running) {
        setBadge("", "Running");
      } else if (data.last_error) {
        setBadge("err", "Failed");
      } else if (data.last_result_total !== null) {
        setBadge("ok", "Done");
      } else {
        setBadge("", "Idle");
      }
    }

    async function startScrape() {
      const headless = (document.getElementById("headless").value || "true").toLowerCase() === "true";
      const limit = Number(document.getElementById("limit").value || 0);
      const slowmo = Number(document.getElementById("slowmo").value || 0);
      const output = document.getElementById("output").value || "";

      const res = await fetch("/simulate/scrape/start", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ headless, limit, slowmo, output })
      });
      const data = await res.json();
      scrapeStatusEl.textContent = JSON.stringify(data, null, 2);
      if (data.started) {
        setBadge("", "Running");
      }
      await refreshStatus();
    }

    async function sendMessage(text) {
      const channel_user_id = document.getElementById("userId").value.trim() || "u123";
      addMsg("me", text);
      const res = await fetch("/simulate/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({channel_user_id, text})
      });
      const data = await res.json();
      addMsg("bot", data.reply || "No reply");
    }

    document.getElementById("startScrapeBtn").addEventListener("click", startScrape);
    document.getElementById("refreshStatusBtn").addEventListener("click", refreshStatus);
    document.getElementById("sendBtn").addEventListener("click", async () => {
      const input = document.getElementById("chatInput");
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      await sendMessage(text);
    });
    document.getElementById("sendQuickBtn").addEventListener("click", async () => {
      const text = document.getElementById("quickMsg").value.trim();
      if (!text) return;
      await sendMessage(text);
    });
    document.getElementById("clearChatBtn").addEventListener("click", () => {
      chatBoxEl.textContent = "";
    });

    setInterval(refreshStatus, 3000);
    refreshStatus();
  </script>
</body>
</html>
    """.strip()


def create_app(settings: Settings | None = None, llm_client: Any | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    catalog = ProductCatalog(settings.products_xlsx)
    catalog.ensure_file()

    orders = OrderSheet(settings.orders_xlsx)
    orders.ensure_file()

    sessions = SessionStore(settings.sessions_db)

    invoice_store = InvoiceStore(settings.data_dir)

    if llm_client:
        llm = llm_client
    elif settings.llm_provider == "groq":
        llm = GroqClient(settings.groq_api_key, settings.groq_model)
    else:
        llm = OllamaClient(settings.ollama_host, settings.ollama_model)
    orchestrator = ChatOrchestrator(catalog, orders, sessions, llm, invoice_store=invoice_store)
    simulator_adapter = SimulatorChannelAdapter()

    app = FastAPI(title="Bazarey Local Chat Simulator")
    app.state.orchestrator = orchestrator
    app.state.scrape_status_lock = threading.Lock()
    app.state.scrape_status = {
        "running": False,
        "started_at": "",
        "finished_at": "",
        "last_error": "",
        "last_result_total": None,
        "last_output": str(settings.products_xlsx),
        "last_options": {},
    }

    def update_scrape_status(**kwargs: Any) -> None:
        with app.state.scrape_status_lock:
            app.state.scrape_status.update(kwargs)

    def get_scrape_status() -> dict[str, Any]:
        with app.state.scrape_status_lock:
            return dict(app.state.scrape_status)

    def resolve_output_path(path_input: str) -> Path:
        if not path_input:
            return settings.products_xlsx
        path = Path(path_input)
        if path.is_absolute():
            return path
        return settings.base_dir / path

    def run_scrape_job(options: ScrapeStartRequest) -> None:
        try:
            from app.scraping.scrape_products import run_scraper

            output_path = resolve_output_path(options.output)
            total = run_scraper(
                headless=options.headless,
                limit=options.limit,
                output=output_path,
                slowmo=options.slowmo,
                api_endpoints_path=settings.api_endpoints_json,
            )
            update_scrape_status(
                running=False,
                finished_at=utc_now_iso(),
                last_error="",
                last_result_total=total,
                last_output=str(output_path),
            )
        except Exception as exc:  # pragma: no cover
            update_scrape_status(
                running=False,
                finished_at=utc_now_iso(),
                last_error=str(exc),
            )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return dashboard_html()

    @app.post("/simulate/chat", response_model=ChatResponse)
    def simulate_chat(req: ChatRequest) -> ChatResponse:
        channel_user_id, text = simulator_adapter.normalize_inbound(req)
        reply = app.state.orchestrator.process_message(channel_user_id, text, channel=simulator_adapter.name)
        return ChatResponse(reply=reply)

    @app.post("/simulate/scrape/start")
    def simulate_scrape_start(req: ScrapeStartRequest) -> dict[str, Any]:
        current = get_scrape_status()
        if current["running"]:
            return {"started": False, "status": current, "message": "A scrape job is already running."}

        update_scrape_status(
            running=True,
            started_at=utc_now_iso(),
            finished_at="",
            last_error="",
            last_result_total=None,
            last_options=req.model_dump(),
        )
        thread = threading.Thread(target=run_scrape_job, args=(req,), daemon=True)
        thread.start()
        return {"started": True, "status": get_scrape_status()}

    @app.get("/simulate/scrape/status")
    def simulate_scrape_status() -> dict[str, Any]:
        return get_scrape_status()

    return app


app = create_app()
