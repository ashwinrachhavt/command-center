# Command Center

A personal workspace for opportunities, relationships, tasks, artifacts and research agents. Sidebar sections open as full pages; related body records open alongside your current work; Appearance offers light, dark and system modes with four accents. FastAPI owns the domain and PostgreSQL; Next.js provides the Clerk-authenticated shadcn interface. Deep Agents on LangGraph discover scoped API tools through MCP and run in Celery workers. Firecrawl and SearXNG connect to the existing `local-research` Docker stack.

## Run locally

Prerequisites: Docker Compose, Python 3.12 with `uv`, Node 24, and the existing research network `local-services`.

```sh
make setup
# Add Clerk keys and the API keys for your selected model providers to root .env.
make env-sync
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

Compose starts PostgreSQL, migrations, FastAPI, Redis, Celery worker/beat and the standalone Next.js server. It reuses Firecrawl, SearXNG and Docling on `local-services`; it does not recreate them. Original documents persist in the private `document-blobs` volume shared by API and worker. Local credentials and provider keys are ignored by Git. Only Clerk's publishable key belongs in the browser. Root `.env` owns all local settings; Compose passes explicit per-service settings so the web container never receives model-provider, Composio or database credentials.

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

Root `.env.example` is the only environment template. Edit root `.env`, then run `make env-sync` to generate the allowlisted `apps/web/.env.local`. Existing web settings migrate into root configuration; conflicting values stop migration without printing credentials. `make env-check` detects drift. Do not edit the generated file. Do not run host and Compose servers on the same ports. Provider errors remain visible without preventing ordinary CRM work.

## Implemented workspace

Companies, contacts, roles, opportunities, tasks, profile, activity, artifacts and immutable versions/reviews have authenticated API endpoints and connected UI controls. Owners are derived from verified Clerk sessions; request bodies cannot select an actor. POST/PATCH/PUT mutations require a UUID `Idempotency-Key`, and edits include `expected_version`. Replaying the same request returns the same row/result; conflicting key reuse or a stale edit returns 409. Synthetic starter records are an explicit opt-in, not production seed data.

**Notes** is a full-page notebook with a persistent Tiptap working draft, explicit checkpoints, recovery and linked tasks. **Library** searches titles and current saved content, filters by document type and opens the selected document in context. Uploaded originals and their pinned text extractions are read together; extraction records stay grouped under the original. Search covers saved versions, not unfinished working drafts. Older `/artifacts` links remain supported.

Follow the Rails-inspired **fat model, thin controller** convention: model methods own state changes, invariants and audit; controllers own identity, HTTP contracts and transactions. Keep provider/network work outside domain transactions. Prefer direct ORM models and small provider adapters over generic repository/service layers. Follow YAGNI and DRY.

From **Opportunities → Discover leads**, search public job pages, confirm the role/company, and capture a company, role and opportunity with source evidence. The opportunity's **Research** tab can fetch its saved source, open the exact captured version, and request an outreach draft in **Conversation**. Captures deduplicate by owner and canonical job URL; fetching adds evidence without overwriting CRM fields or changing job status. Drafts are private, unreviewed message artifacts.

Enrichment currently supports bounded public HTML/text fetches with public DNS pinned per connection and validated redirects. It records `public_http` provenance. JavaScript rendering and PDF extraction are not part of this slice; the existing Firecrawl service remains available for operator research, but its scrape API does not establish the network controls required for arbitrary agent-supplied URLs.

From **Library → Upload document**, import a PDF, DOCX, UTF-8 text or Markdown file up to 20 MiB. The original bytes become an immutable version; a Celery job uses the existing local Docling service to create a separate, linked text/structured extraction. Conversion progress, retry, cancellation and original downloads are visible. Conversion leaves the review task open. **Suggest profile facts** opens that task's conversation and creates evidenced proposals for review. **Settings → Profile facts** supports editing, approving, rejecting and revoking exact revisions; pending changes do not replace the active approved value. Agents can use only active, unexpired approved facts as candidate facts. The default résumé pins an exact original or completed résumé PDF version and does not advance on a new upload or export.

From **Browser**, pair the companion. Run `make companion-browser` to install the native helper and open the dedicated AgentBrowser profile, then click the extension icon on a job application, choose a résumé and select **Autofill this page**. For your ordinary Chrome window, load `apps/extension` unpacked and explicitly select **Direct browser**. The persistent side panel fills supported approved facts, attaches unambiguous résumé controls and reports missing questions. Repeat captures of the same page retain the application task. On a different URL, choose **Continue this application** to keep later pages together, or **Start a new application** for another job; edited answers use **Save review and fill answers** with a fresh page capture. First/last name and separate address fields are explicit profile facts; approve them in Settings before use. Background generation saves grounded suggestions in the preparation task's conversation; you can edit answers and choose the exact resume and upload controls. Saving records an immutable review of every retained answer, selected upload and explicit replacement. Apply rechecks the current page and preserves values entered while generation was running. Native controls, numeric constraints, same-origin frames, React state and bounded Greenhouse-style selections have synthetic regression coverage; unsupported controls remain visible. Hands-on verification across the five ATS targets is deferred to the user. Next and Submit remain user actions.

From **Applications**, search saved application work, reopen an exact answer package and résumé, edit the next task/deadline or continue its conversation. Status changes are your explicit record: filling a page does not mark it submitted. The tracker retains same-page captures and explicitly confirmed later pages under one task and can reopen older forms beyond Browser's recent list. Saved page links omit query parameters; use the companion on the current job page before filling again. The Job description card captures recognized page requirements or opens a recoverable Tiptap writer; save a checkpoint before using edits as generation context.

**Application documents** drafts a cover letter or tailored résumé using the saved job description, a selected résumé with readable text and approved profile facts. Optional writing preferences autosave; an interrupted request can recover its original identity after reload. Open the resulting document beside the application, edit with Tiptap and export a saved version to PDF. Completed résumé and cover-letter PDFs appear in the companion’s separate document selectors. Choose a letter, then Autofill attaches it to compatible, empty, clearly labelled cover-letter controls. Explicit review can target another file control or replace an existing attachment; résumé and letter choices remain distinct in saved application packages. Deterministic keyword coverage compares exact saved résumé/job-description versions with detected or chosen terms; it measures text coverage, not ATS ranking or eligibility. Automatic job identity detection and portal status reconciliation remain future work. Synthetic checks establish workflow correctness; actual model quality and authenticated employer-site coverage remain unverified.

In **Settings → Reviewed candidate facts**, employment and education entries support company/school, role/degree, location, partial dates and Tiptap descriptions. Use **Propose edit → Map fields** on existing imported text, check the suggested values against the pinned source, save a proposal and approve its exact revision. Working drafts autosave and recover after reload. Current status is an explicit choice; an empty end date stays unknown. New LinkedIn imports map unambiguous rows without changing earlier proposals or approvals. The isolated `0.4.4` companion can expand unambiguous empty employment/education sections through explicit Add controls to saved approved-fact targets of up to ten rows per kind, then recapture and prepare under the same application before filling. Each group uses one exact fact revision; an occupied or edited group stays unchanged. Date/month controls and split month/year selections require sufficient known date precision. Ambiguous order or unsupported controls remain for manual review. Retries retain the row-operation identity to avoid duplicate additions.

Branch `application-autofill` includes keyword ancestor `d83c6d7` and companion `0.4.4`; [non-browser verification is complete](docs/tech/engineering.md#career-row-expansion--isolated-branch-non-browser-verified), but it is not deployed. The running smoke-test build remains `frontend-redesign` at `2ad39e7` / companion `0.4.3`. Browser QA is skipped at the user’s request; native AgentBrowser and real-browser integration were not exercised for this increment. Broader portal coverage and exact Simplify parity remain incomplete.

## Agents, MCP, skills and memory

Tasks and opportunities have persistent conversations with a lead or selected specialist. Messages can steer active work at the next safe step; saved activity shows specialist/tool outcomes and links to the exact artifact versions produced. Public model text, tool calls/results and usage stream through durable, replayable SSE into Vercel AI Elements. Independent conversations can run concurrently; each conversation has one active run with shared execution limits, cancellation, independent lease heartbeats and PostgreSQL graph checkpoints. Reconnecting resumes event delivery without rerunning work. Failed or interrupted runs are not automatically resumed. Research scripts and reviewed external actions use separate worker queues. Full ATS tenant coverage and paid-provider quality evaluation remain release work.

Edit `agents/profiles.toml` to choose a `provider` and `model` independently for the lead and each specialist, alongside limits, tools and skills. Supported providers are `openai`, `gemini`, `mistral` and `cohere`; supply `OPENAI_API_KEY`, `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `MISTRAL_API_KEY` and/or `COHERE_API_KEY` in root `.env`. Use a tool-calling chat model from the selected provider. Existing profiles default to OpenAI; adding another key alone does not switch them. For example, change an existing profile to `provider = "gemini"` and `model = "gemini-2.5-flash"`. Settings shows configured providers; each profile reports missing credentials, including its delegated specialists. Missing keys fail before enqueue and never silently select another provider. Keys stay outside snapshots and prompts. Restart Compose services after changing `.env`; profile edits apply to new runs and existing runs retain their snapshots.

Agents can ask a saved question when information is missing. Waiting releases worker capacity; your answer resumes the exact checkpoint and specialist that asked it. Other unanswered drafts remain available while the run continues. Refresh and worker recovery preserve saved questions, and duplicate answers cannot resume a different question. Source-backed drafts record exact input-version links, so later edits do not change what an earlier draft was based on.

Executive directives live in `agents/directives/`, reusable skills in `agents/skills/`, and runtime settings in TOML. `AGENTS.md` is exclusively for coding assistants and is never loaded by the application. A run snapshots the fully validated instructions and a revision covering configuration, directives and skills. Both Compose and `make worker`/`make beat` wait for PostgreSQL, Redis and API readiness; optional `CC_AGENT_DEPENDENCY_URLS` gates configured local mock services with a bounded timeout. Celery transports work; PostgreSQL owns state, leases, checkpoints and outcomes. Duplicate deliveries cannot rerun a claimed/completed job. An interrupted run is marked failed and is not automatically replayed.

The internal Streamable HTTP MCP endpoint is `/mcp/`. LangChain's MCP adapter discovers tools per live agent run. Short-lived credentials are scoped to the run/lease and stay outside model messages. MCP and API credentials have separate audiences. Tools call the same owned, idempotent FastAPI mutations used by Next.js; they do not receive SQL access. The public server is not a general anonymous MCP endpoint. Remote third-party MCP clients and OAuth resource-server support are future work.

Memory contains versioned notes/preferences with human/agent provenance. Agent proposals require human approval of the exact revision before retrieval; pending edits preserve the last approved value, and revocation removes it. PostgreSQL full-text retrieval is bounded to global notes and the run's server-derived task/opportunity scope. Memory is context, not verified candidate facts or authorization. Connected tools use verified account references and pinned typed schemas; raw Composio grants are rejected so they cannot bypass account selection, spending controls or review. Set `CC_COMPOSIO_AUTH_CONFIGS` to a JSON toolkit → auth-config-ID map to enable account connection from Settings. Actual paid-provider execution requires your credentials and has not been inferred from configuration alone.

Vercel AI Elements renders generated Markdown, conversations and tool results. Eve was evaluated as a separate TypeScript durable-session runtime; the selected implementation remains Python/LangGraph/Celery. No second agent runtime is installed.

## Reviewed actions, research and spending

**Agents → Model** searches live catalogs using the configured OpenAI, Gemini, Mistral and Cohere API keys. Refresh reloads the selected provider; unsupported model types remain visible but cannot be selected for agent chat. Provider credentials stay on the server. The selected model applies to a new request. GPT-6 tool calls use the Responses API with provider response storage disabled. New runs distinguish missing models, access/key errors, rate limits, rejected requests and provider outages. No spending setup is required: the first standalone agent request provisions a default rate card with a $100 monthly limit and a $10 limit per task or standalone run. **Settings → Spending controls → Customize spending limits** allows optional changes to limits and rates. The catalog lists the configured models and exact connected operations, including account identity checks and uploads. Reservations cover concurrent chats, specialists and internal compaction, with hidden retries disabled. Missing usage and ambiguous outcomes retain their conservative reserved cost; no automatic top-up or fallback occurs. Provider invoices remain authoritative. Limits use calendar months in UTC.

**Settings → Verified app accounts** refreshes connection identities and selects one Gmail account for outreach. **Reviewed actions** creates and edits exact proposals for Gmail sends, Calendar create/update, Linear create/update and Notion publication/content updates. Approval binds the account, revision, source and attachment versions; workers execute once and persist provider receipts. Stale reviews conflict. Unknown/partial outcomes offer receipt reconciliation without automatic resend. Provider updates include a preflight check; Composio's pinned write tools do not expose conditional revision headers, so the review UI discloses the remaining remote-edit race.

Lead, research and outreach agents can use `connected_context` to read a Calendar window of at most 31 days, an exact Calendar event, a linked Linear issue or a selected Notion page. Each read uses an owned verified account, spending reservations and the conversation's server-derived scope. Saved observations include timestamps, provider revisions and bounded readable content. Truncation is explicit; locally clipped event lists require a narrower request instead of skipping ahead. Reads do not approve external changes or personal facts.

The task conversation can capture public source versions and queue a Python standard-library research script using selected immutable inputs. The execution worker runs a fixed container with no network, provider credentials, host mounts or Docker socket; CPU, memory, process, output and wall-time limits apply. Outputs are editable cited document versions. From an exact document version, **Export PDF** creates a separate immutable PDF derivative with its own progress, download, cancel and explicit retry controls. Failed/abandoned containers are cleaned up by exact job/lease labels before retry becomes available.

Build the local script and PDF images, then set `CC_RESEARCH_SANDBOX_IMAGE` and `CC_PDF_RENDERER_IMAGE` to their immutable image IDs (`docker image inspect --format '{{.Id}}' IMAGE`). Mutable tags are rejected at enqueue. Rebuild and repin after changing either image:

```sh
docker build -t command-center-research:local apps/research-sandbox
docker build -t command-center-pdf:local apps/pdf-renderer
```

Compose isolates `agents`, `control/actions/documents`, and `execution` worker capacity; `CC_AGENT_CONCURRENCY` defaults to 4. The trusted execution controller alone receives the configured Docker socket; generated containers never receive it. `CC_EXECUTOR_DOCKER_SOCKET` and `CC_EXECUTOR_DOCKER_GID` select a dedicated engine/socket group. A rootless dedicated engine is preferred for server deployment. Host development requires `uv sync --project apps/api --extra executor` and a separate worker with `--queues=execution`. Local research, PDF and restore checks use synthetic data; they do not prove live-provider delivery or arbitrary-code resistance against kernel/container-runtime vulnerabilities.

Backup and isolated restore verification are documented in [Backup and restore](docs/tech/backup-and-restore.md). Keep backup data and local agent files out of Git.

## Browser companion

Load or reload `apps/extension` as an unpacked Chromium extension; see [its instructions](apps/extension/README.md). Pair from the workspace, share an active form, prepare values, then review and apply in the extension. The bridge uses a revocable device credential and exact snapshot binding; it does not copy browser cookies. Native controls, numeric constraints, visible same-origin forms and bounded exact dropdown selections are supported. Deliberate clears and edits made during asynchronous file verification are preserved. Search-dependent location/school widgets, unknown custom controls and cross-origin frames require manual handling; Next and Submit remain human actions.

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

Either input may be supplied independently. LinkedIn imports contacts and professional profile
only: positions, education, skills, projects, certifications, courses, languages, publications,
received recommendations and attributed endorsement evidence. Contact source fields appear in
their export history; career facts are proposed for review in Settings. Dates retain their
original precision. Blank end dates do not imply current employment. Existing edits and fact
reviews survive repeat imports, including after moving the export folder.

The private report accounts for every file and column, including exclusions. Messages,
invitations, company follows, saved jobs, private identity/account data and unrelated activity
are excluded from LinkedIn import. Existing imported records are preserved. Notion still imports
the two operational tables and contact registry when explicitly provided. Neither source
authorizes outreach. Real exports and reports must never be committed.

```sh
make test          # pytest + pytest-mock against disposable PostgreSQL
make lint          # Ruff, strict mypy, ESLint and TypeScript
make check         # contracts, lint, backend/unit/companion/offline eval checks, web build
make eval-check    # offline DeepEval adapter/contracts; no model calls
make eval-plan     # private judge-cost proposal with zero execution allowance
make schema-check  # Alembic/ORM drift
make contracts     # regenerate Next.js types and extension runtime validators
make contracts-check # reject generated contract drift
make test-browser  # start/wait for a synthetic form server, then test the extension
make smoke         # functional checks against existing research services
cd apps/web
npx playwright install chromium
npm run test:browser  # companion, with the web server on localhost:3001
npm run test:workspace # real UI components with synthetic API/Clerk/Next fixtures
npm run preview:workspace # interactive synthetic UI on localhost:4318
```

`make migration message="describe change"` generates a migration for review; `make migrate` applies it. One Alembic history owns the schema. The test stack uses pytest with pytest-mock, plus an isolated [DeepEval recorded-output suite](apps/api/evals/README.md). Paid judging requires a reviewed plan, actual synthetic model-output captures and an explicit allowance; it is excluded from ordinary checks. Existing Vitest/TypeScript Playwright checks remain frontend coverage. Tests use synthetic actors/data and mocked paid providers. The MCP worker integration test exercises actual HTTP discovery, authentication and SQL writes. Browser tests execute the extension's content script against a controlled local form.

[GitHub Actions CI](.github/workflows/ci.yml) runs on every pull request, including stacked PRs, and pushes to `main`. Parallel jobs cover Ruff lint/formatting, mypy, PostgreSQL tests/migrations, generated contracts, frontend lint/types/unit tests, both synthetic browser suites, the production build and offline evaluation contracts. Dependencies are locked and cached; actions are pinned to commits. CI uses disposable PostgreSQL and synthetic Clerk build values, so repository secrets and paid-provider access are unnecessary. Manual signed-in QA remains separate.

## Supabase deployment path

Keep FastAPI as the sole database access boundary. The migrations enable RLS on application tables with no public Data API policies; do not expose service-role credentials or connect the browser directly to SQL. Clerk remains the identity provider. Configure `CC_DATABASE_URL` as a `postgresql+psycopg://` connection with TLS. For a transaction pooler, set `CC_DATABASE_POOL_MODE=transaction` (NullPool and prepared statements disabled); use `CC_MIGRATION_DATABASE_URL` for a direct/session connection when applying Alembic. Production requires `CC_ENVIRONMENT=production`, a Clerk issuer, explicit authorized origins/hosts and deployed worker/Redis services. Supabase deployment itself has not been performed.

## Specifications

Three canonical specifications: [Product Spec](docs/product/product-spec.md), [Tech Spec](docs/tech/tech-spec.md), and [Design Spec](docs/design/design-spec.md). The [documentation index](docs/README.md) maps their supporting documents. [Engineering](docs/tech/engineering.md) owns the accepted, pending workspace fixes and verification plan. Portal import staging/live sync, autonomous campaign limits, reviewed outbound actions and complete application workflows remain future work.


Contact discovery: set `APOLLO_API_KEY` and/or `HUNTER_API_KEY` in the root `.env` and recreate the API service (`docker compose up -d api`). Connected apps shows configuration; Contacts → Discover contacts and Company → Find people run explicit searches. Provider endpoint eligibility and credits apply. Apollo search and profile reveal are separate; Hunter supports domain-based professional-email discovery. Verification uses synthetic responses until keys are configured. Saved follow-ups are available from Contacts → Follow up without either integration.

Company research and generated outreach: **Companies → Enrich company** creates a tracked task and saves a cited brief beside the company; **Contacts → Follow up → Draft with agent** saves an editable follow-up. **Open work** shows the task conversation, progress and any questions. Generation uses configured agent credentials and spending controls. Saved drafts can be copied or prepared as a separately reviewed email; generation alone never delivers a message. Replies stream in the conversation timeline, with reconnect recovery and reduced-motion support.
