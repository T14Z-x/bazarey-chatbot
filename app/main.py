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
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Bazarey Local Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Hind+Siliguri:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root[data-theme="light"] {
      --bg-gradient: linear-gradient(135deg, #fef9ef 0%, #f8e6c4 100%);
      --glass-bg: rgba(255, 255, 255, 0.85);
      --glass-border: rgba(233, 220, 197, 0.8);
      --text-main: #202125;
      --text-muted: #6a6f76;
      --accent: #0b8d8c;
      --accent-hover: #097574;
      --accent2: #eb5e28;
      --input-bg: #ffffff;
      --card-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
      --chat-me: #e8f4fb;
      --chat-bot: #fff5df;
      --code-bg: #fffdf8;
    }

    :root[data-theme="dark"] {
      --bg-gradient: linear-gradient(135deg, #121212 0%, #1e1e1e 100%);
      --glass-bg: rgba(30, 30, 30, 0.85);
      --glass-border: rgba(60, 60, 60, 0.5);
      --text-main: #e0e0e0;
      --text-muted: #a0a0a0;
      --accent: #14b8b8;
      --accent-hover: #109696;
      --accent2: #ff7e4d;
      --input-bg: #2a2a2a;
      --card-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
      --chat-me: #1e3a5f;
      --chat-bot: #4d3d20;
      --code-bg: #1a1a1a;
    }

    * { box-sizing: border-box; }
    
    body {
      margin: 0;
      min-height: 100vh;
      font-family: 'Inter', 'Hind Siliguri', sans-serif;
      color: var(--text-main);
      background: var(--bg-gradient);
      background-attachment: fixed;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 24px;
      transition: background 0.3s ease, color 0.3s ease;
    }

    .top-controls {
      display: flex;
      gap: 12px;
      margin-bottom: 24px;
      padding: 8px 16px;
      background: var(--glass-bg);
      border: 1px solid var(--glass-border);
      border-radius: 40px;
      backdrop-filter: blur(8px);
      box-shadow: var(--card-shadow);
    }

    .control-btn {
      background: none;
      border: 1px solid var(--glass-border);
      color: var(--text-main);
      padding: 6px 14px;
      border-radius: 20px;
      cursor: pointer;
      font-weight: 500;
      font-size: 0.85rem;
      transition: all 0.2s ease;
    }

    .control-btn:hover {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }

    .control-btn.active {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }

    .shell {
      width: min(1200px, 100%);
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
      animation: rise 0.4s cubic-bezier(0.16, 1, 0.3, 1);
    }

    @keyframes rise {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .card {
      background: var(--glass-bg);
      border: 1px solid var(--glass-border);
      border-radius: 24px;
      box-shadow: var(--card-shadow);
      padding: 28px;
      backdrop-filter: blur(12px);
      display: flex;
      flex-direction: column;
    }

    h1 {
      margin: 0 0 8px;
      font-size: 1.6rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }

    .muted { 
      color: var(--text-muted); 
      font-size: 0.95rem; 
      margin-bottom: 20px;
      line-height: 1.5;
    }

    .form-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 20px;
    }

    .form-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    label { 
      font-size: 0.85rem; 
      font-weight: 600;
      color: var(--text-muted); 
    }

    input, textarea, select {
      width: 100%;
      border: 1px solid var(--glass-border);
      border-radius: 12px;
      padding: 12px 14px;
      font: inherit;
      background: var(--input-bg);
      color: var(--text-main);
      transition: border-color 0.2s, box-shadow 0.2s;
    }

    input:focus, textarea:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(11, 141, 140, 0.15);
    }

    textarea { resize: vertical; min-height: 80px; }

    .actions {
      display: flex;
      gap: 12px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }

    button.main {
      border: 0;
      border-radius: 12px;
      padding: 12px 20px;
      font-weight: 600;
      font-size: 0.95rem;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
      display: flex;
      align-items: center;
      gap: 8px;
    }

    button.main:active { transform: scale(0.97); }

    .btn-primary { background: var(--accent); color: white; }
    .btn-primary:hover { background: var(--accent-hover); }

    .btn-secondary { background: var(--glass-border); color: var(--text-main); }
    .btn-secondary:hover { background: rgba(0,0,0,0.1); }

    .btn-warm { background: var(--accent2); color: white; }
    .btn-warm:hover { opacity: 0.9; }

    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 0.85rem;
      font-weight: 600;
      margin-bottom: 12px;
      background: rgba(0,0,0,0.05);
    }

    .status-badge.ok { background: rgba(16, 122, 66, 0.15); color: #107a42; }
    .status-badge.err { background: rgba(179, 15, 47, 0.15); color: #b30f2f; }
    .status-badge.running { background: rgba(11, 141, 140, 0.15); color: var(--accent); }

    .chat-box {
      border: 1px solid var(--glass-border);
      border-radius: 16px;
      background: var(--input-bg);
      height: 400px;
      overflow-y: auto;
      padding: 16px;
      margin-bottom: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      scroll-behavior: smooth;
    }

    .msg {
      padding: 12px 16px;
      border-radius: 18px;
      max-width: 85%;
      line-height: 1.5;
      font-size: 0.95rem;
      box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }

    .msg.me {
      align-self: flex-end;
      background: var(--chat-me);
      border-bottom-right-radius: 4px;
      border: 1px solid rgba(0,0,0,0.05);
    }

    .msg.bot {
      align-self: flex-start;
      background: var(--chat-bot);
      border-bottom-left-radius: 4px;
      border: 1px solid rgba(0,0,0,0.05);
    }

    pre {
      margin: 0;
      background: var(--code-bg);
      border: 1px solid var(--glass-border);
      border-radius: 12px;
      padding: 16px;
      font-size: 0.8rem;
      font-family: 'Menlo', 'Courier New', monospace;
      overflow-x: auto;
      color: var(--text-main);
    }

    .footer {
      margin-top: 40px;
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    @media (max-width: 960px) {
      .shell { grid-template-columns: 1fr; }
      body { padding: 16px; }
    }
  </style>
</head>
<body>
  <div class="top-controls">
    <button class="control-btn" id="themeToggle">🌓 Theme</button>
    <div style="width: 1px; background: var(--glass-border); margin: 4px 0;"></div>
    <button class="control-btn" onclick="setLang('en')" id="langEn">English</button>
    <button class="control-btn" onclick="setLang('bn')" id="langBn">বাংলা</button>
  </div>

  <div class="shell">
    <!-- Scraper Section -->
    <section class="card">
      <h1 data-t="scraperTitle">Scraper Console</h1>
      <p class="muted" data-t="scraperDesc">Run catalog scrape into data/products.xlsx with live status.</p>
      
      <div class="form-grid">
        <div class="form-group">
          <label for="headless" data-t="labelHeadless">Headless</label>
          <select id="headless">
            <option value="true">True</option>
            <option value="false">False</option>
          </select>
        </div>
        <div class="form-group">
          <label for="limit" data-t="labelLimit">Limit (0 = all)</label>
          <input id="limit" type="number" value="0" min="0" />
        </div>
        <div class="form-group">
          <label for="slowmo" data-t="labelSlowmo">Slowmo (ms)</label>
          <input id="slowmo" type="number" value="0" min="0" />
        </div>
        <div class="form-group">
          <label for="output" data-t="labelOutput">Output Path</label>
          <input id="output" placeholder="data/products.xlsx" />
        </div>
      </div>

      <div class="actions">
        <button class="main btn-primary" id="startScrapeBtn">
          <span data-t="btnStartScrape">Start Scrape</span>
        </button>
        <button class="main btn-secondary" id="refreshStatusBtn">
          <span data-t="btnRefresh">Refresh</span>
        </button>
      </div>

      <div class="status-badge" id="scrapeBadge">
        <span id="badgeIcon">●</span> <span id="badgeText" data-t="statusIdle">Idle</span>
      </div>
      
      <pre id="scrapeStatus">{}</pre>
    </section>

    <!-- Chat Section -->
    <section class="card">
      <h1 data-t="chatTitle">Chat Simulator</h1>
      <p class="muted" data-t="chatDesc">Local order assistant using LLM + catalog pricing.</p>
      
      <div class="form-grid">
        <div class="form-group" style="grid-column: span 2;">
          <label for="userId" data-t="labelUserId">User ID</label>
          <input id="userId" value="u123" />
        </div>
      </div>

      <div class="chat-box" id="chatBox"></div>
      
      <div class="form-group" style="margin-bottom: 12px;">
        <textarea id="chatInput" placeholder="Type a message..."></textarea>
      </div>

      <div class="actions">
        <button class="main btn-primary" id="sendBtn" style="flex: 1; justify-content: center;">
          <span data-t="btnSend">Send</span>
        </button>
        <button class="main btn-secondary" id="clearChatBtn" data-t="btnClear">
          Clear
        </button>
      </div>
    </section>
  </div>

  <div class="footer">
    Bazarey Bot v1.0 • Built with FastAPI & Playwright
  </div>

  <script>
    const i18n = {
      en: {
        scraperTitle: "Scraper Console",
        scraperDesc: "Run catalog scrape into data/products.xlsx with live status.",
        labelHeadless: "Headless",
        labelLimit: "Limit (0 = all)",
        labelSlowmo: "Slowmo (ms)",
        labelOutput: "Output Path",
        btnStartScrape: "Start Scrape",
        btnRefresh: "Refresh Status",
        statusIdle: "Idle",
        statusRunning: "Running",
        statusDone: "Done",
        statusFailed: "Failed",
        chatTitle: "Chat Simulator",
        chatDesc: "Local order assistant using LLM + catalog pricing.",
        labelUserId: "Channel User ID",
        btnSend: "Send Message",
        btnClear: "Clear Chat",
        placeholder: "Type message...",
        noReply: "No reply from bot"
      },
      bn: {
        scraperTitle: "স্ক্র্যাপার কনসোল",
        scraperDesc: "লাইভ স্ট্যাটাস সহ data/products.xlsx- এ ক্যাটালগ স্ক্র্যাপ চালান।",
        labelHeadless: "হেডলেস",
        labelLimit: "সীমা (০ = সব)",
        labelSlowmo: "স্লোমো (মি.সে.)",
        labelOutput: "আউটপুট পাথ",
        btnStartScrape: "স্ক্র্যাপ শুরু করুন",
        btnRefresh: "স্ট্যাটাস রিফ্রেশ",
        statusIdle: "অলস",
        statusRunning: "চলছে",
        statusDone: "সম্পন্ন",
        statusFailed: "ব্যর্থ",
        chatTitle: "চ্যাট সিমুলেটর",
        chatDesc: "LLM + ক্যাটালগ প্রাক্কলন ব্যবহার করে লোকাল সহকারী।",
        labelUserId: "চ্যানেল ইউজার আইডি",
        btnSend: "বার্তা পাঠান",
        btnClear: "পরিষ্কার করুন",
        placeholder: "বার্তা লিখুন...",
        noReply: "বট থেকে কোন উত্তর নেই"
      }
    };

    let currentLang = localStorage.getItem('bazarey_lang') || 'en';
    let currentTheme = localStorage.getItem('bazarey_theme') || 'light';

    function updateLanguageUI() {
      const texts = i18n[currentLang];
      document.querySelectorAll('[data-t]').forEach(el => {
        const key = el.getAttribute('data-t');
        if (texts[key]) el.textContent = texts[key];
      });
      document.getElementById('chatInput').placeholder = texts.placeholder;
      document.getElementById('langEn').classList.toggle('active', currentLang === 'en');
      document.getElementById('langBn').classList.toggle('active', currentLang === 'bn');
      document.documentElement.lang = currentLang;
    }

    function setLang(lang) {
      currentLang = lang;
      localStorage.setItem('bazarey_lang', lang);
      updateLanguageUI();
    }

    function toggleTheme() {
      currentTheme = currentTheme === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', currentTheme);
      localStorage.setItem('bazarey_theme', currentTheme);
    }

    document.getElementById('themeToggle').addEventListener('click', toggleTheme);
    document.documentElement.setAttribute('data-theme', currentTheme);
    updateLanguageUI();

    const scrapeStatusEl = document.getElementById("scrapeStatus");
    const scrapeBadgeEl = document.getElementById("scrapeBadge");
    const badgeTextEl = document.getElementById("badgeText");
    const chatBoxEl = document.getElementById("chatBox");

    function setBadge(kind, statusKey) {
      scrapeBadgeEl.className = "status-badge" + (kind ? " " + kind : "");
      badgeTextEl.setAttribute('data-t', statusKey);
      badgeTextEl.textContent = i18n[currentLang][statusKey];
    }

    function addMsg(kind, text) {
      const div = document.createElement("div");
      div.className = "msg " + kind;
      div.textContent = text;
      chatBoxEl.appendChild(div);
      chatBoxEl.scrollTop = chatBoxEl.scrollHeight;
    }

    async function refreshStatus() {
      try {
        const res = await fetch("/simulate/scrape/status");
        const data = await res.json();
        if (JSON.stringify(data) !== scrapeStatusEl.textContent) {
            scrapeStatusEl.textContent = JSON.stringify(data, null, 2);
        }
        
        if (data.running) {
          setBadge("running", "statusRunning");
        } else if (data.last_error) {
          setBadge("err", "statusFailed");
        } else if (data.last_result_total !== null) {
          setBadge("ok", "statusDone");
        } else {
          setBadge("", "statusIdle");
        }
      } catch (e) {}
    }

    async function startScrape() {
      const headless = document.getElementById("headless").value === "true";
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
        setBadge("running", "statusRunning");
      }
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
          body: JSON.stringify({channel_user_id, text})
        });
        const data = await res.json();
        addMsg("bot", data.reply || i18n[currentLang].noReply);
      } catch (e) {
        addMsg("bot", "Error connecting to server.");
      }
    }

    document.getElementById("startScrapeBtn").addEventListener("click", startScrape);
    document.getElementById("refreshStatusBtn").addEventListener("click", refreshStatus);
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
