// Copies the browser JS we ship (HTMX, Preline plugins) from node_modules into
// static/vendor, so the Python runtime never needs Node.
import { copyFileSync, mkdirSync } from "node:fs";

const out = "static/vendor";
mkdirSync(out, { recursive: true });

const files = [
  ["node_modules/htmx.org/dist/htmx.min.js", "htmx.min.js"],
  ["node_modules/preline/dist/overlay.js", "preline-overlay.js"],
  ["node_modules/preline/dist/accordion.js", "preline-accordion.js"],
  ["node_modules/preline/dist/collapse.js", "preline-collapse.js"],
];

// Self-hosted fallback fonts (no third-party requests). Apple devices render the system
// face (SF Pro / SF Arabic) and never download these. Elsewhere Inter covers Latin and
// IBM Plex Sans Arabic covers Arabic; unicode-range keeps each page to the script it uses.
const fonts = [
  ["@fontsource-variable/inter/files/inter-latin-wght-normal.woff2", "inter-latin.woff2"],
  ...[400, 500, 600, 700].map((w) => [
    `@fontsource/ibm-plex-sans-arabic/files/ibm-plex-sans-arabic-arabic-${w}-normal.woff2`,
    `plex-arabic-${w}.woff2`,
  ]),
];

for (const [from, to] of files) {
  copyFileSync(from, `${out}/${to}`);
  console.log(`vendored ${to}`);
}

mkdirSync("static/fonts", { recursive: true });
for (const [from, to] of fonts) {
  copyFileSync(`node_modules/${from}`, `static/fonts/${to}`);
  console.log(`vendored font ${to}`);
}
