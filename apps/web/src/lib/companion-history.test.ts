import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const extension = (name: string) =>
  readFileSync(
    path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      "../../../extension",
      name,
    ),
    "utf8",
  );
const contracts = new Function(
  `${extension("contracts.js")}\nreturn CommandCenterContracts;`,
)() as Record<string, (value: unknown) => boolean>;
const executeContent = new Function(
  "chrome",
  "crypto",
  "globalThis",
  extension("content.js"),
);
type Targets = { experience: number; education: number };
type Result = {
  operation_id: string;
  snapshot_id: string;
  state: string;
  counts: Targets;
  added: Targets;
  message: string;
};
type Capture = {
  id: string;
  page_url: string;
  history_expandable?: boolean;
  fields: Array<{
    id: string;
    value_state: string;
    history?: { kind: string; position: number };
  }>;
};
type Listener = (
  message: unknown,
  sender: { id: string },
  respond: (result: unknown) => void,
) => boolean;
const titles = { experience: "Work experience", education: "Education" };

function row(kind: keyof Targets, ordinal: number, value = "") {
  const fields =
    kind === "experience" ? ["Company", "Job title"] : ["School", "Degree"];
  return `<fieldset><legend>${titles[kind]} ${ordinal}</legend>${fields.map((label) => `<label>${label}<input value="${value}"></label>`).join("")}</fieldset>`;
}

function section(
  kind: keyof Targets,
  count = 1,
  button = `<button type="button">Add ${titles[kind]}</button>`,
) {
  return `<section data-kind="${kind}"><h2>${titles[kind]}</h2>${Array.from({ length: count }, (_, index) => row(kind, index + 1)).join("")}${button}</section>`;
}

function harness(html: string) {
  document.body.innerHTML = `<form>${html}</form>`;
  let listener: Listener;
  const chrome = {
    runtime: {
      id: "synthetic-extension",
      onMessage: {
        addListener: (value: Listener) => {
          listener = value;
        },
      },
    },
  };
  executeContent(chrome, { randomUUID }, { CommandCenterContracts: contracts });
  const send = <T>(message: unknown) =>
    new Promise<T>((resolve) =>
      listener(message, { id: chrome.runtime.id }, (result) =>
        resolve(result as T),
      ),
    );
  const inspect = async () => {
    const result = await send<Capture>({ version: 2, action: "inspect" });
    await Promise.resolve();
    return result;
  };
  const request = (
    capture: Capture,
    targets: Partial<Targets> = { experience: 2 },
  ) => ({
    version: 2,
    action: "expand-history",
    id: randomUUID(),
    snapshot_id: capture.id,
    targets: { experience: 0, education: 0, ...targets },
  });
  const expand = async (message: ReturnType<typeof request>) => {
    const result = await send<Result>(message);
    expect(contracts.ExpandHistoryResult(result)).toBe(true);
    return result;
  };
  return {
    send,
    inspect,
    request,
    expand,
    foreign: (message: unknown) =>
      listener(message, { id: "foreign-extension" }, vi.fn()),
  };
}

function addRows(kind: keyof Targets, delay = 0) {
  const scope = document.querySelector(`[data-kind="${kind}"]`)!;
  const button = scope.querySelector("button")!;
  const click = vi.fn(() => {
    const append = () =>
      button.insertAdjacentHTML(
        "beforebegin",
        row(kind, scope.querySelectorAll("fieldset").length + 1),
      );
    if (delay) setTimeout(append, delay);
    else append();
  });
  button.addEventListener("click", click);
  return click;
}

async function finish<T>(pending: Promise<T>) {
  await vi.runAllTimersAsync();
  return pending;
}

beforeEach(() => {
  vi.useFakeTimers();
  window.history.replaceState({}, "", "/apply?job=synthetic");
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockImplementation(
    function (this: HTMLElement) {
      const hidden = this.closest(
        '[hidden],[style*="display: none"],[style*="display:none"]',
      );
      return (hidden
        ? []
        : [{ width: 10, height: 10 }]) as unknown as DOMRectList;
    },
  );
});

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("companion history row expansion", () => {
  it("adds only missing work and education rows, leaves fields empty, and invalidates the old capture", async () => {
    const app = harness(section("experience") + section("education"));
    const work = addRows("experience");
    const education = addRows("education");
    const capture = await app.inspect();
    const result = await finish(
      app.expand(app.request(capture, { experience: 3, education: 2 })),
    );
    expect(result).toMatchObject({
      state: "expanded",
      counts: { experience: 3, education: 2 },
      added: { experience: 2, education: 1 },
    });
    expect(work).toHaveBeenCalledTimes(2);
    expect(education).toHaveBeenCalledTimes(1);
    expect(
      Array.from(document.querySelectorAll("input")).every(
        (input) => input.value === "",
      ),
    ).toBe(true);
    expect((await app.expand(app.request(capture))).state).toBe("rejected");
    const fresh = await app.inspect();
    expect(
      fresh.fields
        .filter((field) => field.history?.kind === "experience")
        .map((field) => field.history?.position),
    ).toEqual([0, 0, 1, 1, 2, 2]);
  });

  it("starts from zero rows inside a labelled section using a generic Add another button", async () => {
    const app = harness(
      section("experience", 0, '<button type="button">Add another</button>'),
    );
    const click = addRows("experience");
    const capture = await app.inspect();
    expect(capture.fields).toHaveLength(0);
    expect(capture.history_expandable).toBe(true);
    expect(await finish(app.expand(app.request(capture)))).toMatchObject({
      state: "expanded",
      counts: { experience: 2, education: 0 },
      added: { experience: 2, education: 0 },
    });
    expect(click).toHaveBeenCalledTimes(2);
  });

  it("keeps the capture valid when no additional rows are needed", async () => {
    const app = harness(section("experience"));
    const click = addRows("experience");
    const capture = await app.inspect();
    expect(
      (await app.expand(app.request(capture, { experience: 1 }))).state,
    ).toBe("unchanged");
    expect((await finish(app.expand(app.request(capture)))).state).toBe(
      "expanded",
    );
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("keeps unchanged captures usable for reviewed application", async () => {
    const app = harness(section("experience", 1, ""));
    const capture = await app.inspect();
    expect((await app.expand(app.request(capture))).state).toBe("unchanged");
    const result = await app.send<Result>({
      version: 2,
      action: "apply",
      files: {},
      command: {
        snapshot_id: capture.id,
        page_url: capture.page_url,
        fields: { f0: "Synthetic Company", f1: "Engineer" },
        uploads: {},
        replace_fields: [],
        preparation_version_id: null,
      },
    });
    expect(result.state).toBe("applied");
    expect(document.querySelector("input")!.value).toBe("Synthetic Company");
  });

  it("accepts a rerendered Add button only after each confirmed appended row", async () => {
    const app = harness(section("experience"));
    const scope = document.querySelector("section")!;
    const click = vi.fn(() => {
      const button = scope.querySelector("button")!;
      button.insertAdjacentHTML(
        "beforebegin",
        row("experience", scope.querySelectorAll("fieldset").length + 1),
      );
      const replacement = button.cloneNode(true);
      button.replaceWith(replacement);
      replacement.addEventListener("click", click);
    });
    scope.querySelector("button")!.addEventListener("click", click);
    expect(
      (
        await finish(
          app.expand(app.request(await app.inspect(), { experience: 4 })),
        )
      ).state,
    ).toBe("expanded");
    expect(click).toHaveBeenCalledTimes(3);
  });

  it("refuses replacement of the captured Add button before any confirmed addition", async () => {
    const app = harness(section("experience"));
    const capture = await app.inspect();
    const button = document.querySelector("button")!;
    const replacement = button.cloneNode(true);
    button.replaceWith(replacement);
    const click = vi.fn();
    replacement.addEventListener("click", click);
    expect((await app.expand(app.request(capture))).state).toBe("unchanged");
    expect(click).not.toHaveBeenCalled();
  });

  it.each([
    "<button>Add work experience</button>",
    '<button type="submit">Add work experience</button>',
    '<button type="reset">Add work experience</button>',
    '<a href="#">Add work experience</a>',
    '<button type="button">Next</button>',
    '<button type="button">Continue</button>',
    '<button type="button">Apply</button>',
    '<button type="button">Save</button>',
    '<button type="button" disabled>Add work experience</button>',
    '<button type="button" hidden>Add work experience</button>',
    '<button type="button" aria-haspopup="dialog">Add work experience</button>',
    '<button type="button" data-bs-toggle="modal">Add work experience</button>',
    '<button type="button" data-bs-target="#dialog">Add work experience</button>',
    '<button type="button">Add work experience</button><button type="button">Add another</button>',
  ])("refuses unsafe or ambiguous Add controls: %s", async (markup) => {
    const app = harness(section("experience", 1, markup));
    const click = vi.fn();
    document.querySelector("form")!.addEventListener("click", click);
    const capture = await app.inspect();
    expect((await app.expand(app.request(capture))).state).toBe("unchanged");
    expect(click).not.toHaveBeenCalled();
  });

  it("does not interpret generic Add in a non-career section", async () => {
    const app = harness(
      '<section><h2>References</h2><button type="button">Add another</button></section>',
    );
    const click = vi.fn();
    document.querySelector("button")!.addEventListener("click", click);
    expect((await app.expand(app.request(await app.inspect()))).state).toBe(
      "unchanged",
    );
    expect(click).not.toHaveBeenCalled();
  });

  it.each(["occupied", "duplicate", "gap", "unrecognized", "sensitive"])(
    "preserves %s career groups without adding duplicates",
    async (scenario) => {
      const app = harness(section("experience"));
      const click = addRows("experience");
      if (scenario === "occupied")
        document.querySelector("input")!.value = "Synthetic Company";
      if (scenario === "duplicate")
        document
          .querySelector("fieldset")!
          .insertAdjacentHTML("beforeend", "<label>Company<input></label>");
      if (scenario === "gap")
        document.querySelector("legend")!.textContent = "Work experience 2";
      if (scenario === "unrecognized")
        document.querySelector("label")!.firstChild!.textContent =
          "Unrecognized field";
      if (scenario === "sensitive")
        document
          .querySelector("fieldset")!
          .insertAdjacentHTML(
            "beforeend",
            '<label>Social security number<input value="synthetic-private-value"></label>',
          );
      expect(
        (await app.expand(app.request(await app.inspect(), { experience: 3 })))
          .state,
      ).toBe("unchanged");
      expect(click).not.toHaveBeenCalled();
    },
  );

  it.each(["url", "replaced", "reordered", "value", "edit-clear"])(
    "rejects a stale %s capture before clicking",
    async (scenario) => {
      const app = harness(section("experience"));
      const click = addRows("experience");
      const capture = await app.inspect();
      const input = document.querySelector("input")!;
      if (scenario === "url")
        window.history.replaceState({}, "", "/apply?job=other");
      if (scenario === "replaced") input.replaceWith(input.cloneNode());
      if (scenario === "reordered")
        input.closest("fieldset")!.append(input.closest("label")!);
      if (scenario === "value") input.value = "New value";
      if (scenario === "edit-clear")
        input.dispatchEvent(new Event("input", { bubbles: true }));
      expect((await app.expand(app.request(capture))).state).toBe("rejected");
      expect(click).not.toHaveBeenCalled();
    },
  );

  it("binds empty same-origin frame sections to their original document", async () => {
    const app = harness('<iframe title="Application"></iframe>');
    const frame = document.querySelector("iframe")!;
    frame.contentDocument!.body.innerHTML = section("experience", 0);
    const frameWindow = frame.contentWindow! as Window & typeof globalThis;
    Object.defineProperty(frameWindow.HTMLElement.prototype, "getClientRects", {
      configurable: true,
      value: () => [{ width: 10, height: 10 }],
    });
    const capture = await app.inspect();
    frame.remove();
    expect((await app.expand(app.request(capture))).state).toBe("rejected");
  });

  it("waits for delayed single-row additions and reuses both pending and final receipts", async () => {
    const app = harness(section("experience"));
    const click = addRows("experience", 200);
    const capture = await app.inspect();
    const message = app.request(capture);
    const first = app.expand(message);
    const retry = app.expand(structuredClone(message));
    expect(
      (await app.send<Result>({ version: 2, action: "inspect" })).state,
    ).toBe("rejected");
    const changed = await app.expand({
      ...message,
      targets: { experience: 3, education: 0 },
    });
    expect(changed.state).toBe("rejected");
    const result = await finish(first);
    expect(result.state).toBe("expanded");
    expect(await retry).toEqual(result);
    await app.inspect();
    expect(await app.expand(message)).toEqual(result);
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("does not click again after a timed-out addition, including after a late row appears", async () => {
    const app = harness(section("experience"));
    const click = addRows("experience", 2000);
    const message = app.request(await app.inspect(), { experience: 3 });
    const pending = app.expand(message);
    await vi.advanceTimersByTimeAsync(1600);
    expect((await pending).state).toBe("outcome_unknown");
    await vi.runAllTimersAsync();
    expect((await app.expand(message)).state).toBe("outcome_unknown");
    expect(click).toHaveBeenCalledTimes(1);
  });

  it.each([
    "multiple",
    "changed-existing",
    "unrelated",
    "navigation",
    "reordered-groups",
    "edited-cleared-new-row",
    "prepended-group",
  ])("stops after an Add causes %s changes", async (scenario) => {
    const app = harness(section("experience", 2));
    const scope = document.querySelector("section")!;
    const button = document.querySelector("button")!;
    const click = vi.fn(() => {
      button.insertAdjacentHTML("beforebegin", row("experience", 3));
      if (scenario === "multiple")
        button.insertAdjacentHTML("beforebegin", row("experience", 4));
      if (scenario === "changed-existing")
        document.querySelector("input")!.value = "Unexpected";
      if (scenario === "unrelated")
        document
          .querySelector("form")!
          .insertAdjacentHTML("beforeend", "<label>Other<input></label>");
      if (scenario === "navigation")
        window.history.replaceState({}, "", "/elsewhere");
      if (scenario === "reordered-groups")
        scope.insertBefore(
          scope.querySelectorAll("fieldset")[1],
          scope.querySelector("fieldset"),
        );
      if (scenario === "edited-cleared-new-row") {
        const input = scope.querySelectorAll("input")[4];
        input.value = "Temporary edit";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.value = "";
      }
      if (scenario === "prepended-group") {
        for (const legend of scope.querySelectorAll("legend"))
          legend.textContent = "Work experience";
        scope.insertBefore(
          scope.querySelectorAll("fieldset")[2],
          scope.querySelector("fieldset"),
        );
      }
    });
    button.addEventListener("click", click);
    const message = app.request(await app.inspect(), { experience: 4 });
    expect((await finish(app.expand(message))).state).toBe("outcome_unknown");
    expect(click).toHaveBeenCalledTimes(1);
    expect((await app.expand(message)).state).toBe("outcome_unknown");
  });

  it("reports a partial result when a later section requires manual addition", async () => {
    const app = harness(section("experience") + section("education", 1, ""));
    addRows("experience");
    expect(
      await finish(
        app.expand(
          app.request(await app.inspect(), { experience: 2, education: 2 }),
        ),
      ),
    ).toMatchObject({
      state: "partial",
      added: { experience: 1, education: 0 },
      counts: { experience: 2, education: 1 },
    });
  });

  it("stops before the capture limit and clamps counts to ten", async () => {
    const unrelated = Array.from(
      { length: 97 },
      () => "<label>Other<input></label>",
    ).join("");
    const app = harness(section("experience") + unrelated);
    const click = addRows("experience");
    const result = await app.expand(app.request(await app.inspect()));
    expect(result.state).toBe("unchanged");
    expect(result.message).toContain("100-control");
    expect(click).not.toHaveBeenCalled();
    const full = harness(section("experience", 12));
    expect(
      await full.expand(full.request(await full.inspect(), { experience: 10 })),
    ).toMatchObject({
      state: "unchanged",
      counts: { experience: 10, education: 0 },
    });
  });

  it("rejects external senders and malformed target counts without clicking", async () => {
    const app = harness(section("experience"));
    const click = addRows("experience");
    const message = app.request(await app.inspect());
    expect(app.foreign(message)).toBe(false);
    expect(
      (
        await app.send<Result>({
          ...message,
          targets: { experience: 11, education: 0 },
        })
      ).state,
    ).toBe("rejected");
    expect(click).not.toHaveBeenCalled();
  });

  it("stops at 100 controls with a partial result after one confirmed row", async () => {
    const app = harness(
      section("experience") +
        Array.from({ length: 96 }, () => "<label>Other<input></label>").join(
          "",
        ),
    );
    const click = addRows("experience");
    const result = await finish(
      app.expand(app.request(await app.inspect(), { experience: 3 })),
    );
    expect(result).toMatchObject({
      state: "partial",
      added: { experience: 1, education: 0 },
      counts: { experience: 2, education: 0 },
    });
    expect(result.message).toContain("100-control");
    expect(document.querySelectorAll("input")).toHaveLength(100);
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("bounds operation receipts without making old identities replayable", async () => {
    const app = harness(section("experience"));
    const click = addRows("experience");
    const capture = await app.inspect();
    const first = app.request(capture, { experience: 1 });
    const receipt = await app.expand(first);
    for (let index = 1; index < 32; index += 1)
      expect(
        (await app.expand(app.request(capture, { experience: 1 }))).state,
      ).toBe("unchanged");
    expect((await app.expand(app.request(capture))).state).toBe("rejected");
    expect(await app.expand(first)).toEqual(receipt);
    expect(click).not.toHaveBeenCalled();
  });
});
