# Runtime pipeline

Collection creates `registry.md` and the `0-archive/`, `1-incoming/`,
`2-curated/`, and `3-synthesis/` directories as needed. They hold source text,
research output, and delivery records that belong to one installation. None is
part of the source repository or the public release snapshot.

The registry starts with a header when the first article is saved. Its schema
and atomic writer live in `scripts/registry.py`; do not edit or commit it by hand.
