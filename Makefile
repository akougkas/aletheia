SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
PY ?= $(UV) run python
PROFILE ?= zbook-single
COMPOSE_FILES ?= -f docker-compose.core.yml
UV_CACHE_DIR ?= /tmp/uv-cache
export UV_CACHE_DIR

.PHONY: help sync sync-dev sync-test sync-crawler lock test test-targeted demo demo-assert onboarding doctor capabilities compose-up compose-down compose-logs

help:
	@echo "ALETHEIA commands"
	@echo "  make sync               - install core runtime deps"
	@echo "  make sync-dev           - install dev deps"
	@echo "  make sync-crawler       - install crawler extras"
	@echo "  make test               - run full test suite"
	@echo "  make test-targeted      - run fast targeted phase-2 tests"
	@echo "  make onboarding         - run onboarding checks (PROFILE=<profile>)"
	@echo "  make doctor             - run db-doctor (PROFILE=<profile>)"
	@echo "  make demo               - run quick demo"
	@echo "  make demo-assert        - run strict phase-2 demo assertions"
	@echo "  make compose-up         - start compose stack (COMPOSE_FILES='-f docker-compose.core.yml ...')"
	@echo "  make compose-down       - stop compose stack"

sync:
	$(UV) sync

sync-dev:
	$(UV) sync --extra dev

sync-test:
	$(UV) sync --extra test

sync-crawler:
	$(UV) sync --extra crawler

lock:
	$(UV) lock

test:
	$(UV) run pytest -q

test-targeted:
	$(UV) run pytest -q \
		tests/test_demo_phase2.py \
		tests/test_cli_profiles.py \
		tests/test_cli_ux.py \
		tests/test_runtime_profiles.py \
		tests/test_compose_profiles.py \
		tests/test_llm_compat.py

onboarding:
	$(PY) cli.py onboarding --profile $(PROFILE)

doctor:
	$(PY) cli.py db-doctor --profile $(PROFILE)

capabilities:
	$(PY) cli.py capabilities --profile $(PROFILE)

demo:
	$(PY) demo.py --quick --profile $(PROFILE)

demo-assert:
	$(PY) demo.py --quick --assert-phase2 --profile $(PROFILE)

compose-up:
	docker compose $(COMPOSE_FILES) up -d

compose-down:
	docker compose $(COMPOSE_FILES) down

compose-logs:
	docker compose $(COMPOSE_FILES) logs -f --tail=200
