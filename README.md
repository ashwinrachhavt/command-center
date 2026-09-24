# Command Center

A personal workspace for opportunities, relationships, tasks, artifacts and research agents. Sidebar sections open as full pages; related body records open alongside your current work; Appearance offers light, dark and system modes with four accents. FastAPI owns the domain and PostgreSQL; Next.js provides the Clerk-authenticated shadcn interface. Deep Agents on LangGraph discover scoped API tools through MCP and run in Celery workers. Firecrawl and SearXNG connect to the existing `local-research` Docker stack.

**Smoke-test release:** `frontend-redesign` includes the completed application and daily-workspace increments through `ed69ac1`. Reload companion `0.4.5` and refresh application pages before testing. Use the [smoke-test checklist](docs/smoke-test.md) for setup, test steps and expected results. See [Engineering](docs/tech/engineering.md) for validation and remaining coverage.

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

**Briefing first slice — 2026-09-24:** implemented and verified locally; deployment and the live database migration remain pending. The default `/` (also `/briefing`) brings together saved daily tasks, questions/reviews, running work, outputs and activity. Quick capture creates an unscheduled task and preserves pasted text in its rationale; Upload document uses existing intake. Waiting is an explicit task state/tab. Opening Briefing does not retrieve mail or call a model/provider. **Assistant** remains at `/agents` with existing conversation links, and `/overview` remains available. See [the delivery checkpoint](docs/tech/engineering.md#briefing-first-vertical-slice--2026-09-24).

**Spaces and document decisions — 2026-09-24:** implemented and verified locally; deployment remains pending. **Spaces** at `/spaces` groups a purpose with explicitly linked tasks, contacts, companies, opportunities and existing artifacts. Create/edit, archive/restore, search, linked-record inspection and atomic task capture are available. Briefing can optionally capture into an active Space; its picker shows the first 100 active Spaces, while the Spaces page is paginated. Uploads retain the ordinary intake flow and can be linked explicitly afterward. See [the current delivery checkpoint](docs/tech/engineering.md#spaces-and-document-decisions--local-implementation-2026-09-24).

**Document Vault** accepts Unclassified uploads and exposes manual type review after extraction. **Settings → Documents** configures an eligible type catalog, optional classification after extraction, and optional rename tasks; both automation settings default to Off. An acknowledged one-document request sends bounded extracted text to the configured Jev provider. Its type proposal and six independent text signals are inspectable, with human type review and a separate Apply name / Keep current name step. **Add research or agent checks** optionally adds relevance, evidence-role, claim-support, output-quality, policy-concern and action-match checks: `document-type.v3` batches at most 13 questions for one extracted document. Context fields are limited to 4,000 characters each and 12,000 total; omitted context produces no corresponding score. Scores use a 0–2 scale distinct from probability/confidence, and action matching grants no permission. The signals create no tasks or authority; a mentioned deadline does not establish urgency. Renaming changes only the display title, preserving original filenames and immutable content. Migrations `0038_spaces` and `0039_document_decisions` are required; API readiness now expects `0039_document_decisions`. No live paid-model call or deployment is claimed for this increment.

**Opportunities** groups broad opportunities, applications and saved roles; **Tasks** keeps the actionable queue. Agent profiles, connectors, skills and memory are accessible from **Agents**. Existing daily task views use your saved timezone. Task status changes remain explicit; snoozing stays paused until you resume. Daily outcome pinning, scheduled pulling and analytics remain outside the delivered slices.

**Library → Notes** is a notebook with a persistent Tiptap working draft, explicit checkpoints, recovery and linked tasks. **Library** holds notes and saved agent work, with All work/Notes/Agent outputs collections and current-version review filters. **Document Vault** holds uploaded originals and extraction status. Both search titles and saved content and open documents in a spacious reading canvas. Uploaded originals and their pinned text extractions are read together; extraction records stay grouped under the original. Search covers saved versions, not unfinished working drafts. Older `/artifacts` links remain supported.

**Contacts → Draft connection note** creates a note of at most 200 characters using saved context and a bounded optional lookup. **Enrich contact** and **Batch enrich** explicitly request deeper research; a batch selects up to ten people and shows each task's queue result. Saved notes support copy and editing, with source evidence when available. **Companies → Enrich company** retains detailed, sourced research. These actions prepare drafts; they do not send LinkedIn requests.

**Contacts → Email & follow-ups → Research & draft email** prepares an editable email using saved context, local send history and focused public research. Open **Review & send or schedule**, edit the message, choose delivery timing, and save the proposal to review it. Each email needs its own approval. Send through the selected Gmail account via Composio after review, at a future local date/time, or a chosen number of 24-hour days after a confirmed send to the same recipient. Editing a queued email or its timing requires fresh approval; cancel it before execution starts. The contact's email history shows pending schedules and confirmed receipts. Command Center must be running for delivery; overdue approved jobs send when it resumes. Replies are not monitored automatically.

Follow the Rails-inspired **fat model, thin controller** convention: model methods own state changes, invariants and audit; controllers own identity, HTTP contracts and transactions. Keep provider/network work outside domain transactions. Prefer direct ORM models and small provider adapters over generic repository/service layers. Follow YAGNI and DRY.

From **Opportunities → Discover leads**, search public job pages, confirm the role/company, and capture a company, role and opportunity with source evidence. The opportunity's **Research** tab can fetch its saved source, open the exact captured version, and request an outreach draft in **Conversation**. Captures deduplicate by owner and canonical job URL; fetching adds evidence without overwriting CRM fields or changing job status. Drafts are private, unreviewed message artifacts.

Enrichment currently supports bounded public HTML/text fetches with public DNS pinned per connection and validated redirects. It records `public_http` provenance. JavaScript rendering and PDF extraction are not part of this slice; the existing Firecrawl service remains available for operator research, but its scrape API does not establish the network controls required for arbitrary agent-supplied URLs.

From **Document Vault → Upload document**, select one or several PDF, DOCX, JPEG (`.jpg`/`.jpeg`), PNG, UTF-8 text or Markdown files, up to 20 MiB each. A batch uses editable per-file titles and a shared document type, shows per-file progress, and retries only failed files with their original request keys. Adding a new original version to an existing document remains a single-file operation. Images must be single-frame and at most 25 megapixels. The original bytes become an immutable version; a Celery job uses the existing local Docling service to create a separate, linked text/structured extraction, with local OCR for images and no additional LLM call. Conversion progress, retry, cancellation and original downloads are visible. Conversion leaves the review task open. **Suggest profile facts** opens that task's conversation and creates evidenced proposals for review. **Settings → Profile facts** supports editing, approving, rejecting and revoking exact revisions; pending changes do not replace the active approved value. Agents can use only active, unexpired approved facts as candidate facts. The default résumé pins an exact original or completed résumé PDF version and does not advance on a new upload or export.

From **Browser companion**, follow the three setup steps and pair the extension. Load `apps/extension` unpacked in Chrome, click its icon on an application tab, choose a résumé and select **Autofill this page**. Companion 0.4.6 defaults to **This browser**, requiring no separate helper. An explicitly saved AgentBrowser selection is preserved; switch it in Capture settings for ordinary Chrome, or run `make companion-browser` for the dedicated native mode. The persistent side panel fills supported approved facts, attaches unambiguous résumé controls and reports missing questions. Repeat captures of the same page retain the application task. On a different URL, choose **Continue this application** to keep later pages together, or **Start a new application** for another job; edited answers use **Save review and fill answers** with a fresh page capture. First/last name and separate address fields are explicit profile facts; approve them in Settings before use. Background generation saves grounded suggestions in the preparation task's conversation; you can edit answers and choose the exact resume and upload controls. Saving records an immutable review of every retained answer, selected upload and explicit replacement. Apply rechecks the current page and preserves values entered while generation was running. Native controls, numeric constraints, same-origin frames, React state and bounded Greenhouse-style selections have synthetic regression coverage; unsupported controls remain visible. Hands-on verification across the five ATS targets is deferred to the user. Next and Submit remain user actions.

From **Opportunities → Applications**, search saved application work, reopen an exact answer package and résumé, edit the next task/deadline or continue its conversation. Status changes are your explicit record: filling a page does not mark it submitted. The tracker retains same-page captures and explicitly confirmed later pages under one task and can reopen older forms beyond Browser's recent list. Saved page links omit query parameters; use the companion on the current job page before filling again. The Job description card captures recognized page requirements or opens a recoverable Tiptap writer; save a checkpoint before using edits as generation context.

**Application documents** drafts a cover letter or tailored résumé using the saved job description, a selected résumé with readable text and approved profile facts. Optional writing preferences autosave; an interrupted request can recover its original identity after reload. Open the resulting document beside the application, edit with Tiptap and export a saved version to PDF. Completed résumé and cover-letter PDFs appear in the companion’s separate document selectors. Choose a letter, then Autofill attaches it to compatible, empty, clearly labelled cover-letter controls. Explicit review can target another file control or replace an existing attachment; résumé and letter choices remain distinct in saved application packages. Deterministic keyword coverage compares exact saved résumé/job-description versions with detected or chosen terms; it measures text coverage, not ATS ranking or eligibility. Companion 0.4.5 recognizes supported current-job posting identities across pages; historical application matching and portal status reconciliation remain future work. Synthetic checks establish workflow correctness; actual model quality and authenticated employer-site coverage remain unverified.

In **Settings → Reviewed candidate facts**, employment and education entries support company/school, role/degree, location, partial dates and Tiptap descriptions. Use **Propose edit → Map fields** on existing imported text, check the suggested values against the pinned source, save a proposal and approve its exact revision. Working drafts autosave and recover after reload. Current status is an explicit choice; an empty end date stays unknown. New LinkedIn imports map unambiguous rows without changing earlier proposals or approvals. Companion `0.4.5` can expand unambiguous empty employment/education sections through explicit Add controls to saved approved-fact targets of up to ten rows per kind, then recapture and prepare under the same application before filling. Each group uses one exact fact revision; an occupied or edited group stays unchanged. Date/month controls and split month/year selections require sufficient known date precision. Ambiguous order or unsupported controls remain for manual review. Retries retain the row-operation identity to avoid duplicate additions.

Branch `application-autofill` includes keyword ancestor `d83c6d7` and companion `0.4.4`; [non-browser verification is complete](docs/tech/engineering.md#career-row-expansion--isolated-branch-non-browser-verified), but it is not deployed. The running smoke-test build remains `frontend-redesign` at `2ad39e7` / companion `0.4.3`. Browser QA is skipped at the user’s request; native AgentBrowser and real-browser integration were not exercised for this increment. Broader portal coverage and exact Simplify parity remain incomplete.

## Local AI clients

Open **Settings → Local AI clients**, create a separate credential for Claude Code or Codex, and save the one-time token with the hidden CLI prompt. Follow [Local MCP setup](docs/tech/local-mcp.md) to register the stdio bridge. Both local clients and in-app chat use the same typed catalog, covering all API operations with explicit direct-tool, assigned-run, human-review or specialized-transport policies. Existing review requirements remain enforced.

Home defaults to the generic **Command Center supervisor**. It uses tools directly for simple requests and can delegate bounded research, writing, application or outreach work. Progressive catalog search loads relevant tool schemas as needed. Paste lead content and ask to save it: the intake operation creates or reuses linked company, contact and opportunity records, preserves the exact private source and returns links. Saved text versions are supported; a job posting URL is optional. Ambiguous identities require clarification.

Conversations have searchable, paginated history, incremental messages, streamed activity and durable questions. Bounded summarization middleware carries older context between turns while retaining the original transcript. Answer reuse is intentionally narrow: an immediate exact repeat of an eligible first-turn text summarization/explanation, with no tool use and matching configuration, can reuse its saved answer for five minutes. The UI shows reuse and offers a fresh answer; mutable workspace queries and writes always execute normally.

## Agents, MCP, skills and memory

Tasks and opportunities have persistent conversations with a lead or selected specialist. Messages can steer active work at the next safe step; saved activity shows specialist/tool outcomes and links to the exact artifact versions produced. Public model text, tool calls/results and usage stream through durable, replayable SSE into Vercel AI Elements. Independent conversations can run concurrently; each conversation has one active run with shared execution limits, cancellation, independent lease heartbeats and PostgreSQL graph checkpoints. Reconnecting resumes event delivery without rerunning work. Failed or interrupted runs are not automatically resumed. Research scripts and reviewed external actions use separate worker queues. Full ATS tenant coverage and paid-provider quality evaluation remain release work.

Edit `agents/profiles.toml` to choose a `provider` and `model` independently for the lead and each specialist, alongside limits, tools and skills. Supported providers are `openai`, `gemini`, `mistral` and `cohere`; supply `OPENAI_API_KEY`, `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `MISTRAL_API_KEY` and/or `COHERE_API_KEY` in root `.env`. Use a tool-calling chat model from the selected provider. Existing profiles default to OpenAI; adding another key alone does not switch them. For example, change an existing profile to `provider = "gemini"` and `model = "gemini-2.5-flash"`. Settings shows configured providers; each profile reports missing credentials, including its delegated specialists. Missing keys fail before enqueue and never silently select another provider. Keys stay outside snapshots and prompts. Restart Compose services after changing `.env`; profile edits apply to new runs and existing runs retain their snapshots.

Agents can ask a saved question when information is missing. Waiting releases worker capacity; your answer resumes the exact checkpoint and specialist that asked it. Other unanswered drafts remain available while the run continues. Refresh and worker recovery preserve saved questions, and duplicate answers cannot resume a different question. Source-backed drafts record exact input-version links, so later edits do not change what an earlier draft was based on.

Executive directives live in `agents/directives/`, reusable skills in `agents/skills/`, and runtime settings in TOML. `AGENTS.md` is exclusively for coding assistants and is never loaded by the application. A run snapshots the fully validated instructions and a revision covering configuration, directives and skills. Both Compose and `make worker`/`make beat` wait for PostgreSQL, Redis and API readiness; optional `CC_AGENT_DEPENDENCY_URLS` gates configured local mock services with a bounded timeout. Celery transports work; PostgreSQL owns state, leases, checkpoints and outcomes. Duplicate deliveries cannot rerun a claimed/completed job. An interrupted run is marked failed and is not automatically replayed.

The shared FastMCP Streamable HTTP endpoint is `/mcp/`. LangChain's MCP adapter discovers tools per live agent run. Short-lived credentials are scoped to the run/lease and stay outside model messages. MCP and API credentials have separate audiences. Tools call the same owned, idempotent FastAPI mutations used by Next.js; they do not receive SQL access. The public server is not a general anonymous MCP endpoint. Local Claude Code and Codex use revocable workspace credentials through the stdio bridge described below. OAuth resource-server support remains future work.

Memory contains versioned notes/preferences with human/agent provenance. Agent proposals require human approval of the exact revision before retrieval; pending edits preserve the last approved value, and revocation removes it. PostgreSQL full-text retrieval is bounded to global notes and the run's server-derived task/opportunity scope. Memory is context, not verified candidate facts or authorization. Connected tools use verified account references and pinned typed schemas; raw Composio grants are rejected so they cannot bypass account selection, spending controls or review. Set `CC_COMPOSIO_AUTH_CONFIGS` to a JSON toolkit → auth-config-ID map to enable account connection from Settings. Actual paid-provider execution requires your credentials and has not been inferred from configuration alone.

Vercel AI Elements renders generated Markdown, conversations and tool results. Eve was evaluated as a separate TypeScript durable-session runtime and is not an approved migration. Python Deep Agents on LangGraph/Celery remains the default. An opt-in experimental Strands backend is implemented behind the optional `strands` dependency extra and an explicit per-profile runtime selection; ordinary production setup does not enable it.

[Agent efficiency research](docs/tech/agent-efficiency.md) explains selective read retries, scoped catalog lookup, stream recovery and the measurement plan.

[Strands experiment](docs/tech/strands-experiment.md) documents the optional worker, evidence previews and supported boundaries. Run `make benchmark-runtime` for a synthetic comparison; [live comparisons](docs/tech/runtime-benchmark.md) require verified rates and an explicit spend cap. Deep Agents remains the default.

## Reviewed actions, research and spending

**Agents → Model** searches live catalogs using the configured OpenAI, Gemini, Mistral and Cohere API keys. Refresh reloads the selected provider; unsupported model types remain visible but cannot be selected for agent chat. Provider credentials stay on the server. The selected model applies to a new request. GPT-6 tool calls use the Responses API with provider response storage disabled. New runs distinguish missing models, access/key errors, rate limits, rejected requests and provider outages. No spending setup is required: the first standalone agent request or app-account verification provisions a default rate card with a $100 monthly limit and a $10 limit per task or standalone run. **Settings → Spending controls → Customize spending limits** allows optional changes to limits and rates. The catalog lists the configured models and exact connected operations, including account identity checks and uploads. Reservations cover concurrent chats, specialists and internal compaction, with hidden retries disabled. Missing usage and ambiguous outcomes retain their conservative reserved cost; no automatic top-up or fallback occurs. Provider invoices remain authoritative. Limits use calendar months in UTC.

**Agents → Connectors** verifies and saves accounts automatically after OAuth returns. A pending connection is also checked when you return manually; retries retain their verification request key. **Refresh accounts** remains available for later changes, and one verified Gmail account can be selected for outreach. New workspaces receive the standard spending defaults, with conservative $0.01 estimates for each account-list or identity check; existing limits and rate cards are preserved. **Reviewed actions** creates and edits exact proposals for Gmail sends, Calendar create/update, Linear create/update and Notion publication/content updates. Approval binds the account, revision, source and attachment versions; workers execute once and persist provider receipts. Stale reviews conflict. Unknown/partial outcomes offer receipt reconciliation without automatic resend. Provider updates include a preflight check; Composio's pinned write tools do not expose conditional revision headers, so the review UI discloses the remaining remote-edit race.

Lead, research and outreach agents can use `connected_context` to read a Calendar window of at most 31 days, an exact Calendar event, a linked Linear issue or a selected Notion page. Each read uses an owned verified account, spending reservations and the conversation's server-derived scope. Saved observations include timestamps, provider revisions and bounded readable content. Truncation is explicit; locally clipped event lists require a narrower request instead of skipping ahead. Reads do not approve external changes or personal facts.

An explicit chat request such as “read Gmail from Jordan and create a lead/contact” can use `gmail_search` through the tool catalog. It reads the selected verified outreach account through a restricted Composio session and saves a source observation. Drafting alone does not fetch mail; sending still requires exact review. Chat can also list recent Document Vault uploads and read their completed text extractions without reattaching files.

**LinkedIn** is available in Agents → Connectors through Composio-managed OAuth (`openid,profile,w_member_social,email`). Chat and local MCP clients share basic member-profile reads (name/account identity), selected post reads when LinkedIn grants access, and reviewed personal text posts up to 3,000 characters. Reviews bind the exact text, audience and verified member account; changing the audience requires fresh approval. Publishing returns a post receipt/link and ambiguous results are never automatically republished. This connector does not expose DMs, connection invitations, general people/job search, company administration or media uploads. LinkedIn may require additional approved scopes for reading posts. The standard spending plan includes conservative local $0.01 estimates per LinkedIn operation; migration 0032 creates an updated immutable default card while retaining existing rates, disabled policies and limits. Custom rate cards remain unchanged. Personal WhatsApp is not supported by Composio and is not enabled.

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

Optional [request-cost tracing and DeepEval reports](docs/tech/request-costs.md) use local Langfuse at **http://localhost:3003**. Run `make langfuse-up` to generate private settings and start its separate stack; rebuild API/workers to enable tracing. `make eval-chat` previews a bounded synthetic chat evaluation, and `make eval-chat allow_paid=1` runs it after correctness checks. Ordinary checks make no paid calls.

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

Isolated companion `0.4.5` on `application-identity` recognizes supported posting URLs and continues the current application when the saved job identity matches. Different recognized jobs stay separate, and unknown pages retain the Continue/New choice. Applications preserves the canonical posting link. These changes passed synthetic verification and are not deployed over the current smoke-test build.
