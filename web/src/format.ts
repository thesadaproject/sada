/** Shared formatting: long-form dates and durations, as the template back-office did. */

/** A list, whatever the server sent. An older back-office answers `tabs` with an object
 *  ({clé: libellé}) where the current one sends an array of keys; a page must not crash
 *  on that, it must show what it can. */
export function liste<T = string>(valeur: unknown): T[] {
  if (Array.isArray(valeur)) return valeur as T[];
  if (valeur && typeof valeur === "object") return Object.keys(valeur as object) as T[];
  if (typeof valeur === "string" && valeur) return [valeur] as T[];
  return [];
}

/** The labels an older server carries along with its keys, if any. */
export function libelles(valeur: unknown): Record<string, string> {
  return valeur && !Array.isArray(valeur) && typeof valeur === "object" ? (valeur as Record<string, string>) : {};
}

/** A calendar day (YYYY-MM-DD) as a Date at local noon: no timezone or DST change moves the day.
 *  The result is an Invalid Date when the text is not a date. */
export function parseDay(iso: string): Date {
  return new Date(`${iso}T12:00:00`);
}

/** A timestamp (ISO) in the interface language: weekday, day, month and time. */
export function dateTime(iso: string, langue: string): string {
  return new Intl.DateTimeFormat(langue, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

/** A number grouped as the interface language does it (thin spaces in French, commas in English). */
export function nombre(n: number, langue: string): string {
  return new Intl.NumberFormat(langue).format(n);
}

export function dateFr(valeur?: string | null, langue = "fr"): string {
  if (!valeur) return "—";
  const d = parseDay(valeur);
  if (Number.isNaN(d.getTime())) return valeur;
  return new Intl.DateTimeFormat(langue, { weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(d);
}

/** Seconds -> mm:ss (clips last one to three minutes). */
export function mmss(secondes?: number | null): string {
  const s = Math.max(0, Math.round(Number(secondes) || 0));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** Duration as the player shows it: h:mm:ss beyond an hour (a tarawih night lasts more than 60 min). */
export function hms(secondes?: number | null): string {
  const v = Math.max(0, Math.floor(Number(secondes) || 0));
  const h = Math.floor(v / 3600), m = Math.floor((v % 3600) / 60), r = v % 60;
  return `${h > 0 ? `${h}:` : ""}${String(m).padStart(h > 0 ? 2 : 1, "0")}:${String(r).padStart(2, "0")}`;
}

/** Time of day from seconds since midnight: always HH:MM:SS (00:49:38, never the duration "49:38"). */
export function heureDuJour(secondes: number): string {
  const v = ((Math.floor(secondes) % 86400) + 86400) % 86400;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(v / 3600))}:${p(Math.floor((v % 3600) / 60))}:${p(v % 60)}`;
}

/** Live clock: null when out of service, otherwise the orchestrator's time. */
export function horloge(valeur?: string | null): string {
  return valeur || "--:--:--";
}
