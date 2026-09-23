# Command Center smoke test

This checklist covers the `frontend-redesign` release with application code through
`ed69ac1` and companion **0.4.5**. It is a test guide, not a claim that every live
provider or employer site has already been verified.

## Start here

- Open **http://localhost:3001** and sign in with your usual account.
- Reload the unpacked **apps/extension** in Chrome's Extensions page, confirm
  version **0.4.5**, then refresh any application tabs already open.
- Use **Direct browser** for ordinary Chrome. For the dedicated AgentBrowser
  profile, run `make companion-browser` from the project directory.
- Use an existing test contact, a small document and a job you can inspect without
  submitting. For a real email-send test, address the message to yourself.
- Mark an item **pass**, **fail**, or **blocked by setup**, with its ID. Optional
  provider/model checks require configured accounts, keys and provider credits.

For a first pass, do **L1–L3, W1–W3, D1–D3, P1–P2, A1–A6 and T1–T2**.

## Leads, contacts and follow-ups

- [ ] **L1 — Find your leads.** Search/filter Contacts, Companies and Opportunities;
  open a record and its linked company/person. Correct records and fields appear;
  closing a contextual panel returns you to the original list.
- [ ] **L2 — Save a LinkedIn follow-up.** Contact → Follow up: write and format a
  message, save it, refresh, and reopen it. The saved text stays linked to that person.
- [ ] **L3 — Use and revise a follow-up.** Copy the saved message, open LinkedIn,
  edit and save another version. Copy matches the chosen saved version; copying
  or opening LinkedIn does not mark anything sent.
- [ ] **L4 — Prepare an email.** Add/check the contact's email, subject and message;
  use Prepare email. Check recipient, account, formatting and selected attachments
  in the reviewed proposal. If shown, Open mail app opens the intended draft.
- [ ] **L5 — Inspect LinkedIn mappings.** Compare several imported contacts with
  your export: name, LinkedIn URL, email when present, company, position and
  connection date/source history. Blank source values must not become invented data.
- [ ] **L6 — Discover job leads.** Opportunities → Discover leads: search a public
  job page, inspect it and capture it. Confirm company, role, opportunity and source;
  capturing the same URL again should not create duplicate leads.

## Contact discovery and company research — optional live integrations

- [ ] **C1 — Apollo discovery.** Contacts → Discover contacts, or Company → Find
  people: search a domain, inspect a result, explicitly Reveal profile when needed,
  then add it. Check the saved contact and provider evidence.
- [ ] **C2 — Hunter discovery.** Search the same company domain with Hunter and add
  a chosen result. Check professional email, name, company and source evidence.
- [ ] **C3 — Recovery and duplicates.** Reopen a saved discovery and repeat adding
  the same result. Existing saved results/contacts should be reused appropriately;
  missing keys, unavailable credits or provider errors should be explained.
- [ ] **C4 — Enrich company.** Open a company and choose Enrich company. Follow its
  task/conversation to completion; inspect the useful job-search context, sources
  and any resulting saved changes. Compare factual accuracy against the sources.
- [ ] **C5 — Enrich an opportunity.** Research → Enrich from source: open the saved
  evidence and request an outreach draft through the conversation. Existing CRM
  fields and application status should not change just because a page was fetched.

## Writing, notes and draft recovery

- [ ] **W1 — Comfortable editing.** Write a note with paragraphs, headings, lists,
  a link and pasted text. Try keyboard selection, undo/redo and formatting; check
  cursor stability and typing responsiveness.
- [ ] **W2 — Autosave and reopen.** Type, wait for the saved indicator, close/reopen
  the editor, and refresh. The working draft should return without requiring a checkpoint.
- [ ] **W3 — Meaningful history.** Save a checkpoint, edit further and save another.
  Reopen both saved versions. Autosave should not create a permanent version per keystroke.
- [ ] **W4 — Linked work.** Create/open a task linked to a note or document. Check
  the link in both contexts and confirm the document remains accessible.
- [ ] **W5 — Competing tabs.** Edit the same draft in two tabs. A conflicting save
  should show a recovery choice and preserve the displaced copy, not silently lose text.

## Document vault

- [ ] **D1 — Upload and extract.** Library → Upload document: try a PDF or DOCX and
  a Markdown/text file. Check progress and completion, readable extraction and
  grouping under the original; extraction should not appear as an unrelated duplicate.
- [ ] **D2 — Retrieve the original.** Download an uploaded original and check it
  opens with the same contents. Open the original and extracted text together.
- [ ] **D3 — Find saved content.** Search by title and a phrase inside a saved
  document, filter by type, and reopen the result. Search uses saved versions,
  not unsaved working text.
- [ ] **D4 — Edit and export.** Edit a document, save a checkpoint and Export PDF.
  Check progress, download and formatting. The PDF must reflect the chosen saved version.
- [ ] **D5 — Failure handling.** If conversion/export fails, check the error and
  explicit retry/cancel controls. Retrying should not silently replace the original.

## Candidate profile and résumé

- [ ] **P1 — Select a résumé.** Choose a readable uploaded résumé as default.
  Refresh and verify the exact version stays selected; uploading a newer file must
  not silently switch the default.
- [ ] **P2 — Approve basic facts.** Check name, separate first/last name, email,
  phone, location/address and profile links in Settings. Approve correct facts;
  check that autofill uses approved values.
- [ ] **P3 — Review career mappings.** Compare employment and education against
  your LinkedIn export: employer/school, role/degree, location, dates and descriptions.
  Try Propose edit → Map fields, correct a value and approve its exact revision.
- [ ] **P4 — Preserve uncertainty.** Check year-only/month-only dates and blank end
  dates. Date precision must stay intact; a blank end date does not mean currently employed.
- [ ] **P5 — Pending changes.** Edit an approved fact without approving the new
  proposal. The earlier approved value should remain active. Reject/revoke a test
  proposal and confirm the resulting state is understandable.

## Application companion — highest-priority live test

- [ ] **A1 — Pair and capture.** Browser → pair the companion, open a job form,
  select the intended résumé and click Autofill this page. Check captured labels,
  page identity and visible progress.
- [ ] **A2 — Fill basic controls.** Verify text/email/phone fields, selects,
  checkboxes/radio groups and dates where supported. Missing or unsupported answers
  must remain visible for manual completion.
- [ ] **A3 — Preserve your edits.** Put a value in a field before capture, and edit
  another while preparation runs. Autofill must preserve these values unless you
  explicitly review replacement; later changes require fresh capture/review.
- [ ] **A4 — Attach the right files.** Check the actual résumé upload and, if
  selected, cover-letter upload. Confirm filenames, exact selected versions and
  file-control targeting; résumé and cover letter must not be swapped.
- [ ] **A5 — Continue the same job.** Click Next yourself, then capture/fill the
  next page. A recognized same job continues automatically; an unknown page offers
  Continue/New. Applications should show one record with both page histories.
- [ ] **A6 — Start a different job.** Open another recognized posting. It must
  become a separate application rather than append to the previous one.
- [ ] **A7 — Employment and education rows.** On an empty, clearly labelled history
  section, test Add-row expansion and filling from approved facts. Check order,
  dates and row count. Occupied or ambiguous sections should remain manual.
- [ ] **A8 — Reopen and retry.** Close/reopen the side panel during preparation;
  refresh after saving a review. The same draft/request should recover, with no
  duplicated rows or silently repeated uncertain fill operation.
- [ ] **A9 — Review generated answers.** Generate an answer for a written question,
  inspect grounding, edit it, and use Save review and fill answers. Check the saved
  review and the value actually placed in the form.
- [ ] **A10 — Submission boundaries.** Next and Submit stay your actions. Filling
  a form must not mark the tracker as submitted; update that status explicitly.

Repeat the relevant A checks on **Greenhouse, Lever, Ashby, Workday and iCIMS**
when you have suitable forms. Record site, page/step, browser mode and failing
control type. Supported URL recognition does not guarantee every tenant's controls
or authenticated portal flow works.

## Application tracker and documents

- [ ] **J1 — Track work.** Find an application, reopen older page packages, view the
  saved posting, change its next task/deadline and continue its conversation.
- [ ] **J2 — Save requirements.** Inspect the captured job description or write it
  with Tiptap, save a checkpoint and reopen it.
- [ ] **J3 — Draft application documents.** With a configured model, request a
  tailored résumé and cover letter from selected sources. Check factual accuracy,
  source links, editable output and recovery after refresh.
- [ ] **J4 — Keyword coverage.** Compare selected saved résumé/job-description
  versions; try custom terms and switch sources. Results must follow the selected
  versions without modifying them. Coverage is text matching, not an ATS score.
- [ ] **J5 — Export and reuse.** Export the saved application documents to PDF;
  confirm completed files appear in the companion's separate résumé/letter selectors.

## Daily tasks, agents and streaming

- [ ] **T1 — Daily task views.** Create tasks for today, a later date and no date.
  Check Today, Upcoming and Unscheduled against your saved profile timezone.
- [ ] **T2 — Explicit task states.** Start, snooze, resume, complete and reopen a
  test task. Check counts, row placement and persistence after refresh. Opening
  its conversation must not implicitly complete it.
- [ ] **T3 — Work queues.** Open attention, running-work and output entries from
  Overview. Each should open its correct question, review, conversation or saved
  document version with useful empty/error states when appropriate.
- [ ] **T4 — Smooth streaming.** Run a short task conversation. Watch text/tool
  progress, scroll up while it streams, change section and return, then refresh.
  Look for jank, duplicate text, lost content and unexpected scroll jumps.
- [ ] **T5 — Questions and cancellation.** If an agent asks a question, refresh
  and answer it once; confirm the right work resumes. Cancel a separate test run
  and confirm it stops without an automatic restart.
- [ ] **T6 — Linked outputs and memory.** Follow a saved output/source link. Review
  a proposed memory if one appears; pending or revoked memory must not masquerade
  as an approved candidate fact.

## Connected apps, email and external actions — optional live integrations

- [ ] **E1 — Configuration status.** Open Connected apps directly and from Settings.
  Check missing configuration versus connected/verified account status for Gmail,
  Calendar, Linear, Notion, Apollo and Hunter where presented.
- [ ] **E2 — OAuth return.** Connect an app, return to the workspace, explicitly
  Refresh accounts, and verify the displayed identity. Select the intended Gmail
  account with Use for outreach; reload and check the selection persists.
- [ ] **E3 — Explicit email pull.** Open Pull email and type a query: neither action
  should fetch Gmail. Click Pull email and check results belong to the selected
  account. Do not expect inbox sync or a true reply/thread workflow in this release.
- [ ] **E4 — Review before sending.** Prepare an email to yourself, inspect its
  exact account, recipients, subject, body and attachments, then explicitly approve
  if you want to send it. Confirm receipt and delivery; editing needs a fresh review.
- [ ] **E5 — Other reviewed actions.** If relevant, use a disposable Calendar
  event, Linear issue or Notion page. Review the exact proposal before approval;
  verify result/receipt and that an unapproved proposal makes no external change.
- [ ] **E6 — Provider errors and spending.** Check that missing credentials,
  disconnected accounts, invalid model choices and unavailable credits produce
  useful errors. Inspect Settings spending controls and recorded usage after a run.

## Workspace usability and feedback

- [ ] **U1 — Navigation.** Every main sidebar entry opens a full section page;
  linked-record panels retain the originating context and sensible Back/Close behavior.
- [ ] **U2 — Appearance and narrow layout.** Try light/dark/system mode and accents,
  then a narrow browser window. Check readable contrast, visible buttons and no
  unintended horizontal overflow in forms, dialogs and long filenames.
- [ ] **U3 — Keyboard.** Navigate with Tab, activate controls with Enter/Space,
  close dialogs with Escape and check that focus returns to the opener.
- [ ] **U4 — Refresh and errors.** Refresh a detail page; test empty searches and
  visible retry controls. Saved data should remain and failures should not look like success.

For each issue, send: **test ID, page/site, steps, expected result, actual result,
and whether refresh/retry changes it**. A redacted screenshot or short recording is
useful for layout/streaming problems; omit credentials and private message contents.

## Known limits for this checkpoint

- Exact Gmail message/thread reply targeting is unfinished. The separate investigation
  has no implementation changes in this release. New reviewed outreach sends are included.
- General scheduled routines are deferred. Unattended Next/Submit is not implemented.
- Historical application matching and full Simplify feature/portal parity are unfinished.
- Live provider delivery, paid-model quality and authenticated ATS coverage need your testing.
- LinkedIn import intentionally covers contacts and professional profile, not message bodies.

The coding goal is paused. No further feature work or deployment is planned until you resume.
