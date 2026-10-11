# .claude/agents/ — least-privilege role subagents (Claude Code / Cowork)

These are **project subagents** (Claude Code's `.claude/agents/*.md` format). Each maps a
pipeline role to a **model tier** and a **tool allowlist**, so the orchestrator can delegate a
step to an agent that (a) runs on a cheaper or stronger model as appropriate and (b) cannot load
any tool outside its allowlist — a hard boundary for MCP tools, with known open surfaces where
`Bash`/`WebFetch` remain listed (see the enforcement section below).

> **Generated — do not hand-edit the `*.md` files.** They are rendered from the single source of
> truth [`config/agents.yaml`](../../config/agents.yaml) by `scripts/gen_agents.py` (which also
> renders the Codex `config/codex-profiles.example.toml`, so the two formats can't drift). Edit
> the spec, then run `python3 scripts/gen_agents.py`; `--check` (in the test suite) fails on drift.
> This `README.md` is hand-written and is not generated.

The role files are additive: Codex / headless runtimes ignore this directory. The Codex
equivalent ships as `config/codex-profiles.example.toml` — it maps the same roles onto Codex
profiles, but **model + reasoning-effort tier only** (Codex has no per-profile tool/MCP
allowlist), so on Codex the cost lever carries over while the capability isolation degrades to
the S1–S9 sanitize gate. See `docs/scheduling.md` "C. Codex".

## The roles

| Agent | Model | Tools (allowlist) | Delivery? | Why this tier / surface |
|---|---|---|---|---|
| `collector` | `sonnet` | Read, Write, Edit, Glob, Grep, Bash, WebFetch, WebSearch | ❌ | Reads untrusted web; ranking + short summaries, not deep reasoning. No `Skill`, no `brain/` send. |
| `curator` | `sonnet` | Read, Write, Edit, Glob, Grep, Bash, Skill | ❌ | Keep/drop judgment over the **sanitized** companions only; no web (nothing to fetch), no delivery. |
| `synthesizer` | `opus` | + Skill, Agent (read/write, web) | ❌ | Quality-critical reasoning; fans out reader subagents (ADR 0012). Worth the top tier. |
| `critic` | `sonnet` | Read, Grep, Glob, Bash, WebFetch, WebSearch, Write, Skill | ❌ | Adversarial verification; runs often; no `Edit` (routes fixes via `wiki-ingest`). |
| `digest-maker` | `haiku` | Read, Glob, Grep, Bash, Write, Skill | ❌ | Mechanical assembly from on-disk files; cheapest; no web. |
| `deliverer` | `haiku` | Read, Bash, Skill (+ MCP names you add) | ✅ only | The **only** role that can send. Mechanical; isolated on purpose. |

This doubles as the **cost lever**: the expensive `opus` tier is confined to `synthesizer`;
everything else runs cheaper. See `docs/scheduling.md` for the per-run token/cost picture.

## How a step reaches an agent

- **Automatic** — Claude Code reads each agent's `description` and delegates a matching task to
  it. The descriptions are scoped to their pipeline step.
- **Explicit** — `@collector` / `@synthesizer …` by name, or name it in natural language. A
  skill or `schedule/weekly-run.md` step can say "delegate this to the `synthesizer` subagent".
- The agent runs with its own model + tool allowlist; the run lock and cwd are inherited from
  the orchestrator, so delegation does not break serialization.

> **Wiring note (v1).** These files make the roles **available and enforced when invoked**;
> hard-wiring every `weekly-run.md` step and skill to delegate to its role is a follow-up
> increment. Until then, rely on description-based auto-delegation and explicit `@`-mention.

## What is and isn't enforceable (read before trusting this as a control)

- **Model tiering — fully enforced.** `model:` binds per agent. ✅
- **Tool / MCP restriction — enforced per tool; a hard boundary for MCP transports only.** A
  present `tools:` line is a strict allowlist; anything unlisted is denied. The four "thinking"
  roles list **no MCP at all**, so the MCP delivery transports (Gmail / Telegram MCP) are
  physically closed to them. But every role keeps `Bash` (the pipeline's helper scripts need it),
  and Bash can equally run the headless `scripts/delivery/deliver.py` (with `config/.env`
  readable); `WebFetch`/`WebSearch`, where listed, can carry data out via a crafted URL. So the
  allowlist is airtight for MCP-tool sends; for the headless path the boundary is the role
  prompt's explicit ban + the sanitize gate + pre-send review. ⚠️
- **Per-skill allowlisting — NOT possible in Claude Code.** `Skill` is all-or-nothing: present =
  every skill can load, absent = none can. So we approximate skill-scoping two ways: (1) omit
  `Skill` from pure roles (`collector` has none); (2) lean on the **tool allowlist** where it
  binds — e.g. even if `synthesizer` loaded a delivery skill, it has no delivery MCP tool, so an
  MCP send fails (the headless send would still be reachable through Bash — forbidden by prompt,
  not by the allowlist). The tool/MCP allowlist, not the skill list, is what contains a role's
  MCP surface.

## Security rationale

research-brain ingests **untrusted external text** (RSS articles) into synthesis, behind the
S1–S9 sanitize gate (`scripts/sanitize_incoming.py`). These roles are **defense-in-depth** on
top of that gate: if an injection survives sanitization, a `synthesizer` / `critic` /
`digest-maker` carries **no delivery MCP tool**, so it cannot send through the MCP transports —
that part is enforced. The honest limit: those roles keep `Bash` (pipeline scripts) and, mostly,
web tools, so the headless `deliver.py` and URL-based exfiltration remain *reachable*; for that
path the containment is the role prompt's explicit ban, the sanitize gate itself, and review
before anything ships. The send responsibility lives only in the small, web-less, cheap
`deliverer`.
