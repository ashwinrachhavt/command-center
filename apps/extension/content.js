(() => {
  if (globalThis.__commandCenterCompanionLoaded) return;
  globalThis.__commandCenterCompanionLoaded = true;

  const contracts = globalThis.CommandCenterContracts;
  const supportedTextTypes = new Set(["text", "email", "tel", "url"]);
  const sensitive =
    /password|passcode|one[ -]?time|\botp\b|social security|\bssn\b|credit card|card number|\bcvv\b|\bcvc\b|bank account|routing number|payment/i;
  let snapshot;
  let applying = false;
  const watchedDocuments = new WeakSet();
  const customSelects = new WeakMap();
  let inspecting = false;
  const ignoredFrames = /captcha|recaptcha|hcaptcha|turnstile/i;

  const pageUrl = () => `${location.origin}${location.pathname}`;
  const trim = (value, maximum) =>
    String(value ?? "")
      .trim()
      .slice(0, maximum);
  const labelsFor = (element) =>
    Array.from(element.labels ?? [])
      .map((label) => trim(label.textContent, 500))
      .filter(Boolean);

  function readableLabel(element) {
    const labelledBy = trim(element.getAttribute("aria-labelledby"), 500)
      .split(/\s+/)
      .map((id) =>
        trim(element.ownerDocument.getElementById(id)?.textContent, 500),
      )
      .filter(Boolean)
      .join(" ");
    return trim(
      labelsFor(element).join(" ") ||
        labelledBy ||
        element.getAttribute("aria-label") ||
        trim(
          element
            .closest(".ashby-application-form-field-entry")
            ?.querySelector(":scope > label")?.textContent,
          500,
        ) ||
        element.placeholder ||
        element.name ||
        element.id ||
        "Unnamed field",
      500,
    );
  }

  function isVisible(element) {
    try {
      const view = element.ownerDocument.defaultView;
      const style = view.getComputedStyle(element);
      if (
        !element.isConnected ||
        element.disabled ||
        style.display === "none" ||
        style.visibility !== "visible" ||
        !element.getClientRects().length
      )
        return false;
      return !view.frameElement || isVisible(view.frameElement);
    } catch {
      return false;
    }
  }

  function formDocuments() {
    const contexts = [];
    function visit(doc, frame = null, parent = null, depth = 0) {
      if (contexts.length >= 20 || depth > 4) return;
      const context = {
        document: doc,
        frame,
        parent,
        url: doc.defaultView.location.href,
      };
      contexts.push(context);
      for (const child of doc.querySelectorAll("iframe")) {
        if (
          !isVisible(child) ||
          ignoredFrames.test(
            [child.title, child.name, child.id, child.src].join(" "),
          )
        )
          continue;
        try {
          // contentDocument is unavailable for cross-origin/opaque frames. Keep
          // document objects locally; a URL alone cannot identify a reloaded form.
          if (child.contentDocument?.defaultView)
            visit(child.contentDocument, child, context, depth + 1);
        } catch {
          // Cross-origin frames are outside the current tab's shared form.
        }
      }
    }
    visit(document);
    return contexts;
  }

  function currentContext(context) {
    try {
      return Boolean(
        context &&
        context.document.defaultView?.location.href === context.url &&
        (!context.frame ||
          (isVisible(context.frame) &&
            context.frame.contentDocument === context.document &&
            currentContext(context.parent))),
      );
    } catch {
      return false;
    }
  }

  function currentPage() {
    return (
      snapshot &&
      location.href === snapshot.full_url &&
      snapshot.entries.every((entry) => currentContext(entry.context))
    );
  }

  function isSensitive(element, label) {
    return sensitive.test(
      [
        label,
        element.name,
        element.id,
        element.autocomplete,
        element.placeholder,
      ].join(" "),
    );
  }

  function optionData(options) {
    const values = [];
    const optionLabels = {};
    for (const option of Array.from(options).slice(0, 300)) {
      const value = trim(option.value, 300);
      if (!value || values.includes(value)) continue;
      values.push(value);
      optionLabels[value] = trim(option.textContent || value, 500);
    }
    return { options: values, option_labels: optionLabels };
  }

  function basicDescription(element, type, overrides = {}) {
    return {
      label: readableLabel(element),
      type,
      required: Boolean(
        element.required || element.getAttribute("aria-required") === "true",
      ),
      options: [],
      value_state:
        type === "checkbox"
          ? element.checked
            ? "present"
            : "empty"
          : type === "file"
            ? element.files?.length
              ? "present"
              : "empty"
            : element.value
              ? "present"
              : "empty",
      autocomplete: trim(element.autocomplete, 100),
      accept: type === "file" ? trim(element.accept, 300) : "",
      option_labels: {},
      unsupported_reason: null,
      ...overrides,
    };
  }

  function unsupportedEntry(element, reason) {
    return {
      key: element,
      elements: [element],
      description: {
        ...basicDescription(element, "unsupported"),
        unsupported_reason: trim(reason, 300),
      },
    };
  }

  function selectContainer(element) {
    if (!element.matches('input.select__input[role="combobox"]')) return null;
    const container = element.closest(".select__container");
    return container?.querySelectorAll('[role="combobox"]').length === 1 &&
      !container.querySelector(".select__multi-value")
      ? container
      : null;
  }

  function selectedLabel(element) {
    return trim(
      selectContainer(element)?.querySelector(".select__single-value")
        ?.textContent,
      500,
    );
  }

  function selectKey(element, key) {
    element.dispatchEvent(
      new element.ownerDocument.defaultView.KeyboardEvent("keydown", {
        key,
        code: key,
        keyCode: key === "ArrowDown" ? 40 : 27,
        bubbles: true,
      }),
    );
  }

  const nextTurn = () => new Promise((resolve) => setTimeout(resolve, 0));

  function finiteNumber(value) {
    return (
      typeof value === "string" &&
      value.length <= 100 &&
      /^-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value) &&
      Number.isFinite(Number(value))
    );
  }

  function numericConstraints(element) {
    const minimum = element.getAttribute("min");
    const maximum = element.getAttribute("max");
    const step = element.getAttribute("step");
    return {
      minimum: finiteNumber(minimum) ? minimum : null,
      maximum: finiteNumber(maximum) ? maximum : null,
      step:
        step === "any" || (finiteNumber(step) && Number(step) > 0) ? step : "1",
      step_base: finiteNumber(minimum)
        ? minimum
        : finiteNumber(element.defaultValue)
          ? element.defaultValue
          : "0",
    };
  }

  function readSelectOptions(element) {
    const container = selectContainer(element);
    const list = element.ownerDocument.getElementById(
      element.getAttribute("aria-controls"),
    );
    if (
      !container ||
      !list ||
      !container.contains(list) ||
      !isVisible(list) ||
      list.getAttribute("role") !== "listbox" ||
      list.getAttribute("aria-multiselectable") === "true" ||
      list.getAttribute("aria-busy") === "true" ||
      container.querySelector('[aria-busy="true"],.select__loading-indicator')
    )
      return null;
    const nodes = Array.from(list.querySelectorAll('[role="option"]'));
    if (!nodes.length || nodes.length > 300) return null;
    const options = [];
    const seen = new Set();
    for (const node of nodes) {
      if (node.getAttribute("aria-disabled") === "true") continue;
      const label = String(node.textContent ?? "").trim();
      const total = Number(node.getAttribute("aria-setsize") || nodes.length);
      if (
        !node.id ||
        !isVisible(node) ||
        !label ||
        label.length > 300 ||
        seen.has(label) ||
        total !== nodes.length
      )
        return null;
      seen.add(label);
      options.push({ value: label, label, node });
    }
    return options.length ? options : null;
  }

  async function openSelect(element) {
    if (!selectContainer(element) || !isVisible(element) || element.value)
      return null;
    if (element.getAttribute("aria-expanded") !== "true") {
      element.focus({ preventScroll: true });
      selectKey(element, "ArrowDown");
      await nextTurn();
    }
    return readSelectOptions(element);
  }

  async function closeSelect(element) {
    if (
      element.isConnected &&
      element.getAttribute("aria-expanded") === "true"
    ) {
      selectKey(element, "Escape");
      await nextTurn();
    }
  }

  async function captureSelect(element) {
    if (!selectContainer(element)) return;
    const wasOpen = element.getAttribute("aria-expanded") === "true";
    const choices = await openSelect(element);
    if (choices)
      customSelects.set(
        element,
        choices.map(({ value, label }) => ({ value, label })),
      );
    else customSelects.delete(element);
    if (!wasOpen) await closeSelect(element);
  }

  function sameSelectOptions(entry, choices) {
    return (
      choices &&
      JSON.stringify(choices.map(({ value, label }) => ({ value, label }))) ===
        JSON.stringify(entry.customOptions)
    );
  }

  async function validateSelect(entry) {
    const element = entry.elements[0];
    const wasOpen = element.getAttribute("aria-expanded") === "true";
    const valid = sameSelectOptions(entry, await openSelect(element));
    if (!wasOpen) await closeSelect(element);
    return valid;
  }

  async function fillSelect(entry, value, replace) {
    const element = entry.elements[0];
    const choices = await openSelect(element);
    if (!sameSelectOptions(entry, choices) || !currentPage()) {
      await closeSelect(element);
      return {
        status: "rejected",
        detail:
          "The dropdown choices changed. Share and review this form again.",
      };
    }
    const preserved = preservationReason(entry, replace);
    if (preserved) {
      await closeSelect(element);
      return { status: "preserved", detail: preserved };
    }
    const choice = choices.find((item) => item.value === value);
    if (!choice) {
      await closeSelect(element);
      return {
        status: "rejected",
        detail: "Choose an exact option from the shared dropdown.",
      };
    }
    choice.node.click();
    await nextTurn();
    if (!currentPage() || !element.isConnected)
      return {
        status: "outcome_unknown",
        detail: "The form changed during selection.",
      };
    const selected = (await openSelect(element))?.filter(
      ({ node }) =>
        node.classList.contains("select__option--is-selected") ||
        node.getAttribute("aria-selected") === "true",
    );
    const verified =
      selected?.length === 1 &&
      selected[0].value === value &&
      selectedLabel(element) === value &&
      !element.value;
    await closeSelect(element);
    if (!verified || !currentPage())
      return {
        status: "outcome_unknown",
        detail:
          "The dropdown did not confirm the exact reviewed selection. Review it manually.",
      };
    return {
      status: "filled",
      detail: "Exact dropdown selection confirmed for review.",
    };
  }

  function radioEntry(element) {
    const name = element.name;
    if (!name)
      return unsupportedEntry(
        element,
        "Radio controls without a group name are unsupported.",
      );
    const radios = Array.from(
      element.ownerDocument.querySelectorAll('input[type="radio"]'),
    ).filter((radio) => radio.name === name && radio.form === element.form);
    const legend = trim(
      element.closest("fieldset")?.querySelector(":scope > legend")
        ?.textContent,
      500,
    );
    const options = [];
    const optionLabels = {};
    for (const radio of radios.slice(0, 100)) {
      const value = trim(radio.value, 300);
      if (!value || options.includes(value)) continue;
      options.push(value);
      optionLabels[value] = readableLabel(radio);
    }
    return {
      key: radios[0] ?? element,
      elements: radios,
      description: {
        label: legend || readableLabel(element),
        type: "radio",
        required: radios.some((radio) => radio.required),
        options,
        value_state: radios.some((radio) => radio.checked)
          ? "present"
          : "empty",
        autocomplete: "",
        accept: "",
        option_labels: optionLabels,
        unsupported_reason: null,
      },
    };
  }

  function describeElement(element) {
    const view = element.ownerDocument.defaultView;
    if (!isVisible(element)) {
      if (
        element instanceof view.HTMLInputElement &&
        element.type === "file" &&
        !element.disabled &&
        Array.from(element.labels ?? []).some(isVisible)
      ) {
        const label = readableLabel(element);
        if (!isSensitive(element, label))
          return {
            key: element,
            elements: [element],
            description: basicDescription(element, "file"),
          };
      }
      return null;
    }
    const label = readableLabel(element);
    if (isSensitive(element, label)) return null;
    if (element.matches('[role="combobox"]')) {
      const choices = customSelects.get(element);
      if (selectContainer(element) && choices)
        return {
          key: element,
          elements: [element],
          customOptions: choices,
          description: basicDescription(element, "select", {
            options: choices.map(({ value }) => value),
            option_labels: Object.fromEntries(
              choices.map(({ value, label }) => [value, label]),
            ),
            value_state:
              selectedLabel(element) || element.value ? "present" : "empty",
          }),
        };
      return unsupportedEntry(
        element,
        "This dropdown needs manual selection; a complete, unambiguous option list could not be verified.",
      );
    }
    if (element.matches('[contenteditable="true"]'))
      return unsupportedEntry(
        element,
        "Rich text editors require manual review and entry.",
      );
    if (element instanceof view.HTMLTextAreaElement)
      return {
        key: element,
        elements: [element],
        description: basicDescription(element, "textarea"),
      };
    if (element instanceof view.HTMLSelectElement) {
      if (element.multiple)
        return unsupportedEntry(
          element,
          "Multi-select controls require manual review and entry.",
        );
      if (element.options.length > 300)
        return unsupportedEntry(
          element,
          "This dropdown has too many choices to share completely. Select it manually.",
        );
      return {
        key: element,
        elements: [element],
        description: basicDescription(
          element,
          "select",
          optionData(element.options),
        ),
      };
    }
    if (!(element instanceof view.HTMLInputElement)) return null;
    if (
      element.name === "location" &&
      element.form?.querySelector(
        'input[type="hidden"][name="selectedLocation"]',
      )
    )
      return unsupportedEntry(
        element,
        "Choose a location suggestion manually; typed text does not verify the selected location.",
      );
    if (element.type === "radio") return radioEntry(element);
    if (element.type === "checkbox")
      return {
        key: element,
        elements: [element],
        description: basicDescription(element, "checkbox", {
          options: ["true", "false"],
          option_labels: { true: "Yes", false: "No" },
        }),
      };
    if (element.type === "file")
      return {
        key: element,
        elements: [element],
        description: basicDescription(element, "file"),
      };
    if (element.type === "number")
      return {
        key: element,
        elements: [element],
        description: basicDescription(element, "number", {
          numeric_constraints: numericConstraints(element),
        }),
      };
    if (supportedTextTypes.has(element.type))
      return {
        key: element,
        elements: [element],
        description: basicDescription(element, element.type),
      };
    return unsupportedEntry(
      element,
      `The ${trim(element.type, 80) || "custom"} control requires manual review and entry.`,
    );
  }

  async function inspectPage() {
    const seen = new Set();
    const entries = [];
    const focused = document.activeElement;
    snapshot = {
      id: crypto.randomUUID(),
      page_url: pageUrl(),
      full_url: location.href,
      entries,
    };
    for (const context of formDocuments()) {
      watchDocument(context.document);
      for (const element of context.document.querySelectorAll(
        'input,textarea,select,[role="combobox"],[contenteditable="true"]',
      )) {
        if (element.matches('[role="combobox"]') && isVisible(element))
          await captureSelect(element);
        const entry = describeElement(element);
        if (!entry || seen.has(entry.key)) continue;
        seen.add(entry.key);
        entry.context = context;
        entry.capturedValues = localValues(entry);
        entry.edited = false;
        entries.push(entry);
        if (entries.length === 100) break;
      }
      if (entries.length === 100) break;
    }
    if (focused?.isConnected && focused !== document.body)
      focused.focus({ preventScroll: true });
    if (!currentPage())
      throw new Error("The page changed while sharing. Try again.");
    return {
      id: snapshot.id,
      protocol_version: 2,
      page_url: snapshot.page_url,
      title: trim(document.title, 300),
      fields: entries.map((entry, index) => ({
        id: `f${index}`,
        ...entry.description,
      })),
    };
  }

  function structural(description) {
    const { value_state: _valueState, ...shape } = description;
    return shape;
  }

  function refreshEntry(entry) {
    const first = entry.elements[0];
    return first?.isConnected ? describeElement(first) : null;
  }

  function requestedEntries(command) {
    return [
      ...new Set([
        ...Object.keys(command.fields),
        ...Object.keys(command.uploads),
      ]),
    ].map((id) => ({
      id,
      entry: /^f\d{1,3}$/.test(id)
        ? snapshot?.entries[Number(id.slice(1))]
        : null,
    }));
  }

  function rejectedResults(requested, detail) {
    return Object.fromEntries(
      requested.map(({ id }) => [
        id,
        { status: "rejected", detail: trim(detail, 300) },
      ]),
    );
  }

  function valuePresent(entry) {
    const element = entry.elements[0];
    if (entry.customOptions)
      return Boolean(selectedLabel(element) || element.value);
    if (entry.description.type === "radio")
      return entry.elements.some((radio) => radio.checked);
    if (entry.description.type === "checkbox") return element.checked;
    if (entry.description.type === "file")
      return Boolean(element.files?.length);
    return Boolean(element.value);
  }

  function localValues(entry) {
    if (entry.customOptions)
      return [selectedLabel(entry.elements[0]), entry.elements[0].value];
    if (entry.description.type === "file")
      return Array.from(entry.elements[0].files ?? []);
    return entry.elements.map((element) =>
      ["radio", "checkbox"].includes(entry.description.type)
        ? element.checked
        : element.value,
    );
  }

  function preservationReason(entry, replace) {
    const current = localValues(entry);
    if (
      entry.edited ||
      current.length !== entry.capturedValues.length ||
      current.some((value, index) => value !== entry.capturedValues[index])
    )
      return "This value changed after sharing. Share and review it again before replacement.";
    if (valuePresent(entry) && !replace)
      return "Existing local value preserved.";
    return null;
  }

  // Exact values stay in this document. An edit followed by a clear is still an
  // intentional edit, even when its final value equals the original empty one.
  function watchDocument(doc) {
    if (watchedDocuments.has(doc)) return;
    watchedDocuments.add(doc);
    for (const type of ["input", "change"])
      doc.addEventListener(
        type,
        (event) => {
          for (const entry of snapshot?.entries ?? []) {
            if (entry.elements.includes(event.target)) entry.edited = true;
          }
        },
        true,
      );
    for (const type of ["click", "keydown"])
      doc.addEventListener(
        type,
        (event) => {
          if (
            type === "keydown" &&
            !["Enter", "Backspace", "Delete"].includes(event.key)
          )
            return;
          for (const entry of snapshot?.entries ?? []) {
            if (!entry.customOptions) continue;
            const container = selectContainer(entry.elements[0]);
            if (
              container?.contains(event.target) &&
              (type === "keydown" ||
                event.target.closest(
                  '[role="option"],.select__clear-indicator',
                ))
            )
              entry.edited = true;
          }
        },
        true,
      );
  }

  function nativeValue(element, prototype, value) {
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (!setter) throw new Error("The browser could not update this control.");
    setter.call(element, value);
  }

  function dispatchChanges(element) {
    const Event = element.ownerDocument.defaultView.Event;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fillText(entry, value) {
    const element = entry.elements[0];
    const view = element.ownerDocument.defaultView;
    if (entry.description.type === "number") {
      const candidate = element.cloneNode(false);
      candidate.value = value;
      if (
        !finiteNumber(value) ||
        candidate.value !== value ||
        !candidate.validity.valid
      )
        return {
          status: "rejected",
          detail: "Use a number within this field's allowed range and step.",
        };
    }
    if (entry.description.type === "select") {
      if (!entry.description.options.includes(value))
        return {
          status: "rejected",
          detail: "Choose one of the captured options.",
        };
      nativeValue(element, view.HTMLSelectElement.prototype, value);
    } else if (entry.description.type === "textarea") {
      nativeValue(element, view.HTMLTextAreaElement.prototype, value);
    } else {
      nativeValue(element, view.HTMLInputElement.prototype, value);
    }
    dispatchChanges(element);
    if (!element.isConnected || !currentPage())
      return {
        status: "outcome_unknown",
        detail: "The page changed while this value was applied.",
      };
    if (element.value !== value)
      return {
        status: "outcome_unknown",
        detail: "The page did not retain the proposed value.",
      };
    return { status: "filled", detail: "Value applied for review." };
  }

  function fillChoice(entry, value) {
    if (entry.description.type === "checkbox") {
      if (!["true", "false"].includes(value))
        return {
          status: "rejected",
          detail: "Checkbox values must be true or false.",
        };
      const element = entry.elements[0];
      const checked = value === "true";
      if (element.checked !== checked) element.click();
      if (!element.isConnected || !currentPage() || element.checked !== checked)
        return {
          status: "outcome_unknown",
          detail: "The page changed while this choice was applied.",
        };
      return { status: "filled", detail: "Choice applied for review." };
    }
    if (!entry.description.options.includes(value))
      return {
        status: "rejected",
        detail: "Choose one of the captured options.",
      };
    const selected = entry.elements.find((radio) => radio.value === value);
    if (!selected)
      return {
        status: "rejected",
        detail: "The radio option is no longer available.",
      };
    if (!selected.checked) selected.click();
    if (!selected.isConnected || !currentPage() || !selected.checked)
      return {
        status: "outcome_unknown",
        detail: "The page changed while this choice was applied.",
      };
    return { status: "filled", detail: "Choice applied for review." };
  }

  function decodeBase64(value) {
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1)
      bytes[index] = binary.charCodeAt(index);
    return bytes;
  }

  async function sha256(bytes) {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
  }

  function acceptsFile(accept, filename, mediaType) {
    if (!accept.trim()) return true;
    const lowerName = filename.toLowerCase();
    const lowerType = mediaType.toLowerCase();
    return accept
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean)
      .some((item) =>
        item.startsWith(".")
          ? lowerName.endsWith(item)
          : item.endsWith("/*")
            ? lowerType.startsWith(item.slice(0, -1))
            : lowerType === item,
      );
  }

  async function uploadFile(entry, transfer, replace) {
    const element = entry.elements[0];
    let bytes;
    try {
      bytes = decodeBase64(transfer.data_base64);
    } catch {
      return {
        status: "rejected",
        detail: "The reviewed file bytes are not valid base64.",
      };
    }
    if (
      bytes.length !== transfer.size_bytes ||
      (await sha256(bytes)) !== transfer.sha256
    )
      return {
        status: "rejected",
        detail: "The reviewed file does not match its pinned size and hash.",
      };
    if (
      !acceptsFile(
        entry.description.accept,
        transfer.filename,
        transfer.media_type,
      )
    )
      return {
        status: "rejected",
        detail: "The reviewed file type is not accepted by this control.",
      };
    if (!element.isConnected || !currentPage())
      return {
        status: "outcome_unknown",
        detail: "The page changed during file verification.",
      };
    const preserved = preservationReason(entry, replace);
    if (preserved) return { status: "preserved", detail: preserved };
    const view = element.ownerDocument.defaultView;
    const file = new view.File([bytes], transfer.filename, {
      type: transfer.media_type,
    });
    const data = new view.DataTransfer();
    data.items.add(file);
    const setter = Object.getOwnPropertyDescriptor(
      view.HTMLInputElement.prototype,
      "files",
    )?.set;
    if (!setter)
      return {
        status: "failed",
        detail: "The browser could not attach this file.",
      };
    setter.call(element, data.files);
    dispatchChanges(element);
    const assigned = element.files?.[0];
    if (!element.isConnected || !currentPage() || !assigned)
      return {
        status: "outcome_unknown",
        detail: "The page changed while this file was attached.",
      };
    if (
      assigned.name !== transfer.filename ||
      assigned.type !== transfer.media_type ||
      assigned.size !== transfer.size_bytes ||
      (await sha256(await assigned.arrayBuffer())) !== transfer.sha256 ||
      element.files?.[0] !== assigned ||
      !element.isConnected ||
      !currentPage()
    )
      return {
        status: "outcome_unknown",
        detail: "The page did not retain the exact reviewed file.",
      };
    return {
      status: "uploaded",
      detail: "Exact reviewed file attached for review.",
    };
  }

  function aggregate(fieldResults) {
    const statuses = Object.values(fieldResults).map((result) => result.status);
    if (statuses.includes("outcome_unknown")) return "outcome_unknown";
    const successes = statuses.filter((status) =>
      ["filled", "uploaded"].includes(status),
    );
    if (successes.length === statuses.length) return "applied";
    if (successes.length) return "partial";
    if (statuses.includes("failed")) return "failed";
    return "rejected";
  }

  async function apply(message) {
    const command = message.command;
    const requested = requestedEntries(command);
    const stale =
      !snapshot ||
      snapshot.id !== command.snapshot_id ||
      snapshot.page_url !== command.page_url ||
      !currentPage() ||
      requested.some(({ entry }) => !entry);
    if (stale) {
      snapshot = undefined;
      return {
        state: "rejected",
        field_results: rejectedResults(
          requested,
          "The page changed. Share this form again.",
        ),
        message: "The page changed. Share this form again.",
      };
    }
    for (const entry of snapshot.entries) {
      const current = refreshEntry(entry);
      if (
        !current ||
        JSON.stringify(structural(current.description)) !==
          JSON.stringify(structural(entry.description))
      ) {
        snapshot = undefined;
        return {
          state: "rejected",
          field_results: rejectedResults(
            requested,
            "A form field changed. Share a fresh snapshot.",
          ),
          message: "A form field changed. Share a fresh snapshot.",
        };
      }
    }

    for (const entry of snapshot.entries) {
      if (entry.customOptions && !(await validateSelect(entry))) {
        snapshot = undefined;
        return {
          state: "rejected",
          field_results: rejectedResults(
            requested,
            "Dropdown choices changed. Share a fresh form.",
          ),
          message: "Dropdown choices changed. Share this form again.",
        };
      }
    }

    const replacements = new Set(command.replace_fields);
    const fieldResults = {};
    try {
      for (const { id, entry } of requested) {
        if (!currentPage()) {
          fieldResults[id] = {
            status: "outcome_unknown",
            detail: "The page changed during apply.",
          };
        } else if (
          !refreshEntry(entry) ||
          JSON.stringify(structural(refreshEntry(entry).description)) !==
            JSON.stringify(structural(entry.description))
        ) {
          fieldResults[id] = {
            status: "outcome_unknown",
            detail:
              "This control changed after validation. Review it manually.",
          };
        } else if (preservationReason(entry, replacements.has(id))) {
          fieldResults[id] = {
            status: "preserved",
            detail: preservationReason(entry, replacements.has(id)),
          };
        } else if (entry.description.type === "unsupported") {
          fieldResults[id] = {
            status: "unsupported",
            detail:
              entry.description.unsupported_reason ||
              "Enter this value manually.",
          };
        } else if (entry.customOptions) {
          fieldResults[id] = await fillSelect(
            entry,
            command.fields[id],
            replacements.has(id),
          );
        } else if (Object.hasOwn(command.uploads, id)) {
          fieldResults[id] = await uploadFile(
            entry,
            message.files[id],
            replacements.has(id),
          );
        } else if (["radio", "checkbox"].includes(entry.description.type)) {
          fieldResults[id] = fillChoice(entry, command.fields[id]);
        } else {
          fieldResults[id] = fillText(entry, command.fields[id]);
        }
      }
    } catch {
      for (const { id } of requested) {
        fieldResults[id] ??= {
          status: "outcome_unknown",
          detail:
            "The page changed during apply. Review every requested field.",
        };
      }
    } finally {
      snapshot = undefined;
    }
    const state = aggregate(fieldResults);
    const messages = {
      applied: "Fields were applied. Review the page before submitting.",
      partial: "Some fields need manual review. Nothing was submitted.",
      rejected: "No fields were applied. Share a fresh form if needed.",
      failed: "The fields could not be applied. Nothing was submitted.",
      outcome_unknown:
        "The page changed during apply. Review every requested field before continuing.",
    };
    return { state, field_results: fieldResults, message: messages[state] };
  }

  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id) return false;
    if (
      !contracts ||
      !(contracts.InspectMessage(message) || contracts.ApplyMessage(message))
    ) {
      respond({
        state: "rejected",
        field_results: {},
        message:
          "Invalid or unsupported companion message. Reload the extension.",
      });
      return false;
    }
    if (applying || inspecting) {
      respond({
        state: "rejected",
        field_results:
          message.action === "apply"
            ? rejectedResults(
                requestedEntries(message.command),
                "Another command is being applied.",
              )
            : {},
        message:
          "Wait for the current form operation to finish before sharing or applying again.",
      });
      return false;
    }
    if (message.action === "inspect") {
      inspecting = true;
      inspectPage()
        .then(respond)
        .catch(() => {
          snapshot = undefined;
          respond({
            state: "rejected",
            field_results: {},
            message: "The form changed while sharing. Try again.",
          });
        })
        .finally(() => {
          inspecting = false;
        });
      return true;
    }
    applying = true;
    apply(message)
      .then(respond)
      .catch(() => {
        snapshot = undefined;
        respond({
          state: "outcome_unknown",
          field_results: Object.fromEntries(
            [
              ...Object.keys(message.command.fields),
              ...Object.keys(message.command.uploads),
            ].map((id) => [
              id,
              {
                status: "outcome_unknown",
                detail:
                  "The form became unavailable during this command. Review it manually.",
              },
            ]),
          ),
          message:
            "The form became unavailable. Review the requested fields before continuing.",
        });
      })
      .finally(() => {
        applying = false;
      });
    return true;
  });
})();
