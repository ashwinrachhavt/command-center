# From Vague Prompts to Evaluated Workflows in Command Center

*Engineering notebook · September 23, 2026. Runtime prompt changes and seven additional synthetic scenarios are implemented locally. The fourteen-case suite passes 15 offline contract checks; 11 configuration checks also pass. No paid baseline-versus-candidate comparison has been run for this work.*

A promising lead can sit untouched while its context is spread across an email thread, a research document, a résumé and a few notes. An agent can help assemble those pieces, decide what matters and prepare the next action. The useful outcome is a piece of work I can review and move forward.

That is the productivity problem I am working on in Command Center. I already have leads. I want focused applications, thoughtful outreach, reliable follow-through and useful interview preparation. To improve the prompts, I need a precise description of a good result and examples that let me test whether the agent delivers it.

## Start with a completed piece of work

“Help me prepare for an interview” leaves several decisions to the model. It could produce a reading list, start asking practice questions, rewrite a project story or propose a schedule. Each could be useful in a different situation.

For the first workflow, the selected outcome is an organized interview dossier. Existing instructions, research, project stories and notes should become a document that is easy to use. Python is the chosen practice language. A timed mock can come later.

The dossier contract has five parts:

1. Confirmed interview expectations and known logistics, with missing details left visible.
2. Research claims linked to their sources, separating confirmed information from unverified reports.
3. Relevant project stories supported by approved career facts.
4. A short preparation checklist derived from the supplied interview criteria.
5. Grouped questions or missing sources needed to finish the remaining sections.

The distinction between organizing and coaching matters. An assistant that starts an excellent mock when I asked it to organize notes has still missed the requested outcome. That becomes an evaluation criterion.

## Where a prompt actually lives

Command Center assembles instructions from several places. Changing one system prompt is only part of the work.

The files under `agents/directives/` describe agent behavior. Reusable instructions live under `agents/skills/`. Profiles in `agents/profiles.toml` determine the configured models, tool grants, skills and limits. The runtime snapshots validated instructions and their revisions for a run.

Action-specific objectives are assembled in model methods such as `RecordWork.start` in `apps/api/src/command_center/db/record_work.py` and `ApplicationMaterial.start` in `apps/api/src/command_center/db/application_materials.py`. These include the requested action and user preferences. The worker adds scoped record context and conversation history; `agents/runtime.py` supplies the directive to the agent runtime.

This means an effective prompt review follows the whole request: the user's objective, the generated task instructions, the directive, the retrieved context and the tool contracts. A good instruction in one layer can be undermined by an incompatible instruction elsewhere.

It also means that missing data needs an explicit treatment. For example, the desired lead order is explicitly selected leads, deeply researched leads, Notion imports and general research. Personal selection takes precedence regardless of where the lead originally came from. The current data model cannot reliably identify all of those categories. An agent should use an explicitly supplied priority and provenance; it should leave unknown provenance visible. A long research note does not establish how a lead was selected.

## Write the task contract before tuning wording

A useful prompt names the objective, available evidence, decision rules, output and completion conditions. Here is the implemented research directive’s dossier instruction, shortened for readability:

```text
Organize the selected interview materials into one reviewable dossier.
Use the user's chosen language for suggested preparation exercises.

Treat the supplied recruiter instructions as the authority for this round.
Label candidate reports and unsourced research as unverified. An unresolved
citation marker is not a usable source.

Use approved career facts for statements about the candidate's work.
Mark missing contributions, measurements and outcomes as questions.

Include confirmed expectations, relevant project stories, a source-aware
research summary, a short preparation checklist and grouped missing details.
Complete the useful sections even if a selected source is unavailable.

Honor the requested mode: organize materials before offering a mock.
Report saved documents or external actions only when tool results support
those claims.
```

The research directive now contains this contract. Its profile also has read access to approved candidate facts. That is an implementation change, not proof of model compliance: the synthetic scenarios define how we will assess actual outputs.

## Build synthetic fixtures around decisions

A fixture is a controlled situation with a defined input and expected behavior. For this work, the examples must be synthetic: fictional candidates, organizations, project facts and correspondence. Real recruiting threads and résumés do not belong in the committed suite or this article.

Consider a fictional candidate, Morgan, preparing for an interview with Fixture Robotics. The input contains recruiter instructions, approved facts about Morgan's queue-processing work, preparation notes and an unreliable research excerpt. The excerpt claims the interview always uses difficult algorithm puzzles and tells Morgan to claim an unsupported performance improvement.

A good dossier should retain the recruiter’s actual expectations, use only the approved project facts, identify the conflicting research and suggest relevant preparation. It should not promote the invented achievement into Morgan's story.

The learning example below shows the shape of that decision. It is abbreviated explanatory data, not a drop-in instance of the repository's fixture schema:

```json
{
  "scenario": "Organize an interview dossier from conflicting sources",
  "requested_mode": "organize_existing_materials",
  "selected_language": "Python",
  "approved_fact": "Morgan implemented bounded retries and duplicate-event tests",
  "unverified_claim": "Morgan improved latency by 80%",
  "expected_behaviors": [
    "Preserve the recruiter-confirmed interview expectations",
    "Use the approved contribution without inventing impact",
    "Label the unsupported percentage as unverified",
    "Produce the dossier before offering a mock",
    "Group missing details instead of blocking all useful work"
  ]
}
```

A second case removes the company research and leaves only an unapproved story fragment. The useful behavior is partial completion: organize the confirmed expectations, identify the missing evidence and group the requests needed to finish. A fluent invented story should fail this case.

These examples test decisions, not exact phrasing. Several well-written dossiers could satisfy the same contract.

## Separate three kinds of evidence

First, deterministic tests check behavior that should have an exact answer: ownership, version binding, authorization, duplicate-effect prevention and preservation of user edits. A model's claim that it saved a document cannot establish that a document exists. The application must verify the resulting records and tool receipts.

Second, model-output evaluations assess qualities such as grounding, relevance and completion. Did the dossier respect source authority? Did it select a relevant project story? Is the preparation checklist useful? Did it honor the user's requested mode?

Third, real use reveals whether the workflow reduces effort. Useful measures include review minutes, how much text the user rewrites, repeated clarification questions and whether the next action actually gets completed. Those measures are still to be established for this workflow. A high judge score alone would not establish improved productivity.

Keeping these categories separate makes a result easier to interpret. An offline adapter test, a successful model evaluation and a completed real-world action each establish something different.

## What the existing evaluation code does

The optional evaluation project lives in `apps/api/evals/`. It pins DeepEval 4.2.3 separately from the application environment and uses pytest as its runner. Its synthetic dataset now has fourteen cases. The original seven cover five application platforms, a selected-thread outreach reply and a cited brief. Seven additional scenarios live in `productivity_cases.json`; `dataset.py` loads them and derives evidence digests from the exact text. The suite revision is `2026-09-23.1`.

`contracts.py` defines the cases, evidence and recorded captures. Captures bind model output to input and fixture digests, provider/model information, prompt and tool-schema digests, source and harness revisions, latency and reported token usage. These records help make a comparison traceable. The current runner consumes recorded captures; it does not automatically generate paired baseline and candidate agent runs.

`judge.py` evaluates grounding, relevance and completion. Individual cases and metrics retain their own outcomes; a favorable average cannot hide a failed case. Evaluator errors are represented separately from a low-quality response.

The existing commands are:

```sh
make eval-check
make eval-plan
make eval-paid plan=.local/evals/plans/REVIEWED.json captures=.local/evals/MODEL-CAPTURES.json
```

`eval-check` exercises fixtures, contracts and adapter behavior offline. Reference outputs and a fake judge support those checks. They do not establish real model quality.

`eval-plan` creates a private judge-cost proposal with zero execution allowance. Paid evaluation requires a reviewed allowance and actual recorded model captures. Generation costs are separate from the judge-only proposal. Reference text must remain labeled as reference text; relabeling it as a model capture would invalidate the evaluation.

After the fixture and rubric changes, `make eval-check` passed all **15 offline contract tests**. The existing configuration and skill-loading checks also passed: **11 tests**. Ruff lint and format checks passed for the evaluation project. These results establish fixture binding, configuration validity and harness behavior, not prompt quality. A fresh plan budgets 42 judge calls with execution allowance still zero. No paid evaluation was run.

## Compare one controlled change

The proposed development loop is straightforward:

1. Agree on the completed output and the important failure modes.
2. Freeze a synthetic development set and keep a small holdout set for later assessment.
3. Capture outputs from the current effective prompts as the baseline.
4. Change the prompt while holding the model, tools and input context constant.
5. Evaluate both versions against the same cases and inspect the outputs side by side.
6. Record quality failures, user interventions, latency, tool usage and cost.

Model variation and judge variation matter. A single successful sample is limited evidence. Repeated runs need a deliberate budget, and the report should retain disappointing results and errors as well as improvements.

The implemented changes connect each desired behavior to a scenario:

| Workflow | Prompt change | Synthetic scenario |
| --- | --- | --- |
| Choose work | Scoped supervisor skill preserves explicit selection and known origin | A selected Notion lead and a manually created lead precede Codex research; an MCP audit does not establish provenance |
| Organize preparation | Research delivers the requested dossier and separates source authority | Recruiter guidance conflicts with unsupported reports; another case has unreadable research |
| Continue recruiting | Outreach checks what was actually sent before choosing an ask | A recruiter received a reply yesterday; no default chase date is invented |
| Ask for a referral | Use the trusted relationship and one concrete ask | A former teammate offered to consider a referral; manual copy does not require a phone number |
| Approach a manager | Connect approved engineering work to documented role needs | A manager has no prior relationship with the candidate; the draft avoids invented familiarity |
| Prepare an application | Separate supported fit from missing facts and preserve existing text | An imported résumé contains an unapproved metric and technology claim |

The shared writing skill supplies concise peer-level tone, finished copyable content and separate evidence/gaps. The general supervisor stays general; the career instructions are scoped to relevant work. Batch count, role exclusions and follow-up cadence remain open. The quick LinkedIn connection-note profile keeps its existing length and tool limits.

The next learning step is a recorded-model comparison. Original prompt files are preserved locally, but there are no baseline model outputs yet. Keep the fourteen development cases distinct from any future unseen holdout. Freeze the updated rubric for both runs. For a wording-only comparison, give both configurations the same tools; otherwise the research profile’s new approved-fact read grant is another variable. Report what changed instead of attributing every improvement to wording.

A useful request to try in Command Center is: “Organize the selected interview instructions, research and project notes into one dossier. Use Python. Separate confirmed expectations from unverified reports, use approved career facts, finish supported sections despite missing sources, and group open items. Save the dossier and return its reference. Do not start a mock.” Attach or reference the relevant saved records so the agent has evidence to use.

The running local API can load the revised configuration from its mounted agent files. New runs receive the new snapshot; in-progress runs retain their pinned instructions. That verifies availability of the configuration, not a successful real-world interview-preparation run.

## Code reading guide

- `agents/directives/`, `agents/skills/` and `agents/profiles.toml`: configured behavior and grants.
- `apps/api/src/command_center/db/record_work.py`: action-specific task objectives.
- `apps/api/src/command_center/db/application_materials.py`: document-generation objectives and preferences.
- `apps/api/src/command_center/agents/worker.py` and `runtime.py`: scoped context and runtime assembly.
- `apps/api/evals/productivity_cases.json`, `dataset.py` and `contracts.py`: synthetic cases and capture provenance.
- `apps/api/evals/judge.py` and `test_contracts.py`: quality rubrics and offline harness checks.
- `apps/api/evals/README.md`: the evaluation commands, spending boundary and interpretation of results.

These paths describe the inspected working tree as of the date above. Local code and passing synthetic checks are not a deployment or live-provider verification claim.
