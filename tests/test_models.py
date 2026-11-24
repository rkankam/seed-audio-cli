import pytest
from pydantic import ValidationError

from seed_audio_cli.models import (
    AudioConfig,
    Reference,
    ReplayReference,
    SeedAudioRequest,
)


def test_prompt_limit() -> None:
    with pytest.raises(ValidationError):
        SeedAudioRequest(text_prompt="x" * 3001)


def test_audio_and_image_references_are_exclusive() -> None:
    with pytest.raises(ValidationError):
        SeedAudioRequest(
            text_prompt="test",
            references=[
                Reference(audio_url="https://example.com/a.wav"),
                Reference(image_url="https://example.com/a.png"),
            ],
        )


def test_audio_reference_limit() -> None:
    refs = [
        Reference(audio_url=f"https://example.com/{index}.wav")
        for index in range(4)
    ]
    with pytest.raises(ValidationError):
        SeedAudioRequest(text_prompt="test", references=refs)


def test_audio_config_bounds() -> None:
    with pytest.raises(ValidationError):
        AudioConfig(pitch_rate=13)


def test_speaker_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Reference.model_validate({"speaker": "some-provider-speaker-id"})


@pytest.mark.parametrize(
    ("source", "is_url"),
    [
        ("https://example.test/reference.wav", False),
        ("refs/reference.wav", True),
    ],
)
def test_replay_reference_classification_must_match_source(
    source: str,
    is_url: bool,
) -> None:
    with pytest.raises(ValidationError, match="classification is inconsistent"):
        ReplayReference(kind="audio", source=source, is_url=is_url)
