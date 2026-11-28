from pathlib import Path

import yaml

from seed_audio_cli.models import SeedAudioRequest
from seed_audio_cli.workflows import (
    audio_config_from_job,
    expand_matrix,
    watermark_from_job,
)


def test_watermark_job_accepts_implicit_metadata() -> None:
    watermark = watermark_from_job(
        {
            "watermark": {
                "aigc_watermark": True,
                "aigc_metadata": {
                    "enable": True,
                    "content_producer": "seed-audio-cli",
                    "produce_id": "production-123",
                },
            }
        }
    )

    assert watermark is not None
    assert watermark.model_dump(exclude_none=True) == {
        "aigc_watermark": True,
        "aigc_metadata": {
            "enable": True,
            "content_producer": "seed-audio-cli",
            "produce_id": "production-123",
        },
    }


def test_matrix_deep_merges_output(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("hello", encoding="utf-8")

    workflow = {
        "base": {
            "output": {
                "format": "wav",
                "sample_rate": 48000,
                "speech_rate": 0,
            }
        },
        "runs": [
            {
                "id": "faster",
                "prompt_file": "prompt.txt",
                "output": {"speech_rate": 20},
            }
        ],
    }
    path = tmp_path / "matrix.yaml"
    path.write_text(yaml.safe_dump(workflow), encoding="utf-8")

    jobs = expand_matrix(path)

    assert jobs[0]["output"] == {
        "format": "wav",
        "sample_rate": 48000,
        "speech_rate": 20,
    }
    assert not list(tmp_path.glob("*.expanded.tmp.yaml"))


def test_matrix_watermark_metadata_override_preserves_effective_payload(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("hello", encoding="utf-8")
    workflow = {
        "base": {
            "output": {"format": "wav"},
            "watermark": {
                "aigc_watermark": True,
                "aigc_metadata": {
                    "enable": True,
                    "content_producer": "studio",
                    "content_propagator": "broadcast",
                },
            },
        },
        "runs": [
            {
                "id": "run-01",
                "prompt_file": "prompt.txt",
                "watermark": {"aigc_metadata": {"produce_id": "run-01"}},
            }
        ],
    }
    path = tmp_path / "matrix.yaml"
    path.write_text(yaml.safe_dump(workflow), encoding="utf-8")

    job = expand_matrix(path)[0]
    request = SeedAudioRequest(
        text_prompt=job["prompt"],
        audio_config=audio_config_from_job(job),
        watermark=watermark_from_job(job),
    )

    assert request.provider_payload()["watermark"] == {
        "aigc_watermark": True,
        "aigc_metadata": {
            "enable": True,
            "content_producer": "studio",
            "produce_id": "run-01",
            "content_propagator": "broadcast",
        },
    }
