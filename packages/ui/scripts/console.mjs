// Captures de la console (web/) servie par Vite : Dashboard, Régie, Réglages > Horaires de prière, Khutbas,
// à 1440 et 390 px, densité 2. Sert de référence à côté des composants (voir visuel.mjs).
// Usage : node scripts/console.mjs --out <dossier> [--url http://127.0.0.1:5173] [--user admin] ; mot de passe dans SADA_DEV_PASSWORD.
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { chromium } from "@playwright/test";

const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const base = opt("--url", "http://127.0.0.1:5173");
const out = opt("--out", "captures-console");
mkdirSync(out, { recursive: true });
const nav = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const ecrans = [
  ["dashboard", "/", null],
  ["regie", "/regie", null],
  ["prayersettings", "/settings", "prayer"],
  ["sermons", "/khutbas", null],
];
for (const [w, h, tag] of [[1440, 900, "1440"], [390, 844, "390"]]) {
  const ctx = await nav.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, locale: "fr-FR" });
  const page = await ctx.newPage();
  await page.goto(base + "/", { waitUntil: "load" });
  await page.waitForSelector("input[name=username]");
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: join(out, `console-login-${tag}.png`), fullPage: true });
  await page.fill("input[name=username]", opt("--user", "admin"));
  await page.fill("input[name=password]", process.env.SADA_DEV_PASSWORD ?? "");
  await page.click("button[type=submit]");
  await page.waitForTimeout(1500);
  for (const [nom, chemin, onglet] of ecrans) {
    await page.goto(base + chemin, { waitUntil: "load" });
    await page.waitForTimeout(1500);
    if (onglet) {
      // L'onglet des réglages est choisi par son intitulé (Horaires de prière).
      await page.getByRole("tab", { name: /prière|horaires|prayer/i }).first().click();
      await page.waitForTimeout(1500);
    }
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: join(out, `console-${nom}-${tag}.png`), fullPage: true });
    console.log("ok", nom, tag);
  }
  await ctx.close();
}
await nav.close();
