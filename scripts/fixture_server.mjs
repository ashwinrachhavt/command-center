// Synthetic extension fixture only. Never exposes local configuration or other files.
import { createServer } from "node:http";
import { readFileSync } from "node:fs";

const fixture = readFileSync(
  new URL("../apps/web/public/fixtures/application.html", import.meta.url),
);
createServer((request, response) => {
  if (request.url === "/health") {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end('{"status":"ready"}');
  } else if (request.url?.split("?")[0] === "/fixtures/application.html") {
    response.writeHead(200, { "Content-Type": "text/html" });
    response.end(fixture);
  } else {
    response.writeHead(404);
    response.end();
  }
}).listen(4319, process.env.FIXTURE_HOST ?? "127.0.0.1");
