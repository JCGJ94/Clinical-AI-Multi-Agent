# Propuesta exacta de pipeline — Clinical AI Multi-Agent

## Contexto validado

- **Proyecto:** `Clinical-AI-Multi-Agent`
- **Carpeta en VPS:** `/opt/apps/clinical-ai`
- **Dominio público:** `api.jccode.dev`
- **DNS:** Cloudflare
- **Reverse proxy:** Traefik ya existente en el VPS
- **Modo real de Traefik:** contenedor Docker
- **Provider real de Traefik:** Docker
- **Red pública compartida esperada:** `proxy`
- **GitHub owner:** `JCGJ94`
- **Usuario de deploy SSH:** `jose`
- **CI/CD:** GitHub Actions
- **Registro de imágenes:** GHCR (`ghcr.io`)

---

## Objetivo

Pasar de un deploy manual basado en `docker compose up --build` a un flujo serio y reproducible:

1. GitHub Actions valida el código
2. GitHub Actions construye y publica imágenes en GHCR
3. GitHub Actions se conecta por SSH al VPS
4. El VPS descarga la nueva imagen, corre migraciones y actualiza el servicio
5. Traefik sigue exponiendo `api.jccode.dev`

---

## Decisiones de arquitectura

### 1) El VPS NO builda imágenes

El build ocurre en GitHub Actions. El VPS solo hace `docker pull`.

**Por qué:**
- reduce tiempo de deploy
- evita drift entre ambientes
- hace al deploy reproducible
- separa build de runtime

### 2) GHCR es la fuente de verdad de las imágenes

Imágenes propuestas:

- `ghcr.io/JCGJ94/clinical-ai-api`
- `ghcr.io/JCGJ94/clinical-ai-indexer`

Tags propuestos:

- `sha-<git_sha>`
- `latest`

### 3) Traefik queda fuera de este repo, pero la app debe integrarse con Docker provider

Este repo no administra Traefik, pero sí debe exponer la app de forma compatible con tu infraestructura real.

**Topología validada para esta propuesta:**
- Traefik corre como contenedor Docker
- Traefik descubre servicios por Docker provider
- `api.jccode.dev` se publicará mediante labels en el servicio `api`
- La API no debe depender de `127.0.0.1:8000`
- La API debe compartir la red Docker externa `proxy` con Traefik

**Conclusión importante:**
- en este proyecto, producción no debe publicarse por loopback del host
- producción debe publicarse por `network + labels`

---

## Estructura objetivo del repo

Archivos a crear o ajustar durante la implementación:

```text
.github/
  workflows/
    ci.yml
    cd.yml

docker/
  compose.yml
  compose.prod.yml
  compose.vps.yml         # override para usar imágenes GHCR en lugar de build local

scripts/
  deploy.sh               # deploy idempotente en VPS
  migrate.sh              # corre alembic upgrade head
  smoke-check.sh          # valida /health o /ready post-deploy

envs/
  env.prod.example
```

---

## Cambios previos requeridos en la app

Antes de activar CD automático, hay que resolver esto:

### A. Startup de producción

**Problema actual:** `app/main.py` ejecuta `Base.metadata.create_all()` siempre.

**Propuesta:**
- agregar variable `ENVIRONMENT=development|production|test`
- en `production`: NO ejecutar `create_all()`
- migraciones solo con Alembic (`alembic upgrade head`)

### A.1. Ejecutar migraciones desde contenedor

**Problema actual adicional:** la imagen `api` hoy copia `app/`, pero no copia `alembic/` ni `alembic.ini`.

**Conclusión técnica:**
- con el Dockerfile actual, `docker compose run --rm api alembic upgrade head` todavía no va a funcionar

**Propuesta:**
- copiar `alembic/` y `alembic.ini` dentro de la imagen `api`, o
- crear un contenedor/imagen de migración dedicado

**Recomendación:**
- para este proyecto conviene reutilizar la imagen `api` y sumarle `alembic/` + `alembic.ini`

### B. Healthcheck

**Problema actual:** `/health` es solo liveness.

**Propuesta:**
- `/health` → proceso vivo
- `/ready` → DB accesible + config mínima válida

### C. Documentación operativa

Actualizar `AGENTS.md` para:
- comandos Unix/Linux reales
- comandos de tests correctos
- proceso de deploy y migraciones

---

## Diseño exacto del pipeline

## Topología objetivo del servidor

```text
Cloudflare (proxied)
  -> api.jccode.dev
  -> IP pública del VPS

Traefik (contenedor Docker en el VPS)
  -> Docker provider
  -> descubre labels del servicio api
  -> enruta tráfico HTTPS

Red Docker externa: proxy
  -> Traefik
  -> clinical-ai api

Stack Clinical AI
  -> postgres (red interna)
  -> api (red interna + proxy)
  -> indexer (red interna)
```

### Red Docker esperada

La red `proxy` debe existir en el VPS antes del primer deploy:

```bash
docker network create proxy
```

Si ya existe porque Traefik la usa, no hay que hacer nada.

## Pipeline 1 — CI

**Archivo:** `.github/workflows/ci.yml`

**Trigger:**
- `pull_request`
- `push` a `main`

**Responsabilidades:**

1. Checkout del repo
2. Setup de Python 3.11
3. Instalar `uv`
4. Sincronizar dependencias con lockfile
5. Ejecutar tests
6. Validar build Docker de `api`
7. Validar build Docker de `indexer`

### Flujo propuesto

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - uses: astral-sh/setup-uv@v4

      - name: Sync dependencies
        run: uv sync --dev

      - name: Run tests
        run: uv run pytest tests/ -v

  docker-build-check:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build API image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile.api
          push: false

      - name: Build Indexer image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile.indexer
          push: false
```

---

## Pipeline 2 — CD

**Archivo:** `.github/workflows/cd.yml`

**Trigger recomendado:**
- `push` a `main`

**Condición:**
- solo si CI pasó

**Responsabilidades:**

1. Checkout
2. Login en GHCR
3. Build y push de imágenes
4. SSH al VPS
5. Pull de imágenes nuevas
6. Migraciones Alembic
7. `docker compose up -d`
8. Smoke check post deploy

### Flujo propuesto

```yaml
name: CD

on:
  push:
    branches: [main]

permissions:
  contents: read
  packages: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata API
        id: meta_api
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository_owner }}/clinical-ai-api
          tags: |
            type=raw,value=latest
            type=raw,value=sha-${{ github.sha }}

      - name: Build and push API image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile.api
          push: true
          tags: ${{ steps.meta_api.outputs.tags }}
          labels: ${{ steps.meta_api.outputs.labels }}

      - name: Extract metadata Indexer
        id: meta_indexer
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository_owner }}/clinical-ai-indexer
          tags: |
            type=raw,value=latest
            type=raw,value=sha-${{ github.sha }}

      - name: Build and push Indexer image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile.indexer
          push: true
          tags: ${{ steps.meta_indexer.outputs.tags }}
          labels: ${{ steps.meta_indexer.outputs.labels }}

      - name: Deploy over SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          port: ${{ secrets.VPS_PORT }}
          script_stop: true
          script: |
            export GIT_SHA=${{ github.sha }}
            export GHCR_USER=${{ github.actor }}
            export GHCR_TOKEN=${{ secrets.GITHUB_TOKEN }}
            cd /opt/apps/clinical-ai
            bash ./scripts/deploy.sh
```

---

## Script exacto de deploy en VPS

**Archivo propuesto:** `scripts/deploy.sh`

### Responsabilidades

1. Validar variables requeridas
2. Loguearse a GHCR
3. Actualizar repo local a `main` para sincronizar compose/scripts
4. Pull de imágenes
5. Correr migraciones
6. Levantar servicios
7. Validar disponibilidad post-deploy

### Flujo propuesto

```bash
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/apps/clinical-ai"
cd "$APP_DIR"

git fetch origin main
git checkout main
git reset --hard origin/main

echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin

export IMAGE_TAG="sha-$GIT_SHA"

docker network inspect proxy >/dev/null 2>&1 || docker network create proxy

docker compose \
  -f docker/compose.yml \
  -f docker/compose.prod.yml \
  -f docker/compose.vps.yml \
  pull api indexer

docker compose \
  -f docker/compose.yml \
  -f docker/compose.prod.yml \
  -f docker/compose.vps.yml \
  run --rm api alembic upgrade head

docker compose \
  -f docker/compose.yml \
  -f docker/compose.prod.yml \
  -f docker/compose.vps.yml \
  up -d postgres api

docker inspect --format='{{.State.Health.Status}}' clinical-ai-api | grep -q healthy
```
```

> Como la API se expondrá por Traefik + red Docker y no por loopback del host, el smoke check local del deploy no debe depender de `127.0.0.1:8000`. La validación correcta es healthcheck de contenedor y, opcionalmente, un check HTTP externo separado contra `https://api.jccode.dev/health` o `/ready`.

---

## Compose específico para VPS

**Archivo propuesto:** `docker/compose.vps.yml`

Este override reemplaza `build:` por `image:` y permite usar tags publicados en GHCR.

```yaml
services:
  api:
    image: ghcr.io/JCGJ94/clinical-ai-api:${IMAGE_TAG:-latest}
    build: null
    networks:
      - clinical-net
      - proxy
    labels:
      - traefik.enable=true
      - traefik.docker.network=proxy
      - traefik.http.routers.clinical-ai.rule=Host(`api.jccode.dev`)
      - traefik.http.routers.clinical-ai.entrypoints=websecure
      - traefik.http.routers.clinical-ai.tls=true
      - traefik.http.services.clinical-ai.loadbalancer.server.port=8000

  indexer:
    image: ghcr.io/JCGJ94/clinical-ai-indexer:${IMAGE_TAG:-latest}
    build: null

networks:
  proxy:
    external: true
```

### Ajuste requerido en `compose.prod.yml`

Para alinear el repo con Traefik Docker provider hay que evitar el publish por loopback del host.

**Hoy:**

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

**Objetivo para VPS con Traefik provider Docker:**

- no depender de `ports` públicos para el servicio `api`
- exponer el puerto interno `8000` solo dentro de Docker
- publicar por labels + red `proxy`

> Si querés mantener compatibilidad con pruebas locales de prod, eso se resuelve mejor con un override separado, no mezclando la topología del VPS con el testing local.

---

## Secrets requeridos en GitHub

### Secrets de pipeline

- `VPS_HOST`
- `VPS_USER`
- `VPS_PORT`
- `VPS_SSH_KEY`

### GHCR

Con GitHub Actions alcanza normalmente con:
- `GITHUB_TOKEN`

### Secrets de runtime

Estos NO deberían venir desde GitHub Actions en cada deploy. Deberían vivir ya en el VPS, por ejemplo en:

- `/opt/apps/clinical-ai/envs/.env.prod`

Ejemplos:
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `DATABASE_URL`
- `LLM_PROVIDER`
- `LLM_MODEL`
- `GROQ_API_KEY`
- `OPENAI_API_KEY`
- `DEBUG=false`
- `ENVIRONMENT=production`

---

## Preparación exacta del VPS

### Layout propuesto

```text
/opt/apps/clinical-ai/
  docker/
  scripts/
  envs/.env.prod
  docker/compose.yml
  docker/compose.prod.yml
  docker/compose.vps.yml
```

### Prerrequisitos

- Docker Engine instalado
- Docker Compose plugin instalado
- Git instalado
- usuario con permisos Docker
- carpeta `/opt/apps/clinical-ai` creada
- repo clonado en `/opt/apps/clinical-ai`
- `envs/.env.prod` creado y completo
- red Docker `proxy` existente
- Traefik ya conectado a la red `proxy`
- Traefik resolviendo labels Docker del servicio `api`

---

## Flujo DNS / Cloudflare / Traefik

### Propuesta operativa

1. Cloudflare administra el DNS de `jccode.dev`
2. `api.jccode.dev` apunta a la IP pública del VPS
3. Traefik recibe tráfico HTTPS
4. Traefik descubre el contenedor `api` por Docker provider
5. Traefik enruta al puerto `8000` interno del servicio `api` sobre la red `proxy`
6. FastAPI responde detrás del proxy

### Nota importante

Si Cloudflare está en modo proxied, perfecto. Pero el certificado TLS efectivo y la política `Full` / `Full (strict)` deben quedar consistentes con Traefik.

### Estado validado actualmente

- `api.jccode.dev` -> `178.104.193.163`
- Cloudflare en modo **proxied** para `api.jccode.dev`
- `jccode.dev` y `www` en **DNS only**

---

## Orden de implementación recomendado

### Fase 1 — Hardening de app
- agregar `ENVIRONMENT`
- desactivar `create_all()` en prod
- agregar `/ready`
- corregir `AGENTS.md`

### Fase 2 — Operación en VPS
- crear `docker/compose.vps.yml`
- crear `scripts/deploy.sh`
- crear `/opt/apps/clinical-ai` y clonar repo
- preparar `/opt/apps/clinical-ai/envs/.env.prod`
- validar Traefik + red `proxy` + labels Docker

### Fase 3 — CI
- crear `.github/workflows/ci.yml`
- tests + build checks

### Fase 4 — CD
- crear `.github/workflows/cd.yml`
- push de imágenes a GHCR
- deploy por SSH al VPS

---

## Riesgos a evitar

### 1) Build en el VPS
Mala idea. Más lento, menos reproducible.

### 2) Migraciones después de levantar la app
Mala idea. La app puede arrancar contra un schema viejo.

### 3) Meter secrets de runtime en GitHub Actions
Mala idea. Mezcla responsabilidades.

### 4) Depender de `latest` solamente
Mala idea. Siempre conservar el tag `sha-<commit>` para trazabilidad.

### 5) Creer que `/health` ya es readiness
No. Son conceptos distintos.

---

## Recomendación final

La opción propuesta es **válida y recomendable** para este proyecto:

- `api.jccode.dev`
- repo clonado en `/opt/apps/clinical-ai`
- GitHub Actions
- GHCR
- deploy remoto por SSH
- Traefik manejado fuera del repo, pero integrado mediante Docker provider + labels

Es una arquitectura sobria, portable y suficientemente profesional para un producto serio en VPS.

No es Kubernetes, y está BIEN. Primero fundamentos sólidos. Después escala.

---

## Siguiente paso sugerido

Implementar en este orden:

1. hardening de producción (`ENVIRONMENT`, migraciones, readiness)
2. `compose.vps.yml` + `deploy.sh`
3. `ci.yml`
4. `cd.yml`
