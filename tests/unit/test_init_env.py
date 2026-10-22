"""Tests for tools/init_env.py (local .env bootstrap)."""

from pathlib import Path

from tools.init_env import generate_values, main, render_env

TEMPLATE = """# comment with API_KEY=
APP_NAME=NetSentinel
DATABASE_URL=
MIGRATION_DATABASE_URL=
POSTGRES_PASSWORD=
NETSENTINEL_DB_PASSWORD=
API_KEY=
"""


def test_render_env_fills_only_secret_lines() -> None:
    values = generate_values()
    rendered = render_env(TEMPLATE, values)

    assert "# comment with API_KEY=\n" in rendered
    assert "APP_NAME=NetSentinel\n" in rendered
    lines = rendered.splitlines()
    for key, value in values.items():
        assert [line for line in lines if line.startswith(f"{key}=")] == [
            f"{key}={value}"
        ]


def test_render_env_appends_keys_missing_from_template() -> None:
    rendered = render_env("APP_NAME=NetSentinel\n", {"API_KEY": "k"})

    assert rendered == "APP_NAME=NetSentinel\nAPI_KEY=k\n"


def test_database_urls_embed_the_matching_passwords() -> None:
    values = generate_values()

    assert values["POSTGRES_PASSWORD"] != values["NETSENTINEL_DB_PASSWORD"]
    assert values["DATABASE_URL"] == (
        "postgresql+asyncpg://netsentinel_app:"
        f"{values['NETSENTINEL_DB_PASSWORD']}@127.0.0.1:5432/netsentinel"
    )
    assert values["MIGRATION_DATABASE_URL"] == (
        "postgresql+asyncpg://netsentinel:"
        f"{values['POSTGRES_PASSWORD']}@127.0.0.1:5432/netsentinel"
    )


def test_main_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    template = tmp_path / ".env.example"
    template.write_text(TEMPLATE, encoding="utf-8")
    output = tmp_path / ".env"
    output.write_text("API_KEY=keep\n", encoding="utf-8")
    args = ["--template", str(template), "--output", str(output)]

    assert main(args) == 1
    assert output.read_text(encoding="utf-8") == "API_KEY=keep\n"

    assert main([*args, "--force"]) == 0
    assert "API_KEY=keep" not in output.read_text(encoding="utf-8")
