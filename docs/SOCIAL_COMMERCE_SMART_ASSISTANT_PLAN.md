# Social Commerce Smart Assistant Plan

## 1. Goal
Build a production-grade social commerce assistant for Messenger, WhatsApp, and future channels that:
- understands Bangla + English + Banglish mixed text reliably,
- feels like a human sales assistant (not robotic),
- helps customers shop in an organized way,
- can hand over to a human agent when needed,
- and is measurable with clear quality metrics.

This plan is designed specifically for the current Bazarey codebase and its existing modules.

## 2. Current Baseline (What You Already Have)

Your current system already has a strong starting foundation:
- FastAPI backend and simulator UI (`app/main.py`)
- Rule-first orchestrator + LLM fallback (`app/bot/orchestrator.py`)
- Bangla/Banglish normalization dictionary (`app/bot/normalizer.py`)
- Hybrid product search: fuzzy + optional vector (`app/tools/product_catalog.py`, `app/tools/vector_store.py`)
- Session memory in SQLite (`app/tools/session_store.py`)
- Order + invoice persistence (`app/tools/order_sheet.py`, `app/tools/invoice_store.py`)
- Catalog scraper pipeline (`app/scraping/scrape_products.py`)

This is good architecture. The next level is to tighten language understanding, conversation policy, and evaluation discipline.

## 3. Target Product Behavior

### 3.1 Customer Experience
- Natural replies in the user’s own style (Bangla/English/Banglish/mixed).
- No confusing jumps between intents.
- Better disambiguation when products are similar.
- Structured guidance for shopping:
  - category browsing,
  - recommendation prompts,
  - cart review and edit,
  - quick checkout.
- Clear fallback behavior:
  - asks one short clarification question,
  - never invents unavailable products/prices,
  - escalates to human when confidence is low.

### 3.2 Business Experience
- Works channel-wise with shared core logic.
- Keeps a full trace of decisions/tool calls for debugging.
- Can be evaluated offline and in production.
- Has operational controls (rate limits, guardrails, handoff triggers).

## 4. Best-in-Class Architecture Pattern

Use a **hybrid controller** (best-performing real-world pattern):

1. Deterministic policy layer first
   - checkout flow, phone validation, cart ops, known intent rules.
2. LLM as structured planner second
   - only with strict tool schema.
3. Business tools as single source of truth
   - pricing/catalog/order persistence only from tools/db.
4. Confidence + policy gate
   - if confidence low, ask clarification or handoff.
5. Evaluation loop
   - each release must pass multilingual benchmark tests.

Why this wins:
- reliability from rules,
- flexibility from LLM,
- control from strict schemas,
- quality from continuous eval.

## 5. Make It Smarter: Core Upgrades

## 5.1 Multilingual Understanding Upgrade

Current issue:
- Some mixed-language user text is misread.

Approach:
- Keep dictionary normalization, but add a second layer:
  - lightweight text classifier for intent + language mix,
  - entity extractor for quantity, units, product mentions.
- Add spelling normalization for Banglish variants (phonetic maps).
- Add confidence scores per parsed field:
  - `intent_confidence`
  - `product_confidence`
  - `quantity_confidence`

Implementation notes:
- Extend `normalize_query()` with variant mapping table + token rewrite rules.
- Add a parser module (e.g. `app/bot/parser.py`) that returns a structured parse object.
- In `process_message()`, gate risky actions if confidence below threshold.

## 5.2 Product Matching Quality Upgrade

Current issue:
- Similar products may be auto-selected incorrectly.

Approach:
- Add ranker signals:
  - lexical score,
  - semantic score,
  - category consistency,
  - unit compatibility (kg/pcs/liter).
- Add disambiguation policy:
  - if top-1 and top-2 close, ask user to choose from 2-3 options.
- Add synonym index from real customer chat logs.

Implementation notes:
- Expand `search_products()` scoring blend in `ProductCatalog`.
- Add "must-ask clarification" threshold band.
- Cache common queries to reduce latency.

## 5.3 Human-Like Conversation Layer

Current issue:
- Replies can feel transactional/robotic.

Approach:
- Add response style profiles:
  - concise sales assistant,
  - warm local helper,
  - formal support.
- Add response micro-policies:
  - acknowledge user goal first,
  - answer directly,
  - one soft next-step prompt.
- Add controlled recommendation templates:
  - “people who buy X also buy Y” (from order co-occurrence).

Implementation notes:
- Keep existing hard rules in orchestrator.
- Add a response formatter (`app/bot/response_style.py`) after business logic.
- Avoid open-ended free-generation for critical paths.

## 5.4 Organized Shopping Experience

Add explicit shopping copilots:
- Guided cart builder:
  - category -> product -> qty -> review.
- Smart bundles:
  - fish + spice suggestions,
  - rice + lentil combos.
- Cart actions:
  - add/remove/update quantity by natural language.
- Pre-checkout summary cards:
  - subtotal + line items + editable actions.

Implementation notes:
- Persist cart with richer item metadata in session state.
- Add `update_item_qty` and `remove_item` tool shapes for structured editing.
- Use category cards in dashboard as operator support.

## 5.5 Omnichannel Production Layer

You want Messenger, WhatsApp, others. Keep adapter-first design:
- Core domain logic stays channel-agnostic.
- Add channel adapters:
  - `MessengerAdapter`
  - `WhatsAppAdapter`
  - later: Instagram, webchat.

Each adapter handles:
- webhook payload normalization,
- outbound message shape,
- channel constraints (message windows, templates, media rules),
- delivery status + retries.

Important:
- Add **Handover Protocol** support for Messenger human handoff.
- Add **template fallback strategy** for WhatsApp when free-form messaging is not allowed.

## 5.6 Human Handoff & Operations

Escalation should trigger when:
- repeated low-confidence parses,
- policy-sensitive requests,
- user asks for human,
- high-value/angry customer signals.

Handoff flow:
1. Bot summarizes context (intent, cart, address, last 5 turns).
2. Assign to agent queue.
3. Lock bot interventions unless agent releases control.

## 5.7 Safety and Guardrails

Hard requirements:
- never fabricate price/stock/discount,
- never finalize order without required fields,
- never break channel policy restrictions,
- always log action traces for audit.

Technical guardrails:
- strict schema tool calling,
- deterministic validators before side effects,
- retry + fallback strategies for external APIs.

## 6. Evaluation Framework (Non-Negotiable)

Without evals, smart bots degrade over time.

Build evaluation sets from real conversations:
- Bangla-only,
- English-only,
- mixed Banglish,
- noisy misspellings,
- ambiguous product requests,
- cart edits and checkout flows.

Track metrics:
- intent accuracy,
- product match precision@1 and @3,
- quantity extraction accuracy,
- order completion rate,
- clarification rate,
- handoff rate,
- hallucination rate (must trend to near zero).

Run:
- offline eval before release,
- online eval on sampled production traffic.

## 7. Implementation Roadmap (Practical)

## Phase A (1-2 weeks): Reliability First
- Add parser confidence layer.
- Add disambiguation thresholds.
- Add better quantity + unit parser.
- Add structured error/fallback responses.

Deliverable:
- noticeably fewer wrong product selections.

## Phase B (2-3 weeks): Shopping Quality
- Add organized cart editing tools.
- Add bundle/recommendation engine from past orders.
- Add richer checkout summaries.

Deliverable:
- more completed orders per conversation.

### Phase B Execution Status (Completed on March 12, 2026)

Implemented in code:
- Organized cart editing in `app/bot/orchestrator.py`
  - `update <product> <qty>`
  - `increase <product> <qty>`
  - `decrease <product> <qty>`
  - `remove <product>`
  - cart-edit help prompt + in-checkout edit support
- Bundle/recommendation engine in `app/tools/recommendation_engine.py`
  - invoice co-occurrence model from historical order items
  - cart-based recommendations
  - product-based recommendations
  - popular fallback recommendations
- Richer cart + checkout summaries in `app/bot/orchestrator.py`
  - numbered line-items
  - unit price + line total
  - subtotal + total units
  - inline edit hints and recommendation block
  - checkout flow resume prompts after cart edits

Validation:
- `tests/test_phase_b_shopping_quality.py`
- `tests/test_quantity_unit_conversion.py`
- `tests/test_orchestrator_random_guard.py`
- `tests/test_parser.py`
- Result: `14 passed`

## Phase C (2-4 weeks): Omnichannel Readiness
- Add webhook adapters for Messenger + WhatsApp.
- Add message policy handler per channel.
- Add human handoff events and agent queue integration.

Deliverable:
- real channel deployment readiness.

## Phase D (ongoing): Evaluation + Optimization
- Build regression benchmark dataset.
- Add CI evaluation gates.
- Run weekly quality review and fix top failure clusters.

Deliverable:
- quality improves release over release, not randomly.

## 8. Concrete Changes Recommended in This Repo

1. Add `app/bot/parser.py`
- structured extraction:
  - `intent`, `language_mix`, `entities`, `confidences`.

2. Add `app/bot/confidence.py`
- thresholds and escalation decisions.

3. Extend `app/tools/product_catalog.py`
- stronger ranking blend + ambiguity detection response payload.

4. Add `app/bot/response_style.py`
- human-like but controlled response templates by intent.

5. Add `app/channels/` adapters
- move from simulator-only to production channel architecture.

6. Add `tests/evals/` dataset-driven evaluations
- multilingual regression set and scoring pipeline.

## 9. Product Mindset: What “Smarter” Means

For your use case, smarter is not "more creative text."
Smarter means:
- fewer misunderstandings,
- fewer wrong cart updates,
- better guided shopping,
- better completion rate,
- safer outputs under channel/business constraints.

That is the standard used by best production assistants.

## 10. References Used for This Plan

- OpenAI Function Calling + strict structured outputs:
  - https://platform.openai.com/docs/guides/function-calling
- OpenAI function calling reliability notes:
  - https://help.openai.com/en/articles/8555517-function-calling-in-the-openai-api
- Rasa forms/slot-filling pattern (strong reference for structured collection flows):
  - https://rasa.com/docs/rasa/forms/
- Messenger official samples (includes handover protocol sample and official doc links):
  - https://github.com/fbsamples/messenger-platform-samples
- LangSmith evaluation quickstart (offline/online eval discipline):
  - https://docs.langchain.com/langsmith/evaluation-quickstart

---

If you want, next step I can implement **Phase A** directly in code (parser confidence + ambiguity handling + improved quantity parser) so you get immediate quality gains.
