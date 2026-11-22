/** Mois hégiriens en français, noms entiers et abréviations (une date hégirienne tient sur une ligne
 *  de téléphone : « 20 Jou. I 1448 »). Index 0 = Mouharram. */
export const MOIS_HIJRI = [
  "Mouharram", "Safar", "Rabi' al-awwal", "Rabi' ath-thani", "Joumada al-oula", "Joumada ath-thania",
  "Rajab", "Chaabane", "Ramadan", "Chawwal", "Dhou al-qida", "Dhou al-hijja",
] as const;

export const MOIS_HIJRI_COURT = [
  "Mouh.", "Saf.", "Rab. I", "Rab. II", "Jou. I", "Jou. II",
  "Raj.", "Chaa.", "Ram.", "Chaw.", "Dhou-q.", "Dhou-h.",
] as const;

/** « 20 Jou. I 1448 » (ou « 20 Joumada al-oula 1448 » avec `court = false`). `mois` va de 1 à 12. */
export function formatHijri(jour: number, mois: number, annee: number, court = true): string {
  const noms = court ? MOIS_HIJRI_COURT : MOIS_HIJRI;
  return `${jour} ${noms[Math.min(11, Math.max(0, mois - 1))]} ${annee}`;
}
