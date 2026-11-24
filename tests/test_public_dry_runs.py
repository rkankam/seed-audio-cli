from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import seed_audio_cli.cli as cli

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_public_readme_dry_runs_work_without_key_or_provider_calls(monkeypatch) -> None:
    monkeypatch.delenv("BYTEPLUS_API_KEY", raising=False)
    monkeypatch.delenv("BYTEPLUS_SEED_AUDIO_URL", raising=False)
    provider_calls: list[dict] = []

    class ForbiddenProviderClient:
        def __init__(self, api_key: str) -> None:
            raise AssertionError("dry-run must not initialize the provider client")

        def create(self, payload: dict) -> None:
            provider_calls.append(payload)

    monkeypatch.setattr(cli, "BytePlusClient", ForbiddenProviderClient)
    monkeypatch.chdir(REPO_ROOT)
    commands = [
        [
            "gen",
            "--prompt",
            "Rain outside a small late-night station.",
            "--dry-run",
            "--json",
        ],
        [
            "batch",
            str(REPO_ROOT / "examples" / "batch.yaml"),
            "--dry-run",
            "--json",
        ],
        [
            "matrix",
            str(REPO_ROOT / "examples" / "matrix.yaml"),
            "--dry-run",
            "--json",
        ],
    ]

    for command in commands:
        result = runner.invoke(cli.app, command)
        assert result.exit_code == 0, result.stdout
        output = json.loads(result.stdout)
        assert output["ok"] is True
        assert all("references" not in run["request"] for run in output["runs"])

    assert provider_calls == []
