"""
test_packaging.py — the 0.8.0 scripts-as-package contract (BACKLOG item 2).

Before 0.8.0 the project was `[tool.uv] package = false`: `scripts` was
importable only through sys.path hacks (one in conftest + ~80 copies across
scripts/ and tests/). The contract now:

1. `uv sync` installs the project (editable) into the venv, so ANY venv python
   — regardless of cwd, no path hacks — can `import scripts.*`. Tests,
   subprocesses, and tools stop needing inserts.
2. Operator CLIs are also exposed as console_scripts (`rb-*`) — an additive
   nicety; the documented `python3 scripts/X.py` invocations stay canonical
   and keep working WITHOUT any installation (the zip-run contract), which
   `test_schema`'s bare-interpreter run and the CLIs' own preludes pin.
"""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The operator CLI surface exposed as console_scripts: name -> module:callable.
EXPECTED_CONSOLE_SCRIPTS = {
    "rb-collect": "scripts.collect:main",
    "rb-digest": "scripts.build_digest:main",
    "rb-deliver": "scripts.delivery.deliver:main",
    "rb-doctor": "scripts.doctor:main",
    "rb-health": "scripts.health:main",
    "rb-setup-check": "scripts.setup_check:main",
    "rb-sanitize": "scripts.sanitize_incoming:main",
    "rb-trends": "scripts.trends:main",
}


def test_scripts_package_is_installed_venv_wide(tmp_path: Path) -> None:
    """From a NEUTRAL cwd, the venv interpreter must import the package tree
    with no sys.path help — the editable install, not a path hack."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import scripts, scripts.delivery.deliver, scripts.digest.render, "
            "scripts.health_checks.summary; print(scripts.__name__)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=tmp_path,  # neutral cwd: no repo-root implicit path
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "scripts"


def test_console_scripts_declared_and_resolve() -> None:
    eps = {
        ep.name: ep
        for ep in entry_points(group="console_scripts")
        if ep.name.startswith("rb-")
    }
    missing = sorted(set(EXPECTED_CONSOLE_SCRIPTS) - set(eps))
    assert not missing, f"console_scripts missing from the installed project: {missing}"
    for name, target in EXPECTED_CONSOLE_SCRIPTS.items():
        assert eps[name].value == target, (
            f"{name} points at {eps[name].value!r}, expected {target!r}"
        )
        assert callable(eps[name].load()), f"{name} does not load to a callable"


def test_pyproject_no_longer_opts_out_of_packaging() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "package = false" not in pyproject, (
        "[tool.uv] package = false contradicts the installed-package contract"
    )
    assert "[build-system]" in pyproject, "a build backend is required to install"


def test_no_sys_path_hacks_left_in_tests() -> None:
    """conftest.py owns the ONE bootstrap insert (robustness for odd invocation
    dirs); with the package installed, per-file copies are dead weight that
    invites drift — none may remain. AST-based: a `sys.path.insert(...)` CALL
    in test code is flagged; the same text inside a generated-child-script
    string literal (a legitimate direct-run simulation) is not."""
    import ast

    def has_path_insert_call(tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "insert"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "path"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "sys"
            ):
                return True
        return False

    offenders = sorted(
        path.name
        for path in (PROJECT_ROOT / "tests").glob("*.py")
        if path.name != "conftest.py"
        and has_path_insert_call(ast.parse(path.read_text(encoding="utf-8")))
    )
    assert not offenders, f"sys.path hacks back in tests: {offenders}"


def test_runtime_path_inserts_are_only_the_guarded_prelude() -> None:
    """scripts/ keeps ONE sanctioned sys.path idiom: the canonical prelude
    `if not __package__: sys.path.insert(...)` in directly-runnable CLIs —
    preserving the zip-run contract (`python3 scripts/X.py`, no install)
    while an installed/venv import skips it. Any other insert (the old
    unconditional blocks, the delivery/search fallback dances) is drift."""
    import ast

    offenders: list[str] = []
    for path in sorted((PROJECT_ROOT / "scripts").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Map each node to its parent so we can climb from a call to its guard.
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "insert"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "path"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "sys"
            ):
                continue
            guard = parents.get(node)
            while guard is not None and not isinstance(guard, ast.If):
                guard = parents.get(guard)
            guarded = (
                isinstance(guard, ast.If)
                and isinstance(guard.test, ast.UnaryOp)
                and isinstance(guard.test.op, ast.Not)
                and isinstance(guard.test.operand, ast.Name)
                and guard.test.operand.id == "__package__"
            )
            if not guarded:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert not offenders, (
        "sys.path.insert outside the canonical `if not __package__:` prelude:\n"
        + "\n".join(offenders)
    )


def test_license_is_present_and_declared() -> None:
    """A public repository without a licence grants nothing.

    Two halves, and both must agree: the LICENSE file is what a reader and every
    archive recipient actually sees, while `[project] license` is what packaging
    metadata reports to a resolver. research-brain shipped with neither until the
    first public release, so nothing in the suite noticed their absence.
    """
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text, "LICENSE must carry the MIT terms"
    assert "Permission is hereby granted, free of charge" in license_text, (
        "LICENSE must carry the MIT grant clause verbatim, not a summary of it"
    )

    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = { text = "MIT" }' in pyproject, (
        "pyproject.toml must declare the same licence the LICENSE file grants"
    )
