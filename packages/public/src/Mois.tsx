import { useEffect, useState } from "react";
import { Legende, MonthTable } from "@sada/ui";
import type { MonthDay } from "@sada/ui";
import type { Boot } from "./boot";
import { PRIERES, decaler, hijriDe, jourSemaine, nuitImpaire } from "./logique";

type JourApi = { date: string; times: Record<string, string>; iqama: Record<string, string> };
type Mensuel = { jumua: string[]; days: JourApi[] };

const lien =
  "inline-flex min-h-11 items-center justify-center rounded-[9px] border border-(--s-line) bg-(--s-card) px-4 font-semibold text-(--s-fg) no-underline";

/** Le mois d'une mosquée : tableau des horaires (API publique `prayer-times?month=`), les noms arabes en sous-titre
 *  des colonnes, l'hégire, Jumu'a, les nuits impaires des dix dernières nuits de Ramadan sans en désigner une,
 *  téléchargements (PDF, CSV, calendrier du Ramadan). */
export function Mois({ boot, tv }: { boot: Boot; tv: boolean }) {
  const L = boot.labels;
  const [donnees, setDonnees] = useState<Mensuel | "erreur" | null>(null);
  useEffect(() => {
    let vivant = true;
    fetch(`${boot.api}/prayer-times?month=${boot.month}`, { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? (r.json() as Promise<Mensuel>) : Promise.reject(new Error(String(r.status)))))
      .then((d) => vivant && setDonnees(d))
      .catch(() => vivant && setDonnees("erreur"));
    return () => {
      vivant = false;
    };
  }, [boot.api, boot.month]);

  const [annee, m] = boot.month.split("-").map(Number);
  const titre = `${L.months[m - 1].charAt(0).toUpperCase()}${L.months[m - 1].slice(1)} ${annee}`;
  const lignes = donnees && donnees !== "erreur" ? donnees.days : [];
  const jumua = donnees && donnees !== "erreur" ? donnees.jumua : [];

  let ramadan = false;
  const jours: MonthDay[] = lignes.map((d) => {
    const h = hijriDe(d.date);
    const impaire = nuitImpaire(h);
    ramadan ||= impaire;
    const vendredi = jourSemaine(d.date) === 4;
    return {
      jour: String(Number(d.date.slice(8))),
      semaine: L.weekdays[jourSemaine(d.date)],
      hijri: `${h.jour} ${L.hijri_short[h.mois - 1]}`,
      heures: Object.fromEntries(PRIERES.map((p) => [p.cle, d.times[p.cle] ?? "—"])),
      aujourdhui: d.date === boot.today,
      vendredi,
      jumua: vendredi && jumua.length ? jumua : undefined,
      repere: impaire ? L.night.replace("{n}", String(h.jour + 1)) : undefined,
    };
  });

  let detail: string | undefined;
  if (lignes.length) {
    const a = hijriDe(lignes[0].date);
    const b = hijriDe(lignes[lignes.length - 1].date);
    const na = L.hijri_months[a.mois - 1];
    const nb = L.hijri_months[b.mois - 1];
    detail =
      a.annee === b.annee && a.mois === b.mois ? `${na} ${a.annee}` : a.annee === b.annee ? `${na} – ${nb} ${a.annee}` : `${na} ${a.annee} – ${nb} ${b.annee}`;
  }

  const nomMois = (mois: string) => {
    const [an, mm] = mois.split("-").map(Number);
    const nom = L.months[mm - 1];
    return `${nom.charAt(0).toUpperCase()}${nom.slice(1)}${an === annee ? "" : ` ${an}`}`;
  };
  const prec = decaler(boot.month, -1);
  const suiv = decaler(boot.month, 1);
  const q = `month=${boot.month}`;
  const exp = `${boot.api}/prayer-times/export`;
  return (
    <div className="grid gap-4">
      <nav aria-label={titre} className="flex items-center justify-between gap-3 text-(--s-fg)">
        <a className={lien} href={`?month=${prec}`} rel="prev" aria-label={`${L.page.prev} : ${nomMois(prec)}`}>‹ {nomMois(prec)}</a>
        <span aria-hidden />
        <a className={lien} href={`?month=${suiv}`} rel="next" aria-label={`${L.page.next} : ${nomMois(suiv)}`}>{nomMois(suiv)} ›</a>
      </nav>
      {donnees === "erreur" ? (
        <p role="alert" className="m-0 text-(--s-muted)">{L.page.empty}</p>
      ) : donnees && lignes.length === 0 ? (
        <p role="status" className="m-0 text-(--s-muted)">{L.page.empty}</p>
      ) : (
        <MonthTable
          surtitre={L.page.kicker}
          titre={titre}
          detail={detail}
          colonnes={PRIERES.map((p) => ({ cle: p.cle, nom: L.col[p.cle], arabe: p.arabe }))}
          jours={jours}
          enteteJour={L.col.date}
          actions={
            <details className="mt-3">
              <summary className={`${lien} cursor-pointer list-none`}>{L.page.download} ▾</summary>
              <div className="mt-2 grid gap-2 rounded-[10px] border border-(--s-line) bg-(--s-card) p-2">
                <a className={lien} href={`${exp}?format=pdf&${q}`} download>{L.page.pdf}</a>
                <a className={lien} href={`${exp}?format=csv&${q}`} download>{L.page.csv}</a>
                <a className={lien} href={`${exp}?format=pdf&ramadan=1`} download>{L.page.ramadan}</a>
                {!tv && <a className={lien} href={location.pathname}>{L.page.screen}</a>}
              </div>
            </details>
          }
          tv={tv}
          legende={
            <Legende
              vendredi={L.legend_friday}
              nuitsImpaires={ramadan ? L.legend_odd_nights : undefined}
              note={ramadan ? L.legend_note : undefined}
              nuitsImpairesNote={ramadan ? L.legend_maghrib : undefined}
              tv={tv}
            />
          }
        />
      )}
    </div>
  );
}
