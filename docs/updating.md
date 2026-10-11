# Updating research-brain

Updating never touches your data. Your knowledge vault, run history, secrets, and
the topics/sources/channels you configured all survive — the update replaces the
**code** (scripts, skills, docs) with the new release and adds, add-only, any *new*
config or `brain/` scaffolding files it introduces (your existing files are never
overwritten).

> **TL;DR**
> ```bash
> ./update.sh path/to/research-brain-<new>.zip
> ```
> from inside your install. It shows what will change, backs up first, and keeps
> all your data. **Windows (PowerShell):** same contract, same flags —
> ```powershell
> .\update.ps1 path\to\research-brain-<new>.zip
> ```
> After the overlay, both runners re-validate your preserved config against the
> new release (`validate_config.py`) and tell you in plain language if anything
> needs adjusting — the update itself never fails on a config finding.

The compatibility rules an update relies on (additive config, `schema_version`,
no-downgrade, version hops, what exactly a release may change) are written down
in **[SUPPORT.md](SUPPORT.md#upgrade-policy)** — the upgrade policy.

---

## What is preserved vs updated

| Preserved (never overwritten) | Updated (replaced by the new release) |
|---|---|
| `brain/` — your knowledge vault | `scripts/` — the pipeline code |
| `pipeline/` — registry, archives, digests, receipts | `skills/` — the agent skills |
| `config/.env` — your secrets | `docs/`, top-level docs (README, guides) |
| **all your `config/`** — schedule/timezone, channels, | root files (`pyproject.toml`, etc.) |
| sources, topics, tags, glossary | *(new config files a release adds ARE added)* |
| user-created `sources/*.md` tier registries | *(shipped `sources/*.example.md` ARE updated)* |

**Your entire `config/` directory is treated as yours** — no existing config file
is overwritten, so your timezone, cadence, channels, sources, topics, tags and
glossary all survive. A config file a *new* release introduces is added; you keep
everything you already set. The same add-only rule applies to `brain/`: scaffolding
a *new* release ships (templates, `.base` views, front-door READMEs) is added, but
your notes are never overwritten and `concepts/` is never touched. User-created
`sources/*.md` tier registries are likewise yours — only the shipped `*.example.md`
templates are updated.

## How to update

> **What version am I on?** From the install folder:
> `python3 scripts/version.py current` (stdlib-only, works anywhere), or run the fuller
> read-only `uv run python scripts/doctor.py` — its report includes the version.

1. **Get the new archive** — the `research-brain-<version>.zip` handed to you (or an
   unpacked folder of it).
2. **From inside your current install**, run:
   ```bash
   ./update.sh path/to/research-brain-new.zip
   ```
   A directory works too: `./update.sh ../research-brain-new/`.
3. Read the preflight — it prints your installed version, the incoming version,
   and the transition (e.g. `updating 0.1.0 → 0.2.0`). Confirm when prompted.

That's it. The script takes a full backup before applying anything and tells you
where it is.

### First update on the public release line

Public `0.1.0` includes `update.sh` and `update.ps1`, so the first later update
uses the ordinary command above. The updater refuses a numerically lower
version. An installation from a separate version line needs a full backup and
compatibility review before migration; do not bypass the version check simply
to adopt a release number.

## Options

| Flag | Effect |
|---|---|
| `--dry-run` | Rehearse: show exactly what would change, copy nothing, take no backup. |
| `--yes` | Don't prompt for confirmation (for scripting). |
| `--force` | Allow a downgrade or a same-version reinstall (refused by default). |
| `--backup-dir DIR` | Where to write the pre-update backup (default: system temp). |

**Always safe to preview first:**
```bash
./update.sh --dry-run path/to/research-brain-new.zip
```

## Safety guarantees

- **No data loss.** The overlay uses `rsync` without `--delete` and an explicit
  preserve-set, so your files are never removed or overwritten — only *new*
  release files are added (new config, and `brain/` scaffolding such as templates
  and `.base` views; your notes and `brain/concepts/` are never touched).
- **No silent downgrade.** The version preflight refuses to install an older (or
  identical) version unless you pass `--force`.
- **Reversible.** A full `.tgz` backup of the install is taken before any change
  (and the update aborts *before* touching anything if the backup can't be
  written). The script prints the exact one-line restore command, e.g.:
  ```bash
  tar -xzf /tmp/research-brain-backup-0.1.0-<stamp>.tgz -C /path/to/parent
  ```
  If an update is **interrupted** (power loss, Ctrl-C mid-copy), the install may be
  in a mixed state — restore from that backup. Note the restore overlays the old
  files back; if you want a clean state, remove the install dir first, then extract.
- **Old files are not deleted.** The overlay never removes files, so a script or
  skill dropped in the new release lingers harmlessly; the [CHANGELOG](../CHANGELOG.md)
  calls out any removal that matters. To spot these leftovers, the update prints an
  **orphan report** — `orphaned (present here, not in the new release):` — listing
  code files your install has that the new release no longer ships (a `--dry-run`
  shows it too, or `no orphaned files.` if clean). It never lists your data
  (`brain/`, `pipeline/`, `config/`, or your own `sources/*.md` tier registries),
  and it's purely informational: review and delete by hand if unwanted.

## After updating

Nothing else is required — the next scheduled run (or a manual `run-now`) uses the
new code against your existing data. If a release note in
[`CHANGELOG.md`](../CHANGELOG.md) mentions a config change, it will say so
explicitly; otherwise your configuration carries over unchanged.

## What this does NOT do (yet)

- **Apply config-schema migrations for you.** When a release ships a migrator for a
  config shape change, the update **offers** it and never auto-applies. For an
  older Markdown-to-YAML sources/topics migration it prints a one-liner naming
  `python3 scripts/schema.py migrate-config` (a sidecar migration — your `.md`
  files stay untouched as the rollback; delete the YAML twins to revert). You run
  it when ready; see [`docs/SUPPORT.md`](SUPPORT.md) for the upgrade policy. A
  future shape change *without* a shipped migrator falls back to the old story:
  your file is kept as-is and `validate_config.py` points out what to edit.
- **Vault format migration.** `brain/` / `pipeline/` frontmatter is left untouched;
  `validate_brain.py` reports any drift advisorily.

See [ADR 0019](adr/0019-assisted-in-place-update.md) for the design and rationale.
