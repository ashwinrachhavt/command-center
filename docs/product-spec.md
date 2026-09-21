# Command Center — Product Spec


This is the single source for product behavior and acceptance. [product.md](product/product.md) owns product direction and scope rationale. [Tech Spec](tech-spec.md) owns architecture and execution contracts. The former Planning Doc, duplicated requirements, lead-planning notes, and interview material are absorbed here or in Tech Spec; superseded copies are historical only.

## 1. Outcome and user

Command Center is a standalone local workspace for Ashwin to run job search, outreach, relationships, research, application materials, and automatic applications. Local Codex or agents built locally should perform the browser work the user currently performs in Chrome: discover roles, judge fit and legitimacy, find useful connections, navigate employer portals, tailor answers, upload a resume, submit, and record the outcome.

A prepared draft alone does not satisfy the requested outcome. The first implementation must prove a complete job-to-application loop before expanding coverage. The longer-term extension is people/company relationship management and finding connections for the user's AI SaaS sales; it is not a requirement to build a sales product now.

## 2. Confirmed scope and release boundary

| Area | Confirmed direction | Boundary still open |
| --- | --- | --- |
| Inputs | Job title, job URL, or LinkedIn-export CSV | Exact CSV schemas and saved-search criteria |
| Existing leads | Seed from Notion Leads Real Data and Contacts & Relationship Registry | Reviewed mapping, deduplication and freshness |
| New discovery | Find additional roles/people with browser research, Hunter, Apollo, Firecrawl and free/public sources | Minimum provider and site coverage; available accounts/quotas |
| Qualification | Find promising, legitimate roles and useful relationship paths; filter suspicious listings | Hard filters, legitimacy threshold and connection priority |
| Materials | Resume/message/document authoring in the portal; tailored application answers | First output formats and candidate fact/answer policy |
| Execution | Local agents fill, upload and submit while the user is absent | Campaign authority, per-run limits, exceptions and supported portals |
| Outreach | Job-search outreach is current scope | Channels, sending authority, cooldowns and sequences |
| Foundations | General artifacts, documents/types, first-class tasks, evidence and human/AI audit | Exact schema, review/version and retention contracts |
| Later | Broader relationship operations and AI SaaS prospecting | No sales workflow implementation in the first release |

The initial proof may support one target profile and limited portal coverage. Automatic applications are core direction; neither an importer-only release nor a blanket submit prohibition is current scope. Full LinkedIn ZIP coverage and Gmail/calendar synchronization can follow the minimum title/URL/CSV/Notion-seed flow. Integration timing is sized against the complete loop rather than automatically deferring all discovery. Docling shall be used for Local extraction as a vendor. Firecrawl with Searxng on Local docker for crawling and scraping. We must use AgentBrowser for autonomous agent application and outreach and we must also have an Open Source Extension like Simplify Pro but running locally that enables one click applications on website and fills QnA on the application forms based on the context from the user's knowledge base. 

## 3. Product vocabulary 

| Object | Meaning |
| --- | --- |
| Person | Reusable contact with identifiers, roles, employment observations, preferences and relationship evidence |
| Company | Employer, agency, client or other organization with dated research and identifiers |
| Job | Specific role with a source identity, description history and observed availability |
| Opportunity | The user's pursuit of a company/job, linked to relevant people and a next action |
| Application | Exact material/answer package, execution attempts, submission evidence and later hiring outcomes |
| Artifact | Captured or created work product such as a message, research result, document or package |
| Document / document type | A document facet of an artifact, classified by purpose such as resume, cover letter or company research; shares the artifact version lifecycle |
| Interaction | Communication/meeting event with participants, channel, time and source |
| Task | Actionable commitment with owner, due semantics, state, rationale and context |
| Lead | Discovery/pursuit term; whether it is a separate lifecycle or a view remains open |
| Audit event | Attributed history of a state change or decision, with redacted details |

Keep person identity separate from opportunity progress. Several people may support one application, and one person may remain useful across many jobs. A discovered email address, a LinkedIn connection, and a confirmed advocate are different relationship signals.

## 4. End-to-end workflows

### Start and seed

A title starts discovery using a saved target profile. A URL captures a specific role and its job description. A LinkedIn CSV supplies relationship/context data; do not assume it contains jobs. Existing Notion records enter a staging and review flow with page/row provenance. Manual entry remains available for missing records.

Preserve both operational sources in place: [Leads Real Data](https://app.notion.com/p/3e22e26208a58027b5f4d84258dd8c6f) and [Contacts & Relationship Registry](https://app.notion.com/p/3e22e26208a58182be40d036fd9561cf). Their historical notes are evidence, not proof of current employment, open roles, or live commitments. Real lead data stays outside committed specifications and fixtures.

### Discover and qualify

Agents explore the selected job sources, find relevant roles and people, and explain accepted, rejected, and uncertain results. Keep role fit, employer/listing legitimacy, identity confidence, source freshness, email deliverability, and relationship strength separate. A single opaque score must not hide a disqualifying condition.

Prefer official employer/job sources where available. Record suspicious indicators such as mismatched domains, unverifiable employer identity, payment requests or contradictory sources. Screening is an evidence-backed assessment, not a guarantee that no scam can pass. A failed fetch means unavailable/unknown, not automatically closed or fraudulent.

### Research the opportunity

| Dossier section | Required information | Quality rule |
| --- | --- | --- |
| Product | What is sold, customer, problem, differentiation, relevant technical signals | Official sources first; separate interpretation from facts |
| Company and story | Leadership, business model, milestones, recent news and hiring context | Claim-level source and collection time |
| Relevant roles | Title/team/location, source link, observed status and target-profile overlap | Show coverage and observation time; do not claim all current jobs were found |
| Job description | Full retained text, requirements, responsibilities and explicit compensation/compatibility statements | Version/hash/source; preserve the description actually used |
| Interview process | Reported stages, participants, timing and source | Distinguish recruiter-confirmed from reported/estimated |
| Interview questions | Question, role family/stage, source and anecdotal status | Reports are not company policy or guaranteed future questions |

Interview preparation should use the job/company dossier, interviewer context and verified experience to suggest stories, then support a post-interview follow-up. Outcome data does not rewrite candidate facts.

### Prepare materials and answers

From an opportunity, select actual candidate source material and write or generate resumes, messages, cover letters, research documents and application answers in the portal. Show relevant evidence, missing information, edits and versions. Preserve the exact material selected for each application.

Tailoring may rephrase supported experience and explain motivation/fit. It must not invent employment, achievements, metrics, eligibility, compensation preferences or demographic/legal declarations. Missing personal answers and the amount of human review are pending decisions, not a reason to substitute generic unpersonalized text. Approved reusable answers should retain context so the user is not asked the same resolved question repeatedly.

### Execute automatically

The local runner navigates the supported application flow, fills answers, uploads the pinned resume and submits within the agreed authority. Simplify or a custom extension may assist; the product must not assume an unverified third-party orchestration interface exists. The active browser/account must be known.

Record submitted, failed-before-submission, paused, and outcome-unknown distinctly. A click is not proof of acceptance by a portal. Unknown outcomes must reconcile before retrying. A change to materials creates a new package rather than altering what an earlier attempt used. Authentication challenges, genuinely missing answers, scope drift and uncertain effects need specific recoverable exceptions.

### Outreach and follow-up

Discovering a person, drafting a message, sending it, and scheduling follow-ups are separate actions. Application authority does not silently authorize messaging. Do-not-contact excludes outreach; it is not a small score penalty. Show the reason and evidence for each reminder, preserve manual user priorities, and avoid duplicate reminders on replay/rescheduling.

## 5. Requirements and acceptance contract

| ID | Requirement | Acceptance evidence |
| --- | --- | --- |
| P-01 | Title/URL/CSV entry | Each mode produces the intended search, job or staged relationship context |
| P-02 | Notion lead seeding | Reviewed mappings retain source references and do not treat historical meetings as current tasks |
| P-03 | Canonical identities | Strong identifiers reconcile unambiguous records; name-only collisions and conflicts enter review |
| P-04 | Source-backed research | Dossier claims and job descriptions retain source/time/version and uncertainty |
| P-05 | Explained qualification | Fit, legitimacy and connection findings are separately inspectable; hard exclusions are enforceable |
| P-06 | General artifacts/documents | Resumes, messages and research share a coherent version/review lifecycle; no resume-only parallel store |
| P-07 | Tailored answers | Answers reference actual facts/material; missing factual content is surfaced and handled by agreed policy |
| P-08 | Automatic browser application | Controlled fixture completes fill/upload/submit and records confirmation without per-field supervision |
| P-09 | Duplicate and outcome handling | Replay/crash does not blindly create another submission; unknown effects enter reconciliation |
| P-10 | Tasks and follow-ups | Owner, due time/date, state, rationale and evidence are present; completion/reminder operations are idempotent |
| P-11 | Human/AI attribution | Consequential state changes and execution actions record the authenticated actor/delegator and material versions |
| P-12 | Local privacy and recovery | Access, secrets, source handling and backup/restore meet the Tech Spec contract |
| P-13 | Provider limits | Quota, failure, no-match and access-denied outcomes are distinguishable; no unapproved spend |
| P-14 | Portability | Selected record/material export is reviewable and excludes sensitive/internal data by default |
| P-15 | Usable portal | Editing, evidence inspection, campaign progress and exception recovery have designed states |

A complete synthetic acceptance scenario covers input → discovery/qualification → source evidence → candidate materials → answers → automatic application → confirmation/reconciliation → follow-up. A bounded real-site pilot follows validated account, candidate-data, site-support and campaign setup. Exact coverage and acceptable intervention count remain open; documentation alone is not a completed feature.

## 6. Success measures and boundaries

Measure discovery-to-confirmed-application time, user intervention count/duration, supported versus unsupported application coverage, duplicate/unknown outcomes, unsupported claims caught, due-task completion, and response/interview conversion using defined cohorts. Separate unknown outcomes from failures. Replace unverifiable claims such as “missed follow-ups prevented” with observable timing/completion counts.

Local-first means the core record store and workflow are local. Cloud models, Google, enrichment and external portals have separate data/spend boundaries. A disabled optional provider should leave supported manual/source alternatives usable. Do not claim complete job coverage, guaranteed scam detection, certain sponsorship from company history, or an absolutely immutable local audit log.

No hosted multi-tenant recruiting product, sales automation release, fabricated personal claims, name-only automatic person merging, credential harvesting, CAPTCHA bypass or site-access-control bypass is included. Outreach sending requires its own product decision.

## 7. Open product decisions — next interview round

On 2026-09-21 the user authorized the scaffold, chose PostgreSQL in Compose and reuse of the existing Firecrawl/SearXNG services, prioritized FastAPI/data-model correctness, and requested Rails-inspired fat models/thin controllers. The user subsequently authorized the mockup-led shadcn frontend, Clerk, LangGraph/OpenAI/Composio, Celery, MCP discovery, skills/memory and a local paired browser companion; these connected scaffold surfaces are now implemented. Foundation work proceeds independently of Q5–Q10; those answers remain open for the workflows they govern.

| ID | Decision | Recommendation to discuss |
| --- | --- | --- |
| Q5 | Target titles, seniority, geography/remote, compensation and compatibility; hard exclusions | Named search profiles with must-haves separate from preferences |
| Q6 | How strong connections affect applying | Boost warm/referral paths; decide explicitly whether a relationship is mandatory |
| Q7 | What is approved once per run/campaign; volume and stopping limits | Bounded campaign authority can cover discovery, personalization and submission without per-field approvals |
| Q8 | Handling an unknown personal/application answer | Tailor narrative from supported experience; collect and retain missing factual answers rather than invent them |
| Q9 | Outreach channels, sending and follow-up authority | Separate find/draft/send/sequence permissions and contact preferences |
| Q10 | Model, enrichment and research budgets | Use free quotas/cache first; separate model spend; no automatic purchase or top-up without policy |

These answers are not yet supplied. They constrain technical and design decisions; their recommendations are not accepted requirements. Continue the section-by-section interview here instead of maintaining a separate planning/interview specification.

## Supporting document

[product.md](product/product.md)
