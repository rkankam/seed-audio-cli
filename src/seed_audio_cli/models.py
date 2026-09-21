from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

AudioFormat = Literal["wav", "mp3", "pcm", "ogg_opus"]
SampleRate = Literal[8000, 16000, 24000, 32000, 44100, 48000]


class AudioConfig(BaseModel):
    format: AudioFormat = "wav"
    sample_rate: SampleRate | None = None
    speech_rate: int = Field(default=0, ge=-50, le=100)
    loudness_rate: int = Field(default=0, ge=-50, le=100)
    pitch_rate: int = Field(default=0, ge=-12, le=12)
    enable_subtitle: bool = False


class WatermarkConfig(BaseModel):
    aigc_watermark: bool = False


class Reference(BaseModel):
    audio_data: str | None = None
    audio_url: str | None = None
    image_data: str | None = None
    image_url: str | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> "Reference":
        populated = [
            self.audio_data,
            self.audio_url,
            self.image_data,
            self.image_url,
        ]
        if sum(value is not None for value in populated) != 1:
            raise ValueError("each reference must contain exactly one media source")
        return self

    @property
    def kind(self) -> Literal["audio", "image"]:
        if self.audio_data is not None or self.audio_url is not None:
            return "audio"
        return "image"


class SeedAudioRequest(BaseModel):
    model: str = Field(default="seed-audio-1.0", min_length=1)
    text_prompt: str = Field(min_length=1, max_length=3000)
    references: list[Reference] | None = None
    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    watermark: WatermarkConfig | None = None

    @model_validator(mode="after")
    def validate_references(self) -> "SeedAudioRequest":
        if not self.references:
            return self

        audio = [ref for ref in self.references if ref.kind == "audio"]
        images = [ref for ref in self.references if ref.kind == "image"]

        if audio and images:
            raise ValueError("audio and image references cannot be mixed")
        if len(audio) > 3:
            raise ValueError("Seed Audio supports at most 3 audio references")
        if len(images) > 1:
            raise ValueError("Seed Audio supports at most 1 image reference")
        return self

    def provider_payload(self) -> dict:
        return self.model_dump(exclude_none=True)


class ReplayReference(BaseModel):
    kind: Literal["audio", "image"]
    source: str
    is_url: bool = False
    sha256: str | None = None
    bytes: int | None = None
    duration_seconds: float | None = None


class ReplayRecipe(BaseModel):
    schema_version: int = 1
    model: str = "seed-audio-1.0"
    text_prompt: str
    references: list[ReplayReference] = Field(default_factory=list)
    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    watermark: WatermarkConfig | None = None
