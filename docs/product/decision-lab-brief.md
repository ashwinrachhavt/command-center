# Decision Lab — portfolio editorial brief

**Date:** 2026-09-24. **Status:** requested direction, concrete draft and proposed interaction contract; not a published article or implemented page. This is supporting editorial material for Ashwin Rachha's portfolio, not a fourth Command Center specification or a product rename.

## Identity and publication status

Use **Decision Lab** as the interactive series name and **From Documents to Decisions** as this two-chapter article's title. This reconciles the user's two concepts: “What should an AI agent be allowed to do?” remains the central question, while the later title names the shared journey through mortgage documents and bank transactions.

| Placement | Draft copy |
| --- | --- |
| Eyebrow / writing category | Field Notes · Decision Lab |
| Headline | From Documents to Decisions |
| Subtitle | Two interactive investigations into how AI handles a mortgage file and a bank transaction—with Jev as an experimental decision layer. |
| Author / identity | An Ashwin Rachha systems experiment |
| Blog card | The Decision Lab: From Documents to Decisions |
| Card description | Can an AI model make a decision without being given unchecked authority? Change a fictional workflow, inspect Jev's judgment, and see where application policy takes over. |
| Main call to action | Inspect the decision |
| Suggested URL | `/writing/jev-decision-lab` — confirm against the eventual publication source; preserve/redirect an existing URL if one is identified. |
| Metadata title | From Documents to Decisions: A Jev Decision Lab — Ashwin Rachha |
| Metadata description | An interactive systems experiment with Jev, uncertain evidence, document classification and human review. Explore how application policy determines what an agent may do. |

The local `AR-Portfolio/src/content/writing` inventory inspected on 2026-09-24 contains `inside-buzz.md` and `mcp-sessions.md`, with no Jev article. Its career-fit specification explicitly leaves a Jev essay embed outside completed scope. This does not establish that no remote/published article exists. No existing article URL, publication source or deployment was verified or changed in this pass.

The user's supplied branding and case-study excerpts are the source for this brief. Their Notion pages were not independently fetched; publication must reconcile claims with the current approved public evidence. In particular, preserve Lois at Loan Labs and Classify AI at Finally as distinct products, employers and architectures. Do not say either originally used Jev. Keep customer data, private screenshots and employer-confidential implementation detail out of the public artifact.

## Editorial claim and opening draft

> A model can return a decision with a probability. It cannot, by itself, decide what authority that probability should carry. That boundary belongs to the product.

A PDF arrives with a name that tells you almost nothing. A bank transaction arrives with a merchant name that could mean several different things. Before either becomes useful, someone has to decide what it represents—and what software may do with that decision.

**Would you let software decide what these are?**

Choose a fictional mortgage file or a fictional bank transaction. Make your own call, reveal the evidence, then change one detail. The interesting moment is where an apparently easy answer stops being enough to act on.

These investigations draw on two different systems I worked on: Lois at Loan Labs and Classify AI at Finally. Jev is a new experimental decision layer in this article. It is not presented as part of either original implementation.

Jev offers a useful interface for the experiment: supply a state and narrowly defined questions, then inspect structured answers. Here, the surrounding application decides what those answers can change, what must be reviewed and what should stop. The point is to make that boundary visible. [TypeSafe introduction](https://docs.typesafe.ai/introduction).

## One experiment, two chapters

The cold open shows two restrained artifact cards: a badly named PDF and `SQ *NORTHSTAR 0824`, a fictional bank line. Each states “Synthetic example — no customer data.” The visitor chooses a chapter. The second remains a visible next chapter, not a competing dashboard widget.

| Stage | Lois-inspired document chapter | Classify AI-inspired transaction chapter |
| --- | --- | --- |
| Make your call | Preview `scan_004.pdf`; choose from displayed fictional document types before revealing the extracted text | Read merchant, amount and date; choose an account in the displayed fictional business's Chart of Accounts |
| Reveal evidence | Show readable text highlights, filename and the complete candidate catalog | Reveal the transaction's business context and a prior categorized transaction, clearly marked as evidence |
| Change one condition | Choose Clear text / Conflicting contents / Unreadable / Embedded bypass instruction | Switch between two fictional business charts, or reveal that the historical purchase served a different purpose |
| Bounded model question | Choice of displayed type plus unknown/mixed; independent Noul for sufficient readable evidence | Choice of this business's displayed account IDs plus needs-clarification; Noul about a specified historical match |
| Policy consequence | Classification proposal may be reviewed; renaming requires its own configured rule/review; sending remains a separate permission | A candidate may be presented to the bookkeeper; missing purpose goes to Ask the client; ledger sync still requires reconciliation |
| Human action | Confirm type, choose another type or request a better file | Approve, ask the client or review later |
| Engineering note | Immutable evidence, classification versus naming, scoped changes and execution-time revalidation | Tenant-specific chart, relevance of history, review lanes and reconciliation before sync |

The mortgage catalog is fictional and belongs only to the public scene. The transaction chapter is not a new bookkeeping feature in Command Center. Historical details such as Rails orchestration for Lois and Pinecone/Elasticsearch/QuickBooks for Classify AI come from the supplied case-study brief and require public-evidence verification before use in “What I actually built.”

## Visible decision boundary

The central instrument has five stages: **State → Question → Model output → Application policy → Outcome**. Clicking a stage reveals its input/output. Use ordinary language first, with exact JSON available inside Inspect this decision.

Model output shows the question text, primitive and answer. Choice exposes the selected option, its probability, the complete distribution and separately labeled confidence. Noul shows the probability of its own proposition. Use Score only where the visitor can read an actual ordered rubric; neither chapter needs a decorative score. Questions in a batch cannot secretly consume one another's answers. [TypeSafe confidence](https://docs.typesafe.ai/confidence), [Noul](https://docs.typesafe.ai/primitives/noul).

Application policy shows source sufficiency, current state, required permissions, review requirements and the exact permitted action. Each action has its own outcome: a classification may be acceptable while renaming requires review and sending is blocked. A green type prediction must not make the entire workflow green.

The inspect pane includes a short “What could be wrong?” note: OCR could omit a heading; the catalog could lack the right type; the historical merchant match could be irrelevant; a strong model probability could still accompany a wrong answer. A bypass instruction remains source text even when the model fails to flag it.

Jev receives the extracted/synthetic text and structured context; the PDF preview is a storytelling surface, not an image sent to Jev. Model request IDs and requested/returned/resolved model versions are shown only when actually captured. Moving aliases are not displayed as pinned versions. [TypeSafe models](https://docs.typesafe.ai/models).

## First-release playback and accessibility

Use curated synthetic scenarios and deterministic playback first. Label hand-authored outputs **Illustrative simulation — no model call**. Reserve **Recorded Jev result** for an actual retained provider response with its input/question/model provenance, and **Live Jev result** for a successful current request. A failed live call may offer simulation, but the visitor must see the mode change.

Do not fabricate token-by-token reasoning. A stage reveal explains application data flow; it is not the model's private thought process. Show configurable policy thresholds as illustrative product choices, distinct from the simulated model values, without claiming calibration. No generic “AI accuracy” meter or promise of safe decisions.

Use generous whitespace, a readable essay column, a compact instrument with visible labels, keyboard-accessible radio/select controls, clear focus, text outcomes independent of color, polite status announcements and reduced motion. Preserve a visitor's initial guess when conditions change so the consequence is easy to compare. Stack stages and evidence on small screens. The two chapters share one interaction pattern.

Release checks cover each scenario/outcome, visible provenance, independent action permissions, business-specific chart changes, unknown/missing evidence, malicious and harmless quoted instructions, no external effects, keyboard/focus/mobile behavior and source links. Optional live access comes later after provider access, privacy, rate limits and a spend allowance are verified. Reuse `/fit`'s disclosure pattern, not its role-evidence scoring or release claims.

## Return to real work — closing draft

A useful classification is only the beginning. A trustworthy workflow also preserves the evidence, limits what can change and leaves a clear way for a person to disagree.

This exercise uses fictional documents and transactions. For the real permission and revalidation problems behind agent actions, read my work on Lois. For the role of customer-specific context, human review and reconciliation, read Classify AI. The historical implementations and this Jev experiment are separate stories.

> The impressive part is not that a model can name a document or an account. It is that the surrounding system knows what evidence it used, what it may change, and when to hand the decision back to a person.

The intended path is Homepage → Decision Lab article → synthetic experiment → relevant Work case study → Explore working together (`/fit`). Field Notes explains the reasoning, Decision Lab exposes the experiment, and Work supplies verified career evidence. Resolve case-study URLs against the portfolio's real routes before publication; this draft does not invent public links.
