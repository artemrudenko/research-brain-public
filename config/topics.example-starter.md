# config/topics.example-starter.md — Starter topics

> **This is a STARTER PACK.** Copy the topics you want into `config/topics.md`
> (and the matching sources from `config/sources.example-starter.md` into
> `config/sources.md`), then run `python3 scripts/schema.py migrate-config --force`
> to land them in the active YAML config — or just run the `setup-wizard` skill,
> which does all of this for you.
>
> Keep each topic **name** in sync with the matching category in the sources config.

**Updated:** YYYY-MM-DD

---

## Topic: tech-news

- **Name:** `tech-news`
- **Save folder:** `pipeline/1-incoming/tech-news/`
- **Frontmatter tags:** `[tech, news]`
- **Include rules:** Substantive tech industry news — product launches, company moves,
  analyses, and deep-dives with concrete content.
- **Exclude rules:** Pure marketing/PR, low-signal hype, and AI/ML-specific items
  (route those to the `ai-ml` topic instead).

---

## Topic: ai-ml

- **Name:** `ai-ml`
- **Save folder:** `pipeline/1-incoming/ai-ml/`
- **Frontmatter tags:** `[ai, ml]`
- **Include rules:** AI/ML research, model releases, tooling, and applied technique
  deep-dives with real substance.
- **Exclude rules:** General tech news with no AI/ML angle (route to `tech-news`),
  and low-signal hype.
