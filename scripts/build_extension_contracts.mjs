// Compile Python JSON Schemas ahead of time: no eval or remote code in the extension.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const require = createRequire(`${root}apps/web/package.json`);
const Ajv = require("ajv/dist/2020");
const addFormats = require("ajv-formats");
const standalone = require("ajv/dist/standalone").default;
const { build } = require("esbuild");
const schemas = JSON.parse(
  readFileSync(`${root}.local/browser-contracts.json`, "utf8"),
);
const ajv = new Ajv({ code: { source: true }, strict: false });
addFormats(ajv);
for (const [name, schema] of Object.entries(schemas))
  ajv.addSchema(schema, name);
const source = standalone(
  ajv,
  Object.fromEntries(Object.keys(schemas).map((name) => [name, name])),
);
const result = await build({
  stdin: {
    contents: source,
    resolveDir: `${root}apps/web`,
    sourcefile: "contracts.cjs",
  },
  bundle: true,
  write: false,
  format: "iife",
  globalName: "CommandCenterContracts",
  platform: "browser",
  target: "chrome120",
  minify: true,
  legalComments: "none",
  banner: {
    js: "// Generated from Python browser_contracts.py by make contracts. Do not edit.",
  },
});
const path = `${root}apps/extension/contracts.js`;
const generated = result.outputFiles[0].text;
if (process.argv.includes("--check")) {
  if (readFileSync(path, "utf8") !== generated)
    throw new Error("Extension contracts are stale; run make contracts.");
} else {
  writeFileSync(path, generated);
}
