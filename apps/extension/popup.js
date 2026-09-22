const contracts = globalThis.CommandCenterContracts;
const element = (id) => document.getElementById(id);
const allowedApis = new Set(["http://localhost:8000", "http://127.0.0.1:8000"]);
await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
const stored = await chrome.storage.local.get([
  "connection",
  "applicationDraft",
  "claimedCommands",
]);
let connection = stored.connection;
let draft = stored.applicationDraft;
let claimedCommands = new Set(stored.claimedCommands ?? []);
let generationTimer;

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
  button.disabled = true;
  try {
    await work();
  } catch (error) {
    message(error.message ?? "Something went wrong. Please try again.");
  } finally {
    button.disabled = false;
    if (draft?.preparation) renderGeneration();
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

function editorFor(field, prepared) {
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
    if (
      prepared?.status === "preserved" &&
      !draft.replaceFields.includes(field.id)
    )
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
    if (field.type === "number" && field.numeric_constraints) {
      if (field.numeric_constraints.minimum !== null)
        control.min = field.numeric_constraints.minimum;
      if (field.numeric_constraints.maximum !== null)
        control.max = field.numeric_constraints.maximum;
      control.step = field.numeric_constraints.step;
    }
  }
  control.addEventListener("input", async () => {
    draft.values[field.id] = control.value;
    draft.touched[field.id] = true;
    await saveDraft();
  });
  control.setAttribute("aria-label", field.label);
  if (
    prepared?.status === "preserved" &&
    !draft.replaceFields.includes(field.id)
  )
    control.disabled = true;
  return control;
}

function renderFields() {
  const container = element("fields");
  container.replaceChildren();
  if (!draft?.preparation) {
    element("prepared-actions").hidden = true;
    return;
  }
  element("prepared-actions").hidden = false;
  element("prepare").hidden = true;
  for (const field of draft.snapshot.fields) {
    const prepared = preparedById(field.id);
    const row = document.createElement("div");
    row.className = "field-review";
    const label = document.createElement("label");
    label.textContent = field.label + (field.required ? " · required" : "");
    row.append(label);
    if (field.type === "unsupported") {
      const reason = document.createElement("small");
      reason.textContent =
        field.unsupported_reason ||
        "Complete this control manually on the page.";
      row.append(reason);
    } else if (field.type === "file") {
      const choice = document.createElement("div");
      choice.className = "choice";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.id = `upload-${field.id}`;
      input.checked = draft.uploadFields.includes(field.id);
      input.disabled = !draft.resumeVersionId;
      input.addEventListener("change", async () => {
        draft.uploadTouched[field.id] = true;
        draft.uploadFields = input.checked
          ? [...new Set([...draft.uploadFields, field.id])]
          : draft.uploadFields.filter((id) => id !== field.id);
        await saveDraft();
      });
      const choiceLabel = document.createElement("label");
      choiceLabel.htmlFor = input.id;
      choiceLabel.textContent = draft.resumeVersionId
        ? "Attach the selected exact resume"
        : "Select a resume version first";
      choice.append(input, choiceLabel);
      row.append(choice);
      if (field.value_state === "present") {
        const replacement = document.createElement("div");
        replacement.className = "choice";
        const replace = document.createElement("input");
        replace.type = "checkbox";
        replace.id = `replace-${field.id}`;
        replace.checked = draft.replaceFields.includes(field.id);
        input.disabled ||= !replace.checked;
        replace.addEventListener("change", async () => {
          draft.replacementTouched[field.id] = true;
          draft.replaceFields = replace.checked
            ? [...new Set([...draft.replaceFields, field.id])]
            : draft.replaceFields.filter((id) => id !== field.id);
          if (!replace.checked) {
            draft.uploadFields = draft.uploadFields.filter(
              (id) => id !== field.id,
            );
            input.checked = false;
          }
          input.disabled = !draft.resumeVersionId || !replace.checked;
          await saveDraft();
        });
        const replaceLabel = document.createElement("label");
        replaceLabel.htmlFor = replace.id;
        replaceLabel.textContent = "Replace the file already on this page";
        replacement.append(replace, replaceLabel);
        row.append(replacement);
      }
    } else {
      const editor = editorFor(field, prepared);
      if (prepared?.status === "preserved") {
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
    container.append(row);
  }
}

async function loadResumes() {
  const resumes = validResumes(await api("device/resumes"));
  draft.resumes = resumes;
  if (draft.resumeVersionId === undefined)
    draft.resumeVersionId = resumes.default_version_id;
  const select = element("resume");
  select.replaceChildren(new Option("No resume selected", ""));
  for (const resume of resumes.items)
    select.append(
      new Option(
        `${resume.title} · v${resume.version} · ${resume.filename}`,
        resume.version_id,
      ),
    );
  select.value = draft.resumeVersionId ?? "";
  await saveDraft();
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
  for (const prepared of preparation.fields) {
    if (!draft.touched[prepared.field_id] && prepared.value !== null)
      draft.values[prepared.field_id] = prepared.value;
  }
  if (preparation.resume?.version_id && !draft.resumeTouched)
    draft.resumeVersionId = preparation.resume.version_id;
  element("resume").value = draft.resumeVersionId ?? "";
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
  if (!draft?.snapshot) return;
  draft.values ??= {};
  draft.touched ??= {};
  draft.replacementTouched ??= {};
  draft.uploadTouched ??= {};
  draft.replaceFields ??= [];
  draft.uploadFields ??= [];
  await loadResumes();
  if (draft.preparation) {
    element("conversation").href =
      `http://localhost:3001/tasks?record=${encodeURIComponent(draft.preparation.task_id)}&tab=conversation`;
    element("conversation").hidden = false;
  }
  renderFields();
  renderGeneration();
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
  if (!draft.resumeVersionId) return {};
  return Object.fromEntries(
    draft.uploadFields.map((fieldId) => [fieldId, draft.resumeVersionId]),
  );
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
      if (claimedCommands.has(command.id))
        throw new Error(
          "This command was already claimed and will not replay.",
        );
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
            [
              ...Object.keys(command.fields),
              ...Object.keys(command.uploads),
            ].map((id) => [
              id,
              {
                status: "outcome_unknown",
                detail: "Claimed; page or exact file became unavailable.",
              },
            ]),
          ),
          message:
            "The claimed command had an uncertain outcome. Review the page; it will not replay.",
        };
      }
      try {
        await api(`device/commands/${command.id}/result`, {
          method: "POST",
          body: { state: result.state, field_results: result.field_results },
        });
      } finally {
        apply.remove();
      }
      renderResult(card, command, result);
      message(result.message);
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

element("share").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    clearTimeout(generationTimer);
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
      const workday = /(^|\.)myworkdayjobs\.com$/.test(
        new URL(tab.url).hostname,
      );
      throw new Error(
        workday
          ? "Open the Workday application step after signing in, then share the form again. This page is not ready for filling."
          : "No supported application controls were found. Open the application step, then share again.",
      );
    }
    await api("snapshots", { method: "POST", body: snapshot });
    draft = {
      snapshot,
      values: {},
      touched: {},
      replacementTouched: {},
      uploadTouched: {},
      replaceFields: [],
      uploadFields: [],
      receipts: {},
    };
    await renderDraft();
    element("prepare").hidden = false;
    message(
      `${snapshot.fields.length} controls shared without their existing values. Choose an exact resume, then prepare.`,
    );
  }),
);

element("resume").addEventListener("change", async (event) => {
  draft.resumeVersionId = event.currentTarget.value || null;
  draft.resumeTouched = true;
  if (!draft.resumeVersionId) draft.uploadFields = [];
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
        },
      }),
    );
    mergePreparation(preparation);
    clearReceipt("prepare");
    await saveDraft();
    message(
      "Answers prepared. Review every value and choose each resume upload explicitly.",
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

element("propose").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    if (generationPending())
      throw new Error(
        "Wait for draft generation to finish before saving a review.",
      );
    const fields = reviewedFields();
    const reviewedRevision = revisionFields();
    const uploads = reviewedUploads();
    if (!Object.keys(fields).length && !Object.keys(uploads).length)
      throw new Error(
        "Review at least one answer or select one resume upload.",
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
      replace_fields: replaceFields,
      upload_fields: draft.uploadFields,
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
            replace_fields: replaceFields,
            upload_fields: draft.uploadFields,
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
    });
    clearReceipt("command");
    await saveDraft();
    message(
      "Reviewed proposal saved. Check fill proposals here before applying it.",
    );
  }),
);

element("discard-draft").addEventListener("click", async () => {
  clearTimeout(generationTimer);
  draft = undefined;
  await chrome.storage.local.remove("applicationDraft");
  element("preparation").hidden = true;
  message("Local draft discarded. Share the page again when ready.");
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
if (connection) await renderDraft();
