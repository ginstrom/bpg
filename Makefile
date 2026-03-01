.PHONY: dry-run-test-suite test test-unit test-e2e

dry-run-test-suite:
	. .venv/bin/activate && uv run pytest -q tests/test_cli_plan.py

test-unit:
	. .venv/bin/activate && uv run pytest --cov=src --cov-report=term-missing tests --ignore=tests/e2e

test:
	$(MAKE) test-unit

test-e2e:
	. .venv/bin/activate && uv run pytest -q tests/e2e
