UV = uv run --project apps/api
ALEMBIC = $(UV) alembic -c apps/api/alembic.ini

.PHONY: setup up down db migrate migration schema-check api web worker beat auth-check auth-sync contracts test test-db lint format check smoke

setup:
	python3 scripts/bootstrap.py
	uv sync --project apps/api --frozen
	npm ci --prefix apps/web

up: auth-sync
	docker compose up -d --build --wait

down:
	docker compose down

db:
	docker compose up -d --wait db

migrate:
	$(ALEMBIC) upgrade head

migration:
	@test -n "$(message)" || (echo 'Use: make migration message="describe change"'; exit 1)
	$(ALEMBIC) revision --autogenerate -m "$(message)"

schema-check:
	$(ALEMBIC) check

api:
	$(UV) uvicorn command_center.main:create_app --factory --reload --reload-dir apps/api/src --host 127.0.0.1 --port 8000 --no-access-log

web:
	npm run dev --prefix apps/web

auth-check:
	node scripts/check-auth.mjs

auth-sync:
	node scripts/check-auth.mjs --sync

worker:
	$(UV) celery -A command_center.agents.queue:celery worker --loglevel=WARNING --concurrency=2

beat:
	$(UV) celery -A command_center.agents.queue:celery beat --loglevel=WARNING --schedule=.local/celerybeat-schedule

contracts:
	$(UV) python scripts/export_openapi.py
	npx --prefix apps/web openapi-typescript .local/openapi.json -o apps/web/src/lib/api-types.ts

test-db:
	docker compose --profile test up -d --wait db-test

test: test-db
	$(UV) pytest apps/api/tests -q
	npm run test:unit --prefix apps/web

lint:
	$(UV) ruff check apps/api scripts
	$(UV) ruff format --check apps/api scripts
	$(UV) mypy --config-file apps/api/pyproject.toml apps/api/src
	npm run lint --prefix apps/web
	npm run typecheck --prefix apps/web

format:
	$(UV) ruff check apps/api scripts --fix
	$(UV) ruff format apps/api scripts
	npx --prefix apps/web prettier --write 'apps/web/src/**/*.{ts,tsx,css}' 'apps/extension/*.{js,html,css,json}'

check: lint test
	npm run build --prefix apps/web

smoke:
	$(UV) python scripts/check_integrations.py --functional
