UV = uv run --project apps/api
ALEMBIC = $(UV) alembic -c apps/api/alembic.ini
EVAL_UV = env UV_PROJECT_ENVIRONMENT=$(CURDIR)/.local/evals-venv PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --project apps/api/evals

.PHONY: companion-setup companion-browser setup up down db migrate migration schema-check api web worker beat env-sync env-check agent-ready contracts-check test-browser auth-check auth-sync contracts test test-db lint format check smoke eval-check eval-plan eval-paid

setup:
	python3 scripts/bootstrap.py
	uv sync --project apps/api --frozen
	npm ci --prefix apps/web
	$(MAKE) env-sync

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

web: env-sync
	npm run dev --prefix apps/web

env-sync:
	$(UV) python scripts/sync_env.py

env-check:
	$(UV) python scripts/sync_env.py --check

auth-check: env-sync
	node scripts/check-auth.mjs

auth-sync: env-sync
	node scripts/check-auth.mjs --sync

agent-ready:
	$(UV) python -m command_center.agents.readiness

worker: agent-ready
	$(UV) celery -A command_center.agents.queue:celery worker --loglevel=WARNING --concurrency=4 --queues=agents,control,actions,documents

beat: agent-ready
	mkdir -p .local
	$(UV) celery -A command_center.agents.queue:celery beat --loglevel=WARNING --schedule=.local/celerybeat-schedule

contracts:
	$(UV) python scripts/export_openapi.py
	npx --prefix apps/web openapi-typescript .local/openapi.json -o apps/web/src/lib/api-types.ts
	node scripts/build_extension_contracts.mjs

contracts-check:
	$(UV) python scripts/export_openapi.py
	npx --prefix apps/web openapi-typescript .local/openapi.json -o .local/api-types.ts
	cmp apps/web/src/lib/api-types.ts .local/api-types.ts
	node scripts/build_extension_contracts.mjs --check

test-browser:
	npm run test:browser --prefix apps/web

companion-setup:
	python3 scripts/companion_bridge.py install

companion-browser:
	python3 scripts/companion_bridge.py launch

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
	npx --prefix apps/web prettier --write 'apps/web/src/**/*.{ts,tsx,css}' 'apps/extension/{content,popup}.js' 'apps/extension/*.{html,css,json}'

eval-check:
	$(EVAL_UV) pytest -p pytest_mock apps/api/evals/test_contracts.py -q

.PHONY: langfuse-setup langfuse-up langfuse-down
langfuse-setup:
	$(UV) python scripts/langfuse_setup.py

langfuse-up: langfuse-setup
	docker compose -f compose.langfuse.yaml up -d --wait

langfuse-down:
	docker compose -f compose.langfuse.yaml down

.PHONY: eval-chat
eval-chat:
	$(EVAL_UV) python -m apps.api.evals.chat_smoke $(if $(filter 1,$(allow_paid)),--allow-paid,)

eval-plan:
	$(UV) python scripts/evaluation_plan.py

eval-paid:
	@test -n "$(plan)" -a -n "$(captures)" || (echo 'Use: make eval-paid plan=REVIEWED_PLAN captures=MODEL_CAPTURES'; exit 1)
	$(EVAL_UV) pytest -p pytest_mock apps/api/evals/test_quality.py --eval-plan "$(plan)" --eval-captures "$(captures)" --allow-paid $(if $(filter 1,$(langfuse)),--langfuse,) -q

check: env-check contracts-check lint test test-browser eval-check
	npm run build --prefix apps/web

smoke:
	$(UV) python scripts/check_integrations.py --functional
