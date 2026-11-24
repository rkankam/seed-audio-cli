# Release checklist

This checklist prepares a release candidate. A tag or GitHub release requires
separate owner approval.

- [ ] Run `uv sync --extra dev`, `uv run ruff check .`, and `uv run pytest -q`
  from a clean clone.
- [ ] Run the README text-only, batch, and matrix dry-runs without credentials;
  confirm they make no provider calls.
- [ ] Build wheel and source distributions; inspect their contents and metadata.
- [ ] Confirm release notes state only provider validation actually performed.
  Seed Audio 1.0 is the only model covered by the provider validation documented
  for this project. Dry-run does not validate provider support for an arbitrary
  model identifier.
- [ ] Verify that no credentials, private media, or personal run artifacts are
  included in the distributions.
- [ ] Verify the BytePlus account terms and rights for any media included in a
  release. No user media should be bundled.
- [ ] Obtain the owner's final approval before creating a version tag or
  GitHub release.

## Findings

- [x] **REL-001 — Project license.** The owner selected the MIT License for
  v0.1.0. The repository license, owner-confirmed 2026 copyright holder,
  package metadata, and README reference are in place.
