# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Cursor, Gemini, etc.) when working with code in this repository.

## Commands

**Always use the venv Python directly — the system Python lacks the project's packages:**
```bash
# Tests (always this form)
.venv/Scripts/python.exe -m pytest tests/ -v

# Single test
.venv/Scripts/python.exe -m pytest tests/test_agents.py::test_clinical_agent_returns_agent_output -v

# Run server
.venv/Scripts/python.exe -m uvicorn app.main:app --reload

# Install a new dependency
.venv/Scripts/python.exe -m pip install <package>
```

**Docker (required for PostgreSQL + pgvector):**
```bash
docker compose up       # start PostgreSQL
docker compose down     # stop
```

## Architecture

Multi-agent clinical AI backend. The system receives a clinical case, classifies its urgency (triage), activates the relevant specialist agents, and integrates their responses.

### Agent contract

Every agent implements `BaseAgent` (`app/agents/base.py`):
```python
async def run(self, caso_clinico: str) -> AgentOutput
```
`AgentOutput` is the universal output schema — all agents return the same Pydantic model regardless of their specialty.

### LLM provider switching

Provider is controlled entirely by env vars (`llm_provider`, `llm_model`, `groq_api_key`, etc.). **Changing provider = changing `.env`, zero code changes.** The pattern lives in `app/agents/clinical.py` and `app/rag/chain.py`:
```python
if settings.llm_provider == "groq":       llm = ChatGroq(...)
elif settings.llm_provider == "lmstudio": llm = ChatOpenAI(base_url=..., api_key="lm-studio", ...)
else:                                     llm = ChatOpenAI(...)
```

### LangChain LCEL chains

All LLM interaction uses LCEL (`prompt | llm | parser`). The agent chain:
```
{"caso_clinico": str} → ChatPromptTemplate → ChatGroq/ChatOpenAI → PydanticOutputParser → AgentOutput
```
The RAG chain:
```
{"caso_clinico": str} → {context: retriever | _format_docs, caso_clinico: passthrough} → prompt → llm → StrOutputParser
```

### RAG knowledge base

`docs/` is the vector store source — loaded by `app/rag/loader.py` and indexed into pgvector:
- `docs/architecture/` — routing rules, agent priority, clinical flow (used by AgentRouter)
- `docs/prompts/` — system prompt definitions for each specialist agent

`PGVector` in `app/rag/retriever.py` uses `psycopg` (not `asyncpg`). The connection string replaces `+asyncpg` with `+psycopg` — this is intentional, both drivers coexist.

### Key Pydantic models (`app/models/clinical.py`)

`TriageInput` → `TriageOutput` for `/clinical-case/triage`
`AnalyzeInput` → `AnalyzeOutput` for `/clinical-case/analyze`
`AgentOutput` is nested inside `AnalyzeOutput.agent_outputs`

## Testing

Mock pattern for LangChain agents — patch the LLM class, return a `RunnableLambda`:
```python
@patch("app.agents.clinical.ChatGroq")
async def test_something(MockChatGroq):
    from langchain_core.runnables import RunnableLambda
    from langchain_core.messages import AIMessage
    MockChatGroq.return_value = RunnableLambda(
        lambda _: AIMessage(content=json.dumps(VALID_RESPONSE))
    )
```

Mock pattern for RAG chain — patch `get_retriever` in addition to the LLM:
```python
@patch("app.rag.chain.get_retriever")
@patch("app.rag.chain.ChatGroq")
async def test_rag(MockChatGroq, mock_get_retriever):
    mock_get_retriever.return_value = RunnableLambda(lambda _: [Document(...)])
```

RAG loader tests (`test_load_docs_directory_*`) read real files from `docs/` — no mocks needed.

## Development phases

| Phase | Status | What it adds |
|-------|--------|-------------|
| 0–1 | ✅ | FastAPI setup, pydantic-settings, `/health` |
| 2 | ✅ | `ClinicalAgent` with OpenAI SDK (Groq-compatible) |
| 3 | ✅ | Migrated to LangChain LCEL |
| 4 | ✅ | RAG modules: embeddings, loader, retriever, chain |
| 5 | ✅ | RAG integrated in ClinicalAgent, EmergencyAgent, DifferentialDiagnosisAgent |
| 6 | ✅ | `AgentRouter` (LLM triage) + `Integrator` (asyncio.gather parallel execution) |
| 7 | ✅ | `CardiologyAgent`, `PharmacologyAgent`, `RadiologyAgent` + `agentes_sugeridos` pipeline |
| 8 | ✅ | SQLAlchemy 2.0 async, Alembic, `ClinicalCaseRepository`, GET `/{case_id}` |
| 9–10 | ⏳ | Dockerfile multi-stage, deploy |

## Current stubs

- `/clinical-case/triage` returns a **hardcoded mock** — real AgentRouter comes in Phase 6
- `app/db/__init__.py` is empty — populated in Phase 8
- `app/services/` exists in the roadmap but is not yet created
