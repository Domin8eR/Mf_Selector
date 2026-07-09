# CLAUDE.md — MFit Build Instructions

> This file is loaded automatically by Claude Code at the start of every session.
> It contains the full project specification and milestone instructions.

---

You are helping me build MFit — a client-rule-based mutual fund research
workspace for Indian funds. We are starting from an empty repo on my Mac.

STEP 0 — READ THE DOCS FIRST.
Before writing a single line of code, read every file in the docs/ folder:
  - Process_Note_-_New.docx
  - AltStreet_MVP_Tech_Stack_Final_Recommendation.docx
  - AltStreet_MVP_Developer_End_to_End_Build_Guide_v8_with_screens.docx
  - mfit_full_wireframes.html

Then post a summary back to me in exactly 5 bullets:
  1. The MVP scope in one sentence
  2. The names of the 9 screens
  3. The 3 non-negotiables you think matter most
  4. The agent-boundary rule (what AI must NOT do)
  5. The data-versioning rule

WAIT for me to reply "OK" before writing any code. If I don't reply OK,
do not proceed.

== PROJECT IDENTITY ==

Name: mfit (the folder is currently called Mf_Selector — that's fine)
Purpose: client-rule-based mutual fund research workspace
Out of scope for MVP: portfolio management, buy/sell recommendations,
proprietary prediction models, personalized investor advice.

LANGUAGE RULE (enforce everywhere — UI strings, API responses, agent
prompts, report templates, code comments, variable names, log messages):
  - USE: "structural improvement", "research candidate", "ranked funds"
  - NEVER USE: "recommendation", "buy", "sell", "best fund", "top pick"

== APPROVED STACK (do not deviate without asking me first) ==

Frontend:
  React 18, Vite, TypeScript (strict mode), TanStack Query, Tailwind CSS,
  shadcn/ui (copied components, not a package), Recharts, React Hook Form,
  Zod, React Router v6, native EventSource for SSE streaming.

Backend:
  FastAPI, Pydantic v2, SQLAlchemy 2.0 sync (NOT async), Alembic for
  migrations, python-jose for JWT, PostgreSQL 16 with pgvector extension,
  Redis 7, Celery + Celery Beat + Flower, boto3 for S3-compatible storage
  (MinIO locally), structlog, sentry-sdk.

Quant engine:
  Pandas, NumPy, SciPy, pytest. Pure-function metric calculators with
  unit tests. NO Numba, NO Polars.

AI layer:
  ONE LLM provider only (Anthropic by default if I have a key, otherwise
  leave a stub). Small tool-calling orchestrator — NOT a full LangGraph
  multi-agent system. RAG via pgvector + Postgres full-text search +
  reciprocal rank fusion. Langfuse for traces (one provider, not both).

Local dev environment:
  Docker Compose with services: postgres (with pgvector), redis, minio,
  api (FastAPI), worker (Celery), beat (Celery scheduler), web (Vite).

FORBIDDEN IN MVP — do not install or import these:
  TimescaleDB, Zustand, Visx, D3, Socket.IO, async SQLAlchemy, multiple
  LLM providers, full LangGraph, OpenSearch, Elasticsearch, Snowflake,
  ClickHouse, BigQuery, Spark, Dask, Numba, Polars.

== HARD ARCHITECTURAL RULES (non-negotiable, enforce in code review) ==

1. AI MUST NOT calculate metrics or rank funds. Quant and ranking are
   pure-Python backend modules with unit tests. AI only explains
   pre-computed results, retrieves documents, drafts narrative, and
   routes user intent to backend tools. If a request asks AI to produce
   a number, route it to a backend tool call instead.

2. Every API response that returns a metric, rank, or explanation MUST
   include these four fields: data_version, rule_version,
   calculation_version, as_of_date. Implement this via a shared Pydantic
   base model — VersionedResponse — that every metric/ranking endpoint
   inherits from.

3. Runtime screens and AI agents read ONLY from internal validated
   Postgres tables. No frontend page and no agent may call a vendor API
   at request time. Vendor data is ingested via batch Celery jobs into
   staging tables, validated, then promoted to production tables.

4. No weekend rows, no forward-filled NAVs, no artificial NAV gaps. Use
   a trading_calendar table and INNER JOIN every NAV query to it.

5. Every default rule change must be versioned, approved, timestamped,
   and reversible. Rulesets and ruleset_versions are append-only
   immutable history; only an "active_version_id" pointer moves.

6. Every AI-callable backend endpoint is on an allow-list. Every AI
   tool call is logged to a tool_call_log table with thread_id,
   tool_name, input_json, output_json, latency_ms, status.

== REPO LAYOUT I WANT ==

Mf_Selector/
├── docker-compose.yml
├── .gitignore
├── .env.example
├── README.md
├── CLAUDE.md                 ← copy this whole prompt here so future
│                                Claude Code sessions read it on load
├── docs/                     ← already has the 4 reference files
├── backend/                  ← FastAPI service
│   ├── app/
│   │   ├── core/             ← config, db session, auth, versioning
│   │   ├── models/           ← SQLAlchemy models
│   │   ├── schemas/          ← Pydantic schemas (incl. VersionedResponse)
│   │   ├── routers/          ← REST endpoints grouped by domain
│   │   ├── services/         ← business logic, called by routers
│   │   ├── quant/            ← pure metric functions + tests
│   │   ├── ai/               ← supervisor, tools, rag, compliance
│   │   ├── jobs/             ← Celery tasks
│   │   └── main.py
│   ├── alembic/              ← migrations
│   ├── tests/                ← pytest suite
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── .python-version       ← pin to 3.11
│   └── Dockerfile
├── frontend/                 ← React + Vite
│   ├── src/
│   │   ├── components/       ← shadcn primitives + composed components
│   │   ├── features/         ← one folder per screen
│   │   ├── lib/              ← api client, query keys, zod schemas
│   │   ├── routes/           ← router config
│   │   └── main.tsx
│   ├── public/
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── vite.config.ts
│   └── Dockerfile
└── scripts/
    ├── seed_synthetic.py     ← generate fake NAVs for dev
    └── README.md

== MILESTONE 1 — DO EXACTLY THIS, NOTHING MORE ==

After I reply "OK" to your summary:

1. Create the .gitignore (Node + Python + macOS + IDE).
2. Create the README.md with project overview, run instructions, and
   the language rule prominently at the top.
3. Create CLAUDE.md containing this entire prompt verbatim.
4. Create docker-compose.yml wiring postgres (with pgvector image),
   redis, minio. Don't wire api/worker/beat/web yet — we'll add those
   in milestone 2.
5. Create .env.example listing every env var the project will need,
   with safe placeholder values. Never put real secrets in this file.
6. Scaffold backend/:
     - pyproject.toml with FastAPI, Pydantic v2, SQLAlchemy 2.0,
       Alembic, psycopg2-binary, redis, celery, structlog, pytest,
       and python-dotenv. Pin to versions known to work together.
     - app/main.py with a FastAPI app exposing:
         GET /health  → {"status": "ok"}
         GET /version → {"data_version":"0", "rule_version":"0",
                         "calculation_version":"0",
                         "as_of_date": today_iso}
     - app/core/config.py reading from environment via Pydantic Settings.
     - app/schemas/base.py defining VersionedResponse.
     - alembic initialized but no migrations yet.
     - tests/test_health.py with one passing test.
7. Scaffold frontend/:
     - Vite + React + TypeScript template.
     - Tailwind configured.
     - shadcn/ui initialized with Button, Card, Sheet, Table, Tabs,
       Dialog, Toast copied into src/components/ui/.
     - React Router with a sidebar layout and 9 empty route stubs
       matching the wireframe nav: Home, Rankings, Funds, Compare,
       Research Chat, Rule Lab, Reports, Data Quality, Admin.
     - TanStack Query provider wrapped around the app.
     - lib/api.ts with a typed fetch wrapper pointing at
       VITE_API_BASE_URL.
8. STOP. Print a checklist of what was created and tell me the exact
   commands I should run to verify each piece:
     - bring up docker compose
     - run backend dev server
     - run frontend dev server
     - run backend tests
   Wait for me to confirm everything works before milestone 2.

== STYLE AND GROUND RULES ==

- Python: type hints everywhere, ruff for linting, black for format.
- TypeScript: strict mode on, no `any`, prefer `unknown` then narrow.
- One concept per file. Small functions. Pure where possible.
- Conventional Commits (feat:, fix:, chore:, docs:, test:).
- Tests for every metric function, every rule-validation function,
  every Pydantic schema that has custom validators.
- Do not install a new dependency without telling me what and why.
- If you find a contradiction between docs/, this prompt, and your own
  judgment, STOP and ask me which wins. Do not silently choose.
- Run commands one at a time. After each command, paste its output and
  wait for me to acknowledge before running the next.
- I am on macOS, zsh shell. No Linux-only or Windows-only commands.

Begin with Step 0 now — read the docs and post the 5-bullet summary.
Do not write any code until I reply "OK".

If you have questions do ask
