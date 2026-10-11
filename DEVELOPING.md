# Contributing to research-brain

This file belongs to the source repository. The end-user archive omits it.
Product behavior and path/schema rules live in `AGENTS.md` and
`docs/CONVENTIONS.md`.

## Local setup

Use Python 3.11+ and `uv`:

```bash
make setup
make gate
```

`make gate` runs lint, type checks, security checks, tests with coverage,
configuration and frontmatter validation, vault hygiene, and the isolated MCP
adapter suite plus its disposable stdio replay. The adapter keeps its own lock
and environment; it does not add a dependency to the core. Run just that check
with `make mcp-test` (or `make mcp-test MCP_PYTHON=3.14`). The Windows CI
job and the second Python version in CI require their own results; a local gate
does not imply that they passed.

Keep shipped Python modules limited to the standard library plus PyYAML. Add
focused tests for behavior changes. Run `make gate` on the final committed tree
before preparing a release candidate.

## Public source repository

The public repository starts with a clean root commit exported from the private
workspace. Private history must never be imported or pushed to the public remote.
Run `make public-check` on every committed change: it refuses tracked files outside
the reviewed source set and checks configuration defaults and example vault notes
for unexpected edits. CI runs the same check.

For a public update, commit the private changes, then run
`python3 tools/export_public.py --output <empty-directory>`. Review and scan the
snapshot, apply only those files to the separate public checkout, and run its
checks before an authorized push. Record the private and public commit relationship
in the private release report. This is a snapshot export, not a history mirror.

Operational data, private working notes, publication drafts, implementation
backlogs and internal release tools stay ignored and outside the export. Users
should run personal collection and delivery from a separate unpacked installation,
not a source checkout they intend to publish.

## End-user archive

`make dist` builds `dist/research-brain-<version>.zip` from the committed tree.
`.gitattributes` excludes contributor-only files from that archive. Check the
archive contents and a fresh unpack before release.

The source repository includes tests and CI; the end-user archive omits them.
Both the Git history and archive must pass content and secret scans. Record the
source commit and archive checksum in the release report.

## Release boundary

Keep `pyproject.toml`, `.claude-plugin/plugin.json`, and `uv.lock` on the same
version. Update `CHANGELOG.md`, rerun the gate, then build the archive. For the
first public `0.1.0`, create the tag on this public history only after
final review. Future tags follow verified public release commits.

A successful test gate is not evidence of unattended recurring value. Use the
two-cycle protocol in `docs/PILOT.md` before claiming that the full agentic
workflow has passed a real-world pilot.

### Plugin release validation

When preparing the Claude plugin manifest, run `claude plugin validate .` with an installed
Claude Code CLI and retain its version and output. JSON parsing alone does not validate
runtime field types. The author is an object with a `name`; optional homepage/repository
fields are added only after their public destinations are verified. Opening the unpacked
project root is the documented workflow. A root `CLAUDE.md` is not automatically injected
when the same files are loaded solely as a plugin; record that validator warning separately
and do not claim it establishes plugin context loading or a full pipeline pilot.
