from pathlib import Path

import yaml

from seed_audio_cli.workflows import expand_matrix


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
