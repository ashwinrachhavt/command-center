const contracts = globalThis.CommandCenterContracts;
const element = (id) => document.getElementById(id);
const allowedApis = new Set(["http://localhost:8000", "http://127.0.0.1:8000"]);
await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
const stored = await chrome.storage.local.get([
  "connection",
  "applicationDraft",
  "claimedCommands",
  "pageReader",
]);
let connection = stored.connection;
let draft = stored.applicationDraft;
let claimedCommands = new Set(stored.claimedCommands ?? []);
let generationTimer;
let resumeChoice;
let coverLetterChoice;
let autofillBusy = false;
let actionBusy = false;
element("page-reader").value = stored.pageReader ?? "agent-browser";

function syncAutofillControls() {
  const pending = draft?.autofill && draft.autofill.stage !== "done";
  const busy = actionBusy || autofillBusy;
  const manualPending = Boolean(draft?.reviewedCommand || draft?.recapture);
  element("fields").inert = busy || Boolean(pending) || manualPending;
  for (const id of [
    "resume",
    "auto-resume",
    "cover-letter",
    "auto-cover-letter",
    "page-reader",
    "share",
    "prepare",
    "generate",
    "propose",
    "reload-preparation",
    "refresh",
  ])
    element(id).disabled =
      busy ||
      Boolean(pending) ||
      (manualPending && id !== "propose") ||
      (id === "auto-cover-letter" && !coverLetterChoice) ||
      (["generate", "propose"].includes(id) && generationPending());
  element("discard-draft").hidden = !draft;
  element("discard-draft").disabled = busy;
  element("disconnect").disabled = busy;
  element("autofill").disabled = busy || manualPending;
  element("autofill").textContent = autofillBusy
    ? "Autofilling…"
    : pending
      ? "Continue autofill"
      : "Autofill this page →";
  if (pending) {
    element("resume").value = draft.autofill.resumeVersionId ?? "";
    element("auto-resume").checked = draft.autofill.attachResume;
    element("cover-letter").value = draft.autofill.coverLetterVersionId ?? "";
    element("auto-cover-letter").checked =
      draft.autofill.attachCoverLetter ?? false;
  }
}

element("page-reader").addEventListener("change", async () => {
  const pageReader = element("page-reader").value;
  await chrome.storage.local.set({ pageReader });
  element("reader-status").textContent =
    pageReader === "agent-browser"
      ? "AgentBrowser uses the local companion browser."
      : "Direct browser reads this tab through the extension.";
});

function validate(name, value) {
  if (!contracts[name](value))
    throw new Error(
      "Invalid companion response. Reload the extension and try again.",
    );
  return value;
}

function message(text) {
  element("message").textContent = text;
}

function renderConnection() {
  element("pairing").hidden = Boolean(connection);
  element("connected").hidden = !connection;
}

function validGeneration(value) {
  const states = new Set([
    "idle",
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
  ]);
  if (
    !value ||
    !states.has(value.state) ||
    !(
      value.conversation_id === null ||
      typeof value.conversation_id === "string"
    ) ||
    !(value.run_id === null || typeof value.run_id === "string") ||
    !(value.error_code === null || typeof value.error_code === "string")
  )
    throw new Error(
      "Invalid generation status. Reload the extension and try again.",
    );
  return value;
}

function generationPending() {
  return ["queued", "running"].includes(draft?.generation?.state);
}

function renderGeneration() {
  const pending = generationPending();
  const state = draft?.generation?.state ?? "idle";
  const generate = element("generate");
  const propose = element("propose");
  generate.disabled = pending;
  propose.disabled = pending;
  generate.textContent =
    state === "queued"
      ? "Generation queued"
      : state === "running"
        ? "Generating grounded drafts…"
        : "Generate grounded drafts";
  const descriptions = {
    idle: "",
    queued:
      "Generation is queued. This popup will refresh the draft when it finishes.",
    running: "Generation is running. Your local edits remain unchanged.",
    completed: "Grounded drafts are ready for review.",
    failed: `Generation failed${draft?.generation?.error_code ? ` (${draft.generation.error_code})` : ""}.`,
    cancelled: "Generation was cancelled. Your current draft is unchanged.",
  };
  element("generation-status").textContent = descriptions[state];
}

async function api(path, options = {}) {
  const base = options.unauthenticated
    ? element("api-url").value
    : connection?.base;
  if (!allowedApis.has(base))
    throw new Error("Choose a supported local API address.");
  const method =
    options.method ?? (options.body === undefined ? "GET" : "POST");
  if (options.key && draft) await saveDraft();
  const response = await fetch(`${base}/api/v1/browser/${path}`, {
    method,
    credentials: "omit",
    redirect: "error",
    signal: AbortSignal.timeout(15000),
    headers: {
      ...(options.body === undefined
        ? {}
        : { "Content-Type": "application/json" }),
      ...(options.unauthenticated
        ? {}
        : { Authorization: `Bearer ${connection.token}` }),
      ...(method === "GET"
        ? {}
        : { "Idempotency-Key": options.key ?? crypto.randomUUID() }),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "The request could not be completed.",
    );
  return result;
}

async function apiBytes(path) {
  if (!allowedApis.has(connection?.base))
    throw new Error("Reconnect this browser first.");
  const response = await fetch(`${connection.base}/api/v1/browser/${path}`, {
    credentials: "omit",
    redirect: "error",
    signal: AbortSignal.timeout(15000),
    headers: { Authorization: `Bearer ${connection.token}` },
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "The file could not be read.",
    );
  }
  return new Uint8Array(await response.arrayBuffer());
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !/^https?:\/\//.test(tab.url ?? ""))
    throw new Error("Open a regular application webpage first.");
  return tab;
}

async function action(button, work) {
  if (actionBusy) return;
  actionBusy = true;
  syncAutofillControls();
  button.disabled = true;
  try {
    await work();
  } catch (error) {
    message(error.message ?? "Something went wrong. Please try again.");
  } finally {
    actionBusy = false;
    button.disabled = false;
    if (draft?.preparation) renderGeneration();
    syncAutofillControls();
  }
}

function receipt(kind) {
  draft.receipts ??= {};
  return (draft.receipts[kind] ??= crypto.randomUUID());
}

async function saveDraft() {
  await chrome.storage.local.set({ applicationDraft: draft });
}

function clearReceipt(kind) {
  delete draft.receipts?.[kind];
}

function validResumes(value) {
  if (
    !value ||
    !Array.isArray(value.items) ||
    !(
      value.default_version_id === null ||
      typeof value.default_version_id === "string"
    )
  )
    throw new Error("Invalid resume options. Reload the extension.");
  return value;
}

function validPreparation(value) {
  const required = [
    "id",
    "snapshot_id",
    "task_id",
    "artifact_id",
    "version_id",
    "version",
    "fields",
  ];
  if (
    !value ||
    required.some((key) => value[key] === undefined) ||
    !Array.isArray(value.fields)
  )
    throw new Error("Invalid application preparation. Reload the extension.");
  return value;
}

function fieldById(id) {
  return draft.snapshot.fields.find((field) => field.id === id);
}

function fieldHasValue(field) {
  const result =
    draft.lastAttempt?.command.snapshot_id === draft.snapshot.id
      ? draft.lastAttempt.result?.field_results?.[field.id]
      : null;
  return (
    field.value_state === "present" ||
    ["filled", "uploaded", "preserved"].includes(result?.status)
  );
}

function preparedById(id) {
  return draft.preparation?.fields.find((field) => field.field_id === id);
}

function appendChoice(container, field, value, label) {
  const row = document.createElement("div");
  row.className = "choice";
  const input = document.createElement("input");
  input.type = "radio";
  input.name = `field-${field.id}`;
  input.value = value;
  input.id = `field-${field.id}-${container.childElementCount}`;
  input.checked = (draft.values[field.id] ?? "") === value;
  input.addEventListener("change", async () => {
    draft.values[field.id] = value;
    draft.touched[field.id] = true;
    await saveDraft();
  });
  const text = document.createElement("label");
  text.htmlFor = input.id;
  text.textContent = label;
  row.append(input, text);
  container.append(row);
}

function editorFor(field) {
  const current = draft.values[field.id] ?? "";
  let control;
  if (field.type === "select" || field.type === "checkbox") {
    control = document.createElement("select");
    control.append(new Option("Leave blank", ""));
    const values =
      field.type === "checkbox" ? ["true", "false"] : field.options;
    for (const value of values)
      control.append(new Option(field.option_labels[value] ?? value, value));
    control.value = current;
  } else if (field.type === "radio") {
    const group = document.createElement("div");
    appendChoice(group, field, "", "Leave blank");
    for (const value of field.options)
      appendChoice(group, field, value, field.option_labels[value] ?? value);
    if (fieldHasValue(field) && !draft.replaceFields.includes(field.id))
      for (const input of group.querySelectorAll("input"))
        input.disabled = true;
    return group;
  } else {
    control =
      field.type === "textarea"
        ? document.createElement("textarea")
        : document.createElement("input");
    if (control instanceof HTMLInputElement) control.type = field.type;
    control.value = current;
    control.maxLength = 5000;
    const constraints = field.temporal_constraints ?? field.numeric_constraints;
    if (constraints) {
      if (constraints.minimum !== null) control.min = constraints.minimum;
      if (constraints.maximum !== null) control.max = constraints.maximum;
      control.step = constraints.step;
    }
  }
  control.addEventListener("input", async () => {
    draft.values[field.id] = control.value;
    draft.touched[field.id] = true;
    await saveDraft();
  });
  control.setAttribute("aria-label", field.label);
  if (field.history)
    control.setAttribute(
      "aria-label",
      `${field.history.label} · ${field.label}`,
    );
  if (fieldHasValue(field) && !draft.replaceFields.includes(field.id))
    control.disabled = true;
  return control;
}

function renderFields() {
  const container = element("fields");
  const wasOpen = container.querySelector("details")?.open ?? false;
  container.replaceChildren();
  if (!draft?.preparation) {
    element("prepared-actions").hidden = true;
    return;
  }
  element("prepared-actions").hidden = false;
  element("prepare").hidden = true;
  const completed = document.createElement("details");
  completed.className = "completed-fields";
  completed.open = wasOpen;
  const summary = document.createElement("summary");
  completed.append(summary);
  let completedCount = 0;
  for (const field of draft.snapshot.fields) {
    const prepared = preparedById(field.id);
    const row = document.createElement("div");
    row.className = "field-review";
    const label = document.createElement("label");
    label.textContent =
      (field.history ? `${field.history.label} · ` : "") +
      field.label +
      (field.required ? " · required" : "");
    row.append(label);
    if (field.type === "unsupported") {
      const reason = document.createElement("small");
      reason.textContent =
        field.unsupported_reason ||
        "Complete this control manually on the page.";
      row.append(reason);
    } else if (field.type === "file") {
      const input = document.createElement("select");
      input.id = `upload-${field.id}`;
      input.setAttribute(
        "aria-label",
        `Document to upload to ${field.label || field.id}`,
      );
      label.htmlFor = input.id;
      input.append(new Option("Leave this file field unchanged", ""));
      const resume = new Option("Attach selected résumé", "resume");
      resume.disabled = !draft.resumeVersionId;
      const letter = new Option("Attach selected cover letter", "cover-letter");
      letter.disabled = !draft.coverLetterVersionId;
      input.append(resume, letter);
      input.value = draft.uploadFields.includes(field.id)
        ? "resume"
        : draft.coverLetterUploadFields.includes(field.id)
          ? "cover-letter"
          : "";
      input.addEventListener("change", async () => {
        draft.uploadTouched[field.id] = true;
        draft.uploadFields = draft.uploadFields.filter((id) => id !== field.id);
        draft.coverLetterUploadFields = draft.coverLetterUploadFields.filter(
          (id) => id !== field.id,
        );
        if (input.value === "resume") draft.uploadFields.push(field.id);
        if (input.value === "cover-letter")
          draft.coverLetterUploadFields.push(field.id);
        await saveDraft();
      });
      row.append(input);
      if (fieldHasValue(field)) {
        const replacement = document.createElement("div");
        replacement.className = "choice";
        const replace = document.createElement("input");
        replace.type = "checkbox";
        replace.id = `replace-${field.id}`;
        replace.checked = draft.replaceFields.includes(field.id);
        input.disabled = !replace.checked;
        replace.addEventListener("change", async () => {
          draft.replacementTouched[field.id] = true;
          draft.replaceFields = replace.checked
            ? [...new Set([...draft.replaceFields, field.id])]
            : draft.replaceFields.filter((id) => id !== field.id);
          if (!replace.checked) {
            draft.uploadFields = draft.uploadFields.filter(
              (id) => id !== field.id,
            );
            draft.coverLetterUploadFields =
              draft.coverLetterUploadFields.filter((id) => id !== field.id);
            draft.uploadTouched[field.id] = true;
            input.value = "";
          }
          input.disabled = !replace.checked;
          await saveDraft();
        });
        const replaceLabel = document.createElement("label");
        replaceLabel.htmlFor = replace.id;
        replaceLabel.textContent = "Replace the file already on this page";
        replacement.append(replace, replaceLabel);
        row.append(replacement);
      }
    } else {
      const editor = editorFor(field);
      if (fieldHasValue(field)) {
        const choice = document.createElement("div");
        choice.className = "choice";
        const replace = document.createElement("input");
        replace.type = "checkbox";
        replace.id = `replace-${field.id}`;
        replace.checked = draft.replaceFields.includes(field.id);
        replace.addEventListener("change", async () => {
          draft.replacementTouched[field.id] = true;
          draft.replaceFields = replace.checked
            ? [...new Set([...draft.replaceFields, field.id])]
            : draft.replaceFields.filter((id) => id !== field.id);
          if ("disabled" in editor) editor.disabled = !replace.checked;
          else
            for (const input of editor.querySelectorAll("input"))
              input.disabled = !replace.checked;
          await saveDraft();
        });
        const replaceLabel = document.createElement("label");
        replaceLabel.htmlFor = replace.id;
        replaceLabel.textContent = "Replace the value already on this page";
        choice.append(replace, replaceLabel);
        row.append(choice);
      }
      row.append(editor);
    }
    if (prepared?.reason) {
      const hint = document.createElement("small");
      hint.textContent = prepared.reason;
      row.append(hint);
    }
    if (fieldHasValue(field)) {
      completedCount += 1;
      completed.append(row);
    } else container.append(row);
  }
  if (completedCount) {
    summary.textContent = `${completedCount} filled or existing fields`;
    container.append(completed);
  }
}

async function loadResumes() {
  const [resumes, letters] = await Promise.all([
    api("device/resumes").then(validResumes),
    api("device/cover-letters").then(validResumes),
  ]);
  if (draft) draft.resumes = resumes;
  if (draft?.resumeVersionId !== undefined)
    resumeChoice = draft.resumeVersionId;
  if (resumeChoice === undefined) resumeChoice = resumes.default_version_id;
  if (draft && draft.resumeVersionId === undefined)
    draft.resumeVersionId = resumeChoice;
  const select = element("resume");
  select.replaceChildren(new Option("No resume selected", ""));
  for (const resume of resumes.items)
    select.append(
      new Option(
        `${resume.title} · v${resume.version} · ${resume.filename}`,
        resume.version_id,
      ),
    );
  select.value = resumeChoice ?? "";
  if (draft?.coverLetterVersionId !== undefined)
    coverLetterChoice = draft.coverLetterVersionId;
  coverLetterChoice ??= null;
  if (draft && draft.coverLetterVersionId === undefined)
    draft.coverLetterVersionId = coverLetterChoice;
  const letterSelect = element("cover-letter");
  letterSelect.replaceChildren(new Option("No cover letter selected", ""));
  for (const letter of letters.items)
    letterSelect.append(
      new Option(
        `${letter.title} · v${letter.version} · ${letter.filename}`,
        letter.version_id,
      ),
    );
  if (
    coverLetterChoice &&
    !letters.items.some((item) => item.version_id === coverLetterChoice)
  ) {
    const unavailable = new Option(
      "Selected cover letter unavailable — choose another",
      coverLetterChoice,
    );
    unavailable.disabled = true;
    letterSelect.append(unavailable);
  }
  letterSelect.value = coverLetterChoice ?? "";
  syncAutofillControls();
  if (draft) await saveDraft();
}

function mergePreparation(preparation) {
  draft.preparation = preparation;
  draft.values ??= {};
  draft.touched ??= {};
  draft.replacementTouched ??= {};
  draft.uploadTouched ??= {};
  const serverReplacements = new Set(preparation.replace_fields ?? []);
  const localReplacements = new Set(draft.replaceFields ?? []);
  const serverUploads = new Set(preparation.upload_fields ?? []);
  const localUploads = new Set(draft.uploadFields ?? []);
  const serverLetters = new Set(preparation.cover_letter_upload_fields ?? []);
  const localLetters = new Set(draft.coverLetterUploadFields ?? []);
  draft.replaceFields = draft.snapshot.fields
    .filter((field) =>
      draft.replacementTouched[field.id]
        ? localReplacements.has(field.id)
        : serverReplacements.has(field.id),
    )
    .map((field) => field.id);
  draft.uploadFields = draft.snapshot.fields
    .filter((field) =>
      draft.uploadTouched[field.id]
        ? localUploads.has(field.id)
        : serverUploads.has(field.id),
    )
    .map((field) => field.id);
  draft.coverLetterUploadFields = draft.snapshot.fields
    .filter((field) =>
      draft.uploadTouched[field.id]
        ? localLetters.has(field.id)
        : serverLetters.has(field.id),
    )
    .map((field) => field.id);
  for (const prepared of preparation.fields) {
    if (!draft.touched[prepared.field_id]) {
      if (prepared.value !== null)
        draft.values[prepared.field_id] = prepared.value;
      else delete draft.values[prepared.field_id];
    }
  }
  if (preparation.resume?.version_id && !draft.resumeTouched)
    draft.resumeVersionId = preparation.resume.version_id;
  element("resume").value = draft.resumeVersionId ?? "";
  if (!draft.coverLetterTouched)
    draft.coverLetterVersionId = preparation.cover_letter?.version_id ?? null;
  element("cover-letter").value = draft.coverLetterVersionId ?? "";
  element("manage-letters").href =
    `http://localhost:3001/applications?application=${encodeURIComponent(preparation.task_id)}`;
  element("conversation").href =
    `http://localhost:3001/tasks?record=${encodeURIComponent(preparation.task_id)}&tab=conversation`;
  element("conversation").hidden = false;
  renderFields();
}

function scheduleGenerationPoll() {
  clearTimeout(generationTimer);
  if (generationPending()) generationTimer = setTimeout(pollGeneration, 1000);
}

async function pollGeneration() {
  if (!draft?.preparation) return;
  try {
    const generation = validGeneration(
      await api(`device/preparations/${draft.preparation.id}/generation`),
    );
    draft.generation = generation;
    if (generation.state === "completed") {
      const latest = validPreparation(
        await api(`device/preparations/${draft.preparation.id}`),
      );
      mergePreparation(latest);
      message("Grounded drafts are ready. Your local edits were kept.");
    } else if (generation.state === "failed") {
      message(
        `Draft generation failed${generation.error_code ? ` (${generation.error_code})` : ""}. Review the conversation or try again.`,
      );
    } else if (generation.state === "cancelled") {
      message("Draft generation was cancelled. Your local edits were kept.");
    }
    await saveDraft();
    renderGeneration();
    scheduleGenerationPoll();
  } catch (error) {
    message(error.message ?? "Generation status is temporarily unavailable.");
    clearTimeout(generationTimer);
    if (draft?.generation?.run_id)
      generationTimer = setTimeout(pollGeneration, 2000);
  }
}

async function renderDraft() {
  element("preparation").hidden = !draft?.snapshot;
  element("application-title").textContent =
    draft?.snapshot?.title || "Your next opportunity.";
  element("page-location").hidden = !draft?.snapshot;
  element("page-location").textContent = draft?.snapshot
    ? new URL(draft.snapshot.page_url).hostname
    : "";
  if (!draft?.snapshot) {
    await loadResumes();
    return;
  }
  draft.values ??= {};
  draft.touched ??= {};
  draft.replacementTouched ??= {};
  draft.uploadTouched ??= {};
  draft.replaceFields ??= [];
  draft.uploadFields ??= [];
  draft.coverLetterUploadFields ??= [];
  await loadResumes();
  if (draft.preparation) {
    element("conversation").href =
      `http://localhost:3001/tasks?record=${encodeURIComponent(draft.preparation.task_id)}&tab=conversation`;
    element("conversation").hidden = false;
  }
  renderFields();
  renderGeneration();
  if (draft.lastAttempt?.result) {
    const card = document.createElement("article");
    card.className = "proposal";
    renderResult(card, draft.lastAttempt.command, draft.lastAttempt.result);
    element("proposals").replaceChildren(card);
    message(draft.lastAttempt.result.message);
  }
  syncAutofillControls();
  if (draft.preparation) void pollGeneration();
}

function reviewedFields() {
  return Object.fromEntries(
    draft.snapshot.fields
      .filter((field) => !["file", "unsupported"].includes(field.type))
      .filter(
        (field) =>
          field.value_state !== "present" ||
          draft.replaceFields.includes(field.id),
      )
      .filter((field) => (draft.values[field.id] ?? "") !== "")
      .map((field) => [field.id, draft.values[field.id]]),
  );
}

function revisionFields() {
  return Object.fromEntries(
    draft.snapshot.fields
      .filter((field) => !["file", "unsupported"].includes(field.type))
      .map((field) => [
        field.id,
        field.value_state === "present" &&
        !draft.replaceFields.includes(field.id)
          ? ""
          : (draft.values[field.id] ?? ""),
      ]),
  );
}

function reviewedUploads() {
  return Object.fromEntries([
    ...(draft.resumeVersionId
      ? draft.uploadFields.map((id) => [id, draft.resumeVersionId])
      : []),
    ...(draft.coverLetterVersionId
      ? draft.coverLetterUploadFields.map((id) => [
          id,
          draft.coverLetterVersionId,
        ])
      : []),
  ]);
}

async function digestHex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function base64(bytes) {
  let result = "";
  const chunk = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunk)
    result += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
  return btoa(result);
}

async function reviewedFiles(command) {
  const files = {};
  for (const [fieldId, metadata] of Object.entries(command.upload_files)) {
    const bytes = await apiBytes(
      `device/commands/${command.id}/files/${encodeURIComponent(fieldId)}`,
    );
    if (
      bytes.length !== metadata.size_bytes ||
      (await digestHex(bytes)) !== metadata.sha256
    )
      throw new Error(
        `The exact reviewed file for ${fieldById(fieldId)?.label ?? fieldId} failed verification.`,
      );
    files[fieldId] = { ...metadata, data_base64: base64(bytes) };
  }
  return files;
}

function renderResult(card, command, result) {
  const list = document.createElement("ul");
  list.className = "result-list";
  for (const [fieldId, fieldResult] of Object.entries(
    result.field_results ?? {},
  )) {
    const item = document.createElement("li");
    const label =
      command.form_fields.find((field) => field.id === fieldId)?.label ??
      fieldId;
    item.textContent = `${label}: ${fieldResult.status}${fieldResult.detail ? ` — ${fieldResult.detail}` : ""}`;
    list.append(item);
  }
  card.append(list);
}

async function applyCommand(command, tab, card, apply) {
  if (
    draft?.lastAttempt?.command.id === command.id &&
    draft.lastAttempt.result
  ) {
    const result = draft.lastAttempt.result;
    await reportResult(command, result);
    renderResult(card, command, result);
    return result;
  }
  if (claimedCommands.has(command.id))
    throw new Error("This command was already claimed and will not replay.");
  validate(
    "ClaimResult",
    await api(`device/commands/${command.id}/claim`, {
      method: "POST",
      body: {},
    }),
  );
  claimedCommands.add(command.id);
  await chrome.storage.local.set({ claimedCommands: [...claimedCommands] });
  let result;
  try {
    const files = await reviewedFiles(command);
    result = validate(
      "ApplyResult",
      await chrome.tabs.sendMessage(tab.id, {
        version: 2,
        action: "apply",
        command: {
          snapshot_id: command.snapshot_id,
          page_url: command.page_url,
          fields: command.fields,
          uploads: command.uploads,
          replace_fields: command.replace_fields,
          preparation_version_id: command.preparation_version_id,
        },
        files,
      }),
    );
  } catch {
    result = {
      state: "outcome_unknown",
      field_results: Object.fromEntries(
        [...Object.keys(command.fields), ...Object.keys(command.uploads)].map(
          (id) => [
            id,
            {
              status: "outcome_unknown",
              detail: "Claimed; page or exact file became unavailable.",
            },
          ],
        ),
      ),
      message:
        "The claimed command had an uncertain outcome. Review the page; it will not replay.",
    };
  }
  if (draft) {
    draft.lastAttempt = { command, result };
    draft.needsRecapture = true;
    await saveDraft();
    renderFields();
  }
  try {
    await reportResult(command, result);
  } finally {
    apply?.remove();
  }

  renderResult(card, command, result);
  message(result.message);
  return result;
}

async function reportResult(command, result) {
  await api(`device/commands/${command.id}/result`, {
    method: "POST",
    key: draft ? receipt(`result-${command.id}`) : undefined,
    body: { state: result.state, field_results: result.field_results },
  });
}

function renderProposal(command, tab) {
  const card = document.createElement("article");
  card.className = "proposal";
  const heading = document.createElement("h2");
  heading.textContent = `Review ${Object.keys(command.fields).length} answers and ${Object.keys(command.uploads).length} files`;
  card.append(heading);
  for (const [id, value] of Object.entries(command.fields)) {
    const row = document.createElement("div");
    row.className = "answer";
    const label = document.createElement("strong");
    label.textContent =
      command.form_fields.find((field) => field.id === id)?.label ?? id;
    const content = document.createElement("span");
    content.textContent = value;
    row.append(label, content);
    card.append(row);
  }
  for (const [id, file] of Object.entries(command.upload_files)) {
    const row = document.createElement("div");
    row.className = "answer";
    const label = document.createElement("strong");
    label.textContent =
      command.form_fields.find((field) => field.id === id)?.label ?? id;
    const content = document.createElement("span");
    content.textContent = `${file.filename} · ${file.size_bytes} bytes · exact version ${file.version_id}`;
    row.append(label, content);
    card.append(row);
  }
  const apply = document.createElement("button");
  apply.textContent = "Apply reviewed values and files";
  apply.addEventListener("click", () =>
    action(apply, async () => {
      return applyCommand(command, tab, card, apply);
    }),
  );
  const note = document.createElement("small");
  note.textContent =
    "Applies only this reviewed proposal. Next and Submit stay manual.";
  card.append(apply, note);
  return card;
}

element("pair-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.submitter, async () => {
    const result = await api("pairings/exchange", {
      body: { code: element("code").value.trim() },
      unauthenticated: true,
    });
    validate("PairCredentials", result);
    connection = { ...result, base: element("api-url").value };
    await chrome.storage.local.set({ connection });
    element("code").value = "";
    renderConnection();
    await renderDraft();
    message("Connected. Open a form to get started.");
  });
});

element("disconnect").addEventListener("click", async () => {
  clearTimeout(generationTimer);
  await chrome.storage.local.remove([
    "connection",
    "applicationDraft",
    "claimedCommands",
  ]);
  connection = undefined;
  draft = undefined;
  claimedCommands = new Set();
  renderConnection();
  element("preparation").hidden = true;
  message(
    "Disconnected here. Revoke the device in your workspace to invalidate its credential.",
  );
});

async function agentBrowserStructure(tab) {
  const nonce = crypto.randomUUID();
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (value) =>
      document.documentElement.setAttribute(
        "data-command-center-inspection",
        value,
      ),
    args: [nonce],
  });
  try {
    const reply = await chrome.runtime.sendNativeMessage(
      "com.commandcenter.agent_browser",
      {
        action: "inspect",
        url: tab.url,
        nonce,
      },
    );
    if (!reply?.ok)
      throw new Error(
        reply?.error ?? "AgentBrowser could not inspect this page.",
      );
    const structure = reply.structure;
    const url = new URL(tab.url);
    if (
      structure?.engine !== "agent-browser" ||
      structure.page_url !== url.origin + url.pathname ||
      typeof structure.title !== "string" ||
      !Array.isArray(structure.controls) ||
      structure.controls.length > 100 ||
      !structure.controls.length
    )
      throw new Error(
        "AgentBrowser found no usable form structure on this page.",
      );
    element("reader-status").textContent =
      `Read by AgentBrowser · ${structure.controls.length} controls`;
    return structure;
  } catch (error) {
    if (
      /native messaging|native host|specified native|receiving end/i.test(
        error.message ?? "",
      )
    )
      throw new Error(
        "Set up AgentBrowser with make companion-setup, then make companion-browser. Direct browser is also available above.",
      );
    throw error;
  } finally {
    await chrome.scripting
      .executeScript({
        target: { tabId: tab.id },
        func: (value) => {
          if (
            document.documentElement.getAttribute(
              "data-command-center-inspection",
            ) === value
          )
            document.documentElement.removeAttribute(
              "data-command-center-inspection",
            );
        },
        args: [nonce],
      })
      .catch(() => {});
  }
}

async function inspectForm(useReader = false) {
  const tab = await activeTab();
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["contracts.js", "content.js"],
  });
  const response = await chrome.tabs.sendMessage(tab.id, {
    version: 2,
    action: "inspect",
  });
  if (response?.state === "rejected" && typeof response.message === "string")
    throw new Error(response.message.slice(0, 300));
  const snapshot = validate("SnapshotCreate", response);
  if (!snapshot.fields.some((field) => field.type !== "unsupported")) {
    const workday = /(^|\.)myworkdayjobs\.com$/.test(new URL(tab.url).hostname);
    throw new Error(
      workday
        ? "Open the Workday application step after signing in, then share the form again. This page is not ready for filling."
        : "No supported application controls were found. Open the application step, then share again.",
    );
  }
  const structure =
    useReader && element("page-reader").value === "agent-browser"
      ? await agentBrowserStructure(tab)
      : null;
  if (structure) snapshot.title = structure.title.slice(0, 300);
  return { tab, snapshot, structure };
}

element("share").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    clearTimeout(generationTimer);
    const { tab, snapshot } = await inspectForm();
    await api("snapshots", { method: "POST", body: snapshot });
    draft = {
      snapshot,
      pageUrl: tab.url,
      values: {},
      touched: {},
      replacementTouched: {},
      uploadTouched: {},
      replaceFields: [],
      uploadFields: [],
      coverLetterUploadFields: [],
      receipts: {},
    };
    await renderDraft();
    element("prepare").hidden = false;
    message(
      `${snapshot.fields.length} controls shared without their existing values. Choose an exact resume, then prepare.`,
    );
  }),
);

function autofillStatus(text) {
  element("autofill-status").textContent = text;
}

element("autofill").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    autofillBusy = true;
    syncAutofillControls();
    try {
      // Keep the exact unfinished operation across popup closure and lost replies.
      if (!draft?.autofill || draft.autofill.stage === "done") {
        autofillStatus("Reading this application…");
        const { tab, snapshot, structure } = await inspectForm(true);
        clearTimeout(generationTimer);
        const previousId =
          draft?.preparation &&
          (draft.pageUrl ?? draft.autofill?.pageUrl) === tab.url
            ? draft.preparation.id
            : null;
        draft = {
          snapshot,
          pageUrl: tab.url,
          structure,
          values: {},
          touched: {},
          replacementTouched: {},
          uploadTouched: {},
          replaceFields: [],
          uploadFields: [],
          coverLetterUploadFields: [],
          receipts: {},
          resumeVersionId: resumeChoice ?? null,
          coverLetterVersionId: coverLetterChoice ?? null,
          autofill: {
            stage: "capture",
            previousId,
            tabId: tab.id,
            pageUrl: tab.url,
            resumeVersionId: resumeChoice ?? null,
            coverLetterVersionId: coverLetterChoice ?? null,
            attachResume: element("auto-resume").checked,
            attachCoverLetter: element("auto-cover-letter").checked,
          },
        };
        element("application-title").textContent =
          snapshot.title || "Application";
        element("page-location").textContent = new URL(
          snapshot.page_url,
        ).hostname;
        element("page-location").hidden = false;
        await saveDraft();
      }
      const operation = draft.autofill;
      if (operation.stage === "uncertain")
        throw new Error(
          "Check the application page after the uncertain fill. Discard this draft before starting again.",
        );
      const tab = await activeTab();
      if (tab.id !== operation.tabId || tab.url !== operation.pageUrl)
        throw new Error(
          "Return to the captured application tab, or discard this draft and start again.",
        );
      if (operation.stage === "capture") {
        await api("snapshots", {
          method: "POST",
          key: receipt("auto-capture"),
          body: draft.snapshot,
        });
        operation.stage = "prepare";
        await saveDraft();
      }
      if (operation.stage === "prepare") {
        autofillStatus("Matching your profile to the fields…");
        const prepared = validPreparation(
          await api(`device/snapshots/${draft.snapshot.id}/preparations`, {
            method: "POST",
            key: receipt("auto-prepare"),
            body: {
              opportunity_id: null,
              resume_version_id: operation.resumeVersionId,
              cover_letter_version_id: operation.coverLetterVersionId ?? null,
              continue_preparation_id: operation.previousId,
              job_context: draft.structure?.job_context ?? null,
            },
          }),
        );
        mergePreparation(prepared);
        operation.baseVersionId = prepared.version_id;
        operation.stage = "authorize";
        await saveDraft();
      }
      if (operation.stage === "authorize") {
        const prepared = validPreparation(
          await api(`device/preparations/${draft.preparation.id}/autofill`, {
            method: "POST",
            key: receipt("auto-authorize"),
            body: {
              expected_version_id: operation.baseVersionId,
              attach_resume: operation.attachResume,
              attach_cover_letter: operation.attachCoverLetter ?? false,
            },
          }),
        );
        operation.prepared = prepared;
        mergePreparation(prepared);
        operation.stage = "command";
        await saveDraft();
      }
      element("preparation").hidden = false;
      if (operation.stage === "command") {
        const prepared = operation.prepared;
        const fields = Object.fromEntries(
          prepared.fields
            .filter(
              (field) => field.status === "suggested" && field.value !== null,
            )
            .map((field) => [field.field_id, field.value]),
        );
        const uploads = Object.fromEntries([
          ...prepared.upload_fields.map((id) => [
            id,
            prepared.resume.version_id,
          ]),
          ...(prepared.cover_letter_upload_fields ?? []).map((id) => [
            id,
            prepared.cover_letter.version_id,
          ]),
        ]);
        if (!Object.keys(fields).length && !Object.keys(uploads).length) {
          operation.stage = "done";
          await saveDraft();
          autofillStatus(
            "No approved answers match yet. Complete the questions below, or add approved profile details in your workspace.",
          );
          return;
        }
        operation.command = validate("PendingCommands", [
          await api("device/commands", {
            method: "POST",
            key: receipt("auto-command"),
            body: {
              snapshot_id: draft.snapshot.id,
              fields,
              uploads,
              replace_fields: [],
              preparation_version_id: prepared.version_id,
            },
          }),
        ])[0];
        operation.stage = "apply";
        await saveDraft();
      }
      if (operation.stage === "apply") {
        if (
          claimedCommands.has(operation.command.id) &&
          !draft.lastAttempt?.result
        )
          throw new Error(
            "Autofill was already attempted. Check the application page before sharing it again; the previous fill will not replay.",
          );
        autofillStatus("Filling available answers and selected documents…");
        const card = document.createElement("article");
        card.className = "proposal";
        element("proposals").replaceChildren(card);
        const result = await applyCommand(operation.command, tab, card);
        operation.stage =
          result.state === "outcome_unknown" ? "uncertain" : "done";
        await saveDraft();
        const unanswered = operation.prepared.fields.filter(
          (field) =>
            ["needs_input", "unsupported"].includes(field.status) &&
            !operation.prepared.upload_fields.includes(field.field_id) &&
            !(operation.prepared.cover_letter_upload_fields ?? []).includes(
              field.field_id,
            ),
        ).length;
        const outcomes = Object.values(result.field_results);
        const filled = outcomes.filter((field) =>
          ["filled", "uploaded"].includes(field.status),
        ).length;
        const failed = outcomes.filter(
          (field) =>
            !["filled", "uploaded", "preserved"].includes(field.status),
        ).length;
        const summary = [`${filled} filled or attached.`];
        if (failed) summary.push(`${failed} could not be filled.`);
        if (unanswered)
          summary.push(
            `${unanswered} ${unanswered === 1 ? "question needs" : "questions need"} your input.`,
          );
        summary.push("Review the page before Next or Submit.");
        autofillStatus(
          !["applied", "partial"].includes(result.state)
            ? result.message
            : summary.join(" "),
        );
      }
    } catch (error) {
      autofillStatus(
        "Autofill needs attention. Your progress is saved; see the message below.",
      );
      throw error;
    } finally {
      autofillBusy = false;
      syncAutofillControls();
    }
  }),
);

element("resume").addEventListener("change", async (event) => {
  resumeChoice = event.currentTarget.value || null;
  if (!draft) return;
  draft.resumeVersionId = resumeChoice;
  draft.resumeTouched = true;
  if (!draft.resumeVersionId) draft.uploadFields = [];
  await saveDraft();
  renderFields();
});

element("cover-letter").addEventListener("change", async (event) => {
  coverLetterChoice = event.currentTarget.value || null;
  syncAutofillControls();
  if (!draft) return;
  draft.coverLetterVersionId = coverLetterChoice;
  draft.coverLetterTouched = true;
  draft.coverLetterUploadFields = [];
  for (const field of draft.snapshot.fields.filter(
    (field) => field.type === "file",
  )) {
    draft.uploadTouched[field.id] = true;
  }
  await saveDraft();
  renderFields();
});

element("prepare").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    const preparation = validPreparation(
      await api(`device/snapshots/${draft.snapshot.id}/preparations`, {
        method: "POST",
        key: receipt("prepare"),
        body: {
          opportunity_id: null,
          resume_version_id: draft.resumeVersionId ?? null,
          cover_letter_version_id: draft.coverLetterVersionId ?? null,
        },
      }),
    );
    mergePreparation(preparation);
    clearReceipt("prepare");
    await saveDraft();
    message(
      "Answers prepared. Review every value and choose each document upload explicitly.",
    );
  }),
);

element("reload-preparation").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    mergePreparation(
      validPreparation(
        await api(`device/preparations/${draft.preparation.id}`),
      ),
    );
    await saveDraft();
    message("Draft refreshed. Your local edits were kept.");
  }),
);

element("generate").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    if (generationPending())
      throw new Error("Generation is already in progress.");
    const result = await api(
      `device/preparations/${draft.preparation.id}/generate`,
      {
        method: "POST",
        key: receipt("generate"),
        body: {},
      },
    );
    draft.generation = {
      conversation_id: result.conversation_id,
      run_id: result.run_id,
      state: "queued",
      error_code: null,
    };
    clearReceipt("generate");
    await saveDraft();
    renderGeneration();
    scheduleGenerationPoll();
    message(
      "Grounded draft generation queued. This popup will refresh it when ready.",
    );
  }),
);

async function refreshForReviewedFill() {
  if (!draft.needsRecapture && !draft.recapture) return;
  if (!draft.recapture) {
    const { tab, snapshot } = await inspectForm();
    const structure = (fields) =>
      JSON.stringify(fields.map(({ value_state, ...field }) => field));
    if (
      tab.url !== (draft.pageUrl ?? draft.autofill?.pageUrl) ||
      snapshot.page_url !== draft.snapshot.page_url ||
      structure(snapshot.fields) !== structure(draft.snapshot.fields)
    )
      throw new Error(
        "The application fields changed. Your answers are saved; start a fresh capture for this step.",
      );
    draft.recapture = {
      snapshot,
      previousId: draft.preparation.id,
      stage: "capture",
    };
    await saveDraft();
  }
  const capture = draft.recapture;
  if (capture.stage === "capture") {
    await api("snapshots", {
      method: "POST",
      key: receipt("review-capture"),
      body: capture.snapshot,
    });
    capture.stage = "prepare";
    await saveDraft();
  }
  const preparation = validPreparation(
    await api(`device/snapshots/${capture.snapshot.id}/preparations`, {
      method: "POST",
      key: receipt("review-prepare"),
      body: {
        opportunity_id: null,
        resume_version_id: draft.resumeVersionId ?? null,
        cover_letter_version_id: draft.coverLetterVersionId ?? null,
        continue_preparation_id: capture.previousId,
      },
    }),
  );
  draft.snapshot = capture.snapshot;
  for (const key of ["uploadFields", "coverLetterUploadFields"]) {
    draft[key] = (draft[key] ?? []).filter((id) =>
      draft.snapshot.fields.some(
        (field) =>
          field.id === id &&
          (field.value_state === "empty" || draft.replaceFields.includes(id)),
      ),
    );
  }
  draft.preparation = preparation;
  draft.recapture = undefined;
  draft.needsRecapture = false;
  draft.savedSignature = undefined;
  draft.savedVersionId = undefined;
  for (const kind of [
    "review-capture",
    "review-prepare",
    "revision",
    "command",
  ])
    clearReceipt(kind);
  await saveDraft();
  renderFields();
}

element("propose").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    autofillStatus("");
    if (generationPending())
      throw new Error(
        "Wait for draft generation to finish before saving a review.",
      );
    if (draft.reviewedCommand) {
      const card = document.createElement("article");
      card.className = "proposal";
      element("proposals").replaceChildren(card);
      await applyCommand(draft.reviewedCommand, await activeTab(), card);
      draft.reviewedCommand = undefined;
      await saveDraft();
      return;
    }
    await refreshForReviewedFill();
    const fields = reviewedFields();
    const reviewedRevision = revisionFields();
    const uploads = reviewedUploads();
    if (!Object.keys(fields).length && !Object.keys(uploads).length)
      throw new Error(
        "Review at least one answer or select one document upload.",
      );
    const requested = new Set([
      ...Object.keys(fields),
      ...Object.keys(uploads),
    ]);
    const replaceFields = draft.replaceFields.filter((fieldId) =>
      requested.has(fieldId),
    );
    const reviewSignature = JSON.stringify({
      fields: reviewedRevision,
      resume_version_id: draft.resumeVersionId ?? null,
      cover_letter_version_id: draft.coverLetterVersionId ?? null,
      replace_fields: replaceFields,
      upload_fields: draft.uploadFields,
      cover_letter_upload_fields: draft.coverLetterUploadFields,
    });
    let saved = draft.preparation;
    if (
      draft.savedSignature !== reviewSignature ||
      draft.savedVersionId !== saved.version_id
    ) {
      saved = validPreparation(
        await api(`device/preparations/${draft.preparation.id}/revisions`, {
          method: "POST",
          key: receipt("revision"),
          body: {
            expected_version_id: draft.preparation.version_id,
            fields: reviewedRevision,
            resume_version_id: draft.resumeVersionId ?? null,
            cover_letter_version_id: draft.coverLetterVersionId ?? null,
            replace_fields: replaceFields,
            upload_fields: draft.uploadFields,
            cover_letter_upload_fields: draft.coverLetterUploadFields,
            remember_fields: [],
          },
        }),
      );
      mergePreparation(saved);
      clearReceipt("revision");
      draft.savedSignature = reviewSignature;
      draft.savedVersionId = saved.version_id;
      await saveDraft();
    }
    const command = validate("PendingCommands", [
      await api("device/commands", {
        method: "POST",
        key: receipt("command"),
        body: {
          snapshot_id: draft.snapshot.id,
          fields,
          uploads,
          replace_fields: replaceFields,
          preparation_version_id: saved.version_id,
        },
      }),
    ])[0];
    draft.reviewedCommand = command;
    clearReceipt("command");
    await saveDraft();
    const tab = await activeTab();
    const card = document.createElement("article");
    card.className = "proposal";
    element("proposals").replaceChildren(card);
    await applyCommand(command, tab, card);
    draft.reviewedCommand = undefined;
    await saveDraft();
  }),
);

element("discard-draft").addEventListener("click", async () => {
  clearTimeout(generationTimer);
  draft = undefined;
  await chrome.storage.local.remove("applicationDraft");
  element("preparation").hidden = true;
  element("application-title").textContent = "Your next opportunity.";
  element("page-location").hidden = true;
  element("proposals").replaceChildren();
  autofillStatus("");
  syncAutofillControls();
  message(
    "Ready for a fresh capture. Saved application tasks remain in your workspace.",
  );
});

element("refresh").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    const tab = await activeTab();
    const target = new URL(tab.url);
    const currentPage = target.origin + target.pathname;
    const commands = validate(
      "PendingCommands",
      await api("device/commands"),
    ).filter(
      (command) =>
        command.page_url === currentPage && !claimedCommands.has(command.id),
    );
    element("proposals").replaceChildren(
      ...commands.map((command) => renderProposal(command, tab)),
    );
    message(
      commands.length
        ? "Review every answer and exact file before applying."
        : "No pending proposals for this page.",
    );
  }),
);

renderConnection();
if (connection) {
  try {
    await renderDraft();
  } catch (error) {
    message(
      error.message ?? "Workspace unavailable. Reopen the companion to retry.",
    );
  }
}
