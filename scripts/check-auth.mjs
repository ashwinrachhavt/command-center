// Verify the actual Next.js environment against Clerk, without printing credentials.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, chmodSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const require = createRequire(`${root}apps/web/package.json`);
require("@next/env").loadEnvConfig(`${root}apps/web`, true);

try {
  const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";
  const secret = process.env.CLERK_SECRET_KEY ?? "";
  if (!/^pk_(test|live)_/.test(key) || !/^sk_(test|live)_/.test(secret)) {
    throw new Error("Add the matching Clerk publishable and secret keys to apps/web/.env.");
  }
  const host = Buffer.from(key.split("_").slice(2).join("_"), "base64").toString().replace(/\$$/, "");
  const issuer = new URL(`https://${host}`);
  if (issuer.username || issuer.password || issuer.pathname !== "/" || issuer.search || issuer.hash) {
    throw new Error("Clerk publishable key contains an invalid issuer.");
  }
  const responses = await Promise.all([
    fetch(`${issuer.origin}/.well-known/jwks.json`, { signal: AbortSignal.timeout(10000) }),
    fetch("https://api.clerk.com/v1/jwks", { headers: { Authorization: `Bearer ${secret}` }, signal: AbortSignal.timeout(10000) }),
  ]);
  if (responses.some(response => !response.ok)) throw new Error("Clerk could not verify the configured key pair.");
  const [publicKeys, privateKeys] = await Promise.all(responses.map(response => response.json()));
  if (!publicKeys.keys.some(key => privateKeys.keys.some(other => key.kid === other.kid && key.n === other.n))) {
    throw new Error("The Clerk keys belong to different applications.");
  }
  const path = `${root}.env`;
  let env = readFileSync(path, "utf8");
  const current = env.match(/^CC_CLERK_ISSUER=(.*)$/m)?.[1];
  if (process.argv.includes("--sync")) {
    for (const [name, value] of Object.entries({ CC_AUTH_MODE: "clerk", CC_CLERK_ISSUER: issuer.origin, NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: key })) {
      const pattern = new RegExp(`^${name}=.*$`, "m");
      env = pattern.test(env) ? env.replace(pattern, `${name}=${value}`) : `${env.trimEnd()}\n${name}=${value}\n`;
    }
    writeFileSync(path, env, { mode: 0o600 });
    chmodSync(path, 0o600);
    console.log("Clerk verified. FastAPI issuer and Docker public build key synchronized. Restart the API after changing keys.");
  } else if (current !== issuer.origin) {
    throw new Error("FastAPI issuer differs from Next.js. Run make auth-sync after changing Clerk credentials.");
  } else {
    console.log("Clerk keys match; Next.js and FastAPI use the same issuer.");
  }
} catch (error) {
  console.error(error instanceof Error && !error.message.includes("fetch") ? error.message : "Clerk verification failed. Check credentials and network access.");
  process.exitCode = 1;
}
