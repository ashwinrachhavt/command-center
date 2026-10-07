// Shared DOM fill helpers for the companion content script and the adapter
// runner. Snapshot-independent: every function takes what it needs explicitly,
// so both flows report the same per-field outcomes from the same code.
(() => {
  if (globalThis.__commandCenterFormFillers) return;
  globalThis.__commandCenterFormFillers = true;

  const api = {};

  api.nativeValue = (element, prototype, value) => {
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (!setter) throw new Error("The browser could not update this control.");
    setter.call(element, value);
  };

  api.dispatchChanges = (element) => {
    const Event = element.ownerDocument.defaultView.Event;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  };

  api.finiteNumber = (value) =>
    typeof value === "string" &&
    value.length <= 100 &&
    /^-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value) &&
    Number.isFinite(Number(value));

  api.decodeBase64 = (value) => {
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1)
      bytes[index] = binary.charCodeAt(index);
    return bytes;
  };

  api.sha256 = async (bytes) => {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
  };

  api.acceptsFile = (accept, filename, mediaType) => {
    if (!accept) return true;
    const extensions = String(accept)
      .split(",")
      .map((part) => part.trim().toLowerCase())
      .filter(Boolean);
    const name = filename.toLowerCase();
    const type = mediaType.toLowerCase();
    return extensions.some((part) => {
      if (!part) return false;
      if (part.startsWith(".")) return name.endsWith(part);
      if (part.endsWith("/*")) return type.startsWith(part.slice(0, -1));
      return type === part;
    });
  };

  api.liveOnPage = (element) =>
    element.isConnected && element.ownerDocument.defaultView === globalThis;

  // Fill one native text/number/date/select/textarea control. The adapter
  // runner resolves entries as { description, elements } pairs, matching the
  // companion's captured entries, and checks validity against the live control.
  api.fillText = (entry, value, sinceStart) => {
    const element = entry.elements[0];
    const view = element.ownerDocument.defaultView;
    const type = element instanceof view.HTMLSelectElement
      ? "select"
      : element instanceof view.HTMLTextAreaElement
        ? "textarea"
        : element.type === "number" ? "number" : element.type;
    if (type === "number") {
      const candidate = element.cloneNode(false);
      candidate.value = value;
      if (!api.finiteNumber(value) || candidate.value !== value || !candidate.validity.valid)
        return { status: "rejected", detail: "Use a number within this field's allowed range and step." };
    }
    if (["date", "month"].includes(type)) {
      const candidate = element.cloneNode(false);
      candidate.value = value;
      if (!value || candidate.value !== value || !candidate.validity.valid)
        return { status: "rejected", detail: "Use a complete calendar value within this control's range and step." };
    }
    if (type === "select") {
      const options = Array.from(element.options).map((option) => option.value);
      if (!options.includes(value))
        return { status: "rejected", detail: "Choose one of the field's own options." };
      api.nativeValue(element, view.HTMLSelectElement.prototype, value);
    } else if (type === "textarea") {
      api.nativeValue(element, view.HTMLTextAreaElement.prototype, value);
    } else {
      api.nativeValue(element, view.HTMLInputElement.prototype, value);
    }
    api.dispatchChanges(element);
    if (!element.isConnected)
      return { status: "outcome_unknown", detail: "The page changed while this value was applied." };
    if (element.value !== value)
      return { status: "outcome_unknown", detail: "The page did not retain the value." };
    return { status: "filled", detail: "Value applied." };
  };

  // Fill one radio or checkbox choice.
  api.fillChoice = (entry, value) => {
    const element = entry.elements[0];
    if (element.type === "checkbox") {
      if (!["true", "false"].includes(value))
        return { status: "rejected", detail: "Checkbox values must be true or false." };
      const checked = value === "true";
      if (element.checked !== checked) element.click();
      if (!element.isConnected || element.checked !== checked)
        return { status: "outcome_unknown", detail: "The page changed while this choice was applied." };
      return { status: "filled", detail: "Choice applied." };
    }
    const selected = entry.elements.find((radio) => radio.value === value);
    if (!selected)
      return { status: "rejected", detail: "The radio option is no longer available." };
    if (!selected.checked) selected.click();
    if (!selected.isConnected || !selected.checked)
      return { status: "outcome_unknown", detail: "The page changed while this choice was applied." };
    return { status: "filled", detail: "Choice applied." };
  };

  // Attach one reviewed file via File + DataTransfer after pin checks.
  api.uploadFile = async (entry, transfer) => {
    const element = entry.elements[0];
    let bytes;
    try {
      bytes = api.decodeBase64(transfer.data_base64);
    } catch {
      return { status: "rejected", detail: "The reviewed file bytes are not valid base64." };
    }
    if (bytes.length !== transfer.size_bytes || (await api.sha256(bytes)) !== transfer.sha256)
      return { status: "rejected", detail: "The reviewed file does not match its pinned size and hash." };
    if (!api.acceptsFile(element.accept, transfer.filename, transfer.media_type))
      return { status: "rejected", detail: "The field does not accept this file type." };
    const view = element.ownerDocument.defaultView;
    const file = new view.File([bytes], transfer.filename, { type: transfer.media_type });
    const transferObject = new view.DataTransfer();
    transferObject.items.add(file);
    try {
      element.files = transferObject.files;
    } catch {
      return { status: "rejected", detail: "The field rejected the reviewed file." };
    }
    api.dispatchChanges(element);
    if (!element.isConnected || element.files.length !== 1)
      return { status: "outcome_unknown", detail: "The page changed while the file was attached." };
    const attached = element.files[0];
    if (attached.name !== transfer.filename || (await api.sha256(new Uint8Array(await attached.arrayBuffer()))) !== transfer.sha256)
      return { status: "outcome_unknown", detail: "The attached file failed its post-check." };
    return { status: "uploaded", detail: "File attached." };
  };

  globalThis.CommandCenterFormFillers = api;
})();
