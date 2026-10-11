# research-brain — developer entrypoints, all built on uv (https://docs.astral.sh/uv/).
# `make setup` is the one command that stands up a working dev environment:
# it creates .venv (pinned to .python-version) and installs runtime + dev deps
# from uv.lock. Everything else runs inside that managed venv via `uv run`.

.DEFAULT_GOAL := help
.PHONY: help install setup lock test mcp-test lint typecheck security gate fmt export clean configure dist schedule \
        exports-check frontmatter config-check pipeline-frontmatter brain-hygiene public-check telegram

# Every quality gate runs through the LOCKED environment, exactly as CI does
# (`uv run --frozen`, see .github/workflows/ci.yml). Without --frozen, `uv run`
# may silently re-resolve and "fix" a stale uv.lock, so a green local `make gate`
# could still fail CI. `lock`/`setup` deliberately do NOT use this (they may
# update or materialize the lock).
UVR := uv run --frozen

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Dependency bootstrap: uv (if missing) + venv + deps. Config is a separate step (spoken wizard, or `make configure`)
	./install.sh

setup: ## Create .venv and install runtime + dev deps (assumes uv is already installed)
	uv sync

lock: ## Re-resolve dependencies and refresh uv.lock
	uv lock

# DEVELOPING.md ships only in the dev checkout (export-ignored), so its absence
# marks a shipped install — where regenerating requirements-dev.txt would
# resurrect a deliberately-stripped dev file and `git diff` has no repo to diff.
define require-dev-checkout
	@test -f DEVELOPING.md || { \
		echo "make $@: dev checkout only — a shipped install uses requirements.txt as-is"; \
		exit 1; }
endef

export: ## Regenerate the pip-fallback requirements*.txt from uv.lock (dev checkout only)
	$(require-dev-checkout)
	uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.txt
	uv export --frozen --no-emit-project --no-hashes -o requirements-dev.txt

test: ## Run the test suite with coverage (the blocking CI gate)
	$(UVR) pytest --cov --cov-report=term-missing -ra

mcp-test: ## Check the optional MCP adapter in its isolated locked environment
	$(UVR) --project integrations/mcp_server $(if $(MCP_PYTHON),--python $(MCP_PYTHON),) --group dev pytest integrations/mcp_server/tests -q
	$(UVR) --project integrations/mcp_server $(if $(MCP_PYTHON),--python $(MCP_PYTHON),) python integrations/mcp_server/examples/replay.py

lint: ## Lint runtime, tests, and contributor tools with ruff
	$(UVR) ruff check scripts tests tools integrations/mcp_server

fmt: ## Auto-fix lint issues with ruff
	$(UVR) ruff check --fix scripts tests tools

typecheck: ## Type-check scripts with mypy
	$(UVR) mypy

security: ## Scan runtime scripts and public-export tooling with bandit
	$(UVR) bandit -r scripts tools -c pyproject.toml

schedule: ## Register the recurring run in cron from config/schedule.yaml (PATH=claude|codex|headless, APPLY=1 to install it)
	$(UVR) python scripts/install_schedule.py --path $(or $(PATH_CHOICE),claude) $(if $(APPLY),--apply,)

configure: ## Interactive headless config installer (advanced; the spoken setup wizard is the recommended path)
	$(UVR) python scripts/configure.py

telegram: ## Start a Claude session with the Telegram channel live (inbound commands work)
	@exec ./scripts/telegram-launch.sh

# --- CI-parity checks (each mirrors a step in .github/workflows/ci.yml) ---
# `gate` must run every blocking CI step that CAN run on a dev box, so a green
# local run rarely fails in CI. When you add a CI step, add a target here and
# wire it into `gate`. Two CI jobs are NOT reproducible locally and a green
# `make gate` says nothing about them: the `windows-smoke` job (real Windows
# host — run_lock/registry win32 paths and the update.ps1 end-to-end) and the
# second Python version in the test matrix. Only CI clears those.

exports-check: ## Fail if requirements*.txt drift from uv.lock (run `make export` to fix; dev checkout only)
	$(require-dev-checkout)
	$(MAKE) export
	git diff --exit-code requirements.txt requirements-dev.txt

frontmatter: ## Enforce SKILL.md frontmatter contract
	$(UVR) python scripts/frontmatter_lint.py --enforce

config-check: ## Validate config schemas (channels/schedule/sources/topics/tags)
	$(UVR) python scripts/validate_config.py

pipeline-frontmatter: ## Strict frontmatter check on the pipeline stages
	$(UVR) python scripts/validate-pipeline-frontmatter.py pipeline/1-incoming --strict
	$(UVR) python scripts/validate-pipeline-frontmatter.py pipeline/2-curated --strict

brain-hygiene: ## Advisory brain-vault hygiene smoke pass
	$(UVR) python scripts/validate_brain.py

public-check: ## Ensure HEAD contains only reviewed public source files
	$(UVR) python tools/export_public.py --check-in-place

gate: lint typecheck security test mcp-test exports-check frontmatter config-check pipeline-frontmatter brain-hygiene public-check ## Run every CI quality gate locally

clean: ## Remove the venv and tooling caches
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov

DIST_DIR ?= dist
# The archive is the user-facing release artifact — name it by the product
# version (what update.sh shows as "updating X → Y"), not the git SHA.
dist: DIST_VERSION = $(shell python3 scripts/version.py current)
dist: ## Build a clean distribution archive (git archive, honors export-ignore). Override the output dir with DIST_DIR=…
	@mkdir -p "$(DIST_DIR)"
	@rm -f "$(DIST_DIR)"/research-brain-*.zip
	@git archive --format=zip --prefix=research-brain/ \
		-o "$(DIST_DIR)/research-brain-$(DIST_VERSION).zip" HEAD
	@echo "built $(DIST_DIR)/research-brain-$(DIST_VERSION).zip (commit $(shell git rev-parse --short HEAD))"
