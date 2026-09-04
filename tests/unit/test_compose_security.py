"""Validate Compose configuration without starting containers or using a DB."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def compose_config():
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not installed")
    version = subprocess.run(
        [docker, "compose", "version"], capture_output=True, timeout=15
    )
    if version.returncode:
        pytest.skip("Docker Compose plugin is not installed")

    def run(admin="test-admin-only", runtime="test-runtime-only"):
        return subprocess.run(
            [
                docker,
                "compose",
                "--env-file",
                str(ROOT / ".env.example"),
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "POSTGRES_PASSWORD": admin,
                "NETSENTINEL_DB_PASSWORD": runtime,
            },
            capture_output=True,
            text=True,
            timeout=15,
        )

    return run


def test_compose_binds_only_loopback_and_preserves_volume(compose_config):
    result = compose_config()
    assert result.returncode == 0, result.stderr
    db = json.loads(result.stdout)["services"]["db"]
    assert len(db["ports"]) == 1
    assert db["ports"][0]["host_ip"] == "127.0.0.1"
    assert db["ports"][0]["target"] == 5432
    assert db["environment"]["POSTGRES_PASSWORD"] == "test-admin-only"
    assert db["environment"]["NETSENTINEL_DB_PASSWORD"] == "test-runtime-only"
    mounts = {volume["target"]: volume for volume in db["volumes"]}
    assert mounts["/var/lib/postgresql/data"]["source"] == "netsentinel_postgres_data"
    assert mounts["/docker-entrypoint-initdb.d/010-runtime-role.sql"]["read_only"]


@pytest.mark.parametrize("missing", ["admin", "runtime"])
def test_compose_refuses_empty_passwords(compose_config, missing):
    result = compose_config(**{missing: ""})
    assert result.returncode != 0
    expected = "POSTGRES_PASSWORD" if missing == "admin" else "NETSENTINEL_DB_PASSWORD"
    assert expected in result.stderr
