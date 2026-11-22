import type { CSSProperties } from "react";

/** Accent par mosquée : une couleur choisie, une encre calculée par contraste.
 *  Pur et sans dépendance, pour servir aussi bien l'écran que la page du mois. */

const NUIT = "#0b1a14";
const IVOIRE = "#f7f3ea";

function rgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join("") : m[1];
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Luminance relative WCAG 2.x (0 = noir, 1 = blanc). */
export function luminance(hex: string): number {
  const c = rgb(hex);
  if (!c) return 0;
  const [r, g, b] = c.map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Rapport de contraste WCAG entre deux couleurs hexadécimales (1 à 21). */
export function contraste(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Encre lisible sur `fond` : la nuit Sada ou l'ivoire, selon le meilleur contraste. */
export function encreSur(fond: string): string {
  return contraste(fond, NUIT) >= contraste(fond, IVOIRE) ? NUIT : IVOIRE;
}

/** Variables CSS d'une mosquée. Couleur absente ou invalide : l'or Sada (rien à surcharger). */
export function accentStyle(accent?: string | null): CSSProperties {
  if (!accent || !rgb(accent)) return {};
  const c = accent.startsWith("#") ? accent : `#${accent}`;
  return { "--accent": c, "--accent-ink": encreSur(c) } as CSSProperties;
}
