.PHONY: help bootstrap up down down-clean logs ps migrate makemigration seed \
        codegen api.dev worker.dev worker.ping web.dev mock.api fmt lint test clean

COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml

help: ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_.-]+:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

bootstrap: ## copy *.env.example -> *.env if missing, generate secrets
	@./scripts/bootstrap.sh

up: ## start data services (postgres, redis, mailhog)
	$(COMPOSE) up -d
	@echo ""
	@echo "  postgres : localhost:55433  (shifted to coexist with Voicebot-Platform; see .env POSTGRES_PORT)"
	@echo "  redis    : localhost:56380"
	@echo "  mailhog  : localhost:1026   (web UI http://localhost:8026)"
	@echo ""

down: ## stop services, keep volumes
	$(COMPOSE) down

down-clean: ## stop services and wipe volumes (DESTRUCTIVE)
	$(COMPOSE) down -v

logs: ## tail compose logs
	$(COMPOSE) logs -f --tail=200

ps: ## show running containers
	$(COMPOSE) ps

migrate: ## alembic upgrade head
	cd infra/migrations && uv run --project ../.. alembic upgrade head

makemigration: ## alembic revision --autogenerate; usage: make makemigration NAME=add_x
	@if [ -z "$(NAME)" ]; then echo "Usage: make makemigration NAME=add_x"; exit 1; fi
	cd infra/migrations && uv run --project ../.. alembic revision --autogenerate -m "$(NAME)"

seed: ## run infra/seed/seed.py (admin user, default settings, brokers)
	uv run python infra/seed/seed.py

codegen: ## regenerate packages/shared-types/src/api.ts from FastAPI's OpenAPI
	@./scripts/codegen.sh

api.dev: ## run FastAPI on the host (hot-reload)
	cd apps/api && uv run uvicorn app.main:app --reload --port 7870 --host 0.0.0.0

worker.dev: ## run Celery worker on the host (embedded beat for sweeps)
	# OBJC_DISABLE_INITIALIZE_FORK_SAFETY: macOS aborts prefork children that
	# fork after google/grpc touch Obj-C; must be set before the process starts.
	cd apps/worker && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES uv run celery -A worker.celery_app worker --loglevel=info -Q default,audio,stt,llm -B

worker.ping: ## verify the placeholder ping task end-to-end
	cd apps/worker && uv run celery -A worker.celery_app call voiceqa.ping

web.dev: ## run Next.js on the host (port 3020)
	cd apps/web && pnpm dev

mock.api: ## run the mock Quam back-office API (port 7880)
	uv run mocks/backoffice_api/main.py

fmt: ## ruff format + prettier
	uv run ruff format .
	pnpm exec prettier --write "apps/web/**/*.{ts,tsx,md,json}" "packages/**/*.{ts,tsx,md,json}"

lint: ## ruff check + eslint
	uv run ruff check .
	cd apps/web && pnpm exec eslint .

test: ## pytest + vitest
	cd apps/api && uv run pytest -x
	cd apps/web && pnpm test --run || true

clean: ## remove generated files and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf apps/web/.next apps/web/.turbo
