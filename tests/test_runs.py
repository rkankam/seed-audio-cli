from pathlib import Path

from seed_audio_cli.models import AudioConfig
from seed_audio_cli.runs import audio_artifact_filename, prepare_recipe


def test_url_reference_does_not_require_local_file() -> None:
    recipe = prepare_recipe(
        model="seed-audio-1.0",
        prompt="test",
        audio_refs=["https://example.com/ref.wav"],
        image_ref=None,
        audio_config=AudioConfig(),
        watermark=None,
        run_dir=None,
    )
    assert recipe.references[0].is_url is True
    assert recipe.references[0].kind == "audio"


def test_image_and_audio_inputs_rejected(tmp_path: Path) -> None:
    audio = tmp_path / "a.wav"
    image = tmp_path / "a.png"
    audio.write_bytes(b"x")
    image.write_bytes(b"x")

    try:
        prepare_recipe(
            model="seed-audio-1.0",
            prompt="test",
            audio_refs=[str(audio)],
            image_ref=str(image),
            audio_config=AudioConfig(),
            watermark=None,
            run_dir=None,
        )
    except ValueError as exc:
        assert "cannot be mixed" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_audio_artifact_filename_uses_workflow_prefix() -> None:
    assert (
        audio_artifact_filename("wav", "laundromat-roomtone")
        == "laundromat-roomtone_audio.wav"
    )
    assert (
        audio_artifact_filename("ogg_opus", "Entrance Door")
        == "entrance-door_audio.ogg"
    )


def test_audio_artifact_filename_preserves_legacy_default() -> None:
    assert audio_artifact_filename("wav") == "audio.wav"
