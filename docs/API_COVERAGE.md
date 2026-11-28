# Seed Audio API coverage

This document separates the provider contract that is covered by the CLI from
product exclusions and from capabilities that still need a documented contract.
The provider source used for the 1.0 comparison is the official BytePlus page:

<https://docs.byteplus.com/en/docs/byteplusvoice/seedaudio-01?lang=en>

The repository contract is implemented in `src/seed_audio_cli/models.py`,
`src/seed_audio_cli/cli.py`, `src/seed_audio_cli/runs.py`, and documented in
`docs/BYTEPLUS_API.md`.

## Seed Audio 1.0 comparison

| Provider capability | Current CLI status | Classification |
| --- | --- | --- |
| Synchronous `POST /api/v3/tts/create` | Implemented by `BytePlusClient`; no submit/status/poll layer | Intentional contract alignment |
| `model=seed-audio-1.0` | Defaulted and persisted; `--model` remains configurable for dry-run experiments | Covered, with dry-run caveat |
| `text_prompt` up to 3000 characters | Validated by Pydantic; invalid prompts are rejected | Covered |
| Text-only generation | Implemented | Covered |
| Up to three ordered audio references | Implemented for local files and URLs; `@Audio1` ordering is preserved | Covered |
| Exactly one image reference | Implemented for local files and URLs | Covered |
| Audio/image mutual exclusion | Validated before request construction | Covered |
| `speaker` reference | Rejected by the strict request model | **Intentional exclusion**: preset, registered, and cloned speaker IDs are outside the product scope lock |
| Output format, sample rate, speech/loudness/pitch controls | Implemented and bounded locally | Covered |
| Subtitle enablement and returned subtitle data | Implemented; subtitle response is persisted when present | Covered |
| Explicit `watermark.aigc_watermark` | Implemented | Covered |
| Implicit `watermark.aigc_metadata` | Implemented on this branch, including direct CLI flags and workflow YAML | Previously missing; now addressed locally |
| Base64 audio response | Preferred and persisted locally | Covered |
| Temporary URL response | Downloaded before success is reported | Covered |
| `duration` and `original_duration` | Persisted as playback and billing duration fields | Covered |
| Provider `code`, `message`, and `X-Tt-Logid` | Business/HTTP failures are raised; log ID is persisted when present | Covered |
| Output up to 120 seconds and URL lifetime of two hours | Provider behavior is documented; the CLI does not impose a generation-duration knob | Informational provider limits, not a missing CLI option |

The official 1.0 page also lists supported languages. The CLI intentionally
passes the natural-language prompt through instead of maintaining a language
allowlist; the provider remains the authority for language acceptance.

## Seed Audio 1.5 status

No public Seed Audio 1.5 API contract was available in the official BytePlus
Voice Audio Creation surface inspected for this review. That surface exposes
`Audio 1.0` at `seedaudio-01`; the live page documents only the
`seed-audio-1.0` model, its request schema, and the synchronous endpoint.
Marketing or partnership references to “Seed Audio 1.5” are not sufficient to
infer a model identifier, request fields, endpoint, authentication behavior,
limits, or response schema.

Therefore this repository does **not** add a speculative `seed-audio-1.5`
model value, alias, endpoint, or compatibility mode. The existing arbitrary
`--model` escape hatch is useful for credential-free request experiments, but a
dry-run is not evidence that a provider model is supported.

## Evolution strategy

1. **Finish the documented 1.0 surface first.** Keep request models strict,
   expose each documented field through direct CLI and YAML workflow paths, and
   add dry-run tests that assert the exact redacted provider payload. Preserve
   schema-version-1 recipes when adding optional fields.
2. **Obtain a first-party 1.5 contract before coding it.** The minimum input is
   an official API reference or an operator-provided provider confirmation that
   identifies the model value, endpoint, request/response differences, limits,
   and availability. Do not use a real provider call as a substitute for this
   contract discovery.
3. **Add capability-specific models only after the contract is known.** Prefer
   an explicit model capability registry or versioned request model over a
   permissive dictionary. Keep synchronous execution and the run artifact
   contract unchanged unless the provider contract itself changes.
4. **Verify in layers.** Add model and dry-run tests first, then mocked HTTP
   contract tests, then—only after operator approval—a minimal real provider
   smoke test. Real calls must be preceded by `--dry-run` and must not be
   introduced into the default test suite.

## Decisions still requiring operator input

- Whether the product scope should ever be widened to `speaker` IDs. The
  current answer remains no, by explicit scope lock.
- Which official Seed Audio 1.5 API reference or account-facing contract should
  be treated as authoritative when available.
- Whether a real, paid Seed Audio 1.0 or 1.5 smoke test is worth running after
  local validation. No provider call was made for this review or implementation.
