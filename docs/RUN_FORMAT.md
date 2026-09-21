# Run format

Every real provider call gets its own run directory.

Example:

    runs/20260921T030000.123456Z_taxi-01/
      audio.wav
      prompt.txt
      recipe.json
      request.json
      response.json
      manifest.json
      subtitles.json
      refs/
        01_driver.wav

The directory is the unit of provenance.

## prompt.txt

Exact prompt text submitted for this run.

## refs/

Local references copied before the provider call.

Replay reads these copies, not the original files outside the run directory. This prevents later edits to a source file from changing historical runs.

URL references are not copied.

## recipe.json

Replayable logical request.

Schema version 1:

    {
      "schema_version": 1,
      "model": "seed-audio-1.0",
      "text_prompt": "...",
      "references": [
        {
          "kind": "audio",
          "source": "refs/01_driver.wav",
          "is_url": false,
          "sha256": "...",
          "bytes": 1234,
          "duration_seconds": 8.2
        }
      ],
      "audio_config": {
        "format": "wav",
        "sample_rate": 48000,
        "speech_rate": 0,
        "loudness_rate": 0,
        "pitch_rate": 0,
        "enable_subtitle": false
      }
    }

Local reference source paths are relative to the run directory.

## request.json

Readable provider request.

Large audio_data and image_data values are replaced by the literal marker:

    <base64 omitted>

This file is for audit and inspection. recipe.json is the replay source.

## response.json

Readable provider response.

The generated Base64 audio body is replaced by:

    <base64 omitted>

Other response metadata, including temporary URLs, durations, provider code/message and subtitles, is preserved when present.

## audio.<ext>

Canonical persisted provider output.

manifest.json records its SHA-256.

## subtitles.json

Written only when the provider returns subtitle data.

## manifest.json

Stable top-level summary for humans and agents.

Important fields:

- schema_version
- run_id
- created_at
- command
- provider
- model
- request_id
- provider_log_id
- duration_seconds
- billing_duration_seconds
- artifacts
- references

Consumers should prefer manifest.json over parsing filenames.

## Replay semantics

Replay creates a new run directory, copies the historical references, rebuilds Base64 media and issues a fresh provider request with a fresh UUID.

Replay does not imply deterministic audio output. It reproduces the logical input and local media state.
