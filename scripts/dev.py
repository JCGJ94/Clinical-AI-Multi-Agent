"""
dev.py — Runner de comandos para desarrollo local.

Uso:
    uv run dev.py <comando>

Comandos:
    db-up       Levanta Postgres en Docker (puerto 5433)
    db-down     Baja los contenedores
    server      Uvicorn con hot reload
    dev         Postgres + uvicorn (todo junto)
    test        Test suite completo
    smoke       Smoke test contra localhost:8000
    smoke-prod  Smoke test contra https://api.jccode.dev
    ps          Estado de los contenedores
    logs        Logs del Postgres
"""

import subprocess
import sys

COMPOSE = "docker compose -f docker/compose.yml -f docker/compose.dev.yml"

COMMANDS: dict[str, str] = {
    "db-up":      f"{COMPOSE} up -d postgres",
    "db-down":    f"{COMPOSE} down",
    "server":     "uv run uvicorn app.main:app --reload",
    "test":       "uv run pytest tests/ -v",
    "smoke":      "uv run python scripts/smoke_test.py",
    "smoke-prod": "uv run python scripts/smoke_test.py",
    "ps":         f"{COMPOSE} ps",
    "logs":       f"{COMPOSE} logs -f postgres",
}

ENV_OVERRIDES: dict[str, dict[str, str]] = {
    "smoke-prod": {"BASE_URL": "https://api.jccode.dev"},
}


def print_help() -> None:
    print("\n  Clinical AI — Dev Runner")
    print("  uv run dev.py <comando>\n")
    for name, cmd in COMMANDS.items():
        print(f"    {name:<14} {cmd[:60]}")
    print()


def run(cmd: str, env_extra: dict[str, str] | None = None) -> None:
    import os
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(cmd, shell=True, env=env)
    sys.exit(result.returncode)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "--help", "-h"):
        print_help()
        return

    cmd_name = sys.argv[1]

    if cmd_name == "dev":
        # db-up primero, luego server
        result = subprocess.run(COMMANDS["db-up"], shell=True)
        if result.returncode != 0:
            sys.exit(result.returncode)
        run(COMMANDS["server"])
        return

    if cmd_name not in COMMANDS:
        print(f"\n  Comando desconocido: '{cmd_name}'")
        print("  Corré 'uv run dev.py help' para ver los disponibles.\n")
        sys.exit(1)

    run(COMMANDS[cmd_name], ENV_OVERRIDES.get(cmd_name))


if __name__ == "__main__":
    main()
