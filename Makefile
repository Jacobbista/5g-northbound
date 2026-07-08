# 5g-northbound - keep this short. Three commands you need to remember.
# Everything else is an alias.

.DEFAULT_GOAL := help

# Path to the local compose stack (moved under deploy/ as part of the
# repo reorganisation; every docker target threads this in so callers do not
# need to remember the path).
# `-p 5g-northbound` pins the project name independently of the compose file
# location, so container / network names stay stable across reorganisations
# and `docker ps` is still searchable by `5g-northbound-<service>-1`.
# `--project-directory .` tells compose to resolve relative paths against the
# repo root (where the user runs `make`), not the compose file's parent dir.
# Without this, paths like ./dev/foo.json would be looked up under
# deploy/compose/dev/ - which doesn't exist.
COMPOSE := docker compose -p 5g-northbound --project-directory . -f deploy/compose/docker-compose.yml

.PHONY: help
help:
	@echo ""
	@echo "  make demo     Build and (re)start the whole stack. Use this after any edit."
	@echo "  make stop     Stop everything (keeps data)."
	@echo "  make test     Run every service's test suite."
	@echo ""
	@echo "  make smoke    Token + curl both devices (sanity check the backend)."
	@echo "  make logs     Tail logs from all services."
	@echo "  make clean    Stop and remove containers + volumes."
	@echo ""

# --- The three you actually use ---

.PHONY: demo stop test env-config
# Bootstrap committed templates into the gitignored runtime files the first
# time `make demo` runs. Idempotent: only copies when the working file is
# absent, so existing local edits (real Mapbox tokens, the real venue
# blueprint) are never overwritten.
env-config:
	@for d in services/positioning-demo/public services/placement-editor/frontend/public; do \
		if [ ! -f "$$d/env-config.js" ] && [ -f "$$d/env-config.example.js" ]; then \
			cp "$$d/env-config.example.js" "$$d/env-config.js"; \
			echo "  -> bootstrapped $$d/env-config.js from example"; \
		fi; \
	done
	@if [ ! -f services/positioning-demo/public/layout.json ] && [ -f services/positioning-demo/public/layout.example.json ]; then \
		cp services/positioning-demo/public/layout.example.json services/positioning-demo/public/layout.json; \
		echo "  -> bootstrapped layout.json from example (generic demo venue)"; \
	fi
# `make demo` auto-detects dev/wifi-config.local.json (gitignored, real
# BSSIDs) and mounts it into wifi-positioning. Falls back to the committed
# placeholder dev/wifi-config.json when the local file is absent.
demo: env-config
	@export HOST_UID=$$(id -u); export HOST_GID=$$(id -g); \
	if [ -f dev/wifi-config.local.json ]; then \
		echo "  -> using dev/wifi-config.local.json (real bindings)"; \
		export WIFI_CONFIG=./dev/wifi-config.local.json; \
	else \
		echo "  -> using dev/wifi-config.json (placeholder bindings; create dev/wifi-config.local.json for real BSSIDs)"; \
	fi; \
	if [ -f services/rest-adapter/.env ]; then \
		if grep -q 'CHANGE-ME' services/rest-adapter/.env; then \
			echo "  !! services/rest-adapter/.env contains CHANGE-ME placeholders; skipped, using mock-wittra"; \
		else \
			echo "  -> using services/rest-adapter/.env (real vendor credentials)"; \
			set -a; . ./services/rest-adapter/.env; set +a; \
		fi; \
	else \
		echo "  -> using rest-adapter demo credentials (mock-wittra; create services/rest-adapter/.env from .env.example for the real cloud)"; \
	fi; \
	$(COMPOSE) up --build -d
	@echo ""
	@echo "  Demo:    http://localhost:3002"
	@echo "  Editor:  http://localhost:3003"
	@echo "  Gateway: http://localhost:8087"
	@echo ""

stop:
	$(COMPOSE) down

test:
	cd services/camara-gateway      && .venv/bin/pytest
	cd services/positioning-engine  && .venv/bin/pytest
	cd services/wifi-positioning    && .venv/bin/pytest
	cd services/placement-editor    && .venv/bin/pytest
	cd services/rest-adapter        && .venv/bin/pytest
	cd mocks/mock-positioning       && .venv/bin/pytest
	cd mocks/mock-wittra            && .venv/bin/pytest
	npm --prefix services/positioning-demo test
	npm --prefix services/placement-editor/frontend test

# --- Occasional helpers ---

.PHONY: logs clean smoke token env-check
# Validate the running compose stack against each service's env.contract.yaml.
# Prints one row per declared variable + flags any required var the compose
# file forgets to set. Read-only - does not touch containers.
env-check:
	@python3 deploy/tools/contracts.py validate

# Validate the positioning fabric: adapter capabilities (compose vs contract),
# and every asset's source/kind is served by some adapter. Static, no stack.
.PHONY: positioning-check
positioning-check:
	@python3 deploy/tools/positioning_check.py

# Contract hygiene + the machine-readable sensitivity manifest KELT consumes
# (var -> tier -> Secret/ConfigMap + provenance). Lint fails on hard problems.
.PHONY: contracts
contracts:
	@python3 deploy/tools/contracts.py lint
	@python3 deploy/tools/contracts.py sensitivity-manifest

# What is published per image, and which images a release actually changed.
# `make images` lists the latest ghcr tag per image; to see which images'
# source changed between two tags (the only ones worth re-pinning), run:
#   python3 deploy/tools/images.py v0.8.6 v0.8.7
.PHONY: images
images:
	@python3 deploy/tools/images.py

logs:
	$(COMPOSE) logs -f --tail=100

clean:
	$(COMPOSE) down -v --remove-orphans

token:
	@curl -s -X POST http://localhost:8180/realms/5g-testbed/protocol/openid-connect/token \
	  -d "grant_type=client_credentials&client_id=camara-gateway&client_secret=changeme" \
	  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])"

smoke:
	@TOKEN=$$($(MAKE) -s token); \
	for phone in +390111234567 +390117654321; do \
	  echo "=== $$phone ==="; \
	  curl -s -X POST http://localhost:8087/location-retrieval/v0.5/retrieve \
	    -H "Authorization: Bearer $$TOKEN" -H "Content-Type: application/json" \
	    -d "{\"device\":{\"phoneNumber\":\"$$phone\"}}" | python3 -m json.tool; \
	done
