"use client";

/** Display exactly the checkpointed HTML in an isolated, network-free document. */
export function EmailPreview({ html }: { html: string }) {
  const document = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'"><style>body{margin:16px;color:#202124;background:white;font:15px/1.7 system-ui,sans-serif;overflow-wrap:anywhere}p{margin:0 0 12px}blockquote{border-left:3px solid #d1d5db;margin:12px 0;padding-left:12px}pre{white-space:pre-wrap}a{color:#1d4ed8}img{max-width:100%}</style></head><body>${html}</body></html>`;
  return (
    <iframe
      title="Saved email preview"
      sandbox=""
      referrerPolicy="no-referrer"
      srcDoc={document}
      className="h-64 w-full rounded-md border bg-white"
    />
  );
}
