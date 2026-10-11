# ADR 0015 — Least-privilege role subagents for model tiering and capability isolation

- **Status:** Accepted (2026-06-29)
- **Tags:** subagents, security, cost, claude-code

## Context
The weekly pipeline is one agentic loop where every step has historically run with the **same**
model and the **same** full tool surface — including delivery MCP and `brain/` write access — even
for steps that need neither. Two problems follow. **Cost:** the whole run pays the top model tier,
when collection (ranking + short summaries) and digest assembly (templating over on-disk files) do
not need it. **Security:** research-brain ingests untrusted external text (RSS) into synthesis
behind the S1–S9 sanitize gate (`scripts/sanitize_incoming.py`, CONVENTIONS §12); if an injection
ever survives that gate, a synthesis or critique step that still holds a delivery tool could be
steered into sending or exfiltrating. The sanitize gate is the primary defense, but there was no
*second* line confining what a compromised step can reach.

Claude Code (and Cowork) support project **subagents** (`.claude/agents/*.md`) that pin a `model`
tier and a strict `tools` allowlist per agent. Codex and the headless path have no equivalent
primitive.

## Decision
Define five least-privilege **role subagents** in `.claude/agents/`, each mapping a pipeline role
to a model tier and a tool allowlist, and delegate each `schedule/weekly-run.md` step to its role
**on Claude Code / Cowork**:

| Role | Model | Delivery surface | Maps to weekly-run step |
|---|---|---|---|
| `collector` | `sonnet` | none | 1 collect |
| `synthesizer` | `opus` | none | 3 synthesis (fans out `critic`) |
| `critic` | `sonnet` | none | audit pass inside synthesis |
| `digest-maker` | `haiku` | none | 5 digest build |
| `deliverer` | `haiku` | **only this role** | 6 deliver |

- **Portability is preserved.** Delegation is Claude-Code/Cowork-only and **optional**; the
  `weekly-run.md` steps are identical when run inline. On Codex / headless runtimes (no subagent
  primitive) the orchestrator runs each step inline. The run lock and cwd are inherited, so
  delegation never affects serialization (ADR 0009).
- **The tool/MCP allowlist is the binding boundary**, not the skill list — and it binds hard for
  MCP tools. Claude Code cannot allowlist *which* skills load (`Skill` is all-or-nothing), so
  containment comes from the tool surface: the four "thinking" roles list **no MCP at all**, so
  even a loaded delivery skill has no MCP tool to send through. Only `deliverer` is sanctioned to
  send, and it defaults to the headless `deliver.py` transports (MCP server names are added by
  the user when they want MCP delivery). For the headless transports the allowlist does *not*
  bind — see Limits below.
- **Single source of truth: `config/agents.yaml`** (role → model tier per runtime + tool
  allowlist + system prompt). `scripts/gen_agents.py` (TDD, stdlib + pyyaml) renders it into both
  runtime-native artifacts — `.claude/agents/*.md` and `config/codex-profiles.example.toml` — so
  the two formats cannot drift; `--check` (in the test suite) fails if a committed artifact is out
  of sync. The generated files carry a "do not hand-edit" notice; edits go to the spec.
- **The Codex mapping is model + reasoning-effort tier only** — Codex has no per-profile tool/MCP
  allowlist, so the cost lever carries over but the capability isolation degrades to the sanitize
  gate on Codex (moot for delivery, which is the headless `deliver.py` script there, not an MCP
  tool). Claude Code remains the runtime where the tool boundary is enforced.

## Consequences
- **Cost lever.** The `opus` tier is confined to `synthesizer`; `collector`/`critic` run `sonnet`,
  `digest-maker`/`deliverer` run `haiku` — the per-run cost driver moves down without touching
  synthesis quality. This is the structural home for the model-tiering recommendation in
  `docs/scheduling.md`.
- **Defense-in-depth (MCP transports).** An injection surviving the sanitize gate still cannot
  send via the MCP delivery transports (Gmail / Telegram MCP) from a synthesis/critique step —
  those roles carry no delivery MCP tool. The headless transports remain reachable through `Bash`
  (see Limits), so the allowlist boundary is real for MCP only; the send *responsibility* is
  isolated in one small, web-less, cheap agent.
- **Limits (known open surfaces).** The allowlist is airtight only for MCP tools. Every role
  keeps `Bash` because the pipeline's helper scripts (`collect.py`, `dedup.py`,
  `build_digest.py`, …) require it — and the same `Bash` can run the headless
  `scripts/delivery/deliver.py` (with `config/.env` secrets readable); `WebFetch`/`WebSearch`,
  where listed, can exfiltrate data via a crafted URL. For the headless path the boundary is
  therefore the role prompt's explicit ban + the sanitize gate + pre-send review — a policy, not
  a technical impossibility. Bash stays anyway: removing it would break the roles' primary job.
- **More agent objects to maintain**, and delegation only binds on Claude Code / Cowork — on Codex
  the protection degrades to the sanitize gate alone (acceptable: Codex is the headless path and
  uses headless transports anyway).
- **Three honest limits, documented:** no per-skill allowlist (mitigated by the tool boundary),
  the Bash/WebFetch open surface for the headless transports (the Limits bullet above), and
  v1 ships the role files for description-based auto-delegation + the `weekly-run.md` step
  parentheticals; per-skill hard-wiring beyond `weekly-run.md` is a follow-up.

## Alternatives considered
- **One agent, full surface (status quo).** Rejected — pays the top tier everywhere and gives a
  surviving injection a delivery tool.
- **Advisory role map the orchestrator reads (no native enforcement).** Rejected as a *security*
  control — an injection is not obliged to honor it; it would only deliver the cost lever. Kept the
  enforced native files instead.
- **Neutral `config/agents.yaml` spec + per-runtime generators now.** Deferred — full cross-runtime
  machinery is more than v1 needs (KISS); Claude-native-first delivers the real enforcement where a
  primitive exists, with the Codex mapping documented for later.
- **Restrict by skill allowlist.** Not possible in Claude Code (`Skill` is all-or-nothing); the
  tool/MCP allowlist is used as the boundary instead.

## References
- `config/agents.yaml` (the single source of truth) + `scripts/gen_agents.py` (the renderer,
  `--check` drift guard) + `tests/test_gen_agents.py`.
- `.claude/agents/` (the five generated role files) + `.claude/agents/README.md` (role table,
  enforcement reality, limits).
- `config/codex-profiles.example.toml` (the generated Codex per-role model/effort mapping).
- `schedule/weekly-run.md` (per-step delegation note + parentheticals).
- `CLAUDE.md` § Subagents.
- ADR 0009 (single gated orchestrator — the loop these roles delegate within),
  ADR 0012 (reader-subagent fan-out — the `synthesizer`→reader pattern this builds on),
  ADR 0003 (internal-corpus synthesis profile — the untrusted-text path the isolation protects).
- `docs/scheduling.md` "C. Codex" (the headless/Codex path that runs the steps inline).
