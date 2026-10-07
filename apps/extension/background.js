// Background orchestrator for the application automation bridge.
//
// Polls the workspace API for queued automation runs, opens the job URL in a
// background tab, runs the served adapter, and reports per-field evidence.
// Invariants: only pre-granted "Automation sites" origins are operated on;
// runs end ready for review and this worker never submits; all run state
// lives in chrome.storage.local so an MV3 service-worker death is recoverable
// on the next alarm tick.
const POLL_ALARM = "command-center-automation-poll";
const POLL_MINUTES = 1;
const RUN_TIMEOUT_MS = 9 * 60 * 1000; // under the server's 10-minute run token

const ALLOWED_APIS = new Set(["http://localhost:8000", "http://127.0.0.1:8000"]);

const sidePanelBehavior = () => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
};
void sidePanelBehavior;

// The saved application stays in the workspace; discard only closed-tab UI state.
chrome.tabs.onRemoved.addListener((tabId) => {
  void chrome.storage.local.remove(`applicationDraft:${tabId}`);
});

async function settings() {
  const stored = await chrome.storage.local.get(["connection", "automationSettings", "grantedOrigins"]);
  return {
    connection: stored.connection ?? null,
    automationSettings: stored.automationSettings ?? { enabled: false },
    grantedOrigins: stored.grantedOrigins ?? [],
  };
}

function apiBase(connection) {
  const base = connection?.base;
  if (!base || !ALLOWED_APIS.has(base)) return null;
  return base;
}

async function apiFetch(connection, path, options = {}) {
  const base = apiBase(connection);
  if (!base) throw new Error("Choose a supported local API address.");
  const headers = { "Content-Type": "application/json" };
  if (connection?.token && !options.unauthenticated) {
    headers.Authorization = `Bearer ${connection.token}`;
  }
  const response = await fetch(`${base}/api/v1/browser${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
    credentials: "omit",
    redirect: "error",
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error(`API ${response.status} on ${path}`);
  return response.json();
}

// Memoized idempotency keys per run, so a service-worker restart replays the
// same receipt instead of duplicating a report.
async function receipt(kind) {
  const store = await chrome.storage.local.get({ automationReceipts: {} });
  const receipts = store.automationReceipts;
  if (!receipts[kind]) receipts[kind] = crypto.randomUUID();
  await chrome.storage.local.set({ automationReceipts: receipts });
  return receipts[kind];
}

async function persistedRuns() {
  const store = await chrome.storage.local.get({ automationRuns: {} });
  return store.automationRuns;
}

async function saveRuns(runs) {
  await chrome.storage.local.set({ automationRuns: runs });
}

async function reportRun(connection, runId, body) {
  const key = await receipt(`automation-result:${runId}`);
  return apiFetch(connection, `/device/automation/commands/${runId}/result`, {
    method: "POST",
    body: { ...body },
    key,
  });
}

async function failRun(run, errorCode) {
  const { connection } = await settings();
  if (!connection) return;
  try {
    await reportRun(connection, run.run_id, {
      run_token: run.run_token,
      state: "failed",
      detail: errorCode,
      field_evidence: {},
    });
  } catch {
    // Server state recycles the run via expire_stale on the next claim.
  }
}

async function originAllowed(origin, grantedOrigins) {
  if (grantedOrigins.includes(origin)) return chrome.permissions.contains({ origins: [`${origin}/*`] });
  return false;
}

async function waitForComplete(tabId) {
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(false);
    }, 30000);
    const listener = (updatedTabId, changeInfo) => {
      if (updatedTabId === tabId && changeInfo.status === "complete") {
        clearTimeout(timeout);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(true);
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function executeRun(run, connection) {
  const settingsNow = await settings();
  let origin;
  try {
    origin = new URL(run.command.application.job_url).origin;
  } catch {
    await failRun(run, "job_url_invalid");
    return;
  }
  if (!(await originAllowed(origin, settingsNow.grantedOrigins))) {
    await failRun(run, "origin_not_authorized");
    return;
  }

  const tab = await chrome.tabs.create({ url: run.command.application.job_url, active: false });
  const opened = await waitForComplete(tab.id);
  if (!opened) {
    await chrome.tabs.remove(tab.id).catch(() => {});
    await failRun(run, "tab_load_failed");
    return;
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["contracts.js", "form-fillers.js", "adapter-runner.js"],
    });
  } catch {
    await chrome.tabs.remove(tab.id).catch(() => {});
    await failRun(run, "injection_failed");
    return;
  }

  // Hand the run to the runner; result messages flow through onMessage below.
  const runs = await persistedRuns();
  runs[run.run_id] = { ...run, tab_id: tab.id, started_at: Date.now() };
  await saveRuns(runs);
}

async function poll() {
  const { connection, automationSettings } = await settings();
  if (!automationSettings.enabled || !connection) return;
  const runs = await persistedRuns();
  const active = Object.entries(runs).filter(([, run]) => !run.finished);
  for (const [runId, run] of active) {
    if (Date.now() - (run.started_at ?? 0) > RUN_TIMEOUT_MS) {
      delete runs[runId];
      await saveRuns(runs);
      await failRun(run, "run_timeout");
    }
  }
  try {
    const commands = await apiFetch(connection, "/device/automation/commands");
    for (const command of commands ?? []) {
      await executeRun({ command, run_id: command.run_id, run_token: command.run_token }, connection);
    }
  } catch {
    // The next alarm tick retries; the server fences duplicate claims.
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === POLL_ALARM) void poll();
});

// Start the alarm on service-worker restart; onInstalled only fires once per
// install/update, but MV3 can kill and relaunch this worker anytime.
chrome.alarms.get(POLL_ALARM, (alarm) => {
  if (!alarm) chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
});
void poll();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;
  if (message?.version !== 3) return false;
  if (message.action !== "automation-start" && message.action !== "automation-evidence" && message.action !== "automation-result") {
    return false;
  }
  void (async () => {
    const { connection } = await settings();
    if (!connection) {
      sendResponse({ recorded: false });
      return;
    }
    const runs = await persistedRuns();
    const run = runs[message.run_id];
    try {
      if (message.action === "automation-start") {
        // The runner asks what its run is; state was persisted at execute time.
        sendResponse({
          command: run?.command ?? null,
          run_token: run?.run_token ?? null,
          profile: run?.profile ?? {},
          resume: run?.resume ?? null,
          files: run?.files ?? {},
        });
        return;
      }
      const path =
        message.action === "automation-evidence"
          ? `/device/automation/commands/${message.run_id}/evidence`
          : `/device/automation/commands/${message.run_id}/result`;
      const body =
        message.action === "automation-evidence"
          ? {
              run_token: message.run_token,
              field_evidence: message.field_evidence ?? {},
              page_evidence: message.page_evidence ?? null,
              simplify_step: message.simplify_step ?? null,
            }
          : {
              run_token: message.run_token,
              state: message.state,
              detail: message.detail ?? "",
              field_evidence: message.field_evidence ?? {},
              page_evidence: message.page_evidence ?? null,
              simplify_step: message.simplify_step ?? null,
            };
      const key = await receipt(`automation-${message.action}:${message.run_id}`);
      const response = await apiFetch(connection, path, { method: "POST", body, key });
      if (message.action === "automation-result" && runs[message.run_id]) {
        runs[message.run_id].finished = true;
        await saveRuns(runs);
      }
      sendResponse(response);
    } catch {
      sendResponse({ recorded: false });
    }
  })();
  return true; // async sendResponse
});
