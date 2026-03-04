.PHONY: dry-run-test-suite test test-unit test-e2e test-system-integration test-ai-metrics build-docs

dry-run-test-suite:
	. .venv/bin/activate && uv run pytest -q tests/test_cli_plan.py

test-unit:
	. .venv/bin/activate && uv run pytest --cov=src --cov-report=term-missing tests --ignore=tests/e2e --ignore=tests/system_integration

test:
	$(MAKE) test-unit

test-e2e:
	. .venv/bin/activate && uv run pytest -q tests/e2e

test-system-integration:
	. .venv/bin/activate && uv run pytest -q -m system_integration tests/system_integration

test-ai-metrics:
	. .venv/bin/activate && uv run pytest -q tests/ai_friendly

build-docs:
	. .venv/bin/activate && ./scripts/build_docs.sh
