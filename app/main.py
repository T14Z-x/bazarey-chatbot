from __future__ import annotations

import logging
import threading
import time
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
from app.routers.messenger_webhook import create_messenger_router
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
  <title>Bazarey Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Hind+Siliguri:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: linear-gradient(130deg, #faf4e8 0%, #fff7ef 52%, #f1f6ef 100%);
      --card: rgba(255, 255, 255, 0.88);
      --border: rgba(64, 79, 67, 0.14);
      --text: #202724;
      --muted: #66706a;
      --brand: #1d8f7a;
      --brand-dark: #0f7462;
      --warm: #d2692f;
      --chat-me: #e4f6f1;
      --chat-bot: #fff2e4;
      --shadow: 0 10px 32px rgba(29, 44, 34, 0.12);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: "Manrope", "Hind Siliguri", sans-serif;
      color: var(--text);
      background: var(--bg);
      min-height: 100vh;
      padding: 18px;
    }

    .page {
      width: min(1380px, 100%);
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .hero {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 18px 20px;
      box-shadow: var(--shadow);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }

    .hero h1 {
      margin: 0 0 4px;
      font-size: clamp(1.2rem, 2vw, 1.6rem);
      font-weight: 800;
      letter-spacing: -0.02em;
    }

    .hero p {
      margin: 0;
      color: var(--muted);
      font-size: 0.92rem;
    }

    .server-pill {
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(29, 143, 122, 0.3);
      background: rgba(29, 143, 122, 0.12);
      font-size: 0.82rem;
      font-weight: 700;
      color: var(--brand-dark);
      white-space: nowrap;
    }

    .top-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      align-items: start;
    }

    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 18px;
      min-width: 0;
    }

    .card h2 {
      margin: 0 0 6px;
      font-size: 1.1rem;
      font-weight: 800;
      letter-spacing: -0.01em;
    }

    .card .sub {
      margin: 0 0 14px;
      font-size: 0.88rem;
      color: var(--muted);
    }

    .form-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 10px;
    }

    .field {
      display: flex;
      flex-direction: column;
      gap: 5px;
    }

    .field label {
      font-size: 0.79rem;
      color: var(--muted);
      font-weight: 700;
    }

    input, textarea, select {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      font: inherit;
      color: var(--text);
      background: rgba(255, 255, 255, 0.96);
    }

    input:focus, textarea:focus, select:focus {
      outline: none;
      border-color: var(--brand);
      box-shadow: 0 0 0 3px rgba(29, 143, 122, 0.17);
    }

    .btn-row {
      display: flex;
      gap: 8px;
      margin: 8px 0 12px;
      flex-wrap: wrap;
    }

    button {
      border: 0;
      border-radius: 10px;
      padding: 10px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform 0.15s ease, opacity 0.15s ease;
    }

    button:active { transform: scale(0.98); }

    .btn-main {
      background: var(--brand);
      color: #fff;
    }

    .btn-main:hover { background: var(--brand-dark); }

    .btn-alt {
      background: rgba(60, 80, 73, 0.12);
      color: var(--text);
    }

    .btn-alt:hover { opacity: 0.88; }

    .status-line {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
      font-size: 0.85rem;
      flex-wrap: wrap;
    }

    .badge {
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 0.76rem;
      font-weight: 800;
      letter-spacing: 0.02em;
      background: rgba(67, 82, 75, 0.12);
      color: #3b4842;
    }

    .badge.running {
      background: rgba(29, 143, 122, 0.16);
      color: var(--brand-dark);
    }

    .badge.done {
      background: rgba(18, 122, 78, 0.16);
      color: #106a46;
    }

    .badge.error {
      background: rgba(180, 34, 34, 0.14);
      color: #952323;
    }

    .progress-wrap {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 10px;
      background: rgba(255, 255, 255, 0.9);
      margin-bottom: 10px;
    }

    .track {
      width: 100%;
      height: 10px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(47, 58, 53, 0.1);
    }

    .fill {
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--brand) 0%, var(--warm) 100%);
      transition: width 0.35s ease;
    }

    .progress-meta {
      margin-top: 6px;
      display: flex;
      justify-content: space-between;
      gap: 8px;
      color: var(--muted);
      font-size: 0.78rem;
    }

    .loader {
      margin-bottom: 10px;
      border: 1px solid rgba(29, 143, 122, 0.25);
      border-radius: 10px;
      background: rgba(29, 143, 122, 0.09);
      padding: 8px 10px;
      font-size: 0.82rem;
      display: none;
      align-items: center;
      gap: 8px;
    }

    .loader.active {
      display: flex;
    }

    .loader-dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--brand);
      animation: pulse 0.9s infinite ease;
    }

    @keyframes pulse {
      0% { transform: scale(0.85); opacity: 0.6; }
      50% { transform: scale(1.2); opacity: 1; }
      100% { transform: scale(0.85); opacity: 0.6; }
    }

    .live-list {
      border: 1px solid var(--border);
      border-radius: 12px;
      min-height: 92px;
      max-height: 210px;
      overflow-y: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 7px;
      background: rgba(255, 255, 255, 0.9);
    }

    .live-item {
      border: 1px solid var(--border);
      border-radius: 9px;
      padding: 8px;
      background: rgba(29, 143, 122, 0.07);
    }

    .live-name {
      font-size: 0.83rem;
      font-weight: 700;
      line-height: 1.3;
    }

    .live-meta {
      font-size: 0.75rem;
      color: var(--muted);
      margin-top: 3px;
    }

    .chat-box {
      border: 1px solid var(--border);
      border-radius: 12px;
      height: 360px;
      overflow-y: auto;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 10px;
      background: rgba(255, 255, 255, 0.92);
    }

    .msg {
      max-width: 88%;
      border-radius: 12px;
      padding: 9px 11px;
      font-size: 0.88rem;
      line-height: 1.45;
      border: 1px solid rgba(0, 0, 0, 0.06);
      white-space: pre-wrap;
    }

    .msg.me {
      align-self: flex-end;
      background: var(--chat-me);
      border-bottom-right-radius: 4px;
    }

    .msg.bot {
      align-self: flex-start;
      background: var(--chat-bot);
      border-bottom-left-radius: 4px;
    }

    .catalog-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }

    .catalog-title-wrap h2 {
      margin: 0 0 3px;
    }

    .catalog-title-wrap p {
      margin: 0;
      color: var(--muted);
      font-size: 0.85rem;
    }

    .catalog-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 10px;
    }

    .cat-card {
      border: 1px solid var(--border);
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.95);
      padding: 10px;
    }

    .cat-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }

    .cat-name {
      margin: 0;
      font-size: 0.9rem;
      font-weight: 800;
      line-height: 1.2;
    }

    .cat-count {
      font-size: 0.74rem;
      color: var(--muted);
      font-weight: 700;
    }

    .prod-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-height: 220px;
      overflow-y: auto;
    }

    .prod {
      border: 1px solid rgba(90, 96, 93, 0.18);
      border-radius: 8px;
      padding: 6px 8px;
      background: rgba(249, 249, 249, 0.95);
    }

    .prod-name {
      font-size: 0.78rem;
      font-weight: 700;
      line-height: 1.25;
      margin-bottom: 2px;
    }

    .prod-meta {
      font-size: 0.72rem;
      color: var(--muted);
    }

    .empty {
      color: var(--muted);
      font-size: 0.84rem;
      padding: 8px;
      border: 1px dashed var(--border);
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.8);
      text-align: center;
    }

    @media (max-width: 1080px) {
      .top-grid {
        grid-template-columns: 1fr;
      }
      .chat-box {
        height: 300px;
      }
    }
  </style>
</head>
<body>
  <div class="page">
    <header class="hero">
      <div>
        <h1>Bazarey Operations Dashboard</h1>
        <p>Scrape products, chat with users, and view category-wise catalog cards.</p>
      </div>
      <div class="server-pill">Local API: 127.0.0.1:8000</div>
    </header>

    <section class="top-grid">
      <article class="card">
        <h2>Scraper</h2>
        <p class="sub">Start scraping and watch live progress with ETA and extracted products.</p>

        <div class="form-grid">
          <div class="field">
            <label for="headless">Headless</label>
            <select id="headless">
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
          <div class="field">
            <label for="limit">Limit (0 = all)</label>
            <input id="limit" type="number" value="0" min="0" />
          </div>
          <div class="field">
            <label for="slowmo">Slowmo (ms)</label>
            <input id="slowmo" type="number" value="0" min="0" />
          </div>
          <div class="field">
            <label for="output">Output path</label>
            <input id="output" placeholder="data/products.xlsx" />
          </div>
        </div>

        <div class="btn-row">
          <button class="btn-main" id="startScrapeBtn">Start Scrape</button>
          <button class="btn-alt" id="refreshStatusBtn">Refresh Status</button>
        </div>

        <div class="status-line">
          <div class="badge" id="scrapeBadge">IDLE</div>
          <div id="phaseText">Waiting to start.</div>
        </div>

        <div class="loader" id="scrapeLoader">
          <div class="loader-dot"></div>
          <div id="loaderMessage">Scraping is running...</div>
        </div>

        <div class="progress-wrap">
          <div class="track"><div class="fill" id="progressFill"></div></div>
          <div class="progress-meta">
            <span id="percentText">0%</span>
            <span id="etaText">ETA --</span>
            <span id="countText">0 products</span>
          </div>
        </div>

        <div class="live-list" id="liveProducts">
          <div class="empty">Latest scraped products will appear here.</div>
        </div>
      </article>

      <article class="card">
        <h2>Chat Simulator</h2>
        <p class="sub">Chat is always active here, independent from the scraper panel.</p>

        <div class="field" style="margin-bottom:10px;">
          <label for="userId">Channel User ID</label>
          <input id="userId" value="u123" />
        </div>

        <div class="chat-box" id="chatBox"></div>

        <div class="field">
          <textarea id="chatInput" placeholder="Type a message..."></textarea>
        </div>

        <div class="btn-row">
          <button class="btn-main" id="sendBtn" style="flex:1;">Send Message</button>
          <button class="btn-alt" id="clearChatBtn">Clear</button>
        </div>
      </article>
    </section>

    <section class="card">
      <div class="catalog-head">
        <div class="catalog-title-wrap">
          <h2>Catalog by Category</h2>
          <p>Products are grouped in separate boxes by category.</p>
        </div>
        <div class="btn-row" style="margin:0;">
          <button class="btn-alt" id="refreshCatalogBtn">Refresh Catalog</button>
        </div>
      </div>
      <div class="catalog-grid" id="catalogGrid">
        <div class="empty">Loading category-wise catalog...</div>
      </div>
    </section>
  </div>

  <script>
    const scrapeBadgeEl = document.getElementById("scrapeBadge");
    const phaseTextEl = document.getElementById("phaseText");
    const loaderEl = document.getElementById("scrapeLoader");
    const loaderMessageEl = document.getElementById("loaderMessage");
    const progressFillEl = document.getElementById("progressFill");
    const percentTextEl = document.getElementById("percentText");
    const etaTextEl = document.getElementById("etaText");
    const countTextEl = document.getElementById("countText");
    const liveProductsEl = document.getElementById("liveProducts");
    const chatBoxEl = document.getElementById("chatBox");
    const catalogGridEl = document.getElementById("catalogGrid");

    let lastScrapeRunning = false;

    function fmtDuration(secRaw) {
      const sec = Math.max(0, Math.round(Number(secRaw || 0)));
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      return m > 0 ? `${m}m ${s}s` : `${s}s`;
    }

    function fmtProductPrice(priceRaw, unitRaw) {
      const price = Number(priceRaw);
      const hasPrice = Number.isFinite(price);
      const unit = String(unitRaw || "").trim();
      if (hasPrice && unit) return `${Math.round(price)} টাকা প্রতি ${unit}`;
      if (hasPrice) return `${Math.round(price)} টাকা`;
      if (unit) return unit;
      return "Price unavailable";
    }

    function setBadge(kind) {
      scrapeBadgeEl.className = "badge";
      if (kind === "running") {
        scrapeBadgeEl.classList.add("running");
        scrapeBadgeEl.textContent = "RUNNING";
        return;
      }
      if (kind === "done") {
        scrapeBadgeEl.classList.add("done");
        scrapeBadgeEl.textContent = "DONE";
        return;
      }
      if (kind === "error") {
        scrapeBadgeEl.classList.add("error");
        scrapeBadgeEl.textContent = "FAILED";
        return;
      }
      scrapeBadgeEl.textContent = "IDLE";
    }

    function renderLiveProducts(items) {
      const rows = Array.isArray(items) ? items.slice().reverse() : [];
      if (!rows.length) {
        liveProductsEl.innerHTML = '<div class="empty">Latest scraped products will appear here.</div>';
        return;
      }
      liveProductsEl.textContent = "";
      for (const item of rows) {
        const card = document.createElement("div");
        card.className = "live-item";
        const name = document.createElement("div");
        name.className = "live-name";
        name.textContent = item.name || "Unnamed product";
        const meta = document.createElement("div");
        meta.className = "live-meta";
        meta.textContent = fmtProductPrice(item.price, item.unit);
        card.appendChild(name);
        card.appendChild(meta);
        liveProductsEl.appendChild(card);
      }
    }

    function renderScrapeStatus(data) {
      const running = Boolean(data.running);
      const percent = Math.max(0, Math.min(100, Number(data.progress_percent || 0)));
      const phase = data.phase_label || data.current_message || "Waiting to start.";
      const processed = Number(data.processed_products || 0);

      if (running) {
        setBadge("running");
      } else if (data.last_error) {
        setBadge("error");
      } else if (data.last_result_total !== null) {
        setBadge("done");
      } else {
        setBadge("idle");
      }

      phaseTextEl.textContent = phase;
      loaderMessageEl.textContent = data.current_message || phase;
      loaderEl.classList.toggle("active", running);
      progressFillEl.style.width = `${percent}%`;
      percentTextEl.textContent = `${percent.toFixed(1)}%`;
      countTextEl.textContent = `${processed} products`;

      if (running) {
        etaTextEl.textContent = data.eta_seconds == null ? "ETA calculating..." : `ETA ${fmtDuration(data.eta_seconds)}`;
      } else if (Number(data.elapsed_seconds || 0) > 0 && data.last_result_total !== null) {
        etaTextEl.textContent = `Done in ${fmtDuration(data.elapsed_seconds)}`;
      } else {
        etaTextEl.textContent = "ETA --";
      }

      renderLiveProducts(data.recent_products || []);

      if (lastScrapeRunning && !running) {
        loadCatalog();
      }
      lastScrapeRunning = running;
    }

    function addMsg(kind, text) {
      const div = document.createElement("div");
      div.className = `msg ${kind}`;
      div.textContent = text;
      chatBoxEl.appendChild(div);
      chatBoxEl.scrollTop = chatBoxEl.scrollHeight;
    }

    async function sendMessage() {
      const input = document.getElementById("chatInput");
      const text = input.value.trim();
      if (!text) return;
      const channel_user_id = document.getElementById("userId").value.trim() || "u123";
      input.value = "";
      addMsg("me", text);

      try {
        const res = await fetch("/simulate/chat", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ channel_user_id, text })
        });
        const data = await res.json();
        addMsg("bot", data.reply || "No reply from bot");
      } catch {
        addMsg("bot", "Failed to connect to server.");
      }
    }

    async function refreshStatus() {
      try {
        const res = await fetch("/simulate/scrape/status");
        const data = await res.json();
        renderScrapeStatus(data);
      } catch {
        phaseTextEl.textContent = "Unable to fetch scrape status.";
      }
    }

    async function startScrape() {
      const headless = document.getElementById("headless").value === "true";
      const limit = Number(document.getElementById("limit").value || 0);
      const slowmo = Number(document.getElementById("slowmo").value || 0);
      const output = document.getElementById("output").value || "";

      try {
        const res = await fetch("/simulate/scrape/start", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ headless, limit, slowmo, output })
        });
        const data = await res.json();
        if (data.status) renderScrapeStatus(data.status);
      } catch {
        phaseTextEl.textContent = "Failed to start scraper.";
      }
    }

    function renderCatalog(data) {
      const categories = Array.isArray(data.categories) ? data.categories : [];
      if (!categories.length) {
        catalogGridEl.innerHTML = '<div class="empty">No products found. Run scraper first.</div>';
        return;
      }
      catalogGridEl.textContent = "";
      for (const cat of categories) {
        const card = document.createElement("div");
        card.className = "cat-card";

        const top = document.createElement("div");
        top.className = "cat-top";

        const name = document.createElement("h3");
        name.className = "cat-name";
        name.textContent = cat.category || "Uncategorized";

        const count = document.createElement("span");
        count.className = "cat-count";
        count.textContent = `${Number(cat.count || 0)} items`;

        top.appendChild(name);
        top.appendChild(count);
        card.appendChild(top);

        const list = document.createElement("div");
        list.className = "prod-list";
        const products = Array.isArray(cat.products) ? cat.products : [];
        if (!products.length) {
          const empty = document.createElement("div");
          empty.className = "empty";
          empty.textContent = "No products in this category.";
          list.appendChild(empty);
        } else {
          for (const p of products) {
            const row = document.createElement("div");
            row.className = "prod";
            const pname = document.createElement("div");
            pname.className = "prod-name";
            pname.textContent = p.name || "Unnamed product";
            const meta = document.createElement("div");
            meta.className = "prod-meta";
            meta.textContent = fmtProductPrice(p.price, p.unit);
            row.appendChild(pname);
            row.appendChild(meta);
            list.appendChild(row);
          }
        }

        card.appendChild(list);
        catalogGridEl.appendChild(card);
      }
    }

    async function loadCatalog() {
      try {
        const res = await fetch("/simulate/catalog?limit_categories=18&per_category=10");
        const data = await res.json();
        renderCatalog(data);
      } catch {
        catalogGridEl.innerHTML = '<div class="empty">Failed to load catalog view.</div>';
      }
    }

    document.getElementById("startScrapeBtn").addEventListener("click", startScrape);
    document.getElementById("refreshStatusBtn").addEventListener("click", refreshStatus);
    document.getElementById("refreshCatalogBtn").addEventListener("click", loadCatalog);
    document.getElementById("sendBtn").addEventListener("click", sendMessage);
    document.getElementById("clearChatBtn").addEventListener("click", () => {
      chatBoxEl.textContent = "";
    });
    document.getElementById("chatInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    refreshStatus();
    loadCatalog();
    setInterval(refreshStatus, 1200);
  </script>
</body>
</html>
    """.strip()



def create_app(settings: Settings | None = None, llm_client: Any | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    catalog = ProductCatalog(settings.products_xlsx, vector_index_path=settings.vector_index_path)
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
    app.state.settings = settings
    app.state.orchestrator = orchestrator
    app.include_router(create_messenger_router(settings))
    app.state.scrape_status_lock = threading.Lock()
    app.state.scrape_status = {
        "running": False,
        "started_at": "",
        "finished_at": "",
        "last_error": "",
        "last_result_total": None,
        "last_output": str(settings.products_xlsx),
        "last_options": {},
        "phase": "",
        "phase_label": "",
        "phase_current": 0,
        "phase_total": 0,
        "progress_percent": 0.0,
        "elapsed_seconds": 0.0,
        "eta_seconds": None,
        "current_message": "",
        "processed_products": 0,
        "total_candidates": 0,
        "collected_dom": 0,
        "discovered_api": 0,
        "endpoint_count": 0,
        "recent_products": [],
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
        started_monotonic = time.monotonic()
        current_phase = ""
        phase_started_monotonic = started_monotonic

        def on_scrape_progress(event: dict[str, Any]) -> None:
            nonlocal current_phase, phase_started_monotonic

            now_monotonic = time.monotonic()
            phase = str(event.get("phase") or "")
            if phase and phase != current_phase:
                current_phase = phase
                phase_started_monotonic = now_monotonic

            try:
                phase_current = int(event.get("phase_current") or 0)
            except Exception:
                phase_current = 0
            try:
                phase_total = int(event.get("phase_total") or 0)
            except Exception:
                phase_total = 0

            progress_percent = 0.0
            if phase_total > 0:
                progress_percent = round((phase_current / phase_total) * 100.0, 1)

            eta_seconds: float | None = None
            if phase_total > 0 and phase_current > 0:
                elapsed_in_phase = now_monotonic - phase_started_monotonic
                remaining = max(0, phase_total - phase_current)
                eta_seconds = round((elapsed_in_phase / phase_current) * remaining, 1)

            recent_product = event.get("product")
            clean_product: dict[str, Any] | None = None
            if isinstance(recent_product, dict):
                name = str(recent_product.get("name") or "").strip()
                if name:
                    clean_product = {
                        "name": name,
                        "unit": str(recent_product.get("unit") or "").strip(),
                        "price": recent_product.get("price"),
                    }

            with app.state.scrape_status_lock:
                status = app.state.scrape_status
                if phase:
                    status["phase"] = phase
                if "phase_label" in event:
                    status["phase_label"] = event["phase_label"]
                if "current_message" in event:
                    status["current_message"] = event["current_message"]
                if "processed_products" in event:
                    status["processed_products"] = event["processed_products"]
                if "total_candidates" in event:
                    status["total_candidates"] = event["total_candidates"]
                if "collected_dom" in event:
                    status["collected_dom"] = event["collected_dom"]
                if "discovered_api" in event:
                    status["discovered_api"] = event["discovered_api"]
                if "endpoint_count" in event:
                    status["endpoint_count"] = event["endpoint_count"]

                status["phase_current"] = phase_current
                status["phase_total"] = phase_total
                status["progress_percent"] = progress_percent
                status["elapsed_seconds"] = round(now_monotonic - started_monotonic, 1)
                status["eta_seconds"] = eta_seconds

                if clean_product:
                    recent = list(status.get("recent_products") or [])
                    recent.append(clean_product)
                    status["recent_products"] = recent[-20:]

        try:
            from app.scraping.scrape_products import run_scraper

            output_path = resolve_output_path(options.output)
            total = run_scraper(
                headless=options.headless,
                limit=options.limit,
                output=output_path,
                slowmo=options.slowmo,
                api_endpoints_path=settings.api_endpoints_json,
                progress_callback=on_scrape_progress,
            )
            update_scrape_status(
                running=False,
                finished_at=utc_now_iso(),
                last_error="",
                last_result_total=total,
                last_output=str(output_path),
                phase="done",
                phase_label="Completed",
                phase_current=1,
                phase_total=1,
                progress_percent=100.0,
                elapsed_seconds=round(time.monotonic() - started_monotonic, 1),
                eta_seconds=0.0,
                current_message=f"Scrape finished. Saved {total} products.",
                processed_products=total,
            )
        except Exception as exc:  # pragma: no cover
            update_scrape_status(
                running=False,
                finished_at=utc_now_iso(),
                last_error=str(exc),
                phase="failed",
                phase_label="Failed",
                phase_current=0,
                phase_total=0,
                progress_percent=0.0,
                elapsed_seconds=round(time.monotonic() - started_monotonic, 1),
                eta_seconds=None,
                current_message=str(exc),
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
            phase="init",
            phase_label="Initializing scraper",
            phase_current=0,
            phase_total=1,
            progress_percent=0.0,
            elapsed_seconds=0.0,
            eta_seconds=None,
            current_message="Starting scrape job...",
            processed_products=0,
            total_candidates=0,
            collected_dom=0,
            discovered_api=0,
            endpoint_count=0,
            recent_products=[],
        )
        thread = threading.Thread(target=run_scrape_job, args=(req,), daemon=True)
        thread.start()
        return {"started": True, "status": get_scrape_status()}

    @app.get("/simulate/scrape/status")
    def simulate_scrape_status() -> dict[str, Any]:
        return get_scrape_status()

    @app.get("/simulate/catalog")
    def simulate_catalog(limit_categories: int = 18, per_category: int = 10) -> dict[str, Any]:
        safe_limit_categories = max(1, min(limit_categories, 60))
        safe_per_category = max(1, min(per_category, 30))

        categories = catalog.list_categories()
        selected = categories[:safe_limit_categories]

        items: list[dict[str, Any]] = []
        for cat in selected:
            category_name = str(cat.get("category") or "").strip()
            if not category_name:
                continue

            result = catalog.browse_category(category_name, limit=safe_per_category)
            products = result.get("products") or []
            slim_products = [
                {
                    "name": str(p.get("name") or "").strip(),
                    "price": p.get("price"),
                    "unit": str(p.get("unit") or "").strip(),
                }
                for p in products
            ]

            items.append(
                {
                    "category": category_name,
                    "count": int(cat.get("count") or 0),
                    "products": slim_products,
                }
            )

        return {"categories": items, "total_categories": len(categories)}

    return app


app = create_app()
