"""
Smoke test — verifica que los endpoints principales de la API responden correctamente.

Flujo de prueba:
  1. GET  /health              → API levantada y DB conectada
  2. POST /clinical-case/triage  → AgentRouter clasifica el caso
  3. POST /clinical-case/analyze → Integrator ejecuta agentes en paralelo
  4. GET  /clinical-case/{id}    → Repository devuelve el caso guardado

Ejecución:
    uv run python scripts/smoke_test.py

Variables de entorno opcionales:
    BASE_URL=http://localhost:8000   (default)
    TIMEOUT=120                      (segundos por request — los LLMs son lentos)
"""

import asyncio
import json
import os
import sys
from datetime import datetime

import httpx

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = float(os.getenv("TIMEOUT", "120"))

CASO_CLINICO = (
    "Paciente masculino de 58 años con dolor torácico opresivo de 45 minutos de evolución, "
    "irradiado a brazo izquierdo, acompañado de diaforesis profusa y disnea. "
    "Antecedentes: HTA, diabetes tipo 2, fumador de 20 pack-years."
)

SINTOMAS = ["dolor torácico", "irradiación a brazo izquierdo", "diaforesis", "disnea"]


def _print_section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _print_ok(label: str, value: str = "") -> None:
    suffix = f" → {value}" if value else ""
    print(f"  ✓  {label}{suffix}")


def _print_fail(label: str, detail: str = "") -> None:
    suffix = f": {detail}" if detail else ""
    print(f"  ✗  {label}{suffix}")


def _dump(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


async def test_health(client: httpx.AsyncClient) -> bool:
    _print_section("1 / 4  GET /health")
    try:
        r = await client.get(f"{BASE_URL}/health")
        r.raise_for_status()
        data = r.json()
        _print_ok("status", data.get("status", "—"))
        _print_ok("HTTP", str(r.status_code))
        _dump(data)
        return True
    except Exception as exc:
        _print_fail("health check", str(exc))
        return False


async def test_triage(client: httpx.AsyncClient) -> dict | None:
    _print_section("2 / 4  POST /clinical-case/triage")
    payload = {
        "texto_clinico": CASO_CLINICO,
        "sintomas": SINTOMAS,
    }
    print(f"  → texto_clinico: {CASO_CLINICO[:80]}…")
    try:
        r = await client.post(f"{BASE_URL}/clinical-case/triage", json=payload)
        r.raise_for_status()
        data = r.json()
        _print_ok("nivel_urgencia", data.get("nivel_urgencia", "—"))
        _print_ok("agentes_sugeridos", str(data.get("agentes_sugeridos", [])))
        _print_ok("HTTP", str(r.status_code))
        _dump(data)
        return data
    except httpx.HTTPStatusError as exc:
        _print_fail(f"HTTP {exc.response.status_code}", exc.response.text[:200])
        return None
    except Exception as exc:
        _print_fail("triage", str(exc))
        return None


async def test_analyze(client: httpx.AsyncClient, triage: dict | None) -> dict | None:
    _print_section("3 / 4  POST /clinical-case/analyze")
    payload: dict = {"caso_clinico": CASO_CLINICO}

    if triage:
        payload["nivel_urgencia"] = triage.get("nivel_urgencia")
        payload["agentes_sugeridos"] = triage.get("agentes_sugeridos")
        _print_ok("usando resultado del triage")
    else:
        payload["nivel_urgencia"] = "CRITICO"
        _print_ok("triage no disponible — usando nivel_urgencia=CRITICO como fallback")

    print("  (puede tardar 30–90s dependiendo del modelo LLM…)")
    try:
        r = await client.post(f"{BASE_URL}/clinical-case/analyze", json=payload)
        r.raise_for_status()
        data = r.json()
        _print_ok("case_id", str(data.get("case_id", "—")))
        _print_ok("agentes_activados", str(data.get("agentes_activados", [])))
        _print_ok("confidence", str(data.get("confidence", "—")))
        _print_ok("has_red_flags", str(data.get("has_red_flags", "—")))
        _print_ok("success_rate", str(data.get("success_rate", "—")))
        if data.get("failed_agents"):
            print(f"  ⚠  failed_agents: {data['failed_agents']}")
        _print_ok("HTTP", str(r.status_code))
        _dump(data)
        return data
    except httpx.HTTPStatusError as exc:
        _print_fail(f"HTTP {exc.response.status_code}", exc.response.text[:200])
        return None
    except Exception as exc:
        _print_fail("analyze", str(exc))
        return None


async def test_get_case(client: httpx.AsyncClient, analyze: dict | None) -> bool:
    _print_section("4 / 4  GET /clinical-case/{case_id}")
    case_id = analyze.get("case_id") if analyze else None
    if not case_id:
        _print_fail("sin case_id — analyze falló o no devolvió ID")
        return False

    print(f"  → case_id: {case_id}")
    try:
        r = await client.get(f"{BASE_URL}/clinical-case/{case_id}")
        r.raise_for_status()
        data = r.json()
        _print_ok("id", str(data.get("id", "—")))
        _print_ok("created_at", data.get("created_at", "—"))
        _print_ok("HTTP", str(r.status_code))
        _dump(data)
        return True
    except httpx.HTTPStatusError as exc:
        _print_fail(f"HTTP {exc.response.status_code}", exc.response.text[:200])
        return False
    except Exception as exc:
        _print_fail("get case", str(exc))
        return False


async def main() -> None:
    started_at = datetime.now()
    print(f"\n{'═' * 60}")
    print(f"  Clinical AI — Smoke Test")
    print(f"  Target : {BASE_URL}")
    print(f"  Timeout: {TIMEOUT}s por request")
    print(f"  Start  : {started_at.strftime('%H:%M:%S')}")
    print(f"{'═' * 60}")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        health_ok = await test_health(client)
        if not health_ok:
            print("\n  API no disponible — abortando.\n")
            sys.exit(1)

        triage_result = await test_triage(client)
        analyze_result = await test_analyze(client, triage_result)
        case_ok = await test_get_case(client, analyze_result)

    elapsed = (datetime.now() - started_at).total_seconds()
    results = {
        "health": health_ok,
        "triage": triage_result is not None,
        "analyze": analyze_result is not None,
        "get_case": case_ok,
    }
    passed = sum(results.values())
    total = len(results)

    print(f"\n{'═' * 60}")
    print(f"  Resultado: {passed}/{total} tests pasaron  ({elapsed:.1f}s)")
    for name, ok in results.items():
        mark = "✓" if ok else "✗"
        print(f"    {mark}  {name}")
    print(f"{'═' * 60}\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
