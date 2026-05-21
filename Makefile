# kraken-alpha-agent — developer shortcuts
# Windows: install make via choco/scoop, or run commands directly (see docs/QUALITY.md)

.PHONY: test lint collect dry-run-once help

help:
	@echo "Targets: test | lint | collect | dry-run-once"

test:
	python -m pytest -q

lint:
	ruff check src tests scripts

collect:
	python -m pytest --collect-only -q

dry-run-once:
	python scripts/dry_run_once.py
