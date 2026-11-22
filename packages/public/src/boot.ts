/** Ce que le serveur Python écrit dans la page (`<script id="boot">`) : quelle vue, quelle mosquée, les libellés
 *  de la langue de la mosquée et, pour l'écran, les deux premiers jours (la page est lisible dès le premier
 *  rendu). Les horaires du mois viennent de l'API publique. */
export type Jour = {
  date: string;
  gregorian: string;
  hijri: string;
  times: Record<string, string>;
  iqama: Record<string, string>;
  jumua: string[];
};

export type Libelles = {
  page: Record<string, string>;
  col: Record<string, string>;
  weekdays: string[];
  months: string[];
  hijri_months: string[];
  hijri_short: string[];
  night: string;
  jumua: string;
  legend_friday: string;
  legend_odd_nights: string;
  legend_note: string;
  legend_maghrib: string;
};

export type Boot = {
  view: "screen" | "month" | "error";
  /** Adresse de l'API publique de la mosquée : /api/v1/public/mosques/<slug> */
  api: string;
  name: string;
  timezone: string;
  /** Jour local de la mosquée (AAAA-MM-JJ) au moment du rendu. */
  today: string;
  accent: string;
  /** URL du logo, vide quand la mosquée ne l'affiche pas. */
  logo: string;
  month: string;
  labels: Libelles;
  days: Jour[];
  error?: { status: number; title: string; text: string; mawaqit_url: string; site: string };
};

export function lireBoot(): Boot {
  const brut = document.getElementById("boot")?.textContent ?? "{}";
  return JSON.parse(brut) as Boot;
}
