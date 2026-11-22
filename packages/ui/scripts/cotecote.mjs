// Planches « côte à côte » : à gauche la capture de la console (console.mjs), à droite la capture du
// composant (visuel.mjs), au même format (densité 2, même hauteur de page). Une TV de 1920 px est
// ramenée à la largeur de la console de bureau (1440 px) pour tenir dans la même planche.
// Usage : node scripts/cotecote.mjs --console <dossier> --ui <dossier> --out <dossier>
import { mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { chromium } from "@playwright/test";

const args = process.argv.slice(2);
const opt = (n) => args[args.indexOf(n) + 1];
const [dc, du, out] = [opt("--console"), opt("--ui"), opt("--out")];
mkdirSync(out, { recursive: true });

// [nom de la planche, capture console, capture composant, largeur CSS de chaque capture]
const paires = [
  ["mobile-accueil", "console-dashboard-390", "horaires-écran--mobile-avec-iqama", 390],
  ["mobile-sans-iqama", "console-prayersettings-390", "horaires-écran--mobile-sans-iqama", 390],
  ["mobile-accent-bordeaux", "console-regie-390", "horaires-écran--mobile-accent-bordeaux", 390],
  ["mois-mobile", "console-sermons-390", "horaires-écran--mois-mobile", 390],
  ["erreur-mobile", "console-login-390", "horaires-écran--erreur-mobile", 390],
  ["galerie-bureau", "console-dashboard-1440", "base-console--galerie", 1440],
  ["tv-accueil", "console-regie-1440", "horaires-écran--tv-avec-iqama", 1440],
  ["mois-tv", "console-sermons-1440", "horaires-écran--mois-tv", 1440],
  ["erreur-tv", "console-login-1440", "horaires-écran--erreur-tv", 1440],
];
const data = (f) => "data:image/png;base64," + readFileSync(f).toString("base64");
const nav = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
for (const [nom, c, u, w] of paires) {
  const page = await (await nav.newContext({ viewport: { width: w * 2 + 48, height: 800 }, deviceScaleFactor: 2 })).newPage();
  await page.setContent(`<body style="margin:0;background:#888;display:flex;gap:16px;padding:16px;align-items:flex-start;font:12px sans-serif">
    <figure style="margin:0"><figcaption style="color:#fff;padding-bottom:4px">console</figcaption><img style="width:${w}px;display:block" src="${data(join(dc, c + ".png"))}"></figure>
    <figure style="margin:0"><figcaption style="color:#fff;padding-bottom:4px">@sada/ui</figcaption><img style="width:${w}px;display:block" src="${data(join(du, u + ".png"))}"></figure></body>`);
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(out, `${nom}.png`), fullPage: true });
  console.log("ok", nom);
}
await nav.close();
