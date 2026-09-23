// Fixed page reader. JobPosting JSON-LD is parsed as data; page scripts are never executed.
(() => {
  const bounded = (value, size = 500) =>
    (typeof value === "string" ? value : "").trim().slice(0, size);
  const controls = [];
  const sourceText = (node) => {
    if (
      node.matches?.(
        "input,select,textarea,form,[contenteditable],[hidden],[aria-hidden=true]",
      )
    )
      return "";
    const copy = node.cloneNode(true);
    copy
      .querySelectorAll(
        "script,style,form,input,select,textarea,button,[contenteditable],iframe,video,audio,[hidden],[aria-hidden=true]",
      )
      .forEach((child) => child.remove());
    copy
      .querySelectorAll("p,li,h1,h2,h3,h4,div,br")
      .forEach((child) => child.append("\n"));
    return String(copy.textContent ?? "")
      .replace(/[ \t]+/g, " ")
      .replace(/\n\s*\n\s*\n/g, "\n\n")
      .trim();
  };
  const jobContext = () => {
    const postings = [];
    let remaining = 262144;
    for (const script of Array.from(
      document.querySelectorAll('script[type="application/ld+json"]'),
    ).slice(0, 12)) {
      const raw = script.textContent ?? "";
      if (raw.length > remaining) continue;
      remaining -= raw.length;
      try {
        const pending = [{ value: JSON.parse(raw), depth: 0 }];
        let visited = 0;
        while (pending.length && visited++ < 100) {
          const { value, depth } = pending.pop();
          if (!value || typeof value !== "object" || depth > 6) continue;
          if (Array.isArray(value)) {
            pending.push(
              ...value
                .slice(0, 50)
                .map((item) => ({ value: item, depth: depth + 1 })),
            );
            continue;
          }
          if (
            [value["@type"]]
              .flat()
              .some(
                (type) =>
                  type === "JobPosting" ||
                  type === "https://schema.org/JobPosting",
              )
          ) {
            if (
              typeof value.description === "string" &&
              value.description.trim()
            )
              postings.push(value);
          }
          if (value["@graph"])
            pending.push({ value: value["@graph"], depth: depth + 1 });
        }
      } catch {
        /* An invalid structured-data block is not a job description. */
      }
    }
    if (postings.length > 1) return null;
    if (postings.length === 1) {
      try {
        const posting = postings[0];
        const template = document.createElement("template");
        // Template contents remain inert; nothing is inserted into the live page.
        template.innerHTML = posting.description.slice(0, 100000);
        const text = sourceText(template.content);
        if (text)
          return {
            job_title:
              bounded(posting.title, 300) || bounded(posting.name, 300),
            company_name: bounded(posting.hiringOrganization?.name, 200),
            text: text.slice(0, 30000),
            extraction_method: "json_ld",
            truncated:
              text.length > 30000 || posting.description.length > 100000,
          };
      } catch {
        /* A site's Trusted Types policy may disallow parsing its HTML description. */
      }
    }
    for (const selector of [
      "[data-automation-id=jobPostingDescription]",
      "#job_description",
      "[data-testid=job-description]",
      ".ashby-job-posting-description",
      ".posting-description",
      "[itemprop=description]",
    ]) {
      const matches = Array.from(document.querySelectorAll(selector)).filter(
        (node) => node.getClientRects().length,
      );
      if (matches.length > 1) return null;
      if (matches.length !== 1) continue;
      const text = sourceText(matches[0]);
      if (text)
        return {
          job_title: bounded(
            document.querySelector("h1")?.textContent || document.title,
            300,
          ),
          company_name: "",
          text: text.slice(0, 30000),
          extraction_method: "semantic_dom",
          truncated: text.length > 30000,
        };
    }
    return null;
  };
  const labelText = (node) => {
    const copy = node.cloneNode(true);
    copy
      .querySelectorAll("input,select,textarea,[contenteditable]")
      .forEach((control) => control.remove());
    return copy.textContent;
  };
  let skippedFrames = 0;
  const visit = (doc, depth = 0) => {
    for (const node of doc.querySelectorAll(
      "input,select,textarea,[role=combobox],[contenteditable=true]",
    )) {
      if (controls.length >= 100) break;
      const type =
        node.getAttribute("type") ||
        node.getAttribute("role") ||
        node.tagName.toLowerCase();
      if (["hidden", "password", "submit", "button", "reset"].includes(type))
        continue;
      if (!node.getClientRects().length && type !== "file") continue;
      const label = bounded(
        Array.from(node.labels ?? [])
          .map(labelText)
          .join(" ") ||
          bounded(node.getAttribute("aria-labelledby"))
            .split(/\s+/)
            .map((id) => doc.getElementById(id)?.textContent ?? "")
            .join(" ")
            .trim() ||
          node.getAttribute("aria-label") ||
          node.getAttribute("placeholder") ||
          node.getAttribute("name") ||
          node.id,
      );
      if (
        /password|passcode|\botp\b|social security|\bssn\b|credit card|card number|\bcvv\b|bank account|routing number/i.test(
          label,
        )
      )
        continue;
      controls.push({
        label,
        type: bounded(type, 50),
        required:
          node.required === true ||
          node.getAttribute("aria-required") === "true",
      });
    }
    if (depth < 3)
      for (const frame of doc.querySelectorAll("iframe")) {
        try {
          if (frame.contentDocument) visit(frame.contentDocument, depth + 1);
          else skippedFrames += 1;
        } catch {
          skippedFrames += 1;
        }
      }
  };
  visit(document);
  return {
    engine: "agent-browser",
    page_url: location.origin + location.pathname,
    title: bounded(document.title, 300),
    headings: Array.from(document.querySelectorAll("h1,h2"))
      .slice(0, 8)
      .map((node) => bounded(node.textContent, 300)),
    controls,
    skipped_frames: skippedFrames,
    job_context: jobContext(),
  };
})();
