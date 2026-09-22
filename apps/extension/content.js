(() => {
  if (globalThis.__commandCenterCompanionLoaded) return;
  globalThis.__commandCenterCompanionLoaded = true;

  const contracts = globalThis.CommandCenterContracts;
  const supportedTextTypes = new Set(["text", "email", "tel", "url"]);
  const sensitive =
    /password|passcode|one[ -]?time|\botp\b|social security|\bssn\b|credit card|card number|\bcvv\b|\bcvc\b|bank account|routing number|payment/i;
  let snapshot;
  let applying = false;

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
      .map((id) => trim(document.getElementById(id)?.textContent, 500))
      .filter(Boolean)
      .join(" ");
    return trim(
      labelsFor(element).join(" ") ||
        labelledBy ||
        element.getAttribute("aria-label") ||
        element.placeholder ||
        element.name ||
        element.id ||
        "Unnamed field",
      500,
    );
  }

  function isVisible(element) {
    const style = getComputedStyle(element);
    return (
      element.isConnected &&
      !element.disabled &&
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      element.getClientRects().length > 0
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
    for (const option of Array.from(options).slice(0, 100)) {
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
      required: Boolean(element.required),
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

  function radioEntry(element) {
    const name = element.name;
    if (!name)
      return unsupportedEntry(
        element,
        "Radio controls without a group name are unsupported.",
      );
    const radios = Array.from(
      document.querySelectorAll('input[type="radio"]'),
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
    if (!isVisible(element)) {
      if (
        element instanceof HTMLInputElement &&
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
    if (element.matches('[role="combobox"]'))
      return unsupportedEntry(
        element,
        "Custom comboboxes require manual review and entry.",
      );
    if (element.matches('[contenteditable="true"]'))
      return unsupportedEntry(
        element,
        "Rich text editors require manual review and entry.",
      );
    if (element instanceof HTMLTextAreaElement)
      return {
        key: element,
        elements: [element],
        description: basicDescription(element, "textarea"),
      };
    if (element instanceof HTMLSelectElement) {
      if (element.multiple)
        return unsupportedEntry(
          element,
          "Multi-select controls require manual review and entry.",
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
    if (!(element instanceof HTMLInputElement)) return null;
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

  function inspectPage() {
    const seen = new Set();
    const entries = [];
    for (const element of document.querySelectorAll(
      'input,textarea,select,[role="combobox"],[contenteditable="true"]',
    )) {
      const entry = describeElement(element);
      if (!entry || seen.has(entry.key)) continue;
      seen.add(entry.key);
      entry.capturedValues = localValues(entry);
      entry.edited = false;
      entries.push(entry);
      if (entries.length === 100) break;
    }
    snapshot = {
      id: crypto.randomUUID(),
      page_url: pageUrl(),
      full_url: location.href,
      entries,
    };
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
    if (entry.description.type === "radio")
      return entry.elements.some((radio) => radio.checked);
    if (entry.description.type === "checkbox") return element.checked;
    if (entry.description.type === "file")
      return Boolean(element.files?.length);
    return Boolean(element.value);
  }

  function localValues(entry) {
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
  for (const type of ["input", "change"]) {
    document.addEventListener(
      type,
      (event) => {
        for (const entry of snapshot?.entries ?? []) {
          if (entry.elements.includes(event.target)) entry.edited = true;
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
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fillText(entry, value) {
    const element = entry.elements[0];
    if (entry.description.type === "select") {
      if (!entry.description.options.includes(value))
        return {
          status: "rejected",
          detail: "Choose one of the captured options.",
        };
      nativeValue(element, HTMLSelectElement.prototype, value);
    } else if (entry.description.type === "textarea") {
      nativeValue(element, HTMLTextAreaElement.prototype, value);
    } else {
      nativeValue(element, HTMLInputElement.prototype, value);
    }
    dispatchChanges(element);
    if (!element.isConnected || location.href !== snapshot.full_url)
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
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "checked",
    )?.set;
    if (!setter)
      return {
        status: "failed",
        detail: "The browser could not update this choice.",
      };
    if (entry.description.type === "checkbox") {
      if (!["true", "false"].includes(value))
        return {
          status: "rejected",
          detail: "Checkbox values must be true or false.",
        };
      const element = entry.elements[0];
      const checked = value === "true";
      setter.call(element, checked);
      dispatchChanges(element);
      if (!element.isConnected || element.checked !== checked)
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
    setter.call(selected, true);
    dispatchChanges(selected);
    if (!selected.isConnected || !selected.checked)
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
    if (
      !element.isConnected ||
      !snapshot ||
      location.href !== snapshot.full_url
    )
      return {
        status: "outcome_unknown",
        detail: "The page changed during file verification.",
      };
    const preserved = preservationReason(entry, replace);
    if (preserved) return { status: "preserved", detail: preserved };
    const file = new File([bytes], transfer.filename, {
      type: transfer.media_type,
    });
    const data = new DataTransfer();
    data.items.add(file);
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
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
    if (!element.isConnected || !assigned)
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
      !element.isConnected
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
      snapshot.full_url !== location.href ||
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

    const replacements = new Set(command.replace_fields);
    const fieldResults = {};
    try {
      for (const { id, entry } of requested) {
        if (location.href !== snapshot.full_url) {
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
    if (applying) {
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
          "Wait for the current apply to finish before sharing or applying again.",
      });
      return false;
    }
    if (message.action === "inspect") {
      respond(inspectPage());
      return false;
    }
    applying = true;
    apply(message)
      .then(respond)
      .finally(() => {
        applying = false;
      });
    return true;
  });
})();
