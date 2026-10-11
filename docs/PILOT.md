# Full-loop pilot and release gate

This protocol proves the product outcome that deterministic unit tests cannot:
a fresh installation repeatedly turns real sources into a useful digest and a
source-grounded knowledge vault.

It is a release gate for the **full agentic research brain**, not for RSS Digest Lite.
Run it before calling a release autonomous or broadly production-ready.

> **The deterministic half is already automated.** `tests/test_golden_journey.py`
> chains the real headless CLIs — collect → sanitize → build → deliver (dry-run) —
> over a hermetic vault on every `make gate` / CI run, so cross-stage contract
> drift can no longer ship. This protocol covers what that test cannot: agentic
> digest quality, real sends, and grounded synthesis on live sources. For the
> recurring-value numbers the evidence log asks for, `scripts/value_metrics.py
> report` computes retention / yield / reuse / feedback from the durable
> artifacts — only model/API **cost stays a manual field** here.

## Safety and scope

- Never run this protocol in the development checkout. `DEVELOPING.md` forbids live
  collect-to-deliver runs there.
- Use a disposable copy or the dedicated live installation.
- Never paste secret values into the evidence log.
- Use one test recipient/channel. Real delivery requires explicit operator approval.
- Preserve the generated vault and pipeline until the review is complete; then archive
  or discard the disposable installation.

## Pilot profile

Use a realistic but bounded configuration:

- 1–2 topics with clear include/exclude rules;
- 5–10 active sources total, with at least 3 RSS feeds per topic whose entries carry
  full bodies or link to static article pages;
- a mix of source tiers and at least two independent domains per topic;
- one enabled delivery channel;
- the default weekly synthesis threshold;
- the full agentic `schedule/weekly-run.md` path.

Record the runtime, model/profile, operating system, product version, topic names, source
count, and channel type. Do not record tokens, passwords, webhook URLs, or email contents
that contain private data.

## Stage 1 — Fresh-install activation

1. Build or unpack the release artifact into the disposable location.
2. Follow `FIRST-RUN.md` without relying on maintainer knowledge.
3. Configure topics, sources, delivery, timezone, and the recurring trigger.
4. Run the read-only doctor.
5. Rehearse delivery.
6. Trigger the full pipeline and allow the real test delivery only after the rehearsal
   identifies the correct recipient.

Capture:

- minutes from unpack to valid configuration;
- minutes from configuration to first delivered digest;
- number of undocumented interventions;
- source fetch successes/failures;
- run duration and estimated model/API cost;
- paths of the digest, synthesis log, and generated concepts.

### Activation pass criteria

- setup completes in ≤30 minutes with the starter path or ≤45 minutes with custom sources;
- the recurring trigger is actually registered, not merely written into
  `config/schedule.yaml`;
- `doctor.py` reports no FAIL findings before the real run;
- the run completes or stops at the correct failed gate;
- no raw incoming content is used by curation or synthesis;
- exactly one test delivery is sent to the intended recipient.

## Stage 2 — Content-quality review

Review the first digest and every concept written by the run.

Score each digest item:

- **Useful:** changes a decision, prompts a follow-up, or saves reading time;
- **Relevant but routine:** belongs in the topic but adds little;
- **Noise:** off-topic, duplicate, unsupported, or too vague.

For every generated concept verify:

- every key fact is supported by a listed source;
- source-diversity wording matches the evidence;
- no concept-level marker is presented as claim-level fact checking;
- tags come from the controlled vocabulary;
- confidence and open questions are honest;
- related concepts are meaningful rather than decorative.

### Quality pass criteria

- ≥60% of surfaced digest items are Useful;
- ≤20% are Noise;
- 100% of generated concepts carry usable `sources:`;
- no critical unsupported claim or leaked instruction appears;
- no duplicate story occupies more than one top-item slot without a reason;
- a reviewer can explain the weekly change in under five minutes.

Any critical unsupported claim, wrong-recipient delivery, leaked secret, or unsanitized
model input is an automatic NO-GO regardless of the aggregate score.

## Stage 3 — Idempotency and knowledge reuse

1. Re-run the same pipeline without changing sources.
2. Confirm unchanged material is not re-collected or re-synthesized unnecessarily.
3. Confirm the already-delivered digest is not sent twice.
4. Ask: “What does my brain know about {one generated concept}?”
5. Confirm the answer uses only the vault, cites the concept and underlying source, and
   does not fetch externally.
6. Ask the same question for a topic absent from the vault. Confirm it reports a miss and
   offers research without silently starting it.

### Reuse pass criteria

- registry and delivery idempotency hold;
- unchanged synthesis remains fresh;
- the vault answers at least one relevant question with explicit provenance;
- the vault-only miss respects its scope;
- the second run requires no maintainer intervention.

## Stage 4 — Degraded-path recovery

In the disposable installation:

1. Add or enable one unreachable feed and run collection.
2. Confirm the failure is visible in health output without hiding successful sources.
3. Rehearse one incomplete delivery configuration; do not send.
4. Confirm the doctor identifies the missing requirement without exposing a secret.
5. Correct both conditions and rerun.
6. Confirm locks are released and health returns to the expected state.

### Recovery pass criteria

- one failed source does not corrupt successful collection;
- a delivery wiring problem is caught before send;
- the failed/degraded state is visible in `status`/doctor output;
- correction and rerun succeed without manual edits to registry or receipts;
- no stale run or delivery lock remains.

## Stage 5 — Second-cycle retention check

Run a second real cycle after sources publish new material, ideally 5–8 days later.

Capture:

- new useful items;
- concepts created versus updated;
- whether prior knowledge improved the result;
- model/API cost and duration change;
- operator interventions;
- whether the recipient still wants the next digest.

### Pilot GO criteria

A pilot is GO only when:

- activation, quality, reuse, and recovery stages pass;
- two real cycles deliver successfully;
- the second cycle has at least one useful new or updated concept;
- total operator intervention after setup is ≤10 minutes per cycle;
- the user explicitly wants to keep the recurring run enabled.

Otherwise record NO-GO with the primary cause:

- onboarding;
- source quality;
- collection reliability;
- synthesis quality;
- trust/citations;
- delivery;
- runtime cost;
- insufficient user value.

## Evidence record

Use [`templates/pilot-evidence.md`](../templates/pilot-evidence.md) as the
copyable evidence contract. Copy it before the live canary run:

```bash
mkdir -p docs/pilot-evidence
cp templates/pilot-evidence.md docs/pilot-evidence/live-canary.md
```

Fill `docs/pilot-evidence/live-canary.md` from the disposable or dedicated live
installation. Keep `docs/PILOT.md` as the source of truth for stage criteria,
but record concrete evidence in the copied file: runtime/model/profile,
operating system, product version source, live target, topic and source count,
redacted channel label, activation time, run duration, estimated model/API cost,
source yield, concept created/updated counts, delivery outcomes, useful surfaced
items, operator interventions, explicit first-send approval, second-cycle useful
new or updated concept evidence, recurring-run preference, and final GO/NO-GO
decision.
The copied template names the retention evidence fields explicitly:
`Second-cycle useful new/updated concept:` and
`User wants recurring run enabled:`.

Validate the completed evidence record before review:

```bash
python3 scripts/pilot_canary.py validate docs/pilot-evidence/live-canary.md
```

The evidence record must preserve the same safety boundary as this protocol:
Never run this protocol in the development checkout, and never include secret
values, webhook URLs, raw tokens, recipient-private message contents, private
vault note contents, or `config/.env` contents. Env-var names, aggregate counts,
relative artifact paths, redacted channel labels, and pass/fail outcomes are
acceptable.

A GO decision requires every stage row to pass, two real cycles to deliver
successfully, the second cycle to include at least one useful new or updated
concept, post-setup operator intervention to stay within the documented limit,
and the user to explicitly want to keep the recurring run enabled. Otherwise
record NO-GO, choose the primary cause from the categories above, and write the
next corrective action.
