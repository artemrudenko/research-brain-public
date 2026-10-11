# Audience levels — `delivery.technical_level`

A single render-time knob that controls **how much is explained vs assumed** in everything the
system shows the user. One value, three levels, set in `config/channels.yaml`:

```yaml
delivery:
  technical_level: balanced   # technical | balanced | non-technical
```

Absent → **`balanced`** (the default for a fresh install). Change it any time via the
`setup-wizard` reconfigure flow or the `/audience` Telegram alias. The enum is validated by
`scripts/validate_config.py` — an off-enum value (e.g. `expert`) is a hard config error, not a
silent default.

---

## The cardinal rule: it is a render-time transform, NOT a data change

The knob affects **presentation only** — the digest, `brain-ask` answers, research output framing,
and Telegram replies. It does **not** change what is stored in `brain/` or in
`pipeline/3-synthesis/`. Concepts and synthesis docs always stay full-fidelity and technical
(every fact still cites its `sources:`). This means:

- Switching levels is instant and free — no re-collection, no re-synthesis. The same vault renders
  three ways.
- The single source of truth is preserved: we never keep a "simplified copy" of knowledge that can
  drift from the real one.

So the transform happens **at the moment of delivery/answering**, reading `technical_level` and
adjusting wording — it is never baked into a stored artifact.

---

## What each level means

| | **technical** | **balanced** (default) | **non-technical** |
|---|---|---|---|
| Jargon | kept as-is | defined on first use | avoided or expanded |
| Acronyms | left bare | expanded once | always expanded |
| Raw identifiers (versions, model IDs, API/config names, numbers) | shown in full | shown, with a short gloss | minimised; kept only when load-bearing, then explained |
| Per-item framing | "so what" implied | one plain-language takeaway line per item | leads with **why it matters** before any detail |
| Analogies / examples | none needed | light | used to ground unfamiliar concepts |
| Length / density | terse, dense | moderate | more words, more explanation, less density |
| Assumed background | domain fluency | some familiarity | none |

**The axis is literacy, not stakes.** The user's stated intuition holds: a *less* technical reader
sees **more explanation** (not more raw detail). A *more* technical reader sees **more raw
specifics and less hand-holding**.

### Worked micro-example — the same finding, three ways

- **technical:** "vLLM 0.6 adds prefix caching; ~2.1× throughput on long shared prefixes."
- **balanced:** "vLLM 0.6 (an LLM serving engine) added *prefix caching* — reusing computation for
  shared prompt prefixes — for ~2.1× throughput on long shared prefixes."
- **non-technical:** "A popular tool for running AI models got faster (~2×) when many requests share
  the same long opening text, because it now reuses work instead of redoing it."

---

## Orthogonal to the research `audience` question

`research-frame`'s Frame questionnaire asks an `audience` question (internal review / external
deliverable / strategic-leadership). That is a **formality / stakes** axis — it governs how much
verification and editorial rigor a deliverable gets (Anti-AI Audit, Critique pass, tiering). It is
**not** the same as `technical_level`, which is a **reader-literacy** axis. They compose: a
*strategic-leadership* deliverable can still be rendered `non-technical`, and an *internal-review*
note can be `technical`. Do not collapse one into the other.

---

## Who reads this knob

Only **delivery / answer surfaces** read the knob — the surfaces that produce text *for the user
to read right now*:

| Surface | Reads `technical_level` to… |
|---|---|
| `digest-build` (RICH agent path) | render the weekly digest at the configured level (the main recurring artifact) |
| `schedule/weekly-digest.md` (the scheduled agent build) | render the *delivered* weekly digest at the configured level when it enriches the deterministic file |
| `brain-ask` | frame status / findings answers at the configured level |
| Telegram replies / chat-answer research | match the level in conversational answers |

Each reads `delivery.technical_level` from `config/channels.yaml`, defaulting to `balanced` when
the key is absent.

**What does NOT read it (by design):** anything that writes a **stored** artifact —
`research-build`'s synthesis documents and `wiki-ingest`'s `brain/concepts/` notes stay
full-fidelity and technical (every fact cites `sources:`). The knob is applied when that stored
knowledge is later *delivered*, never when it is written. This is the render-time principle in
[ADR 0013](adr/0013-technical-level-render-time-knob.md).

**Limitation — the headless deterministic digest can't reword.** `scripts/build_digest.py` is
LLM-free, so it renders the same layout regardless of `technical_level`; the knob shapes the
**RICH agent-authored** digest and the interactive answers above. A headless/cron-only install
therefore sees the level honored in answers but not in its plain deterministic digest. So the
no-op is never silent, a deterministic digest built with a **non-default** level appends an
honest one-line footer (`_🎚 Audience level '<level>' is configured — … this deterministic
(no-agent) build keeps its fixed wording_`); the agent build replaces it with
`_🎚 Detail level: <level>_` once it has actually re-rendered at that level.
