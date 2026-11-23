// Captures des pages publiques en densité 2 : sert dist/ avec un faux back-office (même forme de page que
// sada/backoffice/public_react.py : index.html + <script id="boot">, mêmes réponses JSON que l'API publique)
// et photographie chaque vue avec Chromium. Prérequis : npm run build (dans packages/public).
//   node scripts/captures.mjs --out ~/dev/sada-design-refs/lotB   (CHROMIUM=/usr/bin/chromium si besoin)
// Vérifie aussi : pas d'erreur console, pas de débordement horizontal, mobile sans défilement vertical,
// écran TV tenant dans 1080 px, aucun bouton « plein écran ».
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const dist = fileURLToPath(new URL("../dist", import.meta.url));
const labels = JSON.parse(readFileSync(new URL("./labels-fr.json", import.meta.url), "utf8"));
const args = process.argv.slice(2);
const out = args.includes("--out") ? args[args.indexOf("--out") + 1] : fileURLToPath(new URL("../captures", import.meta.url));
mkdirSync(out, { recursive: true });

const TODAY = "2026-11-22";
const types = { ".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".woff": "font/woff" };
const hhmm = (min) => `${String(Math.floor(min / 60) % 24).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
const dayTimes = (i) => ({ fajr: hhmm(381 + i), sunrise: hhmm(478 + i), dhuhr: hhmm(746), asr: hhmm(878 - i), maghrib: hhmm(1012 - i), isha: hhmm(1100 - i) });
const LOGO = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#7b1e3a"/><path d="M32 12l6 14h14l-11 9 4 15-13-9-13 9 4-15-11-9h14z" fill="#f7f3ea"/></svg>';

function jours(iqama) {
  return [0, 1].map((i) => ({
    date: i ? "2026-11-23" : TODAY,
    gregorian: i ? "Lundi 23 novembre 2026" : "Dimanche 22 novembre 2026",
    hijri: `${20 + i} Joumada al-oula 1448`,
    times: dayTimes(i),
    iqama: iqama ? { fajr: hhmm(381 + i + 20), dhuhr: hhmm(746 + 20), asr: hhmm(878 - i + 15), maghrib: hhmm(1012 - i + 5), isha: hhmm(1100 - i + 17) } : {},
    jumua: [],
  }));
}
const boot = (v) => ({ api: "/api/v1/public/mosques/demo", name: "Mosquée de la Paix", timezone: "Europe/Paris", today: TODAY, accent: "", logo: "", month: "", labels, days: [], ...v });
const ERR404 = { status: 404, title: "Page introuvable", text: "Cette mosquée n'existe pas, ou elle ne publie pas ses horaires ici.", mawaqit_url: "", site: "sadakhutbah.org" };
const ERR422 = { status: 422, title: "Mois invalide", text: "Un mois s'écrit ainsi : 2027-03 (l'année, un tiret, le mois).", mawaqit_url: "", site: "sadakhutbah.org" };
const gabarit = readFileSync(join(dist, "index.html"), "utf8");

function monthJson(month) {
  const [a, m] = month.split("-").map(Number);
  const n = new Date(Date.UTC(a, m, 0)).getUTCDate();
  return { jumua: ["13:30", "14:15"], month, days: Array.from({ length: n }, (_, i) => ({ date: `${month}-${String(i + 1).padStart(2, "0")}`, times: dayTimes(i % 12), iqama: {} })) };
}

const serveur = createServer((req, rep) => {
  const url = new URL(req.url, "http://x");
  const p = url.pathname;
  if (p.startsWith("/api/v1/public/assets/p/")) {
    const f = join(dist, p.slice("/api/v1/public/assets/p/".length));
    if (!existsSync(f)) return void rep.writeHead(404).end();
    return void rep.writeHead(200, { "content-type": types[extname(f)] ?? "application/octet-stream" }).end(readFileSync(f));
  }
  if (p.endsWith("/prayer-times/days")) return void rep.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ days: jours(true) }));
  if (p.endsWith("/prayer-times")) return void rep.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(monthJson(url.searchParams.get("month") ?? "2026-11")));
  if (p.endsWith("/logo")) return void rep.writeHead(200, { "content-type": "image/svg+xml" }).end(LOGO);
  const q = url.searchParams;
  const v = q.get("v") ?? "screen";
  const b =
    v === "404" ? boot({ view: "error", error: ERR404, api: "" })
    : v === "422" ? boot({ view: "error", error: ERR422, api: "" })
    : v === "month" ? boot({ view: "month", month: q.get("month") ?? "2026-11", accent: q.get("accent") ?? "", logo: q.has("logo") ? "/api/v1/public/mosques/demo/logo" : "" })
    : boot({ view: "screen", days: jours(!q.has("sans")), accent: q.get("accent") ?? "", logo: q.has("logo") ? "/api/v1/public/mosques/demo/logo" : "" });
  const html = gabarit.replace("__ICON__", "data:,").replace("__TITLE__", "Sadā").replace("__BOOT__", JSON.stringify(b).replace(/</g, "\\u003c"));
  rep.writeHead(v === "404" ? 404 : v === "422" ? 422 : 200, { "content-type": "text/html; charset=utf-8" }).end(html);
});
await new Promise((ok) => serveur.listen(0, "127.0.0.1", ok));
const base = `http://127.0.0.1:${serveur.address().port}/m/demo`;

const TV = { width: 1920, height: 1080 };
const MOBILE = { width: 390, height: 844 };
const BUREAU = { width: 1440, height: 900 };
const vues = [
  ["tv-accueil", "v=screen", TV],
  ["tv-sans-iqama", "v=screen&sans=1", TV],
  ["tv-accent-bordeaux-logo", "v=screen&accent=%237b1e3a&logo=1", TV],
  ["mobile-accueil", "v=screen", MOBILE],
  ["mobile-sans-iqama", "v=screen&sans=1", MOBILE],
  ["mobile-accent-bordeaux-logo", "v=screen&accent=%237b1e3a&logo=1", MOBILE],
  ["mois-mobile", "v=month&month=2026-11", MOBILE],
  ["mois-ramadan-mobile", "v=month&month=2027-03", MOBILE],
  ["mois-bureau", "v=month&month=2026-11", BUREAU],
  ["mois-decembre-bureau", "v=month&month=2026-12", BUREAU],
  ["mois-ramadan-bureau", "v=month&month=2027-03&accent=%237b1e3a&logo=1", BUREAU],
  ["404-mobile", "v=404", MOBILE],
  ["404-tv", "v=404", TV],
  ["422-mobile", "v=422", MOBILE],
  ["422-bureau", "v=422", BUREAU],
];

const nav = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
let echecs = 0;
for (const [nom, requete, viewport] of vues) {
  const ctx = await nav.newContext({ viewport, deviceScaleFactor: 2, locale: "fr-FR" });
  // The fixtures are dated TODAY: freeze the page clock there (the page compares its clock with the
  // served days, and would otherwise refetch in a loop once the real date moves past TODAY).
  await ctx.clock.install({ time: new Date(`${TODAY}T12:00:00+01:00`) });
  const page = await ctx.newPage();
  const erreurs = [];
  page.on("pageerror", (e) => erreurs.push(e.message));
  page.on("console", (m) => m.type() === "error" && !/status of (404|422)/.test(m.text()) && erreurs.push(m.text()));
  const rep = await page.goto(`${base}?${requete}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  const m = await page.evaluate(() => ({
    doc: document.documentElement.scrollWidth, vue: innerWidth, haut: document.documentElement.scrollHeight, vh: innerHeight,
    plein: /plein écran|fullscreen|kiosk/i.test(document.body.innerText + [...document.querySelectorAll("button")].map((b) => b.outerHTML).join("")),
    boutons: document.querySelectorAll("button").length,
  }));
  const pb = [...erreurs];
  if (m.doc > m.vue) pb.push(`débordement horizontal ${m.doc} > ${m.vue}`);
  if (/^(mobile-|mois-.*mobile|404|422)/.test(nom) && m.haut > m.vh) pb.push(`défilement vertical ${m.haut} > ${m.vh}`);
  if (nom.startsWith("tv") && m.haut > m.vh) pb.push(`écran TV plus haut que la fenêtre ${m.haut}`);
  if (m.plein || (m.boutons && !nom.startsWith("mois"))) pb.push("bouton plein écran / kiosque");
  if (/404/.test(nom) && rep.status() !== 404) pb.push(`statut ${rep.status()}`);
  if (/422/.test(nom) && rep.status() !== 422) pb.push(`statut ${rep.status()}`);
  if (process.env.DUMP) {
    const t = await page.evaluate(() => { const r = (e) => { const b = e.getBoundingClientRect(); return `${Math.round(b.top)}-${Math.round(b.bottom)}`; };
      const h = document.querySelector("time"); const ul = document.querySelector("#root ul");
      return `html:${document.documentElement.className} horloge:${h ? r(h.parentElement.parentElement) : "-"} lignes:${ul ? r(ul) : "-"}\n` + document.body.innerText; });
    (await import("node:fs")).writeFileSync(join(process.env.DUMP, `${nom}.txt`), t);
  }
  await page.screenshot({ path: join(out, `${nom}.png`), fullPage: true });
  console.log(`${pb.length ? "ÉCHEC" : "ok   "} ${nom} (${m.doc}x${m.haut})${pb.length ? " : " + pb.join(" ; ") : ""}`);
  if (pb.length) echecs++;
  await ctx.close();
}
await nav.close();
serveur.close();
process.exit(echecs ? 1 : 0);
