import { describe, expect, it } from "vitest";
import { MOIS_HIJRI, MOIS_HIJRI_COURT, accentStyle, cibleCompteARebours, contraste, encreSur, formatHijri, formatRestant } from "./index";

describe("accent par mosquée", () => {
  it("choisit une encre lisible (contraste >= 4.5) quelle que soit la couleur", () => {
    for (const c of ["#7b1e3a", "#1f6b4a", "#e2c27a", "#ffffff", "#000000", "#808080", "#d4a017", "#2255cc"]) {
      expect(contraste(c, encreSur(c))).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("encre claire sur fond sombre, sombre sur fond clair", () => {
    expect(encreSur("#7b1e3a")).toBe("#f7f3ea");
    expect(encreSur("#e2c27a")).toBe("#0b1a14");
  });
  it("sans couleur ou couleur invalide : rien à surcharger (or Sada)", () => {
    expect(accentStyle()).toEqual({});
    expect(accentStyle("pas-une-couleur")).toEqual({});
  });
  it("pose --accent et --accent-ink", () => {
    expect(accentStyle("#7b1e3a")).toMatchObject({ "--accent": "#7b1e3a", "--accent-ink": "#f7f3ea" });
  });
});

describe("date hégirienne", () => {
  it("abrège le mois par défaut, le nom entier sur demande", () => {
    expect(formatHijri(20, 5, 1448)).toBe("20 Jou. I 1448");
    expect(formatHijri(20, 5, 1448, false)).toBe("20 Joumada al-oula 1448");
  });
  it("12 mois, chacun avec une abréviation", () => {
    expect(MOIS_HIJRI).toHaveLength(12);
    expect(MOIS_HIJRI_COURT).toHaveLength(12);
  });
});

describe("compte à rebours", () => {
  it("n'a jamais Chourouk pour cible", () => {
    const l = [{ nom: "Fajr", passee: true }, { nom: "Chourouk", chourouk: true }, { nom: "Dhuhr" }];
    expect(cibleCompteARebours(l)?.nom).toBe("Dhuhr");
    expect(cibleCompteARebours([{ nom: "Chourouk", chourouk: true }])).toBeUndefined();
  });
  it("formate HH:MM:SS sans valeur négative", () => {
    expect(formatRestant(4723)).toBe("01:18:43");
    expect(formatRestant(-5)).toBe("00:00:00");
  });
});
