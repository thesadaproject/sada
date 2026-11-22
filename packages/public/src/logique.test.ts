import { describe, expect, it } from "vitest";
import { semainesDuMois } from "./logique";

const mois = (a: number, m: number) => {
  const n = new Date(Date.UTC(a, m, 0)).getUTCDate();
  return Array.from({ length: n }, (_, i) => `${a}-${String(m).padStart(2, "0")}-${String(i + 1).padStart(2, "0")}`);
};

describe("semainesDuMois", () => {
  it("découpe novembre 2026 en semaines civiles lundi-dimanche (le 1er est un dimanche)", () => {
    const s = semainesDuMois(mois(2026, 11));
    expect(s.map((w) => [w.dates[0].slice(8), w.dates[w.dates.length - 1].slice(8)])).toEqual([
      ["01", "01"], ["02", "08"], ["09", "15"], ["16", "22"], ["23", "29"], ["30", "30"],
    ]);
  });
  it("couvre chaque jour une seule fois, sans trou", () => {
    const jours = mois(2027, 2);
    const s = semainesDuMois(jours);
    expect(s.flatMap((w) => w.dates)).toEqual(jours);
    expect(s[0].debut).toBe(0);
    expect(s[s.length - 1].fin).toBe(jours.length - 1);
  });
  it("aucune semaine de plus de sept jours", () => {
    for (let m = 1; m <= 12; m++) for (const w of semainesDuMois(mois(2027, m))) expect(w.dates.length).toBeLessThanOrEqual(7);
  });
});
