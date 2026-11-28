from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import seed_audio_cli.cli as cli
from seed_audio_cli import runs
from seed_audio_cli.client import ProviderResult
from seed_audio_cli.models import ReplayRecipe, ReplayReference

runner = CliRunner()


def make_run(
    run_dir: Path,
    *,
    source: str = "refs/reference.wav",
    metadata: bool = True,
    content: bytes = b"synthetic audio fixture",
) -> Path:
    (run_dir / "refs").mkdir(parents=True)
    reference_path = run_dir / "refs" / "reference.wav"
    reference_path.write_bytes(content)
    reference = ReplayReference(
        kind="audio",
        source=source,
        sha256=hashlib.sha256(content).hexdigest() if metadata else None,
        bytes=len(content) if metadata else None,
    )
    recipe = ReplayRecipe(text_prompt="Synthetic replay test", references=[reference])
    (run_dir / "recipe.json").write_text(
        recipe.model_dump_json(exclude_none=True), encoding="utf-8"
    )
    return reference_path


def install_recording_client(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    requests: list[dict] = []

    class RecordingClient:
        def __init__(self, api_key: str) -> None:
            assert api_key == ""

        def create(self, payload: dict) -> ProviderResult:
            requests.append(payload)
            return ProviderResult(
                data={"audio": base64.b64encode(b"synthetic output").decode("ascii")},
                request_id="synthetic-request-id",
                provider_log_id=None,
            )

    monkeypatch.setattr(cli, "BytePlusClient", RecordingClient)
    monkeypatch.setattr(cli, "api_key", lambda required: None)
    return requests


def invoke_replay(run_dir: Path, *, dry_run: bool, runs_root: Path):
    args = ["replay", str(run_dir), "--runs-root", str(runs_root), "--json"]
    if dry_run:
        args.append("--dry-run")
    return runner.invoke(cli.app, args)


def test_replay_accepts_internal_reference(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    make_run(run_dir)

    result = invoke_replay(run_dir, dry_run=True, runs_root=tmp_path / "new-runs")

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["ok"] is True
    assert output["request"]["references"][0]["audio_data"]


@pytest.mark.parametrize(
    "reference",
    ["traversal", "absolute", "windows-absolute", "symlink"],
)
@pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "simulated-real"])
def test_replay_rejects_paths_outside_run_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference: str,
    dry_run: bool,
) -> None:
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"synthetic external fixture")
    source = {
        "traversal": "../outside.wav",
        "absolute": str(outside),
        "windows-absolute": r"C:\Users\someone\reference.wav",
        "symlink": "refs/external.wav",
    }[reference]
    make_run(run_dir, source=source)
    if reference == "symlink":
        (run_dir / "refs" / "external.wav").symlink_to(outside)
    requests = install_recording_client(monkeypatch)

    result = invoke_replay(run_dir, dry_run=dry_run, runs_root=tmp_path / "new-runs")

    assert result.exit_code == 2
    output = json.loads(result.stdout)
    assert output["ok"] is False
    assert "local replay reference" in output["error"]
    assert requests == []


def test_missing_replay_reference_has_clear_error_and_no_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    make_run(run_dir, source="refs/missing.wav")
    requests = install_recording_client(monkeypatch)

    result = invoke_replay(run_dir, dry_run=False, runs_root=tmp_path / "new-runs")

    assert result.exit_code == 2
    assert "local replay reference does not exist" in json.loads(result.stdout)["error"]
    assert requests == []


def test_replay_confines_all_paths_before_reading_or_encoding_any_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    reference_path = make_run(run_dir)
    initial = json.loads((run_dir / "recipe.json").read_text(encoding="utf-8"))
    valid_reference = initial["references"][0]
    invalid_reference = ReplayReference(
        kind="audio",
        source="../outside.wav",
        sha256=hashlib.sha256(b"outside").hexdigest(),
        bytes=len(b"outside"),
    )
    recipe = ReplayRecipe(
        text_prompt="Synthetic replay test",
        references=[
            ReplayReference.model_validate(valid_reference),
            invalid_reference,
        ],
    )
    touched: list[str] = []
    monkeypatch.setattr(runs, "sha256_file", lambda path: touched.append("hash"))
    monkeypatch.setattr(runs, "validate_local_media", lambda path, kind: touched.append("validate"))
    monkeypatch.setattr(runs, "encode_base64", lambda path: touched.append("encode"))

    with pytest.raises(ValueError, match="parent traversal"):
        runs.build_request_from_recipe(recipe, run_dir, replay=True)

    assert reference_path.is_file()
    assert touched == []


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "simulated-real"])
def test_replay_rejects_local_path_misclassified_as_url_before_io_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"synthetic outside reference")
    make_run(run_dir)
    recipe_path = run_dir / "recipe.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe["references"][0].update({"source": str(outside), "is_url": True})
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
    requests = install_recording_client(monkeypatch)
    io_events: list[str] = []

    def observe(name: str, original):
        def wrapped(*args, **kwargs):
            io_events.append(name)
            return original(*args, **kwargs)

        return wrapped

    monkeypatch.setattr(
        runs,
        "validate_local_media",
        observe("validate", runs.validate_local_media),
    )
    monkeypatch.setattr(runs, "_copy_reference", observe("copy", runs._copy_reference))
    monkeypatch.setattr(runs, "sha256_file", observe("hash", runs.sha256_file))
    monkeypatch.setattr(runs, "encode_base64", observe("encode", runs.encode_base64))
    original_request = runs.SeedAudioRequest

    def observe_request(**kwargs):
        io_events.append("request")
        return original_request(**kwargs)

    monkeypatch.setattr(runs, "SeedAudioRequest", observe_request)
    runs_root = tmp_path / "new-runs"

    result = invoke_replay(run_dir, dry_run=dry_run, runs_root=runs_root)

    assert result.exit_code == 2
    error = json.loads(result.stdout)["error"]
    assert "classification" in error.lower()
    assert io_events == []
    assert requests == []
    assert not runs_root.exists()


def test_replay_run_copies_the_exact_integrity_checked_request_bytes(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "source-run"
    reference_path = make_run(run_dir)
    recipe = ReplayRecipe.model_validate_json(
        (run_dir / "recipe.json").read_text(encoding="utf-8")
    )
    request, _ = runs.build_request_from_recipe(recipe, run_dir, replay=True)
    validated_bytes = base64.b64decode(request.references[0].audio_data, validate=True)

    reference_path.write_bytes(b"changed after integrity validation")
    target = tmp_path / "replayed-run"
    target.mkdir()
    replay_recipe = runs.prepare_replay_recipe(recipe, request, target)

    copied = target / replay_recipe.references[0].source
    assert copied.read_bytes() == validated_bytes
    assert replay_recipe.references[0].bytes == len(validated_bytes)
    assert replay_recipe.references[0].sha256 == hashlib.sha256(validated_bytes).hexdigest()


def test_real_replay_preserves_valid_remote_reference_without_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "remote-run"
    run_dir.mkdir()
    remote_url = "https://media.example.test/reference.wav"
    recipe = {
        "schema_version": 1,
        "model": "seed-audio-1.0",
        "text_prompt": "Synthetic remote replay test",
        "references": [
            {"kind": "audio", "source": remote_url, "is_url": True}
        ],
        "audio_config": {"format": "wav"},
    }
    (run_dir / "recipe.json").write_text(json.dumps(recipe), encoding="utf-8")
    requests: list[dict] = []

    class RecordingClient:
        def __init__(self, api_key: str) -> None:
            assert api_key == ""

        def create(self, payload: dict) -> ProviderResult:
            requests.append(payload)
            return ProviderResult(
                data={"audio": base64.b64encode(b"synthetic output").decode("ascii")},
                request_id="synthetic-request-id",
                provider_log_id=None,
            )

    monkeypatch.setattr(cli, "BytePlusClient", RecordingClient)
    monkeypatch.setattr(cli, "api_key", lambda required: None)
    result = invoke_replay(
        run_dir,
        dry_run=False,
        runs_root=tmp_path / "new-runs",
    )

    assert result.exit_code == 0
    assert requests[0]["references"][0]["audio_url"] == remote_url
    new_run_dir = Path(json.loads(result.stdout)["run_dir"])
    assert not (new_run_dir / "refs").exists()


@pytest.mark.parametrize(
    "watermark",
    [
        pytest.param({"aigc_watermark": True}, id="legacy-without-metadata"),
        pytest.param(
            {
                "aigc_watermark": True,
                "aigc_metadata": {
                    "enable": True,
                    "content_producer": "studio",
                    "produce_id": "run-01",
                },
            },
            id="metadata-format",
        ),
    ],
)
def test_replay_round_trip_preserves_legacy_and_metadata_watermark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    watermark: dict,
) -> None:
    run_dir = tmp_path / "source-run"
    make_run(run_dir)
    recipe_path = run_dir / "recipe.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe["watermark"] = watermark
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
    requests = install_recording_client(monkeypatch)

    result = invoke_replay(
        run_dir,
        dry_run=False,
        runs_root=tmp_path / "replayed-runs",
    )

    assert result.exit_code == 0, result.stdout
    assert requests[0]["watermark"] == watermark
    replayed_dir = Path(json.loads(result.stdout)["run_dir"])
    replayed_recipe = json.loads(
        (replayed_dir / "recipe.json").read_text(encoding="utf-8")
    )
    assert replayed_recipe["watermark"] == watermark


@pytest.mark.parametrize(
    ("changed_content", "expected_error"),
    [
        (b"different audio fixture with a different size", "size mismatch"),
        (b"changed audio fixture!!", "SHA-256 mismatch"),
    ],
)
def test_replay_rejects_reference_integrity_drift_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_content: bytes,
    expected_error: str,
) -> None:
    run_dir = tmp_path / "run"
    reference_path = make_run(run_dir)
    reference_path.write_bytes(changed_content)
    requests = install_recording_client(monkeypatch)

    result = invoke_replay(run_dir, dry_run=False, runs_root=tmp_path / "new-runs")

    assert result.exit_code == 2
    assert expected_error in json.loads(result.stdout)["error"]
    assert requests == []


def test_replay_rejects_legacy_local_recipe_without_integrity_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    make_run(run_dir, metadata=False)
    requests = install_recording_client(monkeypatch)

    result = invoke_replay(run_dir, dry_run=True, runs_root=tmp_path / "new-runs")

    assert result.exit_code == 2
    assert "missing integrity metadata" in json.loads(result.stdout)["error"]
    assert requests == []


def test_unchanged_reference_replays_and_normal_generation_accepts_external_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    reference_path = make_run(run_dir)
    requests = install_recording_client(monkeypatch)

    replay_result = invoke_replay(
        run_dir, dry_run=False, runs_root=tmp_path / "replayed-runs"
    )

    assert replay_result.exit_code == 0
    assert len(requests) == 1
    assert requests[0]["references"][0]["audio_data"] == base64.b64encode(
        reference_path.read_bytes()
    ).decode("ascii")

    external = tmp_path / "reference-outside-repository.wav"
    external.write_bytes(b"user supplied fixture")
    generation_result = runner.invoke(
        cli.app,
        [
            "gen",
            "--prompt",
            "Synthetic external reference test",
            "--ref",
            str(external),
            "--runs-root",
            str(tmp_path / "generated-runs"),
            "--json",
        ],
    )

    assert generation_result.exit_code == 0
    assert len(requests) == 2
    assert requests[1]["references"][0]["audio_data"] == base64.b64encode(
        external.read_bytes()
    ).decode("ascii")
