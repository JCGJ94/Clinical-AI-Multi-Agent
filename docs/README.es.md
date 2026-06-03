# Clinical AI Multi-Agent

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi)
![LangChain](https://img.shields.io/badge/LangChain-1.2-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?logo=postgresql)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

> [🇬🇧 Read in English](../README.md)

Backend de IA multi-agente de nivel producción para soporte de decisión clínica y paramédica. Recibe una descripción de caso clínico, clasifica la urgencia mediante triaje con LLM, activa agentes especialistas en paralelo y devuelve una evaluación estructurada e integrada.

---

## Arquitectura

```
HTTP POST /clinical-case/analyze
           │
           ▼
    ┌─────────────┐
    │ AgentRouter │  Triaje LLM — clasifica urgencia (CRITICO / MUY_URGENTE /
    │  temp=0.0   │  URGENTE / NO_URGENTE) y selecciona agentes especialistas
    └──────┬──────┘
           │  agentes_sugeridos: ["EmergencyAgent", "CardiologyAgent", ...]
           ▼
    ┌──────────────────────────────────────────────┐
    │               Integrador                     │
    │         asyncio.gather (paralelo)            │
    │                                              │
    │  ┌─────────────┐  ┌──────────────┐           │
    │  │ClinicalAgent│  │EmergencyAgent│  ...       │
    │  └──────┬──────┘  └──────┬───────┘           │
    │         │                │                    │
    │         ▼                ▼                    │
    │     cadena LCEL      cadena LCEL              │
    │  retriever | prompt | llm | parser            │
    │         │                │                    │
    │         └────────────────┘                    │
    │              fusión de resultados             │
    └──────────────────┬───────────────────────────┘
                       │
                       ▼
               AnalyzeOutput
        (summary, findings, red_flags,
         recommendations, confidence,
         agentes_activados, agent_outputs)
```

Cada agente ejecuta una cadena RAG independiente: recupera guías clínicas relevantes desde **pgvector**, construye el prompt, llama al LLM y parsea la respuesta en un `AgentOutput` tipado. El Integrador los combina: unión de findings/red_flags, confianza promedio, resumen del agente con mayor confianza.

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Framework API | FastAPI 0.136 + Uvicorn (async) |
| Orquestación de agentes | LangChain LCEL (`prompt \| llm \| parser`) |
| Proveedores LLM | Nvidia NIM (openai_compatible), Groq, OpenAI, LM Studio |
| Embeddings | NVIDIAEmbeddings / OpenAIEmbeddings — agnóstico de proveedor |
| Vector store | pgvector vía `langchain-postgres` PGVectorStore |
| Base de datos relacional | PostgreSQL + SQLAlchemy 2.0 async + Alembic migrations |
| Validación de datos | Pydantic v2 + pydantic-settings |
| Concurrencia | `asyncio.gather` — agentes en paralelo |
| Contenedores | Docker multi-stage — imágenes separadas para API e indexer |
| CI/CD | GitHub Actions → Docker → GHCR |
| Producción | VPS + Traefik reverse proxy + Let's Encrypt TLS |

---

## Cómo funciona

**1. Llega la solicitud**

```
POST /clinical-case/analyze
{
  "texto_clinico": "Hombre de 65 años, dolor torácico irradiado al brazo izquierdo...",
  "sintomas": ["dolor torácico", "diaforesis", "disnea"]
}
```

**2. Triaje con LLM**

`AgentRouter` corre con `temperature=0.0` (determinista). Clasifica la urgencia y selecciona qué agentes especialistas necesita el caso, basándose en contenido semántico — no solo en el nivel de urgencia:

```
urgency:  MUY_URGENTE
agents:   ["EmergencyAgent", "ClinicalAgent", "CardiologyAgent"]
```

Los agentes especialistas (Cardiología, Farmacología, Radiología) se activan por contenido, no por urgencia. Un ECG activa `CardiologyAgent` sin importar el nivel de urgencia.

**3. Ejecución en paralelo**

Todos los agentes seleccionados corren de forma concurrente. Tres agentes a 2 s cada uno = ~2 s en total, no 6 s:

```python
results = await asyncio.gather(
    *[_safe_run(agent, name, caso, timeout) for agent, name in zip(agents, names)],
    return_exceptions=True,   # fallo parcial → resultado parcial, no abortar
)
```

Cada agente consulta el vector store de forma independiente, recupera guías clínicas relevantes, construye su prompt y parsea una respuesta tipada.

**4. Fusión de resultados**

```
summary:         del agente con mayor confianza
findings:        unión, orden preservado, deduplicado
red_flags:       unión — nunca se descarta una red flag
recommendations: unión, orden preservado, deduplicado
confidence:      promedio entre todos los agentes
```

**5. Resiliencia**

Si un agente falla o supera el timeout, los resultados del resto siguen devolviéndose. Los campos `failed_agents` y `warnings` en `AnalyzeOutput` hacen que la degradación parcial sea explícita y auditable.

---

## Decisiones de diseño clave

### LLM agnóstico de proveedor

Cero cambios de código para cambiar de proveedor LLM — solo cambia el `.env`:

```bash
# Nvidia NIM (producción)
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_API_KEY=nvapi-...
LLM_MODEL=moonshotai/kimi-k2.6

# Groq (iteración rápida en dev)
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile

# Local (dev sin internet)
LLM_PROVIDER=lmstudio
LLM_MODEL=lmstudio-community/llama-3.2-3b
```

La factory `create_llm()` en `app/core/llm.py` devuelve un `BaseChatModel` — todos los agentes usan la misma interfaz sin importar el proveedor.

### Inicialización lazy de la cadena

Los agentes se instancian sincrónicamente al cargar el módulo. La conexión async al retriever (`PGVectorStore.acreate`) no puede ocurrir en `__init__`. Cada agente lo difiere:

```python
def __init__(self) -> None:
    self._chain = None  # se construye en el primer run()

async def _ensure_chain(self) -> None:
    if self._chain is not None:
        return
    retriever = await get_retriever(k=3)
    self._chain = {"context": retriever | format_docs, "caso_clinico": RunnablePassthrough()} \
                  | self._prompt | self._llm | self._parser
```

### Singleton de PGVectorStore

El vector store se inicializa una sola vez por proceso. El double-checked locking garantiza exactamente una llamada a `acreate()` incluso cuando múltiples agentes inicializan de forma concurrente:

```python
async with _store_lock:
    if _store is None:
        _store = await PGVectorStore.acreate(
            embeddings=get_embeddings(),
            collection_name="clinical_docs",
            connection=psycopg_url,
        )
```

Una sola instancia de PostgreSQL sirve tanto datos relacionales (casos, audit logs) como búsqueda vectorial — sin servicio de vector DB separado.

---

## Ejecución local

**Requisitos previos:** Docker, Python 3.12, `uv`

```bash
# 1. Clonar e instalar dependencias
git clone https://github.com/JCGJ94/Clinical-AI-Multi-Agent.git
cd Clinical-AI-Multi-Agent
uv sync

# 2. Configurar entorno
cp envs/.env.example .env
# Editar .env — configurar LLM_PROVIDER, LLM_API_KEY y DATABASE_URL
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/clinical_ai

# 3. Iniciar PostgreSQL con pgvector (dev usa el puerto 5433)
docker compose -f docker/compose.yml -f docker/compose.dev.yml up -d postgres

# 4. Ejecutar migraciones de base de datos
uv run alembic upgrade head

# 5. Indexar la base de conocimiento clínico (una sola vez)
docker compose -f docker/compose.yml -f docker/compose.dev.yml run indexer

# 6. Iniciar la API
uv run uvicorn app.main:app --reload
```

O usar el runner de desarrollo:

```bash
uv run ./scripts/dev.py db-up    # iniciar Postgres
uv run ./scripts/dev.py server   # iniciar API con .env cargado
uv run ./scripts/dev.py smoke    # smoke test de 4 endpoints
```

La API está disponible en `http://localhost:8000`. Documentación interactiva en `http://localhost:8000/docs`.

### Ejecutar tests

```bash
uv run pytest tests/ -v
```

---

## Endpoints de la API

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/health/ready` | Readiness check (DB + vector store) |
| `POST` | `/clinical-case/analyze` | Análisis multi-agente completo |
| `GET` | `/clinical-case/{case_id}` | Recuperar resultado de un caso guardado |

### Ejemplo de solicitud

```bash
curl -X POST http://localhost:8000/clinical-case/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "texto_clinico": "Hombre de 65 años, dolor torácico súbito, diaforesis, ECG con elevación ST en V1-V4.",
    "sintomas": ["dolor torácico", "diaforesis", "elevación ST"]
  }'
```

### Ejemplo de respuesta (abreviado)

```json
{
  "summary": "IAMCEST anterior agudo. Activación inmediata de sala de hemodinámica requerida.",
  "findings": [
    "Elevación ST en V1-V4 compatible con IAMCEST en territorio de DA",
    "FC 98 lpm, ritmo regular"
  ],
  "red_flags": [
    "IAMCEST — objetivo puerta-balón: 90 minutos",
    "Riesgo de shock cardiogénico"
  ],
  "recommendations": [
    "Activar sala de hemodinámica de inmediato",
    "AAS 300mg + dosis de carga de inhibidor P2Y12",
    "Acceso venoso, O2, monitorización continua"
  ],
  "confidence": 0.91,
  "agentes_activados": ["EmergencyAgent", "ClinicalAgent", "CardiologyAgent"],
  "failed_agents": []
}
```

---

## Estructura del proyecto

```
app/
├── agents/
│   ├── base.py          # BaseAgent ABC — contrato que implementan todos los agentes
│   ├── router.py        # AgentRouter — triaje LLM, no es un agente clínico
│   ├── clinical.py      # ClinicalAgent — médico internista general
│   ├── emergency.py     # EmergencyAgent — protocolo ABCDE, casos críticos
│   ├── diagnosis.py     # DifferentialDiagnosisAgent — generación de hipótesis
│   ├── cardiology.py    # CardiologyAgent — interpretación de ECG
│   ├── pharmacology.py  # PharmacologyAgent — seguridad farmacológica, interacciones
│   └── radiology.py     # RadiologyAgent — interpretación de imágenes
├── services/
│   └── integrator.py    # Ejecución paralela + fusión de resultados
├── rag/
│   ├── retriever.py     # Singleton PGVectorStore + get_retriever()
│   ├── embeddings.py    # Factory de embeddings agnóstica de proveedor
│   ├── loader.py        # Chunking de documentos + format_docs()
│   └── chain.py         # Constructor de cadena RAG
├── core/
│   ├── config.py        # pydantic-settings — toda la config desde .env
│   ├── llm.py           # Factory create_llm() — selección de proveedor
│   ├── exceptions.py    # AgentExecutionError, AllAgentsFailedError, etc.
│   └── logging.py       # Logging estructurado en JSON
├── db/
│   ├── models.py        # Modelos ORM async SQLAlchemy 2.0
│   ├── session.py       # Engine async + session factory
│   └── repository.py   # ClinicalCaseRepository
├── models/
│   └── clinical.py      # Modelos Pydantic v2 — AgentOutput, AnalyzeOutput, etc.
├── routes/
│   ├── clinical.py      # Endpoints /clinical-case
│   └── health.py        # Endpoints /health
└── main.py              # App factory FastAPI, eventos lifespan

docs/
├── README.es.md         # Esta documentación (español)
├── architecture/        # Reglas de routing, prioridad de agentes — indexado en RAG
├── prompts/             # Definiciones de system prompts — indexado en RAG
└── guias_clinicas/      # Guías clínicas — indexado en RAG

docker/
├── Dockerfile.api       # Multi-stage — builder + runtime
├── Dockerfile.indexer   # Job de indexación one-shot
└── compose.*.yml        # dev / prod / vps

alembic/                 # Scripts de migración de base de datos
tests/                   # pytest + pytest-asyncio
```

---

## Despliegue

Producción corre en un VPS con:

- **Traefik** como reverse proxy con TLS automático vía Let's Encrypt
- **GitHub Actions** CI/CD: test → build → push a GHCR → deploy vía SSH
- **Docker Compose** (perfil prod): contenedor API + PostgreSQL + pgvector

```
Push a GitHub → workflow de Actions
  → pytest
  → docker build (multi-stage)
  → docker push ghcr.io/...
  → SSH al VPS → docker compose pull + up
```

---

## Fases de desarrollo completadas

| Fase | Qué agregó |
|------|-----------|
| 0–1 | Esqueleto FastAPI, pydantic-settings, `/health` |
| 2 | `ClinicalAgent` con OpenAI SDK (compatible con Groq) |
| 3 | Migración a LangChain LCEL — todas las cadenas usan composición `\|` |
| 4 | Módulos RAG: embeddings, loader de documentos, retriever pgvector |
| 5 | RAG integrado en ClinicalAgent, EmergencyAgent, DifferentialDiagnosisAgent |
| 6 | `AgentRouter` (triaje LLM) + `Integrator` (asyncio.gather) |
| 7 | CardiologyAgent, PharmacologyAgent, RadiologyAgent + routing por contenido |
| 8 | SQLAlchemy 2.0 async, migraciones Alembic, ClinicalCaseRepository |
| 9 | Resiliencia ante fallos parciales (`return_exceptions=True`), timeout por agente |
| 10 | Dockerfile multi-stage, pipeline CI/CD, despliegue en VPS |
| 11 | Factory `create_llm()` — selección de proveedor DRY en todos los agentes |
| 12 | Proveedor `openai_compatible` — Nvidia NIM, DeepSeek, cualquier API compatible |
| 13 | Migración a PGVectorStore (fix de race condition), actualización de deps, Python 3.12 |

---

## Contribuir

Ver `AGENTS.md` en la raíz del proyecto para el contrato completo de agentes, la lógica de inicialización lazy, las reglas del singleton RAG, la guía de temperaturas e instrucciones paso a paso para agregar un nuevo agente especialista.
