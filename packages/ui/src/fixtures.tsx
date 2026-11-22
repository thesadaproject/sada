import type { ReactNode } from "react";

/** Données et cadres communs aux stories (jamais embarqués dans le paquet publié : seul index.ts est exporté). */
export const BORDEAUX = "#7b1e3a";
export const VERT = "#1f6b4a";

export const PRIERES = [
  { cle: "fajr", nom: "Fajr", arabe: "الفجر", adhan: "06:21", iqama: "06:41", passee: true },
  { cle: "chourouk", nom: "Chourouk", arabe: "الشروق", adhan: "07:58", chourouk: true, passee: true },
  { cle: "dhuhr", nom: "Dhuhr", arabe: "الظهر", adhan: "12:26", iqama: "12:46" },
  { cle: "asr", nom: "Asr", arabe: "العصر", adhan: "14:38", iqama: "14:53" },
  { cle: "maghrib", nom: "Maghrib", arabe: "المغرب", adhan: "16:52", iqama: "16:57" },
  { cle: "isha", nom: "Isha", arabe: "العشاء", adhan: "18:20", iqama: "18:40" },
];

export const ARABE_LONG = "مسجد الشيخ عبد الرحمن بن ناصر السعدي للتعليم والدعوة والإرشاد بمدينة ليون";

/** Cadre à taille fixe : mobile (390 px) ou télévision (1920x1080). */
export function Cadre({ tv = false, children }: { tv?: boolean; children: ReactNode }) {
  return <div style={tv ? { width: 1920, minHeight: 1080 } : { width: 390 }}>{children}</div>;
}

export function jours(n = 30) {
  const sem = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
  return Array.from({ length: n }, (_, i) => {
    const m = (i * 2) % 60;
    const h = (base: number, d: number) =>
      `${String(Math.floor((base * 60 + d + m) / 60)).padStart(2, "0")}:${String((base * 60 + d + m) % 60).padStart(2, "0")}`;
    return {
      jour: String(i + 1),
      semaine: sem[(i + 0) % 7],
      hijri: String(((i + 11) % 29) + 1),
      vendredi: (i + 0) % 7 === 5,
      aujourdhui: i === 21,
      heures: { fajr: h(6, 21), chourouk: h(7, 58), dhuhr: h(12, 26), asr: h(14, 38), maghrib: h(16, 52), isha: h(18, 20) },
    };
  });
}
