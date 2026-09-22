const contracts = globalThis.CommandCenterContracts;
function validate(name, value) {
  if (!contracts[name](value))
    throw new Error(
      "Invalid companion response. Reload the extension and try again.",
    );
  return value;
}
const element = (id) => document.getElementById(id);
const allowedApis = new Set(["http://localhost:8000", "http://127.0.0.1:8000"]);
await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
let connection = (await chrome.storage.local.get("connection")).connection;
const message = (text) => {
  element("message").textContent = text;
};
function renderConnection() {
  element("pairing").hidden = !!connection;
  element("connected").hidden = !connection;
}
async function api(path, body, unauthenticated = false) {
  const base = unauthenticated ? element("api-url").value : connection?.base;
  if (!allowedApis.has(base))
    throw new Error("Choose a supported local API address.");
  const response = await fetch(`${base}/api/v1/browser/${path}`, {
    method: body === undefined ? "GET" : "POST",
    credentials: "omit",
    redirect: "error",
    signal: AbortSignal.timeout(15000),
    headers: {
      "Content-Type": "application/json",
      ...(unauthenticated
        ? {}
        : { Authorization: `Bearer ${connection.token}` }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "The request could not be completed.",
    );
  return result;
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
  }
}
element("pair-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.submitter, async () => {
    const result = await api(
      "pairings/exchange",
      { code: element("code").value.trim() },
      true,
    );
    validate("PairCredentials", result);
    connection = { ...result, base: element("api-url").value };
    await chrome.storage.local.set({ connection });
    element("code").value = "";
    renderConnection();
    message("Connected. Open a form to get started.");
  });
});
element("disconnect").addEventListener("click", async () => {
  await chrome.storage.local.remove("connection");
  connection = undefined;
  renderConnection();
  message(
    "Disconnected here. Revoke the device in your workspace to invalidate its credential.",
  );
});
element("share").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    const tab = await activeTab();
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["contracts.js", "content.js"],
    });
    const snapshot = validate(
      "SnapshotCreate",
      await chrome.tabs.sendMessage(tab.id, {
        version: 1,
        action: "inspect",
      }),
    );
    if (!snapshot.fields.length)
      throw new Error(
        "No supported visible fields found. Passwords, payment details, uploads and hidden fields are excluded.",
      );
    await api("snapshots", snapshot);
    message(
      `${snapshot.fields.length} fields shared. Prepare a proposal in your workspace, then check proposals here.`,
    );
  }),
);
element("refresh").addEventListener("click", (event) =>
  action(event.currentTarget, async () => {
    const tab = await activeTab();
    const target = new URL(tab.url);
    const currentPage = target.origin + target.pathname;
    const commands = validate(
      "PendingCommands",
      await api("device/commands"),
    ).filter((c) => c.page_url === currentPage);
    element("proposals").replaceChildren();
    for (const command of commands) {
      const card = document.createElement("article");
      card.className = "proposal";
      const heading = document.createElement("h2");
      heading.textContent = `Review ${Object.keys(command.fields).length} proposed answers`;
      card.append(heading);
      for (const [id, value] of Object.entries(command.fields)) {
        const row = document.createElement("div");
        row.className = "answer";
        const label = document.createElement("strong");
        label.textContent =
          command.form_fields.find((f) => f.id === id)?.label ?? id;
        const content = document.createElement("span");
        content.textContent = value;
        row.append(label, content);
        card.append(row);
      }
      const apply = document.createElement("button");
      apply.textContent = "Apply these answers";
      apply.addEventListener("click", () =>
        action(apply, async () => {
          validate(
            "ClaimResult",
            await api(`device/commands/${command.id}/claim`, {}),
          );
          let result;
          try {
            result = validate(
              "ApplyResult",
              await chrome.tabs.sendMessage(tab.id, {
                version: 1,
                action: "apply",
                command: {
                  snapshot_id: command.snapshot_id,
                  page_url: command.page_url,
                  fields: command.fields,
                },
              }),
            );
          } catch {
            result = {
              state: "outcome_unknown",
              message:
                "The form is no longer available. Review it before creating a new proposal.",
            };
          }
          try {
            await api(`device/commands/${command.id}/result`, {
              state: result.state,
            });
          } catch {
            message(
              "The result could not be recorded. Review the page; this command will not be replayed.",
            );
            card.remove();
            return;
          }
          message(result.message);
          card.remove();
        }),
      );
      const note = document.createElement("small");
      note.textContent = "Fills only this shared form. Does not click Submit.";
      card.append(apply, note);
      element("proposals").append(card);
    }
    message(
      commands.length
        ? "Check every proposed answer before applying."
        : "No pending proposals for this page.",
    );
  }),
);
renderConnection();
