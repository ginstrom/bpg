.PHONY: dry-run-test-suite test

dry-run-test-suite:
	. .venv/bin/activate && uv run pytest -q tests/test_cli_plan.py

test:
	. .venv/bin/activate && uv run pytest --cov=src --cov-report=term-missing
