(() => {
  if (globalThis.__commandCenterCompanion) return;
  globalThis.__commandCenterCompanion = true;
  let snapshot;
  const sensitive =
    /password|passcode|one.time|credit.?card|card.?number|cvv|cvc|social.?security|\bssn\b|bank.?account|routing.?number|secret|api.?key/i;
  const pageUrl = () => location.origin + location.pathname;
  function available(element) {
    return (
      element.isConnected &&
      !element.disabled &&
      !element.readOnly &&
      element.getClientRects().length > 0
    );
  }
  function describe(element) {
    const type =
      element.tagName === "TEXTAREA"
        ? "textarea"
        : element.tagName === "SELECT"
          ? "select"
          : element.type;
    const label = (
      Array.from(element.labels ?? [])
        .map((l) => l.textContent.trim())
        .join(" ") ||
      element.getAttribute("aria-label") ||
      element.placeholder ||
      element.name ||
      "Unnamed field"
    ).slice(0, 500);
    if (
      !["text", "email", "tel", "url", "textarea", "select"].includes(type) ||
      !available(element) ||
      sensitive.test(label + " " + element.name + " " + element.autocomplete) ||
      element.multiple
    )
      return null;
    return {
      label,
      type,
      required: element.required,
      options:
        type === "select"
          ? Array.from(element.options)
              .slice(0, 100)
              .map((o) => o.value.slice(0, 300))
          : [],
    };
  }
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id) return;
    if (message.action === "inspect") {
      const entries = Array.from(
        document.querySelectorAll("input,textarea,select"),
      )
        .map((element) => ({ element, description: describe(element) }))
        .filter((item) => item.description)
        .slice(0, 100);
      snapshot = {
        id: crypto.randomUUID(),
        page_url: pageUrl(),
        full_url: location.href,
        entries,
      };
      respond({
        id: snapshot.id,
        page_url: snapshot.page_url,
        title: document.title.slice(0, 300),
        fields: entries.map((item, index) => ({
          id: `f${index}`,
          ...item.description,
        })),
      });
    }
    if (message.action === "apply") {
      const command = message.command;
      if (
        !snapshot ||
        snapshot.id !== command.snapshot_id ||
        snapshot.page_url !== command.page_url ||
        snapshot.full_url !== location.href
      ) {
        respond({
          state: "rejected",
          message: "The page changed. Share this form again.",
        });
        return;
      }
      const changes = Object.entries(command.fields).map(([id, value]) => ({
        item: /^f\d+$/.test(id) ? snapshot.entries[Number(id.slice(1))] : null,
        value,
      }));
      if (
        changes.some(
          ({ item, value }) =>
            !item ||
            typeof value !== "string" ||
            value.length > 5000 ||
            JSON.stringify(describe(item.element)) !==
              JSON.stringify(item.description) ||
            (item.description.type === "select" &&
              !item.description.options.includes(value)),
        )
      ) {
        respond({
          state: "rejected",
          message: "A form field changed. Share a fresh snapshot.",
        });
        return;
      }
      try {
        for (const { item, value } of changes) {
          if (!available(item.element) || location.href !== snapshot.full_url)
            throw new Error("Page changed during fill");
          const prototype =
            item.description.type === "textarea"
              ? HTMLTextAreaElement.prototype
              : item.description.type === "select"
                ? HTMLSelectElement.prototype
                : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(prototype, "value").set.call(
            item.element,
            value,
          );
          item.element.dispatchEvent(new Event("input", { bubbles: true }));
          item.element.dispatchEvent(new Event("change", { bubbles: true }));
        }
        respond({
          state: "applied",
          message: "Fields filled. Review the page before submitting.",
        });
      } catch {
        respond({
          state: "outcome_unknown",
          message:
            "The page changed during filling. Review it before trying anything else.",
        });
      }
      snapshot = undefined;
    }
  });
})();
