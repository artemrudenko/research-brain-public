# ADR 0021 — Stable script facades over domain packages

- **Status:** Accepted (2026-07-08)
- **Tags:** scripts, refactoring, compatibility, maintainability

## Context
`scripts/` is no longer a small helper directory. It is the runtime surface of the product: cron
tasks, skills, docs, tests, and users call concrete paths such as `python3 scripts/collect.py`,
`python3 scripts/build_digest.py`, `python3 scripts/validate_brain.py`, and
`python3 scripts/delivery/deliver.py`. Several scripts have grown large enough to mix CLI parsing,
configuration loading, domain logic, formatting, network I/O, persistence, and compatibility helpers
in one file.

The repository already proved a lower-risk pattern:
- `scripts/build_digest.py` is the stable CLI/import facade; implementation lives in
  `scripts/digest/`.
- `scripts/validate_brain.py` is the stable CLI/import facade; implementation lives in
  `scripts/hygiene/`.

The remaining large modules need the same treatment, but the external command paths are a contract.
A broad rename of `scripts/*.py` would touch schedule files, skills, documentation, and user habits
at the same time as behavior, making a maintenance refactor unnecessarily risky.

## Decision
Keep `scripts/*.py` files as the stable public command and compatibility import surface. Move
implementation behind them into domain packages when a script becomes large or mixes unrelated
responsibilities.

The refactor rule is:
1. Preserve the existing CLI path and default behavior.
2. Preserve the existing import surface used by tests and sibling modules, including private helpers
   during the transition, via explicit re-exports.
3. Split by responsibility, not by arbitrary file size.
4. Move one vertical slice at a time, with targeted tests green before moving to the next script.
5. Update docs and ADRs when a split establishes a pattern future contributors should follow.

The first applications are:
- `scripts/collect.py`: feed parsing, text extraction, article rendering/tag seeding, URL registry
  helpers, and HTTP fetching move into `scripts/collection/`, while `scripts/collect.py` remains the
  public command and keeps the compatibility surface for existing tests/callers.
- `scripts/manage_sources.py`: source/topic models, validation, markdown-table helpers, and
  tag-key parsers move into `scripts/sources/`, while mutation functions remain in the facade so
  monkeypatch-based tests and sibling callers keep working unchanged during the transition.
- `scripts/validate_config.py`: CLI orchestration, channels/schedule YAML validators, optional YAML
  validators, markdown validators, placeholder/secret scans, and feed-liveness helpers move into
  `scripts/config_validation/`, while the facade preserves the command path and compatibility
  import surface.
- `scripts/health.py`: the CLI parser, verdict model, rolled-up summary, report renderer,
  append-only event-log storage, event-derived health signals, and artifact-derived health signals
  move into `scripts/health_checks/`, while `health.py` remains the stable CLI/import facade and
  keeps alert-facing helpers available under the existing `scripts.health` names.
- `scripts/brain_status.py`: status record models, source-registry parsing, cadence
  parsing/rendering, digest listing, and latest-finding extraction move into `scripts/status/`,
  while `brain_status.py` remains the stable CLI/import facade for read-only status, cadence,
  digest, and finding queries.
- `scripts/trends.py`: trend record models, concept scanning, metric builders, and Markdown
  rendering move into `scripts/trend_report/`, while `trends.py` remains the stable CLI/import
  facade for report building, embedding, and existing callers.
- `scripts/import_opml.py`: OPML record models, safe OPML parsing, preview construction, and CLI
  helper parsing/rendering move into `scripts/opml_import/`, while `import_opml.py` remains the
  stable CLI/import facade and keeps config mutation routed through `manage_sources`.
- `scripts/intake.py`: URL intake result models, the clarification prompt constant, HTML/JSON-LD
  evidence extraction, URL/topic helpers, classification orchestration, CLI parsing, and output
  rendering move into `scripts/intake_flow/`, while `intake.py` remains the stable CLI/import
  facade.
- `scripts/inbox.py`: inbox queue constants/default normalization, path guards, unique filename
  helpers, article-frontmatter serialization, article/registry lookup, capture/route operations,
  and CLI orchestration move into `scripts/inbox_flow/`, while `inbox.py` remains the stable
  CLI/import facade and compatibility monkeypatch bridge.
- `scripts/sanitize_incoming.py`: CLI parsing, sanitizer result models, the deterministic S1-S9
  rules engine, frontmatter/YAML-value sanitization, companion audit/hash integrity internals, and
  tree-level sanitize/gate operations move into `scripts/sanitizer/`, while `sanitize_incoming.py`
  remains the stable CLI/import facade for existing callers.
- `scripts/delivery/deliver.py`: CLI parsing and delivery model types move into
  `scripts/delivery/cli.py` and `scripts/delivery/model.py`; live delivery orchestration moves into
  `scripts/delivery/runtime.py` with context/lock handling in `runtime_context.py`, channel
  selection in `dispatch.py`, receipt idempotency/persistence in `receipt_flow.py`, final status
  reporting in `runtime_status.py`, default path policy in `paths.py`, and MCP receipt facade wiring
  in `scripts/delivery/mcp.py`, while `deliver.py` remains the stable command/import facade for
  delivery dispatch, receipts, MCP receipt helpers, and existing callers.

A second pass applied the same rule to the three modules that were still the largest in the tree
after the splits above (~950–1000 lines each). It changes no behavior: every name stays importable
from its original module, so tests, skills, and `python3 scripts/X.py` are untouched.
- `scripts/build_digest.py`: the JSON audit-sidecar builder and the browser-report input snapshots
  (concepts, lessons/playbooks, glossary terms, stats, per-topic audit topics) move into
  `scripts/digest/report_inputs.py`, joining the existing `model`/`scan`/`render` modules, while
  `build_digest.py` keeps the CLI, the `build_digest()` orchestration, and the `__all__`
  compatibility surface.
- `scripts/delivery/digest_report_html.py`: the `Report*` dataclasses move into
  `scripts/delivery/report_models.py` (rendering-free, so the tab renderers can import the shapes
  without a cycle back to the facade), the shared inline-markdown helper into `report_inline.py`,
  and the three self-contained tabs into `report_audit.py` (per-topic source-selection drilldown),
  `report_concepts.py` (concept cards + `obsidian://` deep links), and `report_vault.py`
  (lessons/playbooks), while `digest_report_html.py` keeps `render_digest_report`, the digest-body
  and pulse/glossary rendering, and re-exports every moved name.
- `scripts/collect.py`: the per-category collection loop (`collect_category`, `CollectResult`,
  `_record_health`) moves into `scripts/collection/run.py`, joining the existing
  `article`/`feed`/`fetch`/`registry`/`text` modules, while `collect.py` keeps the CLI, the author
  roster merge, and a thin `collect_category` facade. Because `run.py` must not import the facade
  back, the seams tests monkeypatch on `scripts.collect` — `fetch`, `_record_health`,
  `record_decision`, `append_registry_row_if_absent` — are resolved by the facade **at call time**
  and passed down as injected parameters. Binding them as defaults in `run.py` would silently
  capture the pre-patch functions and make those tests assert against dead code.

## Consequences
- Cron, skills, docs, and user commands remain stable while internal code becomes easier to review
  and test.
- Refactors can be scoped to one script at a time. Good next candidates are any future script that
  grows beyond a stable facade plus a clearly owned domain package.
- Compatibility facades may temporarily re-export private helpers. That is intentional during
  migration; once tests and sibling modules stop reaching into private names, the facade can narrow.
- New domain packages should still follow ADR 0002: runtime imports remain stdlib plus `pyyaml`.
- A pure "move files into folders" change is not enough. Each split should clarify ownership:
  parsing, rendering, persistence, transport, validation, CLI, etc.

## Alternatives considered
- **Rename commands into subpackages** (for example `python3 -m scripts.collection.collect`). Rejected:
  breaks the shipped operator contract and forces unrelated docs/skill/schedule churn.
- **Leave large scripts flat.** Rejected: the files already mix layers, and future changes will keep
  increasing hidden coupling.
- **Move everything in one large refactor.** Rejected: too much blast radius for a maintenance
  change; the proven digest/hygiene pattern supports incremental migration.

## References
- `scripts/build_digest.py`, `scripts/digest/`
- `scripts/validate_brain.py`, `scripts/hygiene/`
- `scripts/collect.py`, `scripts/collection/`
- `scripts/manage_sources.py`, `scripts/sources/`
- `scripts/validate_config.py`, `scripts/config_validation/`
- `scripts/health.py`, `scripts/health_checks/`
- `scripts/brain_status.py`, `scripts/status/`
- `scripts/trends.py`, `scripts/trend_report/`
- `scripts/import_opml.py`, `scripts/opml_import/`
- `scripts/intake.py`, `scripts/intake_flow/`
- `scripts/inbox.py`, `scripts/inbox_flow/`
- `scripts/sanitize_incoming.py`, `scripts/sanitizer/`
- `scripts/delivery/deliver.py`, `scripts/delivery/cli.py`, `scripts/delivery/model.py`,
  `scripts/delivery/runtime.py`, `scripts/delivery/runtime_context.py`,
  `scripts/delivery/dispatch.py`, `scripts/delivery/receipt_flow.py`,
  `scripts/delivery/runtime_status.py`, `scripts/delivery/paths.py`, `scripts/delivery/mcp.py`
- Second pass: `scripts/digest/report_inputs.py`; `scripts/delivery/report_models.py`,
  `scripts/delivery/report_inline.py`, `scripts/delivery/report_audit.py`,
  `scripts/delivery/report_concepts.py`, `scripts/delivery/report_vault.py`;
  `scripts/collection/run.py`
- [ADR 0002](0002-stdlib-only-runtime.md) — runtime dependency boundary.
