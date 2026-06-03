# Clinical AI Multi-Agent

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi)
![LangChain](https://img.shields.io/badge/LangChain-1.2-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?logo=postgresql)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

> [🇪🇸 Leer en español](docs/README.es.md)

A production-grade, multi-agent AI backend for paramedic and clinical decision support. Receives a clinical case description, classifies urgency via LLM triage, activates specialist agents in parallel, and returns a structured integrated assessment.

---

## Architecture

```
HTTP POST /clinical-case/analyze
           │
           ▼
    ┌─────────────┐
    │ AgentRouter │  LLM triage — classifies urgency (CRITICO / MUY_URGENTE /
    │  temp=0.0   │  URGENTE / NO_URGENTE) and selects specialist agents
    └──────┬──────┘
           │  agentes_sugeridos: ["EmergencyAgent", "CardiologyAgent", ...]
           ▼
    ┌──────────────────────────────────────────────┐
    │               Integrator                     │
    │         asyncio.gather (parallel)            │
    │                                              │
    │  ┌─────────────┐  ┌──────────────┐           │
    │  │ClinicalAgent│  │EmergencyAgent│  ...       │
    │  └──────┬──────┘  └──────┬───────┘           │
    │         │                │                    │
    │         ▼                ▼                    │
    │     LCEL chain       LCEL chain               │
    │  retriever | prompt | llm | parser            │
    │         │                │                    │
    │         └────────────────┘                    │
    │              merge results                    │
    └──────────────────┬───────────────────────────┘
                       │
                       ▼
               AnalyzeOutput
        (summary, findings, red_flags,
         recommendations, confidence,
         agentes_activados, agent_outputs)
```

Each agent runs an independent RAG chain: it retrieves relevant clinical guidelines from **pgvector**, builds a prompt, calls the LLM, and parses the response into a typed `AgentOutput`. The Integrator combines them: union of findings/red_flags, average confidence, best-confidence summary.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| API framework | FastAPI 0.136 + Uvicorn (async) |
| Agent orchestration | LangChain LCEL (`prompt \| llm \| parser`) |
| LLM providers | Nvidia NIM (openai_compatible), Groq, OpenAI, LM Studio |
| Embeddings | NVIDIAEmbeddings / OpenAIEmbeddings — provider-agnostic |
| Vector store | pgvector via `langchain-postgres` PGVectorStore |
| Relational DB | PostgreSQL + SQLAlchemy 2.0 async + Alembic migrations |
| Data validation | Pydantic v2 + pydantic-settings |
| Concurrency | `asyncio.gather` — agents execute in parallel |
| Containerization | Docker multi-stage build — separate API and indexer images |
| CI/CD | GitHub Actions → Docker → GHCR |
| Production | VPS + Traefik reverse proxy + Let's Encrypt TLS |

---

## How it works

**1. Request arrives**

```
POST /clinical-case/analyze
{
  "texto_clinico": "65-year-old male, chest pain radiating to left arm...",
  "sintomas": ["chest pain", "diaphoresis", "dyspnea"]
}
```

**2. LLM triage**

`AgentRouter` runs at `temperature=0.0` (deterministic). It classifies urgency and selects which specialist agents the case needs, based on semantic content — not just urgency level:

```
urgency:  MUY_URGENTE
agents:   ["EmergencyAgent", "ClinicalAgent", "CardiologyAgent"]
```

Specialist agents (Cardiology, Pharmacology, Radiology) activate on content, not urgency. An ECG reading activates `CardiologyAgent` regardless of urgency level.

**3. Parallel execution**

All selected agents run concurrently. Three agents at 2 s each = ~2 s total, not 6 s:

```python
results = await asyncio.gather(
    *[_safe_run(agent, name, caso, timeout) for agent, name in zip(agents, names)],
    return_exceptions=True,   # partial failure → partial result, not abort
)
```

Each agent independently queries the vector store, retrieves relevant clinical guidelines, builds its prompt, and parses a typed response.

**4. Result merging**

```
summary:        from highest-confidence agent
findings:       union, order-preserved, deduplicated
red_flags:      union — never drop a red flag
recommendations: union, order-preserved, deduplicated
confidence:     average across all agents
```

**5. Resilience**

If one agent times out or fails, the others' results are still returned. `failed_agents` and `warnings` fields on `AnalyzeOutput` make partial degradation explicit and auditable.

---

## Key design decisions

### Provider-agnostic LLM

Zero code changes to switch LLM providers — only `.env` changes:

```bash
# Nvidia NIM (production)
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_API_KEY=nvapi-...
LLM_MODEL=meta/llama-3.1-70b-instruct

# Groq (fast dev iteration)
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile

# Local (offline dev)
LLM_PROVIDER=lmstudio
LLM_MODEL=lmstudio-community/llama-3.2-3b
```

The `create_llm()` factory (`app/core/llm.py`) returns a `BaseChatModel` — all agents use the same interface regardless of provider.

### Lazy chain initialization

Agents are instantiated synchronously at module load. The async retriever connection (`PGVectorStore.acreate`) cannot happen in `__init__`. Each agent defers it:

```python
def __init__(self) -> None:
    self._chain = None  # built on first run()

async def _ensure_chain(self) -> None:
    if self._chain is not None:
        return
    retriever = await get_retriever(k=3)
    self._chain = {"context": retriever | format_docs, "caso_clinico": RunnablePassthrough()} \
                  | self._prompt | self._llm | self._parser
```

### PGVectorStore singleton

The vector store is initialized once per process. Double-checked locking ensures exactly one `acreate()` call even when multiple agents initialize concurrently:

```python
async with _store_lock:
    if _store is None:
        _store = await PGVectorStore.acreate(
            embeddings=get_embeddings(),
            collection_name="clinical_docs",
            connection=psycopg_url,
        )
```

Single PostgreSQL instance serves both relational data (cases, audit logs) and vector search — no separate vector DB service.

---

## Running locally

**Prerequisites:** Docker, Python 3.12, `uv` (or `pip`)

```bash
# 1. Clone and install dependencies
git clone https://github.com/JCGJ94/Clinical-AI-Multi-Agent.git
cd Clinical-AI-Multi-Agent
uv sync

# 2. Configure environment
cp envs/.env.example .env
# Edit .env — set LLM_PROVIDER, LLM_API_KEY, and DATABASE_URL
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/clinical_ai

# 3. Start PostgreSQL with pgvector (dev maps to port 5433)
docker compose -f docker/compose.yml -f docker/compose.dev.yml up -d postgres

# 4. Run database migrations
uv run alembic upgrade head

# 5. Index clinical knowledge base (run once)
docker compose -f docker/compose.yml -f docker/compose.dev.yml run indexer

# 6. Start the API
uv run uvicorn app.main:app --reload
```

Or use the dev runner shortcut:

```bash
uv run ./scripts/dev.py db-up    # start Postgres
uv run ./scripts/dev.py server   # start API with .env loaded
uv run ./scripts/dev.py smoke    # smoke test 4 endpoints
```

API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Run tests

```bash
uv run pytest tests/ -v
```

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/health/ready` | Readiness check (DB + vector store) |
| `POST` | `/clinical-case/analyze` | Full multi-agent analysis |
| `GET` | `/clinical-case/{case_id}` | Retrieve stored case result |

### Example request

```bash
curl -X POST http://localhost:8000/clinical-case/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "texto_clinico": "65-year-old male, sudden chest pain, diaphoresis, ECG shows ST elevation in V1-V4.",
    "sintomas": ["chest pain", "diaphoresis", "ST elevation"]
  }'
```

### Example response (abbreviated)

```json
{
  "summary": "Acute anterior STEMI. Immediate cath lab activation required.",
  "findings": [
    "ST elevation V1-V4 consistent with LAD territory STEMI",
    "HR 98 bpm, regular rhythm"
  ],
  "red_flags": [
    "STEMI — door-to-balloon target: 90 minutes",
    "Cardiogenic shock risk"
  ],
  "recommendations": [
    "Activate cath lab immediately",
    "Aspirin 300mg + P2Y12 inhibitor loading dose",
    "IV access, O2, continuous monitoring"
  ],
  "confidence": 0.91,
  "agentes_activados": ["EmergencyAgent", "ClinicalAgent", "CardiologyAgent"],
  "failed_agents": []
}
```

---

## Project structure

```
app/
├── agents/
│   ├── base.py          # BaseAgent ABC — contract all agents implement
│   ├── router.py        # AgentRouter — LLM triage, not a clinical agent
│   ├── clinical.py      # ClinicalAgent — general internist
│   ├── emergency.py     # EmergencyAgent — ABCDE protocol, critical cases
│   ├── diagnosis.py     # DifferentialDiagnosisAgent — hypothesis generation
│   ├── cardiology.py    # CardiologyAgent — ECG interpretation
│   ├── pharmacology.py  # PharmacologyAgent — drug safety, interactions
│   └── radiology.py     # RadiologyAgent — imaging interpretation
├── services/
│   └── integrator.py    # Parallel execution + result merging
├── rag/
│   ├── retriever.py     # PGVectorStore singleton + get_retriever()
│   ├── embeddings.py    # Provider-agnostic embedding factory
│   ├── loader.py        # Document chunking + format_docs()
│   └── chain.py         # RAG chain builder (legacy, used by some agents)
├── core/
│   ├── config.py        # pydantic-settings — all config from .env
│   ├── llm.py           # create_llm() factory — provider selection
│   ├── exceptions.py    # AgentExecutionError, AllAgentsFailedError, etc.
│   └── logging.py       # Structured JSON logging
├── db/
│   ├── models.py        # SQLAlchemy 2.0 async ORM models
│   ├── session.py       # Async engine + session factory
│   └── repository.py   # ClinicalCaseRepository
├── models/
│   └── clinical.py      # Pydantic v2 models — AgentOutput, AnalyzeOutput, etc.
├── routes/
│   ├── clinical.py      # /clinical-case endpoints
│   └── health.py        # /health endpoints
└── main.py              # FastAPI app factory, lifespan events

docs/
├── README.es.md         # Esta documentación en español
├── architecture/        # Routing rules, agent priority — loaded into RAG
├── prompts/             # System prompt definitions — loaded into RAG
└── guias_clinicas/      # Clinical guidelines — loaded into RAG

docker/
├── Dockerfile.api       # Multi-stage — builder + runtime
├── Dockerfile.indexer   # One-shot indexing job
└── compose.*.yml        # dev / prod / vps compose files

alembic/                 # Database migration scripts
tests/                   # pytest + pytest-asyncio test suite
```

---

## Deployment

Production runs on a VPS with:

- **Traefik** as reverse proxy with automatic Let's Encrypt TLS
- **GitHub Actions** CI/CD: test → build → push to GHCR → deploy via SSH
- **Docker Compose** (prod profile): API container + PostgreSQL + pgvector

```
GitHub push → Actions workflow
  → pytest
  → docker build (multi-stage)
  → docker push ghcr.io/...
  → SSH into VPS → docker compose pull + up
```

---

## Development phases completed

| Phase | What it added |
|-------|--------------|
| 0–1 | FastAPI skeleton, pydantic-settings, `/health` |
| 2 | `ClinicalAgent` with OpenAI SDK (Groq-compatible) |
| 3 | LangChain LCEL migration — all chains use `\|` composition |
| 4 | RAG modules: embeddings, document loader, pgvector retriever |
| 5 | RAG integrated in ClinicalAgent, EmergencyAgent, DifferentialDiagnosisAgent |
| 6 | `AgentRouter` (LLM triage) + `Integrator` (asyncio.gather) |
| 7 | CardiologyAgent, PharmacologyAgent, RadiologyAgent + content-based routing |
| 8 | SQLAlchemy 2.0 async, Alembic migrations, ClinicalCaseRepository |
| 9 | Partial-failure resilience (`return_exceptions=True`), per-agent timeout |
| 10 | Dockerfile multi-stage, CI/CD pipeline, VPS deployment |
| 11 | `create_llm()` factory — DRY provider selection across all agents |
| 12 | `openai_compatible` provider — Nvidia NIM, DeepSeek, any OpenAI-compatible API |
| 13 | PGVectorStore migration (race condition fix), dep bumps (FastAPI 0.136, openai 2.40, pydantic 2.13), Python 3.12 runtime |

---

## Contributing

See `AGENTS.md` for the full agent contract, lazy initialization rationale, RAG singleton rules, temperature guide, and step-by-step instructions for adding a new specialist agent.
