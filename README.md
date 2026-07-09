# AltStreet — Client-Rule-Based Mutual Fund Research Workspace

> A deterministic, auditable mutual fund ranking and research tool for Indian funds.
> Built for internal analyst and relationship-manager workflows.

---

## ⚠️ Language Rule (enforced everywhere)

| Use | Never use |
|-----|-----------|
| "structural improvement" | "recommendation" |
| "research candidate" | "buy" / "sell" |
| "ranked funds" | "best fund" / "top pick" |

This rule applies in UI strings, API responses, agent prompts, report templates,
code comments, variable names, and log messages.

---

## What AltStreet does (MVP scope)

- Ingests clean NAV and benchmark data (no weekend rows, no forward-fills)
- Calculates structural-improvement metrics: rolling IR, IR slope, consistency
- Applies **client-defined rule sets** to rank funds deterministically
- Explains rankings with AI (AI does **not** calculate metrics or rank funds)
- Generates auditable research outputs with full version traceability

### Out of scope for MVP

Portfolio management · buy/sell recommendations · proprietary prediction models ·
personalized investor suitability advice

---

## Screens (9)

| Screen | Primary users |
|--------|--------------|
| AI Command Center / Home | All roles |
| Category Rankings | RM, analyst, product team |
| Fund Detail | RM, analyst |
| Fund Comparison | RM, analyst |
| Research Chat | All roles |
| Rule Playground (Rule Lab) | Product / investment team |
| Rule Approval & Version History | Product team, admin |
| Reports Builder | RM, analyst |
| Data Quality & Operations | Admin, data ops |

---

## Tech stack

| Layer | Stack |
|-------|-------|
| Frontend | React 18, Vite, TypeScript (strict), TanStack Query, Tailwind CSS, shadcn/ui, Recharts, React Router v6 |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2.0 (sync), Alembic, PostgreSQL 16, Redis 7, Celery |
| Quant | Pandas, NumPy, SciPy, pytest — pure functions, no LLM involvement |
| AI | Anthropic (one provider), tool-calling orchestration, RAG via pgvector, Langfuse |
| Infra | Docker Compose (local), MinIO (S3-compatible), structlog, Sentry |

---

## Quick start

### Prerequisites

- Docker Desktop running
- Python 3.11 (`pyenv install 3.11`)
- Node 20+ (`node --version`)

### 1 — Clone and configure

```bash
git clone <repo-url> altstreet
cd altstreet
cp .env.example .env          # then edit with your real values
```

### 2 — Start infrastructure (Postgres + Redis + MinIO)

```bash
docker compose up -d
```

Verify services are healthy:

```bash
docker compose ps
```

### 3 — Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Health check:
```bash
curl http://localhost:8000/health
# → {"status":"ok"}

curl http://localhost:8000/version
# → {"data_version":"0","rule_version":"0","calculation_version":"0","as_of_date":"..."}
```

### 4 — Run backend tests

```bash
cd backend
pytest -v
```

### 5 — Run the frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### 6 — Type-check the frontend

```bash
cd frontend
npm run type-check
```

---

## Repo layout

```
Mf_Selector/
├── docker-compose.yml
├── .env.example
├── docs/                     ← reference docs (process note, build guide, wireframes)
├── backend/
│   ├── app/
│   │   ├── core/             ← config, db session, auth, versioning
│   │   ├── models/           ← SQLAlchemy models
│   │   ├── schemas/          ← Pydantic schemas (incl. VersionedResponse)
│   │   ├── routers/          ← REST endpoints grouped by domain
│   │   ├── services/         ← business logic
│   │   ├── quant/            ← pure metric functions + unit tests
│   │   ├── ai/               ← supervisor, tools, RAG, compliance
│   │   ├── jobs/             ← Celery tasks
│   │   └── main.py
│   ├── alembic/              ← migrations
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── components/       ← shadcn primitives + composed components
│   │   ├── features/         ← one folder per screen
│   │   ├── lib/              ← api client, query keys, zod schemas
│   │   └── routes/           ← router config
└── scripts/
    └── seed_synthetic.py     ← fake NAVs for dev
```

---

## Hard architectural rules (non-negotiable)

1. **AI must not calculate metrics or rank funds.** Quant/ranking is pure-Python backend. AI explains pre-computed results only.
2. **Every metric/ranking response includes** `data_version`, `rule_version`, `calculation_version`, `as_of_date` via the shared `VersionedResponse` base model.
3. **Runtime reads only from internal validated Postgres tables.** No frontend or agent calls vendor APIs at request time.
4. **No weekend rows, no forward-filled NAVs.** Every NAV query JOINs the `trading_calendar` table.
5. **Every rule change is versioned, approved, timestamped, and reversible.**
6. **Every AI tool call is logged** to `tool_call_log` (thread_id, tool_name, input, output, latency, status).

---

## Contributing

- Use Conventional Commits: `feat:`, `fix:`, `chore:`, `docs:`, `test:`
- Python: type hints everywhere, `ruff` for lint, `black` for format (line length 100)
- TypeScript: strict mode on, no `any`, prefer `unknown` then narrow
- Do not add a new dependency without noting what and why in your PR

---

*AltStreet is a research and operational tool. It does not provide investment advice, buy/sell recommendations, or personalized fund selections.*
