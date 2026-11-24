from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from typer.testing import CliRunner

import seed_audio_cli.cli as cli
from seed_audio_cli.client import BytePlusError, ProviderResult

runner = CliRunner()
REFERENCE_URL = (
    "https://REF_USER_MARKER:REF_PASS_MARKER@media.example.test/reference.wav"
    "?token=REF_QUERY_MARKER#REF_FRAGMENT_MARKER"
)
RESPONSE_URL = (
    "https://RESPONSE_USER_MARKER:RESPONSE_PASS_MARKER@cdn.example.test/audio.wav"
    "?signature=RESPONSE_QUERY_MARKER#RESPONSE_FRAGMENT_MARKER"
)


def test_dry_run_redacts_url_userinfo_query_and_fragment() -> None:
    result = runner.invoke(
        cli.app,
        [
            "gen",
            "--prompt",
            "Synthetic URL dry-run",
            "--ref",
            REFERENCE_URL,
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert "https://media.example.test/reference.wav" in result.stdout
    for marker in (
        "REF_USER_MARKER",
        "REF_PASS_MARKER",
        "REF_QUERY_MARKER",
        "REF_FRAGMENT_MARKER",
    ):
        assert marker not in result.stdout


def test_legacy_remote_recipe_remains_dry_runnable_with_redacted_output(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "legacy-run"
    run_dir.mkdir()
    recipe = {
        "schema_version": 1,
        "model": "seed-audio-1.0",
        "text_prompt": "Legacy URL replay test",
        "references": [
            {"kind": "audio", "source": REFERENCE_URL, "is_url": True}
        ],
        "audio_config": {"format": "wav"},
    }
    (run_dir / "recipe.json").write_text(json.dumps(recipe), encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["replay", str(run_dir), "--dry-run", "--json"],
    )

    assert result.exit_code == 0
    assert "https://media.example.test/reference.wav" in result.stdout
    for marker in (
        "REF_USER_MARKER",
        "REF_PASS_MARKER",
        "REF_QUERY_MARKER",
        "REF_FRAGMENT_MARKER",
    ):
        assert marker not in result.stdout


def test_provider_and_download_use_raw_urls_but_artifacts_are_redacted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    provider_payloads: list[dict] = []
    downloaded_urls: list[str] = []

    class FakeProviderClient:
        def __init__(self, api_key: str) -> None:
            assert api_key == ""

        def create(self, payload: dict) -> ProviderResult:
            provider_payloads.append(payload)
            return ProviderResult(
                data={
                    "url": RESPONSE_URL,
                    "duration": 1.0,
                    "subtitle": {"source_url": RESPONSE_URL},
                },
                request_id="synthetic-request-id",
                provider_log_id=None,
            )

    class DownloadResponse:
        content = b"synthetic downloaded audio"

        def raise_for_status(self) -> None:
            return None

    class FakeDownloadClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 120.0

        def __enter__(self) -> FakeDownloadClient:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def get(self, url: str) -> DownloadResponse:
            downloaded_urls.append(url)
            return DownloadResponse()

    monkeypatch.setattr(cli, "BytePlusClient", FakeProviderClient)
    monkeypatch.setattr(cli, "api_key", lambda required: None)
    monkeypatch.setattr(httpx, "Client", FakeDownloadClient)

    result = runner.invoke(
        cli.app,
        [
            "gen",
            "--prompt",
            "Synthetic URL persistence test",
            "--ref",
            REFERENCE_URL,
            "--runs-root",
            str(tmp_path / "runs"),
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert provider_payloads[0]["references"][0]["audio_url"] == REFERENCE_URL
    assert downloaded_urls == [RESPONSE_URL]
    for marker in (
        "REF_USER_MARKER",
        "REF_PASS_MARKER",
        "REF_QUERY_MARKER",
        "REF_FRAGMENT_MARKER",
        "RESPONSE_USER_MARKER",
        "RESPONSE_PASS_MARKER",
        "RESPONSE_QUERY_MARKER",
        "RESPONSE_FRAGMENT_MARKER",
    ):
        assert marker not in result.stdout

    output = json.loads(result.stdout)
    run_dir = Path(output["runs"][0]["run_dir"])
    persisted_recipe = json.loads((run_dir / "recipe.json").read_text())
    assert persisted_recipe["references"][0]["source"] == (
        "https://media.example.test/reference.wav"
    )
    assert persisted_recipe["references"][0]["url_redacted"] is True

    json_artifacts = list(run_dir.glob("*.json"))
    for artifact in json_artifacts:
        content = artifact.read_text(encoding="utf-8")
        for marker in (
            "REF_USER_MARKER",
            "REF_PASS_MARKER",
            "REF_QUERY_MARKER",
            "REF_FRAGMENT_MARKER",
            "RESPONSE_USER_MARKER",
            "RESPONSE_PASS_MARKER",
            "RESPONSE_QUERY_MARKER",
            "RESPONSE_FRAGMENT_MARKER",
        ):
            assert marker not in content

    replay_result = runner.invoke(
        cli.app,
        ["replay", str(run_dir), "--dry-run", "--json"],
    )
    assert replay_result.exit_code == 2
    replay_error = json.loads(replay_result.stdout)["error"]
    assert "redacted for security" in replay_error
    assert "provide a new valid URL" in replay_error


def test_error_output_redacts_url_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    error_url = (
        "https://ERROR_USER_MARKER:ERROR_PASS_MARKER@provider.example.test/create"
        "?credential=ERROR_QUERY_MARKER#ERROR_FRAGMENT_MARKER"
    )

    class FailingProviderClient:
        def __init__(self, api_key: str) -> None:
            assert api_key == ""

        def create(self, payload: dict) -> ProviderResult:
            raise BytePlusError(f"simulated provider failure for {error_url}")

    monkeypatch.setattr(cli, "BytePlusClient", FailingProviderClient)
    monkeypatch.setattr(cli, "api_key", lambda required: None)

    result = runner.invoke(
        cli.app,
        [
            "gen",
            "--prompt",
            "Synthetic error redaction test",
            "--ref",
            REFERENCE_URL,
            "--runs-root",
            str(tmp_path / "runs"),
            "--json",
        ],
    )

    assert result.exit_code == 2
    for marker in (
        "REF_USER_MARKER",
        "REF_PASS_MARKER",
        "REF_QUERY_MARKER",
        "REF_FRAGMENT_MARKER",
        "ERROR_USER_MARKER",
        "ERROR_PASS_MARKER",
        "ERROR_QUERY_MARKER",
        "ERROR_FRAGMENT_MARKER",
    ):
        assert marker not in result.stdout
