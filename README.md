# Command Center

A personal workspace for opportunities, relationships, tasks, artifacts and research agents. FastAPI owns the domain and PostgreSQL; Next.js provides the Clerk-authenticated shadcn interface. LangGraph agents discover scoped API tools through MCP and run in Celery workers. Firecrawl and SearXNG connect to the existing `local-research` Docker stack.

## Run locally

Prerequisites: Docker Compose, Python 3.12 with `uv`, Node 24, and the existing research network `local-services`.

```sh
make setup
# Add your Clerk keys to apps/web/.env.
# Add OPENAI_API_KEY and optional COMPOSIO_API_KEY to root .env.
make auth-sync
make up
```

Open **http://localhost:3001**. Port 3000 is reserved for other work. Use `localhost` consistently: Clerk development redirects normalize that hostname. `make auth-sync` verifies that the Clerk keys match and synchronizes FastAPI's issuer and the public Docker build key without printing secrets. It preserves other environment values. After replacing Clerk keys, run it again and restart/rebuild the stack.

| Service | Local address |
| --- | --- |
| Web workspace | http://localhost:3001 |
| FastAPI/OpenAPI | http://127.0.0.1:8000/docs |
| PostgreSQL | 127.0.0.1:55432 |
| Redis | 127.0.0.1:56379 |
| Disposable test PostgreSQL | 127.0.0.1:55433 |

Compose starts PostgreSQL, migrations, FastAPI, Redis, Celery worker/beat and the standalone Next.js server. It reuses the research services on `local-services`; it does not recreate them. Local credentials and provider keys are ignored by Git. Only Clerk's publishable key belongs in the browser. The Clerk secret belongs in `apps/web/.env`; OpenAI/Composio belong in root `.env`, which is the Python environment for root Make targets.

## Develop on the host

```sh
docker compose stop web api worker beat
make db
make migrate
docker compose up -d --wait redis
make api       # separate terminal, port 8000
make worker    # separate terminal
make beat      # separate terminal
make web       # separate terminal, port 3001
```

The root `.env` configures Python. `apps/web/.env` holds Clerk keys; optional `apps/web/.env.local` overrides the server-only API URL for host development. Do not run host and Compose servers on the same ports. Provider errors remain visible without preventing ordinary CRM work.

## Implemented workspace

Companies, contacts, roles, opportunities, tasks, profile, activity, artifacts and immutable versions/reviews have authenticated API endpoints and connected UI controls. Owners are derived from verified Clerk sessions; request bodies cannot select an actor. POST/PATCH mutations require a UUID `Idempotency-Key`, and edits include `expected_version`. Replaying the same request returns the same row/result; conflicting key reuse or a stale edit returns 409. Synthetic starter records are an explicit opt-in, not production seed data.

Follow the Rails-inspired **fat model, thin controller** convention: model methods own state changes, invariants and audit; controllers own identity, HTTP contracts and transactions. Keep provider/network work outside domain transactions. Prefer direct ORM models and small provider adapters over generic repository/service layers. Follow YAGNI and DRY.

## Agents, MCP, skills and memory

Edit `agents/profiles.toml` to choose OpenAI models, limits, tools and skills. Markdown instructions live in `agents/skills/`. A run stores the configuration and skill revision it started with. Celery transports work; PostgreSQL owns state, leases, checkpoints and outcomes. Duplicate deliveries cannot rerun a claimed/completed job. An interrupted run is marked failed and is not automatically replayed.

The internal Streamable HTTP MCP endpoint is `/mcp/`. LangChain's MCP adapter discovers tools per live agent run. Short-lived credentials are scoped to the run/lease and stay outside model messages. MCP and API credentials have separate audiences. Tools call the same owned, idempotent FastAPI mutations used by Next.js; they do not receive SQL access. The public server is not a general anonymous MCP endpoint. Remote third-party MCP clients and OAuth resource-server support are future work.

Memory contains editable notes/preferences with human/agent source labels. It is context, not verified candidate facts or authorization. Default agents can read memory; only explicitly granted profiles can append a requested note. Composio tools require an operator-reviewed slug, pinned version and read-only grant. Set `CC_COMPOSIO_AUTH_CONFIGS` to a JSON toolkit → auth-config-ID map to enable account connection from Settings. Actual paid-provider execution requires your credentials and has not been inferred from configuration alone.

Vercel AI Elements renders generated Markdown, conversations and tool results. Eve was evaluated as a separate TypeScript durable-session runtime; the selected implementation remains Python/LangGraph/Celery. No second agent runtime is installed.

## Browser companion

Load `apps/extension` as an unpacked Chromium extension; see [its instructions](apps/extension/README.md). Pair from the workspace, share an active form, prepare values, then review and apply in the extension. The bridge uses a revocable device credential and exact snapshot binding; it does not copy browser cookies. Supported fields are ordinary text/email/tel/url, textarea and single-select. Sensitive fields, uploads, cross-origin frames and automatic submission are outside this first slice.

## Checks and migrations

For an operator-run import of existing LinkedIn CSVs and cached Notion lead pages, use
`scripts/import_workspace.py`. Select the existing actor only after verifying its Clerk identity.
Keep source exports, staging reports and a PostgreSQL backup under ignored/private storage.
The importer defaults to a transaction that rolls back after validation; inspect its report,
then repeat with `--apply`. Identical imports reuse source snapshots and record identities.

```sh
uv run --project apps/api python scripts/import_workspace.py \
  --actor VERIFIED_ACTOR_UUID \
  --linkedin /absolute/path/to/linkedin-export \
  --notion .local/source/notion-pre-consolidation.json \
  --report .local/imports/preview.json
```

This imports connections, company follows, saved roles and career context, plus the two
Notion operational tables and contact registry. It retains source artifacts and historical
notes, creates research/review items, and does not infer current interviews or send outreach.
Incomplete saved jobs remain in the source archive with a review task. Identity assets,
private messages, birth dates, saved screening answers and unrelated archive data are excluded.
Real exports and reports must never be committed.

```sh
make test          # pytest + pytest-mock against disposable PostgreSQL
make lint          # Ruff, strict mypy, ESLint and TypeScript
make check         # lint, backend tests and production Next.js build
make schema-check  # Alembic/ORM drift
make contracts     # regenerate the typed Next.js API schema
make smoke         # functional checks against existing research services
cd apps/web
npx playwright install chromium
npm run test:browser  # with the web server on localhost:3001
```

`make migration message="describe change"` generates a migration for review; `make migrate` applies it. One Alembic history owns the schema. Tests use synthetic actors/data and mocked paid providers. The MCP worker integration test exercises actual HTTP discovery, authentication and SQL writes. Browser tests execute the extension's content script against a controlled local form.

## Supabase deployment path

Keep FastAPI as the sole database access boundary. The migrations enable RLS on application tables with no public Data API policies; do not expose service-role credentials or connect the browser directly to SQL. Clerk remains the identity provider. Configure `CC_DATABASE_URL` as a `postgresql+psycopg://` connection with TLS. For a transaction pooler, set `CC_DATABASE_POOL_MODE=transaction` (NullPool and prepared statements disabled); use `CC_MIGRATION_DATABASE_URL` for a direct/session connection when applying Alembic. Production requires `CC_ENVIRONMENT=production`, a Clerk issuer, explicit authorized origins/hosts and deployed worker/Redis services. Supabase deployment itself has not been performed.

## Specifications

Exactly two active specifications: [Product Spec](docs/product-spec.md) and [Tech Spec](docs/tech-spec.md). Supporting [design](docs/tech/design.md), [engineering](docs/tech/engineering.md) and [handoff](docs/HANDOFF.md) documents record interface decisions and delivery evidence. Autonomous campaign limits, imports, verified candidate facts, outreach and application submission remain product work beyond the connected scaffold.
