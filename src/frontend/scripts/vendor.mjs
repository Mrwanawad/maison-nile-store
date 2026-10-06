// Copies the browser JS we ship (HTMX, Preline plugins, Motion) from node_modules into
// static/vendor, so the Python runtime never needs Node.
import { copyFileSync, mkdirSync } from "node:fs";

const out = "static/vendor";
mkdirSync(out, { recursive: true });

const files = [
  ["node_modules/htmx.org/dist/htmx.min.js", "htmx.min.js"],
  ["node_modules/preline/dist/overlay.js", "preline-overlay.js"],
  ["node_modules/preline/dist/accordion.js", "preline-accordion.js"],
  ["node_modules/preline/dist/collapse.js", "preline-collapse.js"],
  ["node_modules/motion/dist/motion.js", "motion.js"],
];

// Self-hosted fonts (no third-party requests). Readex Pro (variable, Latin + Arabic) carries
// display and body; Instrument Serif italic (Latin) and Amiri (Arabic) are the serif accent.
const fonts = [
  ["@fontsource/instrument-serif/files/instrument-serif-latin-400-italic.woff2", "instrument-serif-italic.woff2"],
  ["@fontsource/amiri/files/amiri-arabic-400-normal.woff2", "amiri-arabic.woff2"],
  ["@fontsource-variable/readex-pro/files/readex-pro-latin-wght-normal.woff2", "readex-latin.woff2"],
  ["@fontsource-variable/readex-pro/files/readex-pro-arabic-wght-normal.woff2", "readex-arabic.woff2"],
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
