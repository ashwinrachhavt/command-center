// Adapter runner: executes one served site adapter against this tab on behalf
// of the background orchestrator. Separate from content.js so the user-driven
// side-panel flow is untouched. Steps run in order (identity, resume, known
// questions, validate, Simplify handoff, re-validate); every field records
// DOM-structural evidence. This script never clicks Next or Submit; runs end
// ready for review.
(() => {
  if (globalThis.__commandCenterAdapterRunner) return;
  globalThis.__commandCenterAdapterRunner = true;

  const contracts = globalThis.CommandCenterContracts;
  const fillers = globalThis.CommandCenterFormFillers;
  if (!contracts || !fillers) return;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  // Wait until the DOM is quiet for two animation frames or the cap elapses.
  async function settle(ms) {
    const deadline = Date.now() + Math.min(ms || 0, 30000);
    while (Date.now() < deadline) {
      await sleep(150);
      const before = document.body?.childElementCount ?? 0;
      await new Promise((resolve) => requestAnimationFrame(() => resolve()));
      const after = document.body?.childElementCount ?? 0;
      if (before === after) break;
    }
    await sleep(100);
  }

  function resolveElement(selector) {
    try {
      return document.querySelector(selector);
    } catch {
      return null;
    }
  }

  function matchedLabel(element) {
    const label = element?.labels?.[0]?.textContent?.trim();
    return (label || element?.getAttribute("aria-label") || element?.name || element?.id || "").slice(0, 500);
  }

  function fieldEntry(element) {
    if (!element) return null;
    const description = {
      type: element instanceof HTMLSelectElement
        ? "select"
        : element instanceof HTMLTextAreaElement
          ? "textarea"
          : element.type || "text",
      accept: element.accept || "",
    };
    const elements = element.type === "radio" && element.name
      ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(element.name)}"]`))
      : [element];
    return { description, elements };
  }

  function sourceValue(path, context) {
    const [scope, key] = path.split(".", 2);
    if (scope === "profile") return context.profile?.[key];
    if (scope === "resume") return context.resume;
    return undefined;
  }

  async function executeField(field, context, evidence) {
    const record = (status, detail) => {
      evidence[field.id] = {
        status,
        selector: field.selector,
        matched_label: matchedLabel(resolveElement(field.selector)),
        detail,
      };
      return status;
    };
    if (field.kind === "resume") {
      const element = resolveElement(field.selector);
      if (!element) {
        record("unsupported", "No resume input matched its selector.");
        return;
      }
      const transfer = context.files?.[field.id];
      if (!transfer) {
        record("unsupported", "No reviewed resume bytes were pinned for this run.");
        return;
      }
      const outcome = await fillers.uploadFile(fieldEntry(element), transfer);
      record(outcome.status, outcome.detail);
      return;
    }
    const element = resolveElement(field.selector);
    if (!element) {
      record("failed", "No element matched this selector.");
      return;
    }
    const value = sourceValue(field.source, context);
    if (value === undefined || value === "") {
      record(field.required ? "failed" : "unsupported", "No reviewed profile value for this field.");
      return;
    }
    const entry = fieldEntry(element);
    if (
      element instanceof HTMLSelectElement ||
      element.type === "radio" ||
      element.type === "checkbox"
    ) {
      const outcome =
        element instanceof HTMLSelectElement
          ? fillers.fillText(entry, value)
          : fillers.fillChoice(entry, value);
      record(outcome.status, outcome.detail);
      return;
    }
    record(...Object.values(fillers.fillText(entry, String(value))));
  }

  async function pageFingerprint(selectors) {
    const state = {};
    for (const field of selectors) {
      const element = resolveElement(field.selector);
      state[field.id] = {
        present: Boolean(element),
        has_value: Boolean(element && (element.value || element.checked)),
      };
    }
    return state;
  }

  async function validateStep(step, evidence) {
    const missing = step.required_fields.filter((fieldId) => {
      const record = evidence[fieldId];
      return !record || !["filled", "uploaded", "preserved"].includes(record.status);
    });
    return missing;
  }

  async function snapshotEvidence() {
    const response = await chrome.runtime.sendMessage({
      version: 3,
      action: "automation-evidence",
      run_token: context.runToken,
      run_id: context.runId,
      field_evidence: evidence,
      page_evidence: await pageFingerprint(allFields),
      simplify_step: simplifyStep,
    });
    return response?.recorded === true;
  }

  let context;
  let evidence = {};
  let simplifyStep = { form_detected: false, clicked: false, settled: false, validated_required: false, missing_fields: [] };
  let allFields = [];

  async function run() {
    const start = await chrome.runtime.sendMessage({ version: 3, action: "automation-start" });
    if (!contracts.PendingAutomationCommand(start?.command)) return;
    context = {
      runId: start.command.run_id,
      runToken: start.run_token,
      profile: start.profile ?? {},
      resume: start.resume ?? null,
      files: start.files ?? {},
    };

    for (const step of start.command.adapter.steps) {
      if (step.kind === "identity" || step.kind === "resume" || step.kind === "question") {
        allFields.push(...step.fields);
        for (const field of step.fields) {
          await executeField(field, context, evidence);
          await settle(field.settle_ms);
          await snapshotEvidence();
        }
      } else if (step.kind === "validate") {
        const missing = await validateStep(step, evidence);
        simplifyStep.missing_fields = missing;
        simplifyStep.validated_required = missing.length === 0;
        if (missing.length > 0) {
          await snapshotEvidence();
          await finish("completed", `Missing required fields: ${missing.join(", ")}`);
          return;
        }
      } else if (step.kind === "simplify_handoff") {
        const trigger = step.selector ? resolveElement(step.selector) : null;
        if (!trigger) {
          simplifyStep.form_detected = false;
          continue; // Non-detection is a success-path no-op.
        }
        simplifyStep.form_detected = true;
        trigger.click();
        simplifyStep.clicked = true;
        await settle(step.settle_ms);
        simplifyStep.settled = true;
      }
      await snapshotEvidence();
    }
    await finish("completed", "Adapter steps finished; the application is ready for review.");
  }

  async function finish(state, detail) {
    const response = await chrome.runtime.sendMessage({
      version: 3,
      action: "automation-result",
      run_token: context.runToken,
      run_id: context.runId,
      state,
      detail,
      field_evidence: evidence,
      page_evidence: await pageFingerprint(allFields),
      simplify_step: simplifyStep,
    });
    if (response?.recorded !== true) {
      // The service worker may have died; it replays from persisted state.
      evidence._pending = { state, detail };
    }
  }

  void run();
})();
