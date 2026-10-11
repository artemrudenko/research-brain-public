# tier-rules — extended tiering rules for research-audit

Reference material. Loaded from SKILL.md only for complex edge cases (Phase 0 Step 2). Base rules are in `rules/common.md` § "Cross-source thresholds".

> The vendor / publication names below are illustrative examples of how a tier maps to a real source class. Adapt the registry (`sources/trusted-registry.md`) to your own domain.

---

## Tier classification edge cases

### Vendor docs vs vendor blog vs vendor marketing

| Source | Tier | Notes |
|---|---|---|
| `docs.{vendor}.com` | T1 | Primary technical docs — authoritative |
| `{vendor}.com/news` or `{vendor}.com/blog` | T1 | Vendor announcements — authoritative for the vendor's own claims |
| `{vendor}.com/customers` or case studies | T2 | Vendor-curated, may carry selection bias |
| `{vendor}.com/pricing` | T1 | Authoritative for current pricing (but volatile — recency 3mo) |
| `{vendor}.com/landing-page` (marketing) | T2 | May contain unverified claims, needs a cross-check |

### Vendor about a competitor

- **Vendor's own benchmark vs a competitor:** T2 (a motivated party; needs an independent T1/T2)
- **Vendor's docs mentioning a competitor's feature parity:** T2 (the vendor describes how they fit — a relative claim)
- **Independent benchmark in a peer-reviewed paper:** T1
- **Trade-press review:** T2/T3 depending on depth

### Self-published research

- **Vendor's own research blog:** T1 for the vendor's own ML claims (model releases, benchmarks on their own tests)
- **Vendor's research paper** in a reputable venue (NeurIPS, ICLR, ACL) → T1
- **Vendor's preprint on arXiv**, not peer-reviewed → T1 for the academic claim, but flag "preprint" for the audit trail

### Practitioner blog tiers

| Pattern | Tier | Examples |
|---|---|---|
| Recognised industry expert with a track record | T2 | a well-known analyst or researcher with a public record |
| Active practitioner with publications | T2 | a practitioner who publishes and speaks |
| Random tech blogger without a verifiable track record | T3 | most generic blog posts |
| Corporate engineering blog | T2 | authoritative for that company's own engineering claims |

### Community forums detail

| Pattern | Tier |
|---|---|
| Q&A site accepted answer with high upvotes | T2 |
| Q&A site new answer without confirmation | T3 |
| Forum post with verified expert flair | T2 for opinion sampling |
| Forum anonymous comments | T3 |
| Aggregator comments — top-rated discussion | T3 (signal, not fact) |
| Issue / discussion on a vendor repo | T2 (a vendor reply is often present) |

---

## Numeric claim — detailed rules

### Strict (numeric requires cross-source)

- Statistic with %: "X% of teams use Y" — minimum 2 sources, ≥1 T1/T2
- Market share / sizing: "$X billion market" — an analyst firm (T2) + cross-check with vendor disclosure (T1) or another analyst (T2)
- Benchmark numbers: "X scored 87% on benchmark Y" — preferably peer-reviewed (T1) or vendor primary

### Soft (single T1 acceptable)

- Vendor's own product metrics: "product X supports a 200k context" from `docs.{vendor}.com` — single T1 OK (vendor primary)
- Pricing: "Plan Z is $20/mo" from `{vendor}.com/pricing` — single T1 OK
- Version numbers: "version 4.5" from `{vendor}.com/news` — single T1 OK

### Always require cross-source (strict)

- Cross-vendor comparisons: "X is 2× faster than Y" — vendor benchmarks are always biased; need an independent source
- Industry-wide adoption claims: "70% of enterprises piloting AI" — survey methodology matters; need ≥2 analysts
- ROI claims: "companies see a 40% productivity gain" — usually vendor-sourced; a T1 vendor claim alone = 🟡, with an independent audit firm = 🟢

---

## Vendor-claim — detailed rules

### Own product, own docs

- Feature presence: T1 docs sufficient → 🟢
- Compatibility statement: T1 docs sufficient → 🟢
- Limit / quota: T1 docs sufficient (but flag recency, prices/limits change often) → 🟢

### Own product, vendor blog

- Roadmap announcement: T1 blog sufficient → 🟢, but flag "forward-looking statement" (date-bound)
- Feature deprecation: T1 blog sufficient → 🟢
- Performance claim with a specific number: needs cross-source if public-facing (an own benchmark is biased)

### Competitor product mentions

- Always require independent confirmation
- Vendor saying "X does not support Y" — needs a cross-check against `docs.X.com` or a third-party check

---

## Contradiction handling — extended

### Same value, different sources — easy case

Both confirm — even if from different tiers, the claim is 🟢 (or 🟡 if only T2).

### Different values, same metric

Resolution priority:

1. **Tier disparity:** if T1 vs T3 → trust T1, note the T3 in the log as outdated/community-myth, claim → 🟡 (the single authoritative survives)
2. **Recency disparity:** if both the same tier, the newer wins → claim → 🟡 (newer single source) + a note about the update in the log
3. **Methodology disparity (for surveys/benchmarks):** if explainable (different sample, different version) → both versions explicit, claim → 🔴

### Pseudo-contradictions

Claims that look contradictory but aren't:

- Different definitions: "product X has N tokens context" (max stated by the vendor) vs "product X effective context M" (third-party benchmark) — both true, different metrics
- Different time slices: "Q1 share 30%" vs "Q3 share 25%" — both true, the market changed
- Different segments: "70% enterprise adoption" vs "30% SMB adoption" — both true, segmentation matters

The verification log must distinguish: "pseudo-contradiction (different metrics/segments)" — the claim is rewritten, not flagged 🔴.

---

## Tier downgrade signals

The skill can downgrade a tier (note it in the log; do not edit the registry without an AskUserQuestion):

- T1 source with explicit marketing language and no data → effective T2
- T2 analyst report >24mo old → effective T3 for current-state claims
- T1 vendor blog with promises ("we will…") without confirmed delivery → effective T2 for verification (promises vs done)

A downgrade is soft, recorded in the claim entry of the verification log as `effective_tier: T2 (downgraded from T1: marketing language)`.

---

## Special cases

### Vendor pricing pages (`{vendor}.com/pricing`)

- T1 for current pricing
- Recency strict — 3mo override (always-volatile per `sources/always-volatile-domains.md`)
- If scraping is not possible (dynamic pricing, login wall) — a manual hand-off is required; research-audit marks the claim 🟡 "manual-confirmed pending"

### Regulator portals (NIST, EU, CoE)

- Always T1
- Recency for regulators — a meaningful threshold is 24mo (regulators iterate slowly), but if the topic is active legislation → 6mo

### Academic preprints (arXiv)

- T1 for academic claims
- Flag "preprint, not peer-reviewed" in the log entry — for transparency
- If a preprint has a peer-reviewed published version — preferentially cite the published one, fall back to the preprint only if a paywall blocks it

---

## Evidence-type taxonomy — extended rules

Reference for extended mode (when `grading_mode == extended` in the brief). 8 evidence types + detailed rules for determination and downgrade signals.

### Type definitions (extended)

#### `peer-reviewed` (T1 baseline)

- Conferences: NeurIPS, ICLR, ACL, EMNLP, AAAI, ICML, KDD, CVPR, IJCAI
- Journals: Nature, Science, JMLR, Communications of the ACM
- Reviewed standards bodies: IETF RFCs, ISO docs, NIST publications
- **Downgrade signal:** if peer-reviewed but >36mo old → effective T2 for current-state claims

#### `official-doc` (T1 baseline)

- Vendor primary technical docs: `docs.{vendor}.com`
- Regulator portals: NIST cybersecurity framework, EU regulatory docs, privacy-law texts
- Standards bodies: ISO 27001, IEC 62443, IEEE specs
- **Downgrade signal:** if the doc page contains "coming soon" / "alpha" / "may change" disclaimers → effective T2 (content not stable)

#### `vendor-blog` (T1 baseline)

- Authoritative for own-product claims
- Examples: `{vendor}.com/news`, `{vendor}.com/blog`, an engineering blog
- **Downgrade signal:**
  - Forward-looking statements ("we will ship Y by Q2") → effective T2 (promise vs delivered)
  - Marketing-heavy posts without data / specifics → effective T2 (vendor-marketing)
  - Cross-vendor comparison posts → effective T2 (motivated bias)

#### `vendor-marketing` (T2 baseline)

- Sales-oriented landing pages, feature comparison pages (especially "us vs them")
- Pricing pages with stated values but no data on guarantees
- Customer case studies (vendor-curated, selection bias)
- **Never upgrade to T1** even if on a vendor primary domain

#### `trade-press` (T2 baseline)

- Established technology and business news outlets
- **Downgrade signal:**
  - Article merely retells a vendor blog without independent reporting → effective T3 (echo chamber)
  - Speculative / opinion piece → effective T3 (no fact base)
- **Upgrade signal:** an in-depth investigative piece with FOIA / leaked docs → T1 for the cited primary materials

#### `expert-opinion` (T2-T3 baseline)

- T2: recognised analysts and practitioners with a verifiable track record
- T3: generic blog posts without a verifiable track record
- **Trigger T2:** the practitioner has publications, citations, conference talks, recognised expertise in the domain
- **Stays T3:** an anonymous author, a random social post, an untraced expert claim

#### `forum-post` (T3 baseline)

- Discussion forums, Q&A sites, aggregator threads
- **Upgrade signal:**
  - Q&A accepted answer with >50 upvotes + independent verification → effective T2 for technical claims
  - Aggregator top comment with the author's identity verified → effective T2 for opinion sampling
  - Forum post with verified expert flair → effective T2 for opinion sampling

#### `anon-source` (T3, never upgraded)

- Unattributed claims, leaked memos without verification, anonymous social threads, dark social
- In extended mode triggers an automatic 🔴 **Very-Low** marker
- In standard mode triggers 🔴

### Evidence-type assignment heuristics

When extracting a claim in Phase 2 (Extract verifiable claims) — automatic evidence-type assignment by host:

```python
def infer_evidence_type(host, url_path):
    if host in PEER_REVIEWED_HOSTS:           # arxiv (if cross-referenced with a published version), nature.com, etc.
        return "peer-reviewed"
    if host.startswith("docs.") or host in REGULATOR_HOSTS:
        return "official-doc"
    if "/news/" in url_path or "/blog/" in url_path:
        if host in VENDOR_HOSTS:
            return "vendor-blog"
    if host in TRADE_PRESS_HOSTS:
        return "trade-press"
    if host in EXPERT_BLOG_HOSTS:
        return "expert-opinion"
    if host in FORUM_HOSTS:
        return "forum-post"
    if host in MARKETING_HOSTS or "/products/" in url_path:
        return "vendor-marketing"
    return "anon-source"  # fallback for unrecognised
```

In a real implementation, the mapping is stubbed in `sources/trusted-registry.md` via an extra `evidence_type` field per registry entry. If the field is absent, it falls back to the host pattern.

### Per-claim downgrade signals in extended mode

The skill can downgrade an evidence-type effectively (note it in the log; do not edit the registry without an AskUserQuestion):

- Peer-reviewed but >36mo old → effective `expert-opinion` for current-state claims
- Vendor-blog with forward-looking statements → effective `vendor-marketing`
- Trade-press echo of a vendor → effective `forum-post` (no independent reporting)
- Expert-opinion without citation / data → effective `forum-post`

A downgrade is recorded in the claim entry of the verification log as:

```yaml
- id: C7
  text: "..."
  evidence_type: peer-reviewed
  effective_evidence_type: expert-opinion  # downgraded
  downgrade_reason: "Paper >36mo, claim about current-state model performance — outdated"
```
