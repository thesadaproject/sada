// Extrait le tracé du mot صدى depuis assets/logo/sada-mark-or.svg vers src/logo-data.ts.
// Usage : node packages/ui/scripts/gen-logo.mjs
import { readFileSync, writeFileSync } from "node:fs";

const svg = readFileSync(new URL("../../../assets/logo/sada-mark-or.svg", import.meta.url), "utf8");
const pick = (re) => { const m = svg.match(re); if (!m) throw new Error(`absent : ${re}`); return m[1]; };

writeFileSync(
  new URL("../src/logo-data.ts", import.meta.url),
  `/** Généré par scripts/gen-logo.mjs depuis assets/logo/sada-mark-or.svg (le mot صدى).
 *  Ne pas éditer à la main. Jamais le croissant de static/emblem.svg. */
export const LOGO_VIEWBOX = ${JSON.stringify(pick(/viewBox="([^"]+)"/))};
export const LOGO_TRANSFORM = ${JSON.stringify(pick(/transform="([^"]+)"/))};
export const LOGO_PATH = ${JSON.stringify(pick(/ d="([^"]+)"/))};
`,
);
