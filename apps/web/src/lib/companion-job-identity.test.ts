import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const source = readFileSync(
  path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../../../extension/page-structure.js",
  ),
  "utf8",
);
// Execute the actual fixed reader's IIFE. Only location is supplied synthetically;
// the DOM is jsdom and no employer page scripts or browser session are involved.
const readPage = new Function(
  "document",
  "location",
  `return ${source.slice(source.indexOf("(() => {"))}`,
) as (
  document: Document,
  location: { href: string; origin: string; pathname: string },
) => {
  engine: string;
  full_url: string;
  page_url: string;
  title: string;
  controls: Array<{ label: string; type: string; required: boolean }>;
  job_context: { job_title: string; company_name: string; text: string } | null;
  job_identity: {
    platform: string;
    organization: string;
    posting_id: string;
    canonical_url: string;
  } | null;
};
const uuid = "12345678-90ab-cdef-1234-567890abcdef";
const upperUuid = uuid.toUpperCase();

function read(href: string, html = "") {
  document.body.innerHTML = html;
  document.title = "Synthetic application";
  let url: URL;
  try {
    url = new URL(href);
  } catch {
    url = new URL("https://unsupported.example/");
  }
  return readPage(document, {
    href,
    origin: url.origin,
    pathname: url.pathname,
  });
}

beforeEach(() => {
  document.head.innerHTML = "";
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
    { width: 10, height: 10 },
  ] as unknown as DOMRectList);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fixed reader URL identities", () => {
  it.each([
    [
      "https://boards.greenhouse.io/Acme/jobs/00123?gh_src=tracking#application",
      "greenhouse",
      "Acme",
      "00123",
      "https://job-boards.greenhouse.io/Acme/jobs/00123",
    ],
    [
      "https://job-boards.greenhouse.io/%41cme/jobs/123/",
      "greenhouse",
      "Acme",
      "123",
      "https://job-boards.greenhouse.io/Acme/jobs/123",
    ],
    [
      "https://boards.greenhouse.io/embed/job_app?for=Acme&token=123&source=tracking",
      "greenhouse",
      "Acme",
      "123",
      "https://job-boards.greenhouse.io/Acme/jobs/123",
    ],
    [
      "https://job-boards.greenhouse.io/embed/job_app/?token=00123&for=%41cme",
      "greenhouse",
      "Acme",
      "00123",
      "https://job-boards.greenhouse.io/Acme/jobs/00123",
    ],
    [
      `https://jobs.lever.co/Acme/${upperUuid}/apply?source=tracking`,
      "lever",
      "Acme",
      uuid,
      `https://jobs.lever.co/Acme/${uuid}`,
    ],
    [
      `https://jobs.eu.lever.co/Acme/${uuid}/`,
      "lever",
      "Acme",
      uuid,
      `https://jobs.eu.lever.co/Acme/${uuid}`,
    ],
    [
      `HTTPS://JOBS.LEVER.CO:443/Acme/${uuid}`,
      "lever",
      "Acme",
      uuid,
      `https://jobs.lever.co/Acme/${uuid}`,
    ],
    [
      `https://jobs.ashbyhq.com/Acme/${upperUuid}/application?utm_campaign=test`,
      "ashby",
      "Acme",
      uuid,
      `https://jobs.ashbyhq.com/Acme/${uuid}`,
    ],
    [
      `https://jobs.ashbyhq.com/Acme/${uuid}/`,
      "ashby",
      "Acme",
      uuid,
      `https://jobs.ashbyhq.com/Acme/${uuid}`,
    ],
    [
      "https://acme.wd5.myworkdayjobs.com/en-US/External/job/US-Remote/Senior_Engineer_R-123/apply/autofillWithResume?source=test",
      "workday",
      "acme.wd5.myworkdayjobs.com@External",
      "R-123",
      "https://acme.wd5.myworkdayjobs.com/en-US/External/job/US-Remote/Senior_Engineer_R-123",
    ],
    [
      "https://ACME.wd12.myworkdayjobs.com/External/job/London/Engineer_REQ1/apply",
      "workday",
      "acme.wd12.myworkdayjobs.com@External",
      "REQ1",
      "https://acme.wd12.myworkdayjobs.com/External/job/London/Engineer_REQ1",
    ],
    [
      "https://acme.wd1.myworkdayjobs.com/fr-FR/Careers/job/Paris/Engineer_REQ1/",
      "workday",
      "acme.wd1.myworkdayjobs.com@Careers",
      "REQ1",
      "https://acme.wd1.myworkdayjobs.com/fr-FR/Careers/job/Paris/Engineer_REQ1",
    ],
    [
      "https://careers-acme.icims.com/jobs/00123/synthetic-engineer/job?mode=apply#review",
      "icims",
      "careers-acme.icims.com",
      "00123",
      "https://careers-acme.icims.com/jobs/00123",
    ],
    [
      "https://CAREERS-ACME.icims.com/jobs/123",
      "icims",
      "careers-acme.icims.com",
      "123",
      "https://careers-acme.icims.com/jobs/123",
    ],
  ])(
    "normalizes %s without requiring a description or form",
    (url, platform, organization, postingId, canonicalUrl) => {
      const page = read(url);
      expect(page.job_identity).toEqual({
        platform,
        organization,
        posting_id: postingId,
        canonical_url: canonicalUrl,
      });
      expect(page.job_context).toBeNull();
      expect(page.controls).toEqual([]);
      expect(page.engine).toBe("agent-browser");
      expect(page.full_url).toBe(url);
      expect(page.page_url).toBe(new URL(url).origin + new URL(url).pathname);
      expect(page.job_identity?.canonical_url).not.toMatch(/[?#]/);
      expect(page.title).toBe("Synthetic application");
    },
  );

  it("keeps query-distinct jobs bound to their exact local reader URL", () => {
    const firstUrl =
      "https://boards.greenhouse.io/embed/job_app?for=Acme&token=123#application";
    const secondUrl =
      "https://boards.greenhouse.io/embed/job_app?for=Acme&token=456#application";
    const first = read(firstUrl);
    const second = read(secondUrl);
    expect(first.full_url).toBe(firstUrl);
    expect(second.full_url).toBe(secondUrl);
    expect(first.full_url).not.toBe(second.full_url);
    expect(first.page_url).toBe(second.page_url);
    expect(first.job_identity?.posting_id).toBe("123");
    expect(second.job_identity?.posting_id).toBe("456");
    expect(first.job_identity?.canonical_url).not.toMatch(/[?#]/);
    expect(second.job_identity?.canonical_url).not.toMatch(/[?#]/);
  });

  it("keeps matching Workday requisition IDs in different clusters distinct", () => {
    const first = read(
      "https://acme.wd1.myworkdayjobs.com/External/job/Remote/Engineer_REQ1",
    ).job_identity;
    const second = read(
      "https://acme.wd5.myworkdayjobs.com/External/job/Remote/Engineer_REQ1",
    ).job_identity;
    expect(first?.posting_id).toBe(second?.posting_id);
    expect(first?.organization).toBe("acme.wd1.myworkdayjobs.com@External");
    expect(second?.organization).toBe("acme.wd5.myworkdayjobs.com@External");
  });

  it.each([
    "https://boards.greenhouse.io/embed/job_app?for=Acme&for=Acme&token=123",
    "https://boards.greenhouse.io/embed/job_app?for=Acme&for=Other&token=123",
    "https://boards.greenhouse.io/embed/job_app?for=Acme&token=123&token=456",
    "https://boards.greenhouse.io/embed/job_app?for=Acme&token=123&token=123",
    "https://boards.greenhouse.io/embed/job_app?for=Acme&f%6fr=Other&token=123",
    "https://boards.greenhouse.io/embed/job_app?for=Acme",
    "https://boards.greenhouse.io/embed/job_app?for=Acme&token=abc",
    "https://boards.greenhouse.io/embed/job_app?for=Acme%2FOther&token=123",
    "https://boards.greenhouse.io/embed/job_app?for=%2541cme&token=123",
    "https://boards.greenhouse.io/Acme/jobs/123/apply",
    "https://boards.greenhouse.io/Acme/jobs/123/456",
    "https://job-boards.greenhouse.io/Acme/jobs/abc",
    `https://jobs.lever.co/Acme/${uuid}/apply/unknown`,
    `https://jobs.lever.co/Acme/${uuid}/edit`,
    "https://jobs.lever.co/Acme/not-a-uuid",
    `https://jobs.ashbyhq.com/Acme/${uuid}/apply`,
    `https://jobs.ashbyhq.com/Acme/${uuid}/application/unknown`,
    "https://acme.wd5.myworkdayjobs.com/en/External/job/Remote/Engineer_REQ1",
    "https://acme.wd5.myworkdayjobs.com/EN-us/External/job/Remote/Engineer_REQ1",
    "https://acme.wd5.myworkdayjobs.com/External/job/Remote/Engineer_REQ1/preview",
    "https://acme.wd5.myworkdayjobs.com/External/job/Remote/REQ1",
    "https://acme.wd5.myworkdayjobs.com/External/job/Remote/Engineer_",
    "https://acme.wd5.myworkdayjobs.com/External/job/Remote/Engineer_REQ.1",
    "https://acme.wd.myworkdayjobs.com/External/job/Remote/Engineer_REQ1",
    "https://acme.icims.com/jobs/abc/engineer/job",
    "https://acme.icims.com/job/123/engineer",
  ])("returns null for ambiguous or unsupported job paths: %s", (url) => {
    expect(read(url).job_identity).toBeNull();
  });

  it.each([
    "http://boards.greenhouse.io/Acme/jobs/123",
    "https://user:password@boards.greenhouse.io/Acme/jobs/123",
    "https://@boards.greenhouse.io/Acme/jobs/123",
    "https://boards.greenhouse.io:444/Acme/jobs/123",
    "https://boards.greenhouse.io.evil.example/Acme/jobs/123",
    "https://evil-boards.greenhouse.io/Acme/jobs/123",
    "https://boards.greenhouse.io./Acme/jobs/123",
    "https://careers.acme.example/Acme/jobs/123",
    "https://127.0.0.1/Acme/jobs/123",
    "https://localhost/Acme/jobs/123",
    "https://[::1]/Acme/jobs/123",
    "https://boards.greenhouse.io//Acme/jobs/123",
    "https://boards.greenhouse.io/Acme/jobs/123//",
    "https://boards.greenhouse.io/Acme%2FOther/jobs/123",
    "https://boards.greenhouse.io/Acme%5COther/jobs/123",
    "https://boards.greenhouse.io/Acme%3FOther/jobs/123",
    "https://boards.greenhouse.io/Acme%23Other/jobs/123",
    "https://boards.greenhouse.io/Acme%252FOther/jobs/123",
    "https://boards.greenhouse.io/Acme%00/jobs/123",
    "https://boards.greenhouse.io/%2e%2e/Acme/jobs/123",
    "https://boards.greenhouse.io/Other/../Acme/jobs/123",
    "https://boards.greenhouse.io/%E0%A4%A/jobs/123",
    " https://boards.greenhouse.io/Acme/jobs/123",
    "https://boards.greenhouse.io/Acme/jobs/123\n",
    "https://boards.greenhouse.io/Acme\t/jobs/123",
    "https://boards.greenhouse.io/Acme/jobs/123?source=\u00a0",
    "https://boards.greenhouse.io/Acme/jobs/123?source=\u0085",
    "https://boards.greenhouse.io/Acme\\jobs\\123",
    "javascript:alert('not executed')",
    "/Acme/jobs/123",
  ])("rejects unsafe origins, delimiters, and malformed URLs: %s", (url) => {
    expect(read(url).job_identity).toBeNull();
  });

  it("bounds input length, path depth, segments, posting IDs and combined Workday organizations", () => {
    for (const url of [
      `https://boards.greenhouse.io/Acme/jobs/123?private=${"x".repeat(4096)}`,
      `https://acme.icims.com/jobs/123/${Array.from({ length: 15 }, () => "step").join("/")}`,
      `https://boards.greenhouse.io/${"a".repeat(201)}/jobs/123`,
      `https://boards.greenhouse.io/Acme/jobs/${"1".repeat(201)}`,
      `https://${"a".repeat(63)}.wd5.myworkdayjobs.com/${"S".repeat(137)}/job/Remote/Engineer_REQ1`,
    ])
      expect(read(url).job_identity).toBeNull();
    expect(
      read(
        `https://boards.greenhouse.io/${"a".repeat(200)}/jobs/${"1".repeat(200)}`,
      ).job_identity,
    ).not.toBeNull();
  });

  it("does not use or return private query values, fragments, or form values for identity", () => {
    const page = read(
      "https://boards.greenhouse.io/Acme/jobs/123?email=private-email&token=private-session&gh_jid=456#private-fragment",
      `
      <h1>Synthetic role</h1><section id="job_description"><p>Build reliable tools.</p>
      <form><label>Company<input value="Private Company"></label><label>Answer<textarea>Private answer</textarea></label></form>
      <div contenteditable="true" aria-label="Notes">Private editable note</div></section>`,
    );
    expect(page.job_identity).toEqual({
      platform: "greenhouse",
      organization: "Acme",
      posting_id: "123",
      canonical_url: "https://job-boards.greenhouse.io/Acme/jobs/123",
    });
    expect(page.job_context?.company_name).toBe("");
    expect(page.job_context?.text).toBe("Build reliable tools.");
    expect(page.controls.map((control) => control.label)).toEqual([
      "Company",
      "Answer",
      "Notes",
    ]);
    const { full_url: localCaptureUrl, ...pageMetadata } = page;
    expect(localCaptureUrl).toBe(
      "https://boards.greenhouse.io/Acme/jobs/123?email=private-email&token=private-session&gh_jid=456#private-fragment",
    );
    expect(JSON.stringify(pageMetadata)).not.toMatch(/private|Private|456/);
  });

  it("keeps JSON-LD description metadata separate from URL identity and never executes page scripts or networking", () => {
    const pageScript = vi.fn();
    const network = vi.spyOn(global, "fetch");
    vi.stubGlobal("identityPageCode", pageScript);
    const posting = {
      "@type": "JobPosting",
      title: "Synthetic title",
      hiringOrganization: { name: "Different displayed organization" },
      identifier: "untrusted-other-id",
      url: `https://jobs.lever.co/Other/${uuid}`,
      description:
        "<p>Useful description.</p><script>identityPageCode()</script><form><textarea>Private saved answer</textarea></form>",
    };
    const page = read(
      `https://jobs.ashbyhq.com/URL-Organization/${uuid}`,
      `<script>identityPageCode()</script><script type="application/ld+json">${JSON.stringify(posting).replaceAll("<", "\\u003c")}</script>`,
    );
    expect(page.job_context).toMatchObject({
      job_title: "Synthetic title",
      company_name: "Different displayed organization",
      text: "Useful description.",
    });
    expect(page.job_identity).toMatchObject({
      platform: "ashby",
      organization: "URL-Organization",
      posting_id: uuid,
    });
    expect(pageScript).not.toHaveBeenCalled();
    expect(network).not.toHaveBeenCalled();
    expect(JSON.stringify(page)).not.toMatch(
      /untrusted-other-id|Private saved answer/,
    );
    expect(
      read(
        "https://custom.example/careers/job",
        `<script type="application/ld+json">${JSON.stringify(posting).replaceAll("<", "\\u003c")}</script>`,
      ).job_identity,
    ).toBeNull();
  });

  it("retains URL identity when description data is malformed or describes multiple jobs", () => {
    const url = "https://boards.greenhouse.io/Acme/jobs/123";
    const ambiguous = {
      "@graph": [
        { "@type": "JobPosting", description: "First role" },
        { "@type": "JobPosting", description: "Second role" },
      ],
    };
    for (const data of ["not valid JSON", JSON.stringify(ambiguous)]) {
      const page = read(
        url,
        `<script type="application/ld+json">${data}</script>`,
      );
      expect(page.job_context).toBeNull();
      expect(page.job_identity?.posting_id).toBe("123");
    }
  });
});
