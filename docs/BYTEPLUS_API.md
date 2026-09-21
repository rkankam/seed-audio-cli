# BytePlus API contract

This document records the provider surface used by the CLI.

Official documentation:
https://docs.byteplus.com/en/docs/byteplusvoice/seedaudio-01?lang=en

## Endpoint

    POST https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create

Headers:

    Content-Type: application/json
    X-Api-Key: <secret>
    X-Api-Request-Id: <uuid>

The endpoint is synchronous.

## Request

Core shape:

    {
      "model": "seed-audio-1.0",
      "text_prompt": "...",
      "references": [],
      "audio_config": {
        "format": "wav",
        "sample_rate": 48000,
        "speech_rate": 0,
        "loudness_rate": 0,
        "pitch_rate": 0,
        "enable_subtitle": false
      }
    }

text_prompt is limited to 3000 characters.

The CLI intentionally does not expose speaker references.

### Audio references

Up to three audio references. A reference may use either audio_data or audio_url.

Local files are encoded into audio_data immediately before the provider call.

Documented provider constraints:

- max 3 audio references
- max 30 seconds per reference
- max 10 MB per reference
- wav, mp3, pcm, ogg/opus family

The prompt can address references by request order as @Audio1, @Audio2 and @Audio3.

### Image reference

Exactly one image reference may be supplied with image_data or image_url.

Documented constraints:

- max 10 MB
- jpeg, png or webp

An image reference cannot be mixed with audio references.

### Audio configuration

Supported output formats:

- wav
- mp3
- pcm
- ogg_opus

Supported sample rates:

- 8000
- 16000
- 24000
- 32000
- 44100
- 48000

Controls:

- speech_rate: -50 to 100
- loudness_rate: -50 to 100
- pitch_rate: -12 to 12
- enable_subtitle: boolean

### Watermark

The initial CLI exposes the explicit aigc_watermark boolean only. It does not expose the full implicit metadata structure.

## Response

The CLI consumes the documented top-level fields:

- audio: Base64 audio
- url: temporary provider URL
- duration
- original_duration
- subtitle
- code
- message

audio is preferred for persistence. url is only a fallback because provider URLs are temporary.

original_duration is stored as billing_duration_seconds in the local manifest.

The X-Tt-Logid response header is stored as provider_log_id when present.

## Error behavior

HTTP errors and non-zero provider business codes fail the command. The CLI does not convert failed provider calls into successful run manifests.
