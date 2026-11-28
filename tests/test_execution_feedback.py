from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import wave
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import seed_audio_cli.cli as cli
from seed_audio_cli.client import BytePlusError, ProviderResult
from seed_audio_cli.models import ReplayRecipe, ReplayReference

runner = CliRunner()


def _write_wav(path: Path, *, duration_seconds: int = 1) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * duration_seconds)


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    behavior: Callable | None = None,
    response_data: dict | None = None,
) -> list[dict]:
    calls: list[dict] = []
    data = response_data or {
        "audio": base64.b64encode(b"synthetic generated audio").decode("ascii"),
        "duration": 2.5,
        "original_duration": 3.0,
    }

    class RecordingClient:
        def __init__(self, api_key: str) -> None:
            assert api_key == ""

        def create_observed(self, payload, *, on_request_start, on_response_received):
            calls.append(payload)
            on_request_start("synthetic-request-id")
            if behavior is not None:
                return behavior(
                    payload,
                    on_request_start,
                    on_response_received,
                    len(calls),
                )
            on_response_received("synthetic-provider-log-id")
            return ProviderResult(
                data=data,
                request_id="synthetic-request-id",
                provider_log_id="synthetic-provider-log-id",
            )

    monkeypatch.setattr(cli, "BytePlusClient", RecordingClient)
    monkeypatch.setattr(cli, "api_key", lambda required: None)
    return calls


def _invoke_gen(tmp_path: Path, *args: str):
    return runner.invoke(
        cli.app,
        [
            "gen",
            "--prompt",
            "A synthetic voice line.",
            "--runs-root",
            str(tmp_path / "runs"),
            *args,
        ],
    )


def test_ux_t01_text_only_generation_shows_inputs_and_real_stages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    calls = _install_provider(monkeypatch)

    result = _invoke_gen(tmp_path)

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    for expected in (
        "SEED AUDIO / GEN",
        "Generations",
        "Mode",
        "[01/01] run",
        "INPUTS",
        "Model",
        "seed-audio-1.0",
        "A synthetic voice line.",
        "References",
        "    None",
        "Sample rate",
        "omitted (provider default)",
        "Input validated",
        "API request started",
        "API response received",
        "Persisting run artifacts",
        "Audio and metadata saved",
        "GEN COMPLETED",
        "1/1",
        "Audio produced",
        "2.5s",
        "Billable audio",
        "3.0s",
    ):
        assert expected in result.output


def test_ux_t02_local_audio_reference_metadata_is_displayed_without_base64(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    reference = tmp_path / "voice.wav"
    _write_wav(reference)
    calls = _install_provider(monkeypatch)

    result = _invoke_gen(tmp_path, "--ref", str(reference))

    assert result.exit_code == 0, result.output
    assert "@Audio1" in result.output
    assert "WAV" in result.output
    assert "16.0 KB" in result.output
    assert "1.0s" in result.output
    encoded = base64.b64encode(reference.read_bytes()).decode("ascii")
    assert encoded not in result.output
    assert "audio_data" not in result.output
    assert calls[0]["references"][0]["audio_data"] == encoded


def test_ux_t03_image_metadata_is_displayed_and_duration_is_not_invented(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    image = tmp_path / "character.png"
    image.write_bytes(b"synthetic-png-fixture")
    _install_provider(monkeypatch)

    result = _invoke_gen(tmp_path, "--image", str(image))

    assert result.exit_code == 0, result.output
    assert "Image 1" in result.output
    assert "PNG" in result.output
    assert "21 B" in result.output
    assert "Audio duration" in result.output
    assert "References" in result.output
    assert "1.0s" not in result.output


def test_ux_t04_sensitive_reference_url_is_redacted_in_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    url = "https://user:pass@media.example.test/ref.wav?token=query-secret#fragment-secret"
    calls = _install_provider(monkeypatch)

    result = _invoke_gen(tmp_path, "--ref", url)

    assert result.exit_code == 0, result.output
    assert "https://media.example.test/ref.wav" in result.output
    assert "query-secret" not in result.output
    assert "fragment-secret" not in result.output
    assert "user" not in result.output
    assert calls[0]["references"][0]["audio_url"] == url


def test_ux_t05_variations_repeat_complete_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    calls = _install_provider(monkeypatch)

    result = _invoke_gen(tmp_path, "-n", "2")

    assert result.exit_code == 0, result.output
    assert len(calls) == 2
    assert result.output.count("INPUTS") == 2
    assert result.output.count("A synthetic voice line.") == 2
    assert re.search(r"Variation\s+1/2", result.output)
    assert re.search(r"Variation\s+2/2", result.output)
    assert "[01/02] run-01" in result.output
    assert "[02/02] run-02" in result.output


def test_ux_t06_batch_reports_count_order_and_stops_at_actual_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    calls = _install_provider(monkeypatch)
    workflow = tmp_path / "batch.yaml"
    workflow.write_text(
        yaml.safe_dump(
            {
                "jobs": [
                    {"id": "beta", "prompt": "First synthetic prompt", "variations": 2},
                    {"id": "alpha", "prompt": "Second synthetic prompt"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        cli.app,
        ["batch", str(workflow), "--runs-root", str(tmp_path / "runs")],
    )

    assert result.exit_code == 0, result.output
    assert len(calls) == 3
    assert re.search(r"Jobs\s+2", result.output)
    assert re.search(r"Generations\s+3", result.output)
    positions = [
        result.output.index("[01/03] beta-01"),
        result.output.index("[02/03] beta-02"),
        result.output.index("[03/03] alpha"),
    ]
    assert positions == sorted(positions)


def test_ux_t07_matrix_reports_inherited_effective_values_in_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    class ForbiddenClient:
        def __init__(self, api_key: str) -> None:
            raise AssertionError("dry-run must not initialize the provider client")

    monkeypatch.setattr(cli, "BytePlusClient", ForbiddenClient)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Inherited matrix prompt", encoding="utf-8")
    workflow = tmp_path / "matrix.yaml"
    workflow.write_text(
        yaml.safe_dump(
            {
                "base": {
                    "model": "synthetic-model-id",
                    "variations": 2,
                    "output": {
                        "format": "wav",
                        "sample_rate": 48000,
                        "speech_rate": -5,
                        "loudness_rate": 2,
                        "pitch_rate": 1,
                    },
                    "watermark": {"aigc_watermark": True},
                },
                "runs": [{"id": "inherited", "prompt_file": "prompt.txt"}],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        cli.app,
        ["matrix", str(workflow), "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.stderr
    assert "Workflow loaded" in result.stderr
    assert re.search(r"Jobs\s+1", result.stderr)
    assert re.search(r"Generations\s+2", result.stderr)
    assert "synthetic-model-id" in result.stderr
    assert re.search(r"Sample rate\s+48000 Hz", result.stderr)
    assert re.search(r"Speech rate\s+-5", result.stderr)
    assert re.search(r"Loudness rate\s+2", result.stderr)
    assert re.search(r"Pitch rate\s+1", result.stderr)
    assert re.search(r"Watermark\s+true", result.stderr)
    assert "no provider call was made" in result.stderr
    assert "API request started" not in result.stderr
    assert json.loads(result.stdout)["ok"] is True


def test_gen_dry_run_exposes_full_watermark_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    class ForbiddenClient:
        def __init__(self, api_key: str) -> None:
            raise AssertionError("dry-run must not initialize the provider client")

    monkeypatch.setattr(cli, "BytePlusClient", ForbiddenClient)
    result = _invoke_gen(
        tmp_path,
        "--aigc-watermark",
        "--aigc-metadata-enable",
        "--content-producer",
        "seed-audio-cli",
        "--produce-id",
        "production-123",
        "--content-propagator",
        "studio",
        "--propagate-id",
        "distribution-456",
        "--dry-run",
        "--json",
    )

    assert result.exit_code == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["runs"][0]["request"]["watermark"] == {
        "aigc_watermark": True,
        "aigc_metadata": {
            "enable": True,
            "content_producer": "seed-audio-cli",
            "produce_id": "production-123",
            "content_propagator": "studio",
            "propagate_id": "distribution-456",
        },
    }
    assert re.search(r"Implicit watermark\s+true", result.stderr)
    assert re.search(r"Content producer\s+seed-audio-cli", result.stderr)


def test_ux_t08_replay_reports_verified_recipe_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "historical-run"
    reference_dir = source / "refs"
    reference_dir.mkdir(parents=True)
    reference = reference_dir / "voice.wav"
    _write_wav(reference)
    content = reference.read_bytes()
    recipe = ReplayRecipe(
        text_prompt="Synthetic replay prompt",
        references=[
            ReplayReference(
                kind="audio",
                source="refs/voice.wav",
                sha256=hashlib.sha256(content).hexdigest(),
                bytes=len(content),
                duration_seconds=1.0,
            )
        ],
    )
    (source / "recipe.json").write_text(
        recipe.model_dump_json(exclude_none=True),
        encoding="utf-8",
    )

    result = runner.invoke(
        cli.app,
        ["replay", str(source), "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.stderr
    assert "Replay recipe loaded" in result.stderr
    assert "Local replay reference integrity verified" in result.stderr
    assert "Replay inputs reconstructed and validated" in result.stderr
    assert "@Audio1" in result.stderr
    assert "refs/voice.wav" in result.stderr
    assert "no provider call was made" in result.stderr
    output = json.loads(result.stdout)
    assert output["ok"] is True
    assert output["request"]["references"][0]["audio_data"] == "<base64 omitted>"


def test_ux_t09_dry_run_shows_plan_without_provider_or_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    class ForbiddenClient:
        def __init__(self, api_key: str) -> None:
            raise AssertionError("dry-run must not initialize the provider client")

    monkeypatch.setattr(cli, "BytePlusClient", ForbiddenClient)

    result = _invoke_gen(tmp_path, "--dry-run", "--json")

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True
    assert "GEN DRY RUN PREPARED" in result.stderr
    assert "Dry-run plan prepared; no provider call was made" in result.stderr
    assert "API request started" not in result.stderr
    assert "Persisting run artifacts" not in result.stderr
    assert "Audio and metadata saved" not in result.stderr


def test_ux_t10_t11_json_stdout_and_human_stderr_remain_separate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _install_provider(monkeypatch)

    result = _invoke_gen(tmp_path, "--json")

    assert result.exit_code == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["ok"] is True
    assert "SEED AUDIO / GEN" not in result.stdout
    assert result.stdout.count("\n") == 1
    assert "SEED AUDIO / GEN" in result.stderr
    assert "API response received" in result.stderr


def test_json_preserves_valid_prompt_text_that_matches_display_redaction_patterns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    prompt = (
        "Say the literal text audio=warm and base64=visible; "
        "api_key=inline-secret.\nKeep marker \x1b[31m as input."
    )

    result = runner.invoke(
        cli.app,
        ["gen", "--prompt", prompt, "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.stderr
    parsed = json.loads(result.stdout)
    emitted_prompt = parsed["runs"][0]["request"]["text_prompt"]
    assert emitted_prompt == (
        "Say the literal text audio=warm and base64=visible; "
        "api_key=<redacted>\nKeep marker \x1b[31m as input."
    )
    assert "inline-secret" not in result.stdout
    assert "\x1b" not in result.stdout


def test_json_preserves_artifact_paths_that_match_display_redaction_patterns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _install_provider(monkeypatch)
    runs_root = tmp_path / "audio=studio" / ("A" * 170) / "runs"

    result = runner.invoke(
        cli.app,
        [
            "gen",
            "--prompt",
            "Synthetic artifact path regression.",
            "--runs-root",
            str(runs_root),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stderr
    parsed = json.loads(result.stdout)
    run_dir = Path(parsed["runs"][0]["run_dir"])
    assert run_dir.parent == runs_root
    assert str(runs_root) in result.stdout


def test_ux_t12_wait_activity_is_written_before_slow_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    wait_line_seen = threading.Event()
    lines: list[str] = []
    original_reporter = cli.ExecutionReporter

    def writer(line: str) -> None:
        lines.append(line)
        if "Awaiting API response..." in line:
            wait_line_seen.set()

    def reporter_factory(**kwargs):
        return original_reporter(
            **kwargs,
            writer=writer,
            wait_interval=0.005,
        )

    monkeypatch.setattr(cli, "ExecutionReporter", reporter_factory)

    def slow_response(payload, on_request_start, on_response_received, call_number):
        assert wait_line_seen.wait(timeout=2), "wait line must precede the response"
        on_response_received("slow-provider-log-id")
        return ProviderResult(
            data={"audio": base64.b64encode(b"slow output").decode("ascii")},
            request_id="slow-request-id",
            provider_log_id="slow-provider-log-id",
        )

    _install_provider(monkeypatch, behavior=slow_response)
    result = _invoke_gen(tmp_path)

    assert result.exit_code == 0
    assert any("Awaiting API response..." in line for line in lines)
    response_index = next(
        index for index, line in enumerate(lines) if "API response received" in line
    )
    wait_index = next(
        index for index, line in enumerate(lines) if "Awaiting API response..." in line
    )
    assert wait_index < response_index


def test_ux_t13_provider_error_is_redacted_and_stops_wait_reporting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    def fail_after_response(payload, on_request_start, on_response_received, call_number):
        on_response_received("error-provider-log-id")
        raise BytePlusError(
            "simulated provider failure at "
            "https://user:pass@provider.example.test/create?token=error-secret"
        )

    _install_provider(monkeypatch, behavior=fail_after_response)
    result = _invoke_gen(tmp_path)

    assert result.exit_code == 2
    assert "API response received" in result.output
    assert "Provider log ID: error-provider-log-id" in result.output
    assert "Generation failed during provider response handling" in result.output
    assert "https://provider.example.test/create" in result.output
    assert "error-secret" not in result.output
    assert "user:pass" not in result.output
    assert not any(
        thread.name == "seed-audio-reporting-wait" for thread in threading.enumerate()
    )


def test_ux_t14_timeout_stops_wait_counter_and_preserves_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    def timeout_before_response(payload, on_request_start, on_response_received, call_number):
        raise BytePlusError("synthetic request timed out")

    _install_provider(monkeypatch, behavior=timeout_before_response)
    result = _invoke_gen(tmp_path)

    assert result.exit_code == 2
    assert "Generation failed during provider request" in result.output
    assert re.search(r"synthetic\s+request\s+timed\s+out", result.output)
    assert not any(
        thread.name == "seed-audio-reporting-wait" for thread in threading.enumerate()
    )


def test_ux_t15_persistence_failure_never_reports_generation_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _install_provider(monkeypatch)

    def fail_persistence(**kwargs):
        raise OSError("synthetic disk full")

    monkeypatch.setattr(cli, "persist_result", fail_persistence)
    result = _invoke_gen(tmp_path)

    assert result.exit_code == 2
    assert "Persisting run artifacts" in result.output
    assert "Generation failed during artifact persistence" in result.output
    assert "synthetic disk full" in result.output
    assert "Audio and metadata saved" not in result.output
    assert "GEN COMPLETED" not in result.output
    assert "GEN FAILED" in result.output


def test_ux_t16_partial_batch_failure_reports_saved_failed_and_unexecuted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    def fail_second(payload, on_request_start, on_response_received, call_number):
        if call_number == 2:
            raise BytePlusError("synthetic second request failure")
        on_response_received("first-provider-log-id")
        return ProviderResult(
            data={
                "audio": base64.b64encode(b"first saved audio").decode("ascii"),
                "duration": 1.25,
            },
            request_id="first-request-id",
            provider_log_id="first-provider-log-id",
        )

    calls = _install_provider(monkeypatch, behavior=fail_second)
    workflow = tmp_path / "partial.yaml"
    workflow.write_text(
        yaml.safe_dump(
            {
                "jobs": [
                    {"id": "saved", "prompt": "first"},
                    {"id": "failed", "prompt": "second"},
                    {"id": "not-run", "prompt": "third"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        cli.app,
        ["batch", str(workflow), "--runs-root", str(tmp_path / "runs")],
    )

    assert result.exit_code == 2
    assert len(calls) == 2
    assert "BATCH FAILED" in result.output
    assert re.search(r"Completed generations\s+1/3", result.output)
    assert re.search(r"(?m)^\s*Failed\s+1$", result.output)
    assert re.search(r"(?m)^\s*Not executed\s+1$", result.output)
    assert re.search(r"Audio\s+saved_audio\.wav\s+1.2s", result.output)


def test_ux_t17_t19_noninteractive_output_neutralizes_controls_only_for_display(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    prompt = "line one\x1b[31m\x07\r\nline two api_key=prompt-secret"
    calls = _install_provider(monkeypatch)

    result = runner.invoke(
        cli.app,
        ["gen", "--prompt", prompt, "--runs-root", str(tmp_path / "runs")],
    )

    assert result.exit_code == 0, result.output
    assert calls[0]["text_prompt"] == prompt
    assert "\x1b" not in result.output
    assert "\x07" not in result.output
    assert "\r" not in result.output
    assert "prompt-secret" not in result.output
    assert "line one" in result.output
    assert "line two" in result.output


def test_ux_t18_absent_provider_durations_are_omitted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _install_provider(
        monkeypatch,
        response_data={"audio": base64.b64encode(b"audio without metadata").decode("ascii")},
    )

    result = _invoke_gen(tmp_path)

    assert result.exit_code == 0, result.output
    assert "Audio duration" not in result.output
    assert "Billable audio" not in result.output
    assert "Audio produced" not in result.output
    assert "0.0s" in result.output  # local elapsed time is independent of provider metadata


def test_ux_t20_interrupt_cleans_up_wait_thread(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    def interrupt(payload, on_request_start, on_response_received, call_number):
        raise KeyboardInterrupt

    _install_provider(monkeypatch, behavior=interrupt)
    result = runner.invoke(
        cli.app,
        ["gen", "--prompt", "interrupt", "--runs-root", str(tmp_path / "runs")],
    )

    assert result.exit_code == 130
    assert "Generation interrupted during provider request" in result.output
    assert not any(
        thread.name == "seed-audio-reporting-wait" for thread in threading.enumerate()
    )
