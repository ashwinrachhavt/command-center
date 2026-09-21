# Command Center implementation handoff

## Objective and confirmed direction

Build the connected FastAPI/PostgreSQL/Next.js workspace from user mockups and trycrm.ai, using prebuilt shadcn components, Clerk across Next.js/FastAPI, stable idempotent writes and Rails-inspired fat models/thin controllers. User chose LangGraph ReAct/OpenAI, Composio, skills/memory, Celery/Redis, pytest/pytest-mock and MCP tool discovery. Browser extension pairs with the local server and retains browser sessions on the host. Frontend is localhost:3001. Follow YAGNI/DRY. Coding authority does not authorize actual outreach or applications.

Latest steering: use Vercel AI Elements and evaluate Eve; user explicitly confirmed design-review scope as the current Command Center design and agent experience. AI Elements integrated. Eve evaluated from official docs as a second TypeScript runtime; no migration requested/installed. Native seven-pass review in docs/tech/design.md; independent engineering/outside review not run. gstack separate review-sections file absent; equivalent inline passes read. Design generator unavailable; reference mockups and live synthetic captures inspected.

## Changed files and implementation

- Backend models/controllers/contracts: owned CRM/task/profile/artifact/version/review/activity, browser devices/snapshots/commands, memory and agent runs. Model methods own artifact drafting/reviews, browser pairing/fill transitions and agent claims/outcomes. Migrations through 0003_memory, PostgreSQL RLS without public Data API grants, optional separate migration connection and transaction-pool settings.
- Clerk RS256 issuer/JWKS/origin verification, stable actor UUID, Next same-origin authenticated proxy; root .env configures Python, apps/web/.env Clerk. scripts/check-auth.mjs verifies key pair and synchronizes issuer/public build key. No secrets printed or committed.
- MCP Streamable HTTP internal endpoint, run/lease/audience-scoped credentials, pinned tool discovery, API-backed idempotent tools, Composio version allowlists, LangGraph ReAct, Markdown skills/config, Celery worker/beat and Redis Compose services. Interrupted runs fail explicitly, no automatic paid action replay. Public tool-step projection excludes system instructions/hidden reasoning.
- Next.js/shadcn responsive workspace, resource tables/edit/detail, artifact content/review, agent runs with actual AI Elements messages/Markdown/tool panels, browser bridge UI, memory, activity and settings. Canonical localhost:3001 avoids Clerk self-rewrite loops caused by binding Next dev to 127.0.0.1.
- MV3 extension in apps/extension with activeTab/scripting/storage, loopback host permissions, one-time pairing, exact form snapshot binding, explicit apply, sensitive-field exclusion and no submission. Playwright tests run the actual content script on a local synthetic fixture.
- README/spec/supporting docs updated to actual scope. Exactly two active specs retained. No commit or deployment made; repository was all untracked initially.

## Validation and runtime — complete

46 pytest tests pass against PostgreSQL. Ruff lint/format, strict mypy (36 source files), ESLint and TypeScript pass. Alembic drift check passes. Generated API types are current. Final API and web Docker production images build; Docker Compose startup completes with PostgreSQL/API/web/Redis healthy and worker/beat running; Celery inspect ping returns pong. Host temporary processes stopped. The persistent web service is **http://localhost:3001** (Docker maps host3001 to internal3000), API8000, PostgreSQL55432, Redis56379. The project's old host3000 binding is released.

Actual Clerk login was verified with a synthetic test user in a provisional development Clerk app, including after switching to Docker standalone. Keys remain in ignored env files; user will supply their own credentials. Synthetic examples and a clearly labelled mocked-model/real-MCP UI fixture exist only in that synthetic user's workspace. Desktop/mobile screenshots were viewed under ignored .local/qa, including the final full-width 390px detail sheet on the Docker runtime. Actual connected create-company and linked-record navigation were verified in browser. The synthetic agent fixture renders Markdown tables/lists and an expandable real MCP tool outcome. All three Playwright browser-companion regressions pass, including against the Docker-hosted fixture. Paid model output is mocked; no actual application or outreach occurred.

Functional smoke: existing Firecrawl and SearXNG both online; SearXNG JSON search returns public results and Firecrawl v2 returns example.com Markdown. RTK savings inspected. Raw check outputs are retained in ignored .local/qa. No independent engineering/outside review or production deployment was performed. The native design review and flat tasks are recorded under ~/.gstack/projects/command-center and summarized in docs/tech/design.md.

Browser CLI session: BROWSER_TASK=command-center-ui-20260921 ab clean. Do not dump .local/qa/web.log, browser-login.log or clerk-ticket.json; they may contain private auth redirects. No commits were created; original repo files were untracked before work.

## Limits and next product work

Paid OpenAI/Composio provider execution untested without user credentials. Research adapters previously functionally verified against existing services; rerun smoke if needed. Browser extension is an unpacked development client; uploads, cross-origin frames and arbitrary browser navigation are not implemented. Supabase compatibility exists but no deployment is performed. Future imports, verified candidate facts, campaigns/outreach/application submission, budget policy and multi-turn agent sessions remain separate product slices. Do not describe these as shipped.

## Commands

make setup; make auth-sync; make up; make lint; make test; make schema-check; make contracts; make smoke. Host: make api, make worker, make beat, make web. Browser regression: cd apps/web && npm run test:browser (localhost:3001 required; first npx playwright install chromium).

## Engineering review completed — 2026-09-21

Objective: finish the requested plan-eng-review with React/Next.js guidance, scoped by the user to custom frontend and authenticated API boundary. User approved remedies 1–5 individually, then directed “take all recommended”; after a stop, the user resumed with an explicit goal to finish without intervention. The review is complete. Implementation of its remedies has not started. Keep explicit commits; no commits were created. Git is on main with no commits and all source untracked, so no branch-diff baseline exists.

Files changed by this review: this handoff only within project source/docs. Synthetic diagnostic evidence and raw validation logs are ignored under `.local/qa/`. Review, QA plan and machine-readable tasks live in `~/.gstack/projects/command-center/`; they are review artifacts, not additional active specifications. The two active specs remain Product Spec and Tech Spec.

Accepted findings (3 P1, 6 P2):
1. P1: preserve dirty record/profile drafts and original revisions across refresh; handle 409 and pending-save races. `record-detail.tsx:555`, `settings.tsx:112`.
2. P1: pin artifact content, reason and submitted review to the opened immutable version. `record-detail.tsx:104,131`.
3. P1: scope QueryClient and workspace state to Clerk identity, including unresolved auth and late old responses. `providers.tsx:8`, `app/layout.tsx:37`.
4. P2: retain method/target/serialized-payload operation keys across ambiguous/manual retries for receipt-backed writes. `api.ts:59` and workspace mutations; provider connect guarantees remain unverified.
5. P2: complete loading/empty/error/stale/retry states for artifact reviews, agent steps and browser commands. `record-detail.tsx:245`, `agents.tsx:219`, `browser.tsx:294`.
6. P2: paginate Memory; currently only the first 100 notes are reachable. `memory.tsx:127`.
7. P2: add repeatable frontend component/API-client tests (Vitest + React Testing Library) alongside Playwright, with separate discovery patterns and integration into make check.
8. P2: test Next forwarding guards and authenticated synthetic-actor journeys; distinguish real Clerk integration from simulated identity tests.
9. P2: split conditional rich rendering from ordinary screens. Production manifest: 24 workspace JS chunks, 2,332,461 raw / 665,001 gzip bytes; section increment beyond layout is 1,944,442 raw / 544,336 gzip bytes. These are dependency sizes, not browser transfer or latency measurements.

Validation performed in this review: frontend lint and typecheck passed; production Next build passed; make test passed 46 backend tests with one existing dependency deprecation warning; Playwright passed all 3 extension tests. Backend style/type checks and research-service smoke were not rerun, so do not claim a fresh full make check. Four actual-component/helper synthetic probes reproduced draft loss, approval retargeting, identity-independent cache reuse and duplicate writes after manual retry. Evidence: `.local/qa/eng-review-draft-loss/{result,artifact-result,cache-result,retry-result}.json`. Bundle evidence: `.local/qa/eng-review-bundle.json`; raw logs: `.local/qa/eng-review-*.log`. No live Clerk account switch, server auth bypass, heap/latency benchmark or new regression-suite pass is claimed.

Status: nine actionable findings and nine tasks; six current silent failure families have no maintained test/handling and remain open in implementation. All review decisions are resolved and remedies/test requirements accepted. Review is complete, implementation is not cleared for release. Outside challenge was explicitly disabled by codex_reviews=disabled; no external or native substitute review was run. No unrelated TODOs were proposed or TODOS.md created. Sequential implementation is recommended because the changes share workspace modules. No agents or worktrees were spawned.

Artifacts:
- `/Users/ashwinrachha/.gstack/projects/command-center/ashwinrachha-main-eng-review-20260921-64621.md`
- `/Users/ashwinrachha/.gstack/projects/command-center/ashwinrachha-main-eng-review-test-plan-20260921-64621.md`
- `/Users/ashwinrachha/.gstack/projects/command-center/tasks-eng-review-20260921-64621.jsonl`

Next step when implementation is requested: T7 test foundation → T3 identity boundary → T4 retained operation keys → T1 drafts → T2 review target → T5 panel states → T6 memory → T8 authenticated integration → T9 bundle validation. Tests for each remedy land with it. Run new non-watching frontend tests, appropriate Playwright targets and make check before release. Review-only authorization does not itself request implementation, commits, production deployment or external actions.

Tool context: Serena active for Python/TypeScript; QMD has no matching indexed project documents. Use local docs and Context7 for library guidance. The gstack separate review sections were found and read in this review; the older implementation-session note above saying they were absent is historical. Session: `64621-1789989714-43290849`.

## Data import completed — 2026-09-21

Objective fulfilled: populate the actual user's local dashboard from Notion leads and the LinkedIn export in ashwin-portfolio. Real workspace ownership was verified against Clerk; the separate synthetic QA account was left unchanged. Imported 2,749 companies, 3,703 contacts, 48 saved jobs, 169 research opportunities, 7 review tasks and 11 private source artifacts; the career profile is populated. No external messages/applications or agent runs were performed.

Sources: complete same-day locally cached Notion pages (46 historical interactions, 75 company targets, six priority contacts), plus LinkedIn connections/company follows/saved jobs/career CSVs. Live Notion MCP required authentication and browser cookie import required Keychain interaction, so do not claim a live sync. Of 3,569 LinkedIn connection rows, 57 were empty. Six of 54 saved-job rows lacked both title and employer: preserved in the source artifact and surfaced through a review task, without invented details. Historical events remain notes; saved-job availability is unknown and opportunities are researching. Unrelated private messages, identity assets and saved screening answers were excluded.

Changed code/docs: `scripts/import_workspace.py`, `apps/api/tests/test_workspace_import.py`, company-label endpoint/contracts in `apps/api/src/command_center/api/{workspace,schemas}.py`, `apps/api/tests/test_workspace.py`, `apps/web/src/components/workspace/records.tsx`, regenerated `apps/web/src/lib/api-types.ts`, `README.md`, and this handoff. The batch label endpoint fixes the old first-100-companies lookup limit exposed by the imported dataset. It is actor-owned, bounded and excludes archived companies. No migrations or commits were created.

Validation: make check passed with 50 backend tests, backend Ruff/format/mypy, frontend lint/typecheck and production web build. Import tests use only synthetic fixtures and cover repeat imports, source completeness, contact identity conflicts and owner isolation. Batch labels test >100 companies and rejects cross-owner, invalid and oversized requests. A full dry run preceded the atomic live import; a replay dry run created/updated zero rows. Browser/API verification under the real Clerk user confirms dashboard counts and successful contacts/companies/jobs/opportunities/artifact queries; company labels resolved. Anonymous dashboard access returns 401. Docker API/web were rebuilt and restarted locally, with database volumes retained.

Private operational artifacts are ignored in `.local/imports/20260921-notion-linkedin/`: pre-import PostgreSQL backup `before-import.pgdump`, preview/applied/replay JSON manifests, `IMPORT-SUMMARY.md`, validation/deployment logs and dashboard capture. These contain or reference private source data; never commit them. The complete source snapshots remain under ignored `.local/source/` and in the original portfolio export directory. The temporary verification browser used its own task session.

Next step: no import work remains. The user can open localhost:3001 using the same existing account. Six incomplete saved-job entries and the imported priority leads have review tasks; no assumptions about current availability or outreach authorization were made. The earlier engineering-review fixes remain a separate pending implementation plan.
