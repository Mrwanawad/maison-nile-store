// Copies the browser JS we ship (HTMX, Preline overlay) from node_modules into
// app/static/vendor, so the Python runtime never needs Node.
import { copyFileSync, mkdirSync } from "node:fs";

const out = "app/static/vendor";
mkdirSync(out, { recursive: true });

const files = [
  ["node_modules/htmx.org/dist/htmx.min.js", "htmx.min.js"],
  ["node_modules/preline/dist/overlay.js", "preline-overlay.js"],
];

for (const [from, to] of files) {
  copyFileSync(from, `${out}/${to}`);
  console.log(`vendored ${to}`);
}
