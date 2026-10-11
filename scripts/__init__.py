"""research-brain runtime package (installed editable by `uv sync` since 0.8.0).

Deliberately empty of imports: entry modules are loaded explicitly
(`scripts.collect`, `scripts.delivery.deliver`, …) so importing the package
costs nothing and cannot create import cycles.
"""
