# AGENTS.md

Instructions for AI coding agents working on this repository. Read this before making any change.

---

## Project snapshot

FastAPI backend. Receives a clinical case (text), classifies urgency via LLM triage, runs specialist agents in parallel, returns a merged structured assessment. Python 3.12, async throughout, deployed on a VPS via Docker + GitHub Actions CI/CD.

---

## Commands

```bash
uv run pytest tests/ -v                          # full test suite
uv run pytest tests/test_agents.py -v            # single file
uv run uvicorn app.main:app --reload             # dev server (reads .env)
uv run ./scripts/dev.py db-up                    # start Postgres in Docker (port 5433)
uv run ./scripts/dev.py smoke                    # smoke test localhost
uv add <package> && uv lock                      # add a dependency
uv run alembic upgrade head                      # run DB migrations
```

Never use `pip install` or `.venv/Scripts/python.exe` directly. Always use `uv`.

---

## Project structure

```
app/
├── agents/          # One file per agent. base.py defines the contract.
├── core/            # config.py (settings), llm.py (factory), exceptions.py
├── db/              # models.py, session.py, repository.py
├── models/          # clinical.py — all Pydantic I/O schemas
├── rag/             # retriever.py, embeddings.py, loader.py, chain.py
├── routes/          # clinical.py, health.py
└── main.py
docs/                # Markdown files indexed into the vector store (RAG knowledge base)
docker/              # Dockerfile.api, Dockerfile.indexer, compose.*.yml
alembic/             # migration scripts
tests/               # mirrors app/ structure
scripts/             # dev.py (runner), smoke_test.py, indexer.py
```

**Rules:**
- New agent → `app/agents/<name>.py`. No exceptions.
- New DB table → Alembic migration in `alembic/versions/`. Never use `create_all()` outside of startup init.
- New config value → add field to `Settings` in `app/core/config.py`. Never read `os.environ` directly.
- New route → `app/routes/<name>.py`, registered in `app/main.py`.
- New Pydantic schema → `app/models/clinical.py`.

---

## Coding rules

- All I/O is async. Never use `requests`, `psycopg2`, or any sync HTTP client in the request path.
- Never import `os.environ` — use `get_settings()` from `app/core/config.py`.
- Never hardcode provider names, URLs, or API keys. They live in `.env` via pydantic-settings.
- `extra="ignore"` is set on `Settings` — Docker-specific vars (POSTGRES_*) are silently ignored.
- Use `from __future__ import annotations` only if needed for forward references.
- Type-hint everything. Pydantic models are the source of truth for shapes.

---

## Agent pattern (mandatory)

Every clinical agent must follow this exact structure. Do not deviate.

```python
from typing import ClassVar
from app.agents.base import BaseAgent
from app.models.clinical import AgentOutput
from app.core.llm import create_llm
from app.rag.retriever import get_retriever
from app.rag.loader import format_docs
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnablePassthrough


class YourAgent(BaseAgent):
    NAME: ClassVar[str] = "YourAgent"   # exact string used in AGENT_REGISTRY

    def __init__(self) -> None:
        # sync only — no I/O, no async, no DB calls
        self._parser = PydanticOutputParser(pydantic_object=AgentOutput)
        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "{caso_clinico}"),
        ]).partial(format_instructions=self._parser.get_format_instructions())
        self._llm = create_llm(temperature=0.1)
        self._chain = None

    async def _ensure_chain(self) -> None:
        if self._chain is not None:
            return
        retriever = await get_retriever(k=3)
        self._chain = (
            {"context": retriever | format_docs, "caso_clinico": RunnablePassthrough()}
            | self._prompt | self._llm | self._parser
        )

    async def run(self, caso_clinico: str) -> AgentOutput:
        await self._ensure_chain()
        result = await self._chain.ainvoke(caso_clinico)
        result.agent_name = self.NAME   # always override — LLM cannot be trusted here
        return result
```

**Why `_ensure_chain` exists:** agents are instantiated synchronously inside a list comprehension before `asyncio.gather`. `__init__` cannot await. The retriever fetch (`PGVectorStore.acreate`) is deferred to the first `run()` call.

**Why `result.agent_name = self.NAME`:** `PydanticOutputParser` seeds the LLM prompt with a schema example that contains a hardcoded agent name. The LLM copies it. Always override after parse.

---

## Adding a new agent — checklist

1. Create `app/agents/<yourname>.py` using the pattern above.
2. Add to `AGENT_REGISTRY` in `app/services/integrator.py`.
3. Update `SYSTEM_PROMPT` in `app/agents/router.py`: add to `AGENTES DISPONIBLES` + add a routing rule to `REGLAS DE ACTIVACIÓN`.
4. Write a test asserting `result.agent_name == YourAgent.NAME`.

Do **not** add a new agent to `AGENTS_BY_URGENCY` unless it must activate as a fallback for all cases of that urgency. Specialist agents activate via `agentes_sugeridos` only.

---

## RAG / vector store rules

- The vector store is a **process-level singleton** (`_store` in `app/rag/retriever.py`).
- Use `get_retriever(k=3)` — never call `PGVectorStore.acreate()` directly in an agent.
- `PGVector` (old class) is **deprecated since langchain-postgres 0.0.14** and causes race conditions under `asyncio.gather`. Never use it.
- PGVectorStore connection uses `+psycopg` (psycopg3). SQLAlchemy uses `+asyncpg`. Both coexist intentionally — do not unify them.
- Documents indexed into the vector store live in `docs/`. Add new knowledge there, then re-run the indexer.

---

## LLM / embeddings

- LLM factory: `create_llm(temperature)` in `app/core/llm.py`. Returns `BaseChatModel`. Use this everywhere.
- Provider is selected by `LLM_PROVIDER` in `.env`. Never branch on provider name in agent code.
- Embeddings factory: `get_embeddings()` in `app/rag/embeddings.py`. Same pattern.
- Active in prod: `LLM_PROVIDER=openai_compatible` → Nvidia NIM. Groq and LM Studio also supported.

---

## Temperature guide

| Value | When to use |
|-------|-------------|
| `0.0` | Routing/triage — must be deterministic |
| `0.1` | Safety-critical: cardiology, pharmacology, emergency |
| `0.2` | General clinical: internal medicine, radiology |
| `0.3` | Differential diagnosis — breadth helps |

Do not exceed `0.3` for any clinical agent.

---

## Database rules

- ORM: SQLAlchemy 2.0 async with `Mapped[]` type annotations.
- Session dependency: `get_session()` in `app/db/session.py` — inject via `Depends`.
- Data access: go through `ClinicalCaseRepository` (`app/db/repository.py`). No raw SQL in routes or services.
- Migrations: `uv run alembic revision --autogenerate -m "description"` then `upgrade head`. Never skip migrations for schema changes.

---

## Testing rules

- Framework: `pytest` + `pytest-asyncio`. All async tests use `@pytest.mark.asyncio`.
- Mock the chain directly — do not mock the LLM class or provider:
  ```python
  agent._chain = AsyncMock()
  agent._chain.ainvoke = AsyncMock(return_value=valid_output)
  ```
- Mock `get_retriever` when testing chain assembly:
  ```python
  @patch("app.rag.retriever.get_vector_store", new_callable=AsyncMock)
  ```
- Every new agent must have a test asserting `result.agent_name == AgentClass.NAME`.
- Do not write tests that assert a specific `llm_provider` value — the env may differ.

---

## Security constraints

- **Never commit `.env`, `envs/.env.dev`, or `envs/.env.prod`** — all are gitignored.
- Never log API keys, tokens, or patient data.
- `Cloudflare Access` (email verification) protects the VPS API at `api.jccode.dev` — do not bypass or expose the origin IP.

---

## CI/CD and deployment

- CI: `uv run pytest tests/ -v` → `docker build` check. Runs on every push.
- CD: push to `main` → GitHub Actions → Docker image → GHCR → SSH deploy to VPS at `/opt/apps/clinical-ai`.
- Do not push directly to `main` for non-trivial changes. Use a branch + PR.
- Before deploying after a PGVectorStore schema change: drop `langchain_pg_collection` + `langchain_pg_embedding`, then re-run indexer.

---

## Existing agents

| Class | File | Temp | Activates on |
|-------|------|------|-------------|
| `ClinicalAgent` | `agents/clinical.py` | 0.2 | Always in critical/urgent |
| `EmergencyAgent` | `agents/emergency.py` | 0.1 | Critical/very urgent — ABCDE |
| `DifferentialDiagnosisAgent` | `agents/diagnosis.py` | 0.3 | Ambiguous/multi-system cases |
| `CardiologyAgent` | `agents/cardiology.py` | 0.1 | ECG, arrhythmia, ST changes |
| `PharmacologyAgent` | `agents/pharmacology.py` | 0.1 | Medications, interactions, dosing |
| `RadiologyAgent` | `agents/radiology.py` | 0.2 | X-ray, CT, MRI, US |
| `AgentRouter` | `agents/router.py` | 0.0 | Not in AGENT_REGISTRY — triage only |
