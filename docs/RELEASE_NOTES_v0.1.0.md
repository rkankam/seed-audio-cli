# seed-audio-cli v0.1.0

## Features

- Create Seed Audio 1.0 audio from text prompts through BytePlus's official
  creation API.
- Use local files or remote URLs as media references: up to three audio
  references or one image reference per request.
- Define ordered YAML batch jobs and matrix runs with one to five variations
  per job.
- Save each successful generation in a replayable run folder with its recipe,
  request and response records, manifest, audio, and copied local references.
- Replay runs with local reference confinement and recorded size and SHA-256
  verification.
- Redact sensitive URL components in CLI output and persisted metadata.
- Follow a chronological terminal log of effective inputs, actual execution
  stages, local elapsed wait time, and persisted outputs.
- Use structured JSON output for agent and script integrations; in JSON mode,
  the result stays on stdout and the human log goes to stderr.
- Run credential-free dry-runs to validate local inputs and construct requests
  without contacting BytePlus.

## Limitations

- Seed Audio 1.0 is the only model covered by the provider validation documented
  for this project. A dry-run does not confirm that BytePlus supports an
  arbitrary model identifier.
- Batch and matrix jobs execute sequentially and stop at the first error. The
  CLI does not retry, run jobs in parallel, or resume a workflow.
- Replay reproduces the logical request and verifies copied local references,
  but provider changes mean generated audio is not guaranteed to be identical.
- Redacted remote URLs cannot be replayed from a recipe; supply a fresh URL.
- The CLI does not implement preset, registered, or cloned speaker IDs.

This is an independent CLI project, not software developed or maintained by
BytePlus. It is distributed under the MIT License.
