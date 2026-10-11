# ADR 0019 — Assisted in-place update

- **Status:** Accepted
- **Tags:** update, installation, data-preservation

## Context

An installation contains both shipped program files and user-owned data:
configuration, source material, vault notes, delivery receipts, and run history.
Replacing the whole directory would erase or overwrite the latter. An upgrade
also needs a visible version check and a recovery path if an overlay fails.

## Decision

Ship `update.sh` and `update.ps1` with the product. They read the incoming
archive's version, refuse a downgrade by default, validate the new archive,
create a full backup, then overlay program files while preserving user-owned
files. The scripts report files removed from the release without deleting a
user's copy. `docs/updating.md` defines the operator commands and recovery
steps; `docs/SUPPORT.md` states platform limits.

Configuration shape migrations are separate, explicit operations. When a
migrator exists, an update offers its command and leaves the user's files alone
until they run it. `scripts/schema.py migrate-config` is the supported import
for installations that still carry legacy Markdown source/topic tables.

The updater is the one supported code/data boundary. Contributor tooling and
public-export tooling must not define a second, conflicting overlay policy.

## Consequences

- A failed update has a backup and does not silently replace user configuration
  or vault content.
- New releases need fixture tests for preservation, downgrade refusal, and
  recovery on supported platforms.
- A public source repository is distinct from an unpacked installation. Run
  personal collection in a separate install so runtime material stays outside
  the source repository.

## Alternatives considered

- **Replace the installation directory:** rejected because it would discard
  user-owned state.
- **Automatically rewrite old configuration:** rejected because an operator
  should review the migration and its backup before applying a shape change.

## References

- `update.sh`, `update.ps1`, `docs/updating.md`, `docs/SUPPORT.md`
- `docs/CONVENTIONS.md` §8 (secrets and preserved data)
