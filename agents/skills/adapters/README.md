# Site adapters

Declarative, deterministic site adapters for the browser automation bridge, one
YAML file per ATS (`greenhouse.yaml` first). The API serves these read-only to
paired browser devices; the extension's adapter runner executes the ordered
steps against a live tab.

Invariants:

- **Never a submit selector.** Adapters never contain Next/Submit button
  selectors. Runs end in `ready_for_review`; submission requires an explicit
  `submit_authorized_at` on the application row, and the extension never clicks
  submit in this release.
- **Ordered schema.** Identity fields first, resume upload second, known
  questions third, then validation. Every field records DOM-structural
  evidence (selector attempted, matched label, outcome); failures are evidence,
  never screenshots.
- **Simplify handoff is best-effort.** The `simplify_handoff` click happens
  only after the validate step confirms an eligible form, followed by a settle
  wait and re-validation. Non-detection is a success-path no-op; Simplify
  completing every field is never assumed.
- **Stable selectors only.** Direct CSS selectors; no nth-child chains or
  XPath. The served `revision` (content hash) is pinned onto each run so
  staleness is detectable.

These YAML files are served to browser devices, never ingested by the agent
skill loader (`agents/skills/<slug>.md` glob, top level only).
