// Copies the browser JS we ship (HTMX, Preline overlay) from node_modules into
// static/vendor, so the Python runtime never needs Node.
import { copyFileSync, mkdirSync } from "node:fs";

const out = "static/vendor";
mkdirSync(out, { recursive: true });

const files = [
  ["node_modules/htmx.org/dist/htmx.min.js", "htmx.min.js"],
  ["node_modules/preline/dist/overlay.js", "preline-overlay.js"],
];

// Self-hosted fonts (no third-party requests): Latin for EN, Arabic for AR.
const fonts = [
  ["@fontsource-variable/fraunces/files/fraunces-latin-opsz-normal.woff2", "fraunces-latin.woff2"],
  ["@fontsource-variable/manrope/files/manrope-latin-wght-normal.woff2", "manrope-latin.woff2"],
  ["@fontsource-variable/alexandria/files/alexandria-arabic-wght-normal.woff2", "alexandria-arabic.woff2"],
  ["@fontsource/ibm-plex-sans-arabic/files/ibm-plex-sans-arabic-arabic-400-normal.woff2", "plex-arabic-400.woff2"],
  ["@fontsource/ibm-plex-sans-arabic/files/ibm-plex-sans-arabic-arabic-500-normal.woff2", "plex-arabic-500.woff2"],
  ["@fontsource/ibm-plex-sans-arabic/files/ibm-plex-sans-arabic-arabic-600-normal.woff2", "plex-arabic-600.woff2"],
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
