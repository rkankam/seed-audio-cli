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

URL references are not copied. Their complete values are kept in memory only as needed for the provider request or download. Userinfo, query parameters, and fragments are removed from CLI output, recipe/request/response JSON, manifests, and subtitle JSON. A replay recipe records `url_redacted: true` when those components were removed. Such a remote reference cannot be replayed from that recipe; provide a new valid URL with `seed-audio gen --ref` or `--image`.

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

For remote references, `source` contains the redacted URL. `url_redacted` is `true` if userinfo, a query, or a fragment was removed. The field is omitted or `false` for older recipes and URLs that needed no redaction.

## request.json

Readable provider request.

Large audio_data and image_data values are replaced by the literal marker:

    <base64 omitted>

This file is for audit and inspection. recipe.json is the replay source.

## response.json

Readable provider response.

The generated Base64 audio body is replaced by:

    <base64 omitted>

Other response metadata, including temporary URLs, durations, provider code/message and subtitles, is preserved when present, with URL userinfo, query parameters, and fragments redacted. A temporary response URL is used in memory to download audio before it is redacted from response.json.

## audio artifact

Canonical persisted provider output.

For direct `gen` and replay runs, the default filename remains:

    audio.<ext>

For `batch` and `matrix` workflows, the workflow run name derived from `jobs[].id`
or `runs[].id` prefixes the canonical artifact:

    laundromat-roomtone_audio.wav
    entrance-door_audio.wav
    baseline-01_audio.wav

When a workflow has multiple variations, the variation suffix is included in the prefix.

manifest.json always records the exact audio filename and its SHA-256. Consumers should
read the manifest instead of assuming a fixed filename.

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

The `is_url` flag must agree with whether `source` is an HTTP(S) URL; inconsistent references are rejected before request construction. Before request construction, local references must resolve inside the run directory. Absolute paths, parent traversal, and symlinks that resolve outside it are rejected. The reference size and SHA-256 must match recipe.json; a mismatch fails before any provider request. Older local recipes missing either integrity field are rejected with an explicit error because their content cannot be verified. CLI-created schema-version-1 local recipes already include both values.

Older remote recipes without `url_redacted` remain replayable while their stored URL is valid; their URL is redacted from new output and artifacts. The old recipe itself is not rewritten, so protect or remove older run folders that already contain sensitive URLs. Newly persisted recipes with `url_redacted: true` require a fresh reference URL.

Replay does not imply deterministic audio output. It reproduces the logical input and verified local media state, but provider behavior, model implementations, and service versions may change. Seed Audio 1.0 is the only model covered by the provider validation documented for this project. A successful dry-run checks local validation and request construction, not provider compatibility for an arbitrary model identifier.
