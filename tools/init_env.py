"""Create a local .env with fresh random secrets for the Docker Compose stack.

Run from the repository root: python -m tools.init_env [--force]

The file is copied from .env.example and these values are filled in:
POSTGRES_PASSWORD, NETSENTINEL_DB_PASSWORD, DATABASE_URL,
MIGRATION_DATABASE_URL and API_KEY. Secrets are hexadecimal, so the
database URLs need no percent-encoding.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

DB_HOST = "127.0.0.1:5432"
DB_NAME = "netsentinel"


def database_url(user: str, password: str) -> str:
    return f"postgresql+asyncpg://{user}:{password}@{DB_HOST}/{DB_NAME}"


def generate_values() -> dict[str, str]:
    admin_password = secrets.token_hex(16)
    app_password = secrets.token_hex(16)
    return {
        "POSTGRES_PASSWORD": admin_password,
        "NETSENTINEL_DB_PASSWORD": app_password,
        "DATABASE_URL": database_url("netsentinel_app", app_password),
        "MIGRATION_DATABASE_URL": database_url("netsentinel", admin_password),
        "API_KEY": secrets.token_urlsafe(32),
    }


def render_env(template: str, values: dict[str, str]) -> str:
    """Return ``template`` with the ``KEY=`` lines of ``values`` filled in."""
    pending = dict(values)
    lines: list[str] = []
    for line in template.splitlines():
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in pending:
            line = f"{key}={pending.pop(key)}"
        lines.append(line)
    lines.extend(f"{key}={value}" for key, value in pending.items())
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing .env file"
    )
    parser.add_argument("--template", type=Path, default=Path(".env.example"))
    parser.add_argument("--output", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)

    if args.output.exists() and not args.force:
        print(
            f"{args.output} already exists; keeping it. Use --force to replace it "
            "(an existing database volume keeps its old passwords).",
            file=sys.stderr,
        )
        return 1

    template = args.template.read_text(encoding="utf-8")
    args.output.write_text(render_env(template, generate_values()), encoding="utf-8")
    print(f"Wrote {args.output} with new database passwords and API_KEY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
