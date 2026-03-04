.PHONY: help dry-run-test-suite test test-unit test-e2e test-system-integration test-ai-metrics build-docs

help:
	@echo "Available targets:"
	@echo "  help                    Show this help text"
	@echo "  dry-run-test-suite      Run quick dry-run planning test"
	@echo "  test                    Run default test suite (unit)"
	@echo "  test-unit               Run unit tests with coverage"
	@echo "  test-e2e                Run end-to-end tests"
	@echo "  test-system-integration Run system tests + live system-integration tests"
	@echo "  test-ai-metrics         Run AI-friendly test corpus"
	@echo "  build-docs              Build docs"

dry-run-test-suite:
	. .venv/bin/activate && uv run pytest -q tests/test_cli_plan.py

test-unit:
	. .venv/bin/activate && uv run pytest --cov=src --cov-report=term-missing tests --ignore=tests/e2e --ignore=tests/system_integration

test:
	$(MAKE) test-unit

test-e2e:
	. .venv/bin/activate && uv run pytest -q tests/e2e

test-system-integration:
	. .venv/bin/activate && uv run pytest -q tests/system && uv run pytest -q -m system_integration tests/system_integration

test-ai-metrics:
	. .venv/bin/activate && uv run pytest -q tests/ai_friendly

build-docs:
	. .venv/bin/activate && ./scripts/build_docs.sh
