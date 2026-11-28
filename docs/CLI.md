# CLI reference

## seed-audio gen

Generate one or more independent outputs.

Exactly one prompt source is required:

    --prompt TEXT
    --prompt-file PATH

References:

    --ref PATH_OR_URL

Repeat --ref up to three times. Ordering is significant because prompts may refer to @Audio1, @Audio2 and @Audio3.

Image reference:

    --image PATH_OR_URL

Do not combine --image with --ref.

Output controls:

    --format wav|mp3|pcm|ogg_opus
    --sample-rate 8000|16000|24000|32000|44100|48000
    --speech-rate -50..100
    --loudness-rate -50..100
    --pitch-rate -12..12
    --subtitles
    --aigc-watermark
    --aigc-metadata-enable
    --content-producer TEXT
    --produce-id TEXT
    --content-propagator TEXT
    --propagate-id TEXT

Experiment controls:

    -n, --variations 1..5
    --name NAME
    --runs-root PATH
    --out PATH
    --dry-run
    --json

--out creates an additional convenience copy. The canonical artifact remains inside the run directory.

`--aigc-watermark` enables the explicit audio watermark. The four metadata
options populate the provider's implicit watermark object; use
`--aigc-metadata-enable` to enable that object. They can be combined, and all
values are persisted in `recipe.json` for replay.

### Execution log

The default human output is an append-only chronological log. Every generation
prints its effective inputs, including the full prompt, the exact model, each
reference and available local metadata, and the audio configuration in the
prepared request. It then reports completed input preparation, provider
request/response, and artifact persistence stages, followed by the saved paths
and available result metadata. Identical inputs are repeated for each
variation. Batch and matrix jobs are reported in their execution order without
presenting a misleading global configuration.

The pending-response counter uses a monotonic local clock and reports elapsed
time in this CLI only. It is not a provider progress signal or an estimate of
remaining time. Dry-runs show the prepared inputs and plan, and state that no
provider call or audio persistence occurred.

Human output goes to stdout by default. With `--json`, stdout remains the
existing final JSON object and the human log goes to stderr, so the result can
be parsed directly. Output is line-oriented in non-interactive terminals and
does not use terminal animations.

Prompts and local reference paths can contain personal information. Review a
terminal log before sharing it publicly.

`--dry-run` performs local validation and shows a redacted request without contacting BytePlus or requiring an API key. It does not verify that BytePlus supports an arbitrary `--model` value; Seed Audio 1.0 is the only model covered by the provider validation documented for this project.

## seed-audio replay

    seed-audio replay RUN_DIR

Options:

    --name NAME
    --runs-root PATH
    --out PATH
    --dry-run
    --json

Replay uses recipe.json and the copied refs inside RUN_DIR. Each local reference must stay inside the resolved run directory and match its recorded byte size and SHA-256 before request construction. Absolute paths, `..` traversal, escaping symlinks, missing references, and integrity mismatches fail before a provider call. Older recipes missing local integrity metadata are rejected because their contents cannot be verified.

Remote URLs are not copied. Userinfo, query parameters, and fragments are redacted from output and persisted artifacts. When a recipe records `url_redacted: true`, supply a fresh URL with `gen`; the redacted recipe cannot replay that reference.

## seed-audio batch

    seed-audio batch workflow.yaml

Batch file:

    jobs:
      - id: first
        prompt: "..."
        variations: 2
        output:
          format: wav
          sample_rate: 48000
        watermark:
          aigc_watermark: true
          aigc_metadata:
            enable: true
            content_producer: seed-audio-cli
            produce_id: production-123
            content_propagator: studio
            propagate_id: distribution-456

The `watermark` block belongs inside the job that should use it. A job may
also omit it or set only the explicit `aigc_watermark` field.

A job may use prompt_file instead of prompt. Relative paths are resolved from the YAML file directory.


## seed-audio matrix

    seed-audio matrix matrix.yaml

Matrix file:

    base:
      output:
        format: wav
        sample_rate: 48000

    variations: 2

    runs:
      - id: neutral
        prompt_file: prompts/neutral.txt

      - id: aggressive
        prompt_file: prompts/aggressive.txt
        output:
          format: mp3
          sample_rate: 44100

Each run inherits base values and may override them.

## Exit behavior

0: command completed successfully

2: validation, local I/O, provider or persistence failure

In JSON mode, stdout remains parseable JSON on both success and failure.

Batch and matrix jobs run sequentially and stop at the first error. The human
log reports generations already completed and persisted, the generation that
failed when known, and generations not executed. Inspect run folders before
retrying.
