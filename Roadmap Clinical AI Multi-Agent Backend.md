# **Roadmap de Desarrollo**

## **Proyecto: Clinical AI Multi-Agent Backend (Python)**

Autor: Jose Carlos González
Objetivo: Construir un backend en Python basado en agentes de IA para asistir a profesionales médicos en el análisis estructurado de casos clínicos.

> **Nota sobre el roadmap**: Este es un proyecto de aprendizaje progresivo. El timeline está pensado para entender cada capa antes de construir la siguiente. No se saltean fases.

---

## Metodología de desarrollo: SDD (Spec-Driven Development)

Antes de escribir una línea de código, cada fase define:

1. **Spec** → qué debe hacer (comportamiento esperado, inputs/outputs)
2. **Design** → cómo lo hace (arquitectura, decisiones técnicas)
3. **Tasks** → checklist de implementación
4. **Apply** → código
5. **Verify** → tests que prueban que el código cumple la spec

> **Por qué SDD**: evita el "vibe-coding" — escribir código sin entender qué se está construyendo. Cada fase del roadmap sigue este ciclo. No pasás a la siguiente fase sin verificar la actual.

---

## Mapa de conceptos fundamentales

Estos son los conceptos que vas a dominar al finalizar el proyecto. Están ordenados por dependencia — no podés entender RAG sin entender embeddings, y no podés entender embeddings sin entender cómo funciona un LLM.

```
LLM Providers (qué son, cómo difieren)
  └── OpenAI SDK (llamadas directas)
        └── LangChain (abstracción sobre el SDK)
              ├── Chains (LCEL: prompt | llm | parser)
              ├── Agents (LLM + tools + memory)
              └── RAG (LLM + documentos + búsqueda semántica)
                    ├── Embeddings (representación vectorial del texto)
                    ├── Vector Store (búsqueda por similitud)
                    └── Retriever (busca contexto relevante antes de responder)
```

---

## Proveedores LLM: comparativa

Entender los providers ANTES de empezar es clave. LangChain abstrae todos — cambiar de provider es cambiar una línea de código.

| Provider | Modelo de ejemplo | Coste | Privacidad | Velocidad | Cuándo usarlo |
|---------|------------------|-------|-----------|-----------|--------------|
| **OpenAI** | gpt-4o-mini, gpt-4o | Pago por tokens | Cloud (datos salen) | Alta | Producción, calidad máxima |
| **Groq** | llama3-70b, mixtral-8x7b | **Gratis** (free tier) | Cloud | **Muy alta** (hardware dedicado) | Desarrollo y testing gratuito |
| **LM Studio** | Llama3, Mistral, Phi-3 | **Gratis** (local) | **100% local** | Depende de tu hardware | Datos sensibles, sin internet |
| **OpenRouter** | 100+ modelos | Free + pago | Cloud | Variable | Exploración de modelos |

### Estrategia para este proyecto
```
Desarrollo local   → Groq (gratis, rápido) o LM Studio (privacidad total)
Testing CI         → Groq (free tier)
Demo / Portfolio   → OpenAI gpt-4o-mini (calidad visible, bajo costo)
Producción real    → OpenAI gpt-4o
```

### Cómo LangChain hace posible el cambio de provider
```python
# Groq (desarrollo gratuito)
from langchain_groq import ChatGroq
llm = ChatGroq(model="llama3-70b-8192")

# LM Studio (local, privacidad total)
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

# OpenAI (producción)
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4o-mini")

# El resto del código NO cambia. Eso es el valor de LangChain.
chain = prompt | llm | parser
```

---

## Stack definitivo

| Capa | Tecnología |
|------|-----------|
| Backend Framework | FastAPI (async) |
| Lenguaje | Python 3.11+ |
| Validación | Pydantic v2 |
| LLM Provider (dev) | Groq (gratis) / LM Studio (local) |
| LLM Provider (prod) | OpenAI gpt-4o-mini / gpt-4o |
| Orquestación LLM | LangChain (LCEL) |
| RAG | LangChain + pgvector (PostgreSQL como vector store) |
| Base de datos | PostgreSQL + SQLAlchemy async |
| Vector Store | pgvector (extensión PostgreSQL) |
| Contenedores | Docker + docker-compose |
| Testing | pytest + httpx |
| Secrets | python-dotenv + .env |
| Deploy | Railway o Fly.io |
| Infraestructura avanzada | Kubernetes (fase opcional) |

---

## Arquitectura del sistema (con RAG)

```
Cliente
  → API FastAPI (async)
    → AgentRouter (triage + selección)
      ↓                         ↓
  Agentes LLM              RAG Retriever
  (LangChain)              (pgvector)
      ↓                         ↓
  ClinicalAgent  ←──── contexto de guías clínicas
  EmergencyAgent ←──── protocolos de urgencia
  DiagnosisAgent ←──── base de diagnósticos
  CardiologyAgent ←─── guías cardiológicas
  PharmacologyAgent ←── base de medicamentos e interacciones
  RadiologyAgent ←───── hallazgos radiológicos de referencia
      ↓
  Integrator (combina respuestas)
      ↓
  Respuesta estructurada al cliente
  → PostgreSQL (persistencia + auditoría + vectores)
```

---

# **Fase 0 — Setup y Fundamentos (Semana 1)**

**Objetivo**: entorno listo, estructura clara, sin código de negocio aún.

### SDD para esta fase
- **Spec**: el proyecto arranca con `uvicorn app.main:app` y responde `GET /health`
- **Design**: pydantic-settings carga config desde `.env`; logging configurado desde el inicio
- **Verify**: `GET /health` devuelve `{"status": "ok"}` — si no, no pasás a Fase 1

### Estructura del proyecto

```
app/
  main.py              # Entry point FastAPI
  core/
    config.py          # Settings con pydantic-settings
    logging.py         # Logging estructurado
  routes/
    clinical.py        # Endpoints clínicos
    health.py          # GET /health
  models/
    clinical.py        # Pydantic v2 schemas (input/output)
  services/
    triage.py          # Lógica de clasificación
    integrator.py      # Combina respuestas de agentes
  agents/
    base.py            # BaseAgent (clase abstracta)
    clinical.py
    emergency.py
    diagnosis.py
    cardiology.py
    pharmacology.py
    radiology.py
    router.py          # AgentRouter
  rag/
    embeddings.py      # Configuración de embeddings
    retriever.py       # Búsqueda semántica
    loader.py          # Carga de documentos clínicos
  db/
    session.py         # Conexión async PostgreSQL
    models.py          # SQLAlchemy models
tests/
  test_routes.py
  test_agents.py
  test_rag.py
.env
.env.example
docker-compose.yml
Dockerfile
requirements.txt
```

### Tareas
- [ ] Crear entorno virtual (`python -m venv .venv`)
- [ ] Instalar deps base: `fastapi uvicorn pydantic pydantic-settings python-dotenv`
- [ ] Configurar `.env` con `OPENAI_API_KEY`, `GROQ_API_KEY`, `DATABASE_URL`
- [ ] `GET /health` funcionando
- [ ] `core/config.py` con `pydantic-settings` cargando env vars

---

# **Fase 1 — FastAPI Async: API Base (Semana 1-2)**

**Objetivo**: dominar FastAPI async antes de tocar LLMs. Los endpoints existen pero devuelven respuestas mockeadas.

### SDD para esta fase
- **Spec**: los tres endpoints existen, validan input con Pydantic, devuelven estructura correcta
- **Design**: async def, Depends para inyección, HTTPException para errores
- **Verify**: tests con `httpx.AsyncClient` pasan al 100%

### Conceptos a aprender
- `async def` vs `def` en FastAPI — cuándo y por qué
- Pydantic v2: `BaseModel`, `Field`, `model_validator`
- Dependency Injection con `Depends`
- Error handling con `HTTPException` y handlers globales
- Logging estructurado

### Endpoints

**POST /clinical-case/triage**
```
Input:  texto_clinico, sintomas: list[str], contexto
Output: nivel_urgencia (CRITICO|MUY_URGENTE|URGENTE|NO_URGENTE), agentes_sugeridos, razonamiento
```

**POST /clinical-case/analyze**
```
Input:  caso_clinico, nivel_urgencia
Output: summary, findings, red_flags, recommendations, confidence, agentes_activados
```

**GET /health**
```
Output: status, version, timestamp
```

### Tareas
- [ ] Pydantic v2 models para todos los endpoints
- [ ] Endpoints con respuestas mockeadas (sin LLM)
- [ ] Logging estructurado
- [ ] Tests con `pytest` + `httpx.AsyncClient`
- [ ] 100% de tests pasando antes de continuar

---

# **Fase 2 — OpenAI SDK: Primer Agente (Semana 2)**

**Objetivo**: conectar UN agente a OpenAI. Entender la API base antes de usar LangChain.

### SDD para esta fase
- **Spec**: `ClinicalAgent.run(caso)` devuelve `AgentOutput` validado con Pydantic
- **Design**: `AsyncOpenAI`, structured outputs con `response_format`
- **Verify**: test con caso clínico real devuelve estructura correcta; mock para CI

### Conceptos a aprender
- OpenAI SDK: `AsyncOpenAI`, `chat.completions.create`
- System prompts vs user prompts — diferencia y cuándo usar cada uno
- Structured outputs: `response_format` + Pydantic
- Manejo de errores: rate limits, timeouts, `RateLimitError`
- Control de costos: `gpt-4o-mini` (10x más barato que `gpt-4o`)
- Alternativa gratuita: mismo código con Groq (`langchain_groq`)

### Tareas
- [ ] Instalar `openai`
- [ ] Implementar `BaseAgent` abstracto
- [ ] Implementar `ClinicalAgent` con OpenAI SDK directo
- [ ] Conectar al endpoint `/clinical-case/analyze`
- [ ] Test: mockear OpenAI con `pytest-mock`
- [ ] Probar con Groq como alternativa gratuita

---

# **Fase 3 — LangChain Core (Semana 2-3)**

**Objetivo**: entender LangChain migrando el `ClinicalAgent` de SDK directo a LCEL. Ver el contraste.

### SDD para esta fase
- **Spec**: `ClinicalAgent` produce el mismo output que en Fase 2, pero usa LangChain internamente
- **Design**: `ChatPromptTemplate | ChatOpenAI | PydanticOutputParser`
- **Verify**: los tests de Fase 2 siguen pasando sin cambios

### Conceptos a aprender
- LCEL: el operador `|` encadena componentes (`prompt | llm | parser`)
- `ChatPromptTemplate`: plantillas con variables
- `ChatOpenAI` vs `ChatGroq` vs `ChatOpenAI(base_url=LMStudio)` — misma interfaz
- `PydanticOutputParser`: salida validada automáticamente
- Callbacks: observabilidad de chains (cuántos tokens, cuánto tiempo)
- Por qué LangChain sobre SDK directo: abstracción de providers, composición, observabilidad

### Tareas
- [ ] Instalar `langchain langchain-openai langchain-groq`
- [ ] Reescribir `ClinicalAgent` con LCEL
- [ ] Probar el mismo agente con Groq (cambiar una línea)
- [ ] Probar con LM Studio (cambiar `base_url`)
- [ ] Tests de Fase 2 siguen pasando
- [ ] Documentar diferencia SDK directo vs LangChain en comentarios

---

# **Fase 4 — RAG: Fundamentos (Semana 3)**

**Objetivo**: entender RAG antes de aplicarlo. Es un concepto fundamental — no saltear esta fase.

### ¿Qué es RAG?

```
Sin RAG:
  pregunta → LLM → respuesta (basada solo en lo que el LLM aprendió en entrenamiento)

Con RAG:
  pregunta → buscar documentos relevantes → [documentos + pregunta] → LLM → respuesta
```

El LLM no "sabe" de tus guías clínicas internas. RAG le inyecta ese conocimiento en cada llamada.

### Conceptos a aprender

**Embeddings**
- Un embedding es un vector numérico que representa el significado semántico de un texto
- "dolor torácico" y "angina de pecho" tienen embeddings muy cercanos aunque las palabras sean distintas
- Modelo: `text-embedding-3-small` (OpenAI) o `nomic-embed-text` (local con LM Studio)

**Vector Store**
- Base de datos que almacena embeddings y permite búsqueda por similitud
- Usaremos `pgvector` — extensión de PostgreSQL (no necesitamos Pinecone ni Chroma)
- Ventaja: un solo contenedor Docker para datos relacionales Y vectoriales

**Retriever**
- Componente que dada una query, busca los N documentos más relevantes en el vector store
- LangChain tiene retrievers prebuilt que se conectan a pgvector

**RAG Chain completa (LCEL)**
```python
rag_chain = (
    {"context": retriever, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)
```

### Aplicación en este proyecto
- Cargar guías clínicas (PDF/texto) → chunking → embeddings → pgvector
- Cada agente hace RAG antes de responder: busca guías relevantes para el caso clínico

### Tareas
- [ ] Instalar `langchain-postgres pgvector psycopg`
- [ ] Habilitar extensión `pgvector` en PostgreSQL
- [ ] Cargar un documento de guías clínicas de ejemplo (PDF o texto)
- [ ] Generar embeddings y almacenarlos en pgvector
- [ ] Implementar `Retriever` que busca guías por similitud semántica
- [ ] Construir RAG chain básica y probarla con un caso clínico

---

# **Fase 5 — Agentes con RAG (Semana 4)**

**Objetivo**: integrar RAG en los agentes — cada agente consulta su base de conocimiento especializada.

### SDD para esta fase
- **Spec**: `ClinicalAgent.run(caso)` primero recupera guías relevantes, luego genera respuesta
- **Design**: `retriever | prompt | llm | parser` — el retriever inyecta contexto
- **Verify**: la respuesta del agente cita o referencia el contexto recuperado

### Agentes iniciales con RAG

| Agente | Base de conocimiento |
|--------|---------------------|
| `ClinicalAgent` | Guías clínicas generales |
| `EmergencyAgent` | Protocolos de urgencias |
| `DifferentialDiagnosisAgent` | Base de diagnósticos diferenciales |

### Tareas
- [ ] Cargar documentos especializados por agente
- [ ] Retriever por dominio (un vector store o colecciones separadas)
- [ ] Integrar RAG en `ClinicalAgent` primero
- [ ] Migrar `EmergencyAgent` y `DifferentialDiagnosisAgent`
- [ ] Tests: verificar que el retriever devuelve contexto relevante

---

# **Fase 6 — AgentRouter + Multi-Agente (Semana 4)**

**Objetivo**: el sistema decide qué agentes activar y los ejecuta en paralelo.

### Conceptos a aprender
- Patrón Router / Dispatcher
- `asyncio.gather` para ejecución paralela de agentes
- Cómo combinar respuestas de múltiples agentes

### Agentes a implementar

| Agente | Cuándo se activa |
|--------|-----------------|
| `ClinicalAgent` | siempre |
| `EmergencyAgent` | urgencia CRITICO o MUY_URGENTE |
| `DifferentialDiagnosisAgent` | siempre junto a ClinicalAgent |

### Flujo
```
input → triage → AgentRouter → asyncio.gather(agent1, agent2, ...) → Integrator → respuesta
```

### Tareas
- [ ] Implementar `AgentRouter` con lógica de selección
- [ ] Ejecución paralela con `asyncio.gather`
- [ ] `Integrator` que combina salidas en una respuesta única
- [ ] Tests de integración del flujo completo

---

# **Fase 7 — Agentes Especializados (Semana 5)**

**Objetivo**: completar el sistema con agentes de dominio específico, todos con RAG.

| Agente | Dominio | Base de conocimiento |
|--------|---------|---------------------|
| `CardiologyAgent` | ECG, síntomas cardíacos | Guías ESC / ACC |
| `PharmacologyAgent` | Medicación, interacciones | Base de datos de fármacos |
| `RadiologyAgent` | Hallazgos radiológicos (texto) | Guías de radiología |

### Formato de salida estándar

```python
class AgentOutput(BaseModel):
    agent_name: str
    summary: str
    findings: list[str]
    red_flags: list[str]
    recommendations: list[str]
    confidence: float        # 0.0 - 1.0
    context_sources: list[str]  # documentos usados por RAG
```

### Tareas
- [ ] Implementar los tres agentes con LangChain + RAG
- [ ] Actualizar `AgentRouter`
- [ ] Tests unitarios por agente
- [ ] Test de integración: 6 agentes activados en paralelo

---

# **Fase 8 — Persistencia (Semana 5-6)**

**Objetivo**: guardar casos, logs de agentes y trazabilidad completa.

### Tablas

```
clinical_cases       → id, texto_clinico, nivel_urgencia, created_at
triage_results       → id, case_id, nivel_urgencia, agentes_sugeridos, razonamiento
agent_logs           → id, case_id, agent_name, input, output, duration_ms, context_sources
analysis_results     → id, case_id, summary, findings, red_flags, recommendations, agentes_activados
```

### Conceptos a aprender
- SQLAlchemy async con `asyncpg`
- Migraciones con Alembic
- Repository pattern

### Tareas
- [ ] Instalar `sqlalchemy asyncpg alembic`
- [ ] Modelos SQLAlchemy + primera migración Alembic
- [ ] Guardar cada análisis en DB
- [ ] Tests con PostgreSQL en Docker

---

# **Fase 9 — Docker (Semana 6)**

**Objetivo**: API + PostgreSQL + pgvector corriendo en contenedores.

### docker-compose.yml (servicios)
```
api        → FastAPI + uvicorn
postgres   → PostgreSQL 16 + pgvector extension
```

### Tareas
- [ ] `Dockerfile` multi-stage
- [ ] `docker-compose.yml` con `api` y `postgres`
- [ ] `docker compose up` levanta todo el sistema
- [ ] Tests pasan dentro del contenedor

---

# **Fase 10 — Deploy (Semana 6-7)**

### Opciones recomendadas

| Plataforma | Pros | Contras |
|-----------|------|---------|
| Railway | Fácil, PostgreSQL incluido, gratis tier | Límites en free tier |
| Fly.io | Más control, buen free tier | Más configuración |
| VPS + Docker | Control total | Más mantenimiento |

### Tareas
- [ ] Configurar secrets en la plataforma (no en código)
- [ ] Deploy inicial
- [ ] Verificar endpoints en producción

---

# **Fase 11 — Avanzada (Opcional)**

### LangChain avanzado
- Memoria conversacional (`ConversationBufferMemory`)
- Streaming de respuestas via SSE
- LangSmith para observabilidad de chains

### RAG avanzado
- Re-ranking de documentos recuperados
- Evaluación de calidad RAG (ragas framework)
- RAG con imágenes: análisis multimodal ECG/RX con gpt-4o vision

### Infraestructura
- Kubernetes: Deployment, Service, Ingress, ConfigMaps, Secrets, Autoscaling

---

# **Resultado esperado**

Sistema backend que:
- Recibe casos clínicos en texto
- Clasifica urgencia automáticamente
- Recupera guías clínicas relevantes via RAG
- Activa agentes especializados en paralelo
- Cada agente razona con conocimiento médico recuperado dinámicamente
- Integra respuestas en un análisis estructurado
- Persiste casos y auditoría completa
- Corre en Docker y está deployado

Stack final:
- Python 3.11+ · FastAPI async · Pydantic v2
- OpenAI / Groq / LM Studio (intercambiables via LangChain)
- LangChain + LCEL · RAG · pgvector
- PostgreSQL + SQLAlchemy async · Alembic
- Docker · pytest + httpx

**Proyecto ideal para portfolio Backend AI Engineer.**
