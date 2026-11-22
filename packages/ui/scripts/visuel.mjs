// Test visuel de @sada/ui : sert storybook-static, ouvre chaque story à sa taille (390 px mobile,
// 1920x1080 TV selon le nom) et
//   - vérifie qu'elle s'affiche sans erreur console et sans débordement horizontal ;
//   - enregistre une capture PNG en densité 2 dans le dossier donné (--out, défaut : captures/).
// Avec --compare <dossier>, compare en plus pixel à pixel aux captures de référence de ce dossier
// (tolérance --seuil, 0.5 % des pixels par défaut) : réservé au poste de développement, car le rendu
// des polices diffère d'une machine à l'autre ; la CI ne lance que les vérifications.
// Prérequis : npm run build-storybook (dans packages/ui).
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const racine = fileURLToPath(new URL("../storybook-static", import.meta.url));
const args = process.argv.slice(2);
const opt = (nom, defaut) => { const i = args.indexOf(nom); return i >= 0 ? args[i + 1] : defaut; };
const sortie = opt("--out", fileURLToPath(new URL("../captures", import.meta.url)));
const reference = opt("--compare", null);
const seuil = Number(opt("--seuil", "0.005"));
const filtre = opt("--filtre", "");

if (!existsSync(join(racine, "index.json"))) { console.error("storybook-static absent : lancer npm run build-storybook"); process.exit(2); }

const types = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff", ".png": "image/png" };
const serveur = createServer((req, rep) => {
  const chemin = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname)).replace(/^(\.\.[/\\])+/, "");
  const fichier = join(racine, chemin === "/" ? "index.html" : chemin);
  if (!fichier.startsWith(racine) || !existsSync(fichier)) { rep.writeHead(404).end(); return; }
  rep.writeHead(200, { "content-type": types[extname(fichier)] ?? "application/octet-stream" }).end(readFileSync(fichier));
});
await new Promise((ok) => serveur.listen(0, "127.0.0.1", ok));
const base = `http://127.0.0.1:${serveur.address().port}`;

const index = JSON.parse(readFileSync(join(racine, "index.json"), "utf8"));
const histoires = Object.values(index.entries).filter((e) => e.type === "story" && e.id.includes(filtre));
mkdirSync(sortie, { recursive: true });

const navigateur = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
let echecs = 0;
for (const h of histoires) {
  const tv = /\btv\b/i.test(h.name) || /^tv/i.test(h.name.replace(/\s/g, ""));
  // La galerie de la console se juge pleine largeur, comme une page de bureau (1440 px).
  const bureau = /galerie/i.test(h.id);
  const ctx = await navigateur.newContext({
    viewport: tv ? { width: 1920, height: 1080 } : bureau ? { width: 1440, height: 900 } : { width: 390, height: 844 },
    deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  const erreurs = [];
  page.on("pageerror", (e) => erreurs.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") erreurs.push(m.text()); });
  await page.goto(`${base}/iframe.html?id=${h.id}&viewMode=story`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  const largeur = await page.evaluate(() => ({ doc: document.documentElement.scrollWidth, vue: window.innerWidth, haut: document.documentElement.scrollHeight }));
  const problemes = [...erreurs];
  if (largeur.doc > largeur.vue) problemes.push(`débordement horizontal (${largeur.doc} > ${largeur.vue})`);
  if (/--tv-/.test(h.id) && largeur.haut > 1080) problemes.push(`écran TV plus haut que 1080 (${largeur.haut})`);
  const png = join(sortie, `${h.id}.png`);
  const octets = await page.screenshot({ path: png, fullPage: true });
  if (reference) {
    const ref = join(reference, `${h.id}.png`);
    if (!existsSync(ref)) problemes.push("pas de capture de référence");
    else if (!readFileSync(ref).equals(octets)) {
      // Comparaison brute d'abord ; sinon mesure de l'écart par décodage dans la page.
      const ecart = await page.evaluate(async ([a, b]) => {
        const charge = (u) => new Promise((ok) => { const i = new Image(); i.onload = () => ok(i); i.src = u; });
        const [x, y] = await Promise.all([charge(a), charge(b)]);
        if (x.width !== y.width || x.height !== y.height) return 1;
        const c = (i) => { const k = document.createElement("canvas"); k.width = i.width; k.height = i.height; const g = k.getContext("2d"); g.drawImage(i, 0, 0); return g.getImageData(0, 0, i.width, i.height).data; };
        const p = c(x), q = c(y); let n = 0;
        for (let i = 0; i < p.length; i += 4) if (Math.abs(p[i] - q[i]) + Math.abs(p[i + 1] - q[i + 1]) + Math.abs(p[i + 2] - q[i + 2]) > 24) n++;
        return n / (p.length / 4);
      }, ["data:image/png;base64," + octets.toString("base64"), "data:image/png;base64," + readFileSync(ref).toString("base64")]);
      if (ecart > seuil) problemes.push(`écart visuel ${(ecart * 100).toFixed(2)} %`);
    }
  }
  console.log(`${problemes.length ? "ECHEC" : "ok   "} ${h.id} (${largeur.haut}px)${problemes.length ? " : " + problemes.join(" ; ") : ""}`);
  if (problemes.length) echecs++;
  await ctx.close();
}
await navigateur.close();
serveur.close();
writeFileSync(join(sortie, ".gitkeep"), "");
console.log(`${histoires.length} stories, ${echecs} en échec`);
process.exit(echecs ? 1 : 0);
