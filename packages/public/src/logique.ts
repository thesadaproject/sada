import type { Jour } from "./boot";

/** Logique pure de l'écran et du mois : rien ici ne lit l'horloge ni le réseau (testable). */

export const PRIERES = [
  { cle: "fajr", nom: "Fajr", arabe: "الفجر" },
  { cle: "sunrise", nom: "Chourouk", arabe: "الشروق" },
  { cle: "dhuhr", nom: "Dhuhr", arabe: "الظهر" },
  { cle: "asr", nom: "Asr", arabe: "العصر" },
  { cle: "maghrib", nom: "Maghrib", arabe: "المغرب" },
  { cle: "isha", nom: "Isha", arabe: "العشاء" },
] as const;

/** Les cinq prières visées par le compte à rebours : jamais Chourouk, jamais Jumu'a. */
const VISEES = ["fajr", "dhuhr", "asr", "maghrib", "isha"] as const;

export const secondes = (hhmm: string): number => {
  const [h, m] = hhmm.split(":");
  return Number(h) * 3600 + Number(m) * 60;
};

export type Evenement = { cle: (typeof VISEES)[number]; genre: "adhan" | "iqama"; a: number; jour: 0 | 1 };

/** Adhan et iqama à venir d'aujourd'hui et de demain, en secondes depuis minuit d'aujourd'hui, triés. */
export function evenements(jours: Jour[]): Evenement[] {
  const sortie: Evenement[] = [];
  jours.slice(0, 2).forEach((j, i) => {
    for (const cle of VISEES) {
      const t = j.times[cle];
      if (!t) continue;
      sortie.push({ cle, genre: "adhan", a: i * 86400 + secondes(t), jour: i as 0 | 1 });
      const q = j.iqama[cle];
      if (q && secondes(q) > secondes(t)) sortie.push({ cle, genre: "iqama", a: i * 86400 + secondes(q), jour: i as 0 | 1 });
    }
  });
  return sortie.sort((x, y) => x.a - y.a);
}

export const suivant = (jours: Jour[], maintenant: number): Evenement | undefined =>
  evenements(jours).find((e) => e.a > maintenant);

/** Heure locale « HH:MM:SS » dans un fuseau, et jour AAAA-MM-JJ. */
export function maintenantDans(fuseau: string, date = new Date()): { iso: string; s: number } {
  const f = new Intl.DateTimeFormat("en-CA", {
    timeZone: fuseau, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const o: Record<string, string> = {};
  for (const p of f.formatToParts(date)) o[p.type] = p.value;
  return { iso: `${o.year}-${o.month}-${o.day}`, s: Number(o.hour) * 3600 + Number(o.minute) * 60 + Number(o.second) };
}

/** Date hégirienne (Umm al-Qura, comme le PDF) d'un jour AAAA-MM-JJ. */
export function hijriDe(iso: string): { jour: number; mois: number; annee: number } {
  const f = new Intl.DateTimeFormat("en-u-ca-islamic-umalqura-nu-latn", { timeZone: "UTC", day: "numeric", month: "numeric", year: "numeric" });
  const o: Record<string, string> = {};
  for (const p of f.formatToParts(new Date(`${iso}T12:00:00Z`))) o[p.type] = p.value;
  return { jour: Number(o.day), mois: Number(o.month), annee: Number(o.relatedYear ?? o.year) };
}

/** Veilles des nuits impaires des dix dernières nuits de Ramadan : le 20, 22, 24, 26 et 28 (la nuit commence au
 *  Maghrib de la veille). Aucune nuit n'est désignée : toutes les nuits impaires portent le même repère. */
export const RAMADAN = 9;
export const VEILLES_IMPAIRES = [20, 22, 24, 26, 28];

export const nuitImpaire = (h: { jour: number; mois: number }): boolean => h.mois === RAMADAN && VEILLES_IMPAIRES.includes(h.jour);

/** Jour de la semaine, lundi = 0. */
export const jourSemaine = (iso: string): number => (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7;

export function decaler(mois: string, n: number): string {
  const [a, m] = mois.split("-").map(Number);
  const t = a * 12 + (m - 1) + n;
  return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`;
}
