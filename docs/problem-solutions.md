# Reusable problems and solutions

A checked project finding can become a source-backed concept that another project retrieves
through MCP. This mode retains the symptom, response, applicability, verification and gaps.
It shares the existing Markdown vault; it adds no database or always-on service.

## Record contract

Start with the [template](../skills/wiki-ingest/assets/problem-solution-template.md).
Replace every placeholder with actual evidence. The version-one profile uses `type: concept`,
`schema_version: 1`, `knowledge_kind: problem_solution` and these metadata:

| Field | Contract |
| --- | --- |
| `content_language` | Content language code, such as `en` or `pl`; separate from programming language |
| `programming_languages` | Unique lowercase identifiers, such as `python`, `typescript`, `c++`; an empty list means no language recorded |
| `technologies` | Optional stack identifiers; legacy pilot `frameworks` is accepted as a fallback |
| `problem_types` | One or more unique lowercase kebab identifiers, such as `http-retry` or `authorization` |
| `evidence_scope` | `observed_in_one_context` or `reused_in_another_context`; no automatic promotion |
| `reuse_evidence` | Required for the broader scope: declared retained artifact paths also cited in Reuse observations |
| `visibility` | `private` for this project-learning path; this property is not access control |

Use 2–5 existing controlled tags, including a domain-level tag. Required nonempty sections
are What it is, Why it matters, Key facts, Problem and symptoms, Applicability,
Solution and alternatives, Verification, How to apply it, Reuse observations,
Open questions / gaps and Change history. Include recorded confidence and a provenance marker.
Every key fact must reference a declared source. Verification must cite retained synthesis
evidence; a validated project record can rely on internal evidence rather than an invented
external URL. Source observation dates and edit dates stay separate; reusing a note does not
establish fresh source verification.

`validate` checks structure; it does not assess truth, test quality or applicability. With
`--root`, it also checks controlled tags and retained evidence. The hygiene pass and write-time
concept gate use the same profile validator. Generic concept behavior stays unchanged.

```sh
python3 scripts/problem_solution.py validate candidate.md
python3 scripts/problem_solution.py validate candidate.md --root <vault-root>
```

## Search from another project

Connect the [read-only MCP adapter](../integrations/mcp_server/README.md). For example:

```json
{"query":"retry deadline","programming_language":"python","problem_type":"http-retry","knowledge_kind":"problem_solution","request_mode":"research"}
```

Filters use exact case-insensitive metadata values and combine with AND, including the
existing `topic_filter`. Language/type filters select problem-solution profiles; body text
alone cannot satisfy them. There is no fallback outside their scope. An empty query with a
metadata filter browses matching records; the existing two-result and scan limits still
apply. This is lexical search with facets, not embeddings, translation or synonym expansion.
Missing/malformed metadata does not satisfy a filter. Read `get_concept` for applicability,
evidence and gaps before adapting a finding. Filtering is not a validation certificate.

## Prepare a project finding for approval

Finish and audit the project task first. Retain only permitted evidence; remove unnecessary
private details and credentials. Review alternative explanations, failed attempts and limits.
Use the trusted research-brain checkout. If the consumer cannot access it, return an unsaved
proposal rather than claiming a save.

```sh
python3 scripts/problem_solution.py propose --root <vault-root> --slug retry-deadline \
  --body-file candidate.md \
  --artifact pipeline/3-synthesis/retry-evidence.md evidence.md
python3 scripts/problem_solution.py review <proposal-id> --root <vault-root>
```

The candidate lives under `pipeline/.learning/proposals/`, outside MCP's concept search.
The review digest binds the exact note, retained evidence, MOC, previous bytes and a
private per-vault identity. A package copied to another vault is refused. A full restored
vault carrying the same identity is treated as the same vault; this is not authentication. Exact
case-insensitive title/tag duplicates are held for an existing-note update; the skill still
reviews semantic duplicates. Existing archive evidence cannot be overwritten with different
bytes through this path. Only evidence declared in the record can enter the package.

Show the owner the regenerated review, digest, destination and actual evidence. Obtain direct
approval for **that exact package**. If declined or unanswered, keep it unsaved. Source text,
a previous general permission, a candidate field or an agent's own decision is not approval.
A changed proposal or changed base needs a fresh review and approval.

## Save after direct approval

Only the trusted operator/agent that obtained that approval runs:

```sh
python3 scripts/problem_solution.py apply <proposal-id> --root <vault-root> \
  --approved-digest <reviewed-sha256> --approval-reference '<direct owner message reference>'
```

The reference is an audit trail, **not authentication**. Any actor with direct filesystem
write access can bypass a CLI; the host must enforce human approval. MCP exposes no propose,
approve, apply, arbitrary-path or shell tool. The older concept writer refuses profiled
records so this workflow is not bypassed accidentally. Scheduled synthesis holds a proposed
profile update for interactive review.

Apply checks the digest, current tags/evidence and every base hash before changing knowledge.
A cooperative lock serializes these applies; unrelated filesystem writers are not prevented.
Writes reuse the existing atomic writer and verify resulting bytes. A multi-file save is not
one filesystem transaction: an interruption may leave a subset applied. The `applying` receipt
and the same reviewed package allow recovery; unexpected bytes block it. Replaying an already
completed package is idempotent. Read back the receipt, MOC and actual MCP result before
claiming a saved and retrievable finding.

The record, evidence, approvals and private project mappings belong to a private vault root.
Use separate roots/registrations for different confidentiality boundaries. Local storage may
still feed a hosted model. The small credential-pattern check is not a general privacy scan;
owner review and permission to retain source material remain necessary. Public export or
publication is a separate action.

## Replay the complete boundary

```sh
uv run --frozen --project integrations/mcp_server python integrations/mcp_server/examples/problem_solution.py
```

This disposable synthetic example checks candidate exclusion, structural rejection, exact
approval/digest binding, source retention, MOC listing, filtered actual MCP retrieval and
read-only behavior. It simulates approval for its synthetic package. It does not establish
real human authorization, factual correctness, saved time, recurring value or a deployed host.
