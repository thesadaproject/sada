import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Legende, MonthTable } from "@sada/ui";
import type { MonthDay } from "@sada/ui";
import type { Boot } from "./boot";
import { PRIERES, decaler, hijriDe, jourSemaine, nuitImpaire, semainesDuMois } from "./logique";

const MOBILE = "(max-width: 767px)";

/** Téléphone : le mois est découpé par semaine pour tenir dans l'écran sans défilement. */
function useMobile(): boolean {
  const [m, setM] = useState(() => window.matchMedia(MOBILE).matches);
  useEffect(() => {
    const q = window.matchMedia(MOBILE);
    const f = () => setM(q.matches);
    q.addEventListener("change", f);
    return () => q.removeEventListener("change", f);
  }, []);
  return m;
}

/** « novembre » -> « nov. » ; les noms courts (mars, mai, juin, août) restent entiers. */
const abrege = (nom: string) => (nom.length <= 4 || !/^[a-zà-ÿ]/i.test(nom) ? nom : `${nom.slice(0, 3)}.`);

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

  const mobile = useMobile();
  const [semaine, setSemaine] = useState<number | null>(null);
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

  const semaines = semainesDuMois(lignes.map((d) => d.date));
  const initiale = (() => {
    if (new URLSearchParams(location.search).get("w") === "last") return semaines.length - 1;
    const i = semaines.findIndex((w) => w.dates.includes(boot.today));
    return i >= 0 ? i : 0;
  })();
  const courante = Math.min(semaine ?? initiale, Math.max(semaines.length - 1, 0));
  const visibles = mobile && semaines.length ? jours.slice(semaines[courante].debut, semaines[courante].fin + 1) : jours;
  const etiquette = (i: number) => {
    const w = semaines[i];
    if (!w) return "";
    const a = Number(w.dates[0].slice(8));
    const b = Number(w.dates[w.dates.length - 1].slice(8));
    const nom = abrege(L.months[Number(w.dates[0].slice(5, 7)) - 1]);
    return a === b ? `${a} ${nom}` : `${a}–${b} ${nom}`;
  };
  const repere = visibles.some((j) => j.repere);

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
      <nav aria-label={titre} className="hidden items-center justify-between gap-3 text-(--s-fg) md:flex">
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
          jours={visibles}
          compact={mobile}
          enteteJour={L.col.date}
          actions={
            <div className="relative">
              <details className="mt-3">
                <summary className={`${lien} cursor-pointer list-none`}>{L.page.download} ▾</summary>
                <div className="absolute inset-x-0 z-10 mt-2 grid gap-2 rounded-[10px] border border-(--s-line) bg-(--s-card) p-2 shadow-lg">
                  <a className={lien} href={`${exp}?format=pdf&${q}`} download>{L.page.pdf}</a>
                  <a className={lien} href={`${exp}?format=csv&${q}`} download>{L.page.csv}</a>
                  <a className={lien} href={`${exp}?format=pdf&ramadan=1`} download>{L.page.ramadan}</a>
                  {!tv && <a className={lien} href={location.pathname}>{L.page.screen}</a>}
                </div>
              </details>
              {mobile && semaines.length > 0 && (
                <SemaineNav
                  courante={courante}
                  total={semaines.length}
                  etiquette={etiquette}
                  onChoix={setSemaine}
                  prevMois={{ href: `?month=${prec}&w=last`, nom: nomMois(prec) }}
                  suivMois={{ href: `?month=${suiv}`, nom: nomMois(suiv) }}
                  prevLabel={L.page.prev}
                  nextLabel={L.page.next}
                />
              )}
            </div>
          }
          tv={tv}
          legende={
            <Legende
              vendredi={L.legend_friday}
              nuitsImpaires={ramadan && (!mobile || repere) ? L.legend_odd_nights : undefined}
              note={ramadan && (!mobile || repere) ? L.legend_note : undefined}
              nuitsImpairesNote={ramadan && !mobile ? L.legend_maghrib : undefined}
              tv={tv}
              compact={mobile}
            />
          }
        />
      )}
    </div>
  );
}

/** Navigation par semaine (téléphone) : libellés de dates, jamais des flèches seules ; en bout de mois, le lien
 *  mène au mois voisin. Rangée S1…Sn pour sauter directement. */
function SemaineNav({ courante, total, etiquette, onChoix, prevMois, suivMois, prevLabel, nextLabel }: {
  courante: number;
  total: number;
  etiquette: (i: number) => string;
  onChoix: (i: number) => void;
  prevMois: { href: string; nom: string };
  suivMois: { href: string; nom: string };
  prevLabel: string;
  nextLabel: string;
}) {
  const bouton = (cible: number, texte: ReactNode, rel: "prev" | "next", libelle: string) => (
    <button type="button" rel={rel} aria-label={`${libelle} : ${etiquette(cible)}`} onClick={() => onChoix(cible)} className={`${lien} cursor-pointer text-[0.9rem]`}>
      {texte}
    </button>
  );
  return (
    <div className="mt-2 grid gap-2">
      <div className="grid grid-cols-2 gap-2">
        {courante > 0 ? (
          bouton(courante - 1, <>‹ {etiquette(courante - 1)}</>, "prev", prevLabel)
        ) : (
          <a className={`${lien} text-[0.9rem]`} href={prevMois.href} rel="prev" aria-label={`${prevLabel} : ${prevMois.nom}`}>‹ {prevMois.nom}</a>
        )}
        {courante < total - 1 ? (
          bouton(courante + 1, <>{etiquette(courante + 1)} ›</>, "next", nextLabel)
        ) : (
          <a className={`${lien} text-[0.9rem]`} href={suivMois.href} rel="next" aria-label={`${nextLabel} : ${suivMois.nom}`}>{suivMois.nom} ›</a>
        )}
      </div>
      <div role="group" aria-label="Semaines" className="flex justify-between gap-1">
        {Array.from({ length: total }, (_, i) => (
          <button
            key={i}
            type="button"
            aria-label={etiquette(i)}
            aria-current={i === courante ? "true" : undefined}
            onClick={() => onChoix(i)}
            className={`inline-flex min-h-9 flex-1 cursor-pointer items-center justify-center rounded-[9px] border px-2 text-[0.8rem] font-semibold ${i === courante ? "border-(--accent) bg-(--s-actif) text-(--s-fg)" : "border-(--s-line) bg-(--s-card) text-(--s-muted)"}`}
          >
            S{i + 1}
          </button>
        ))}
      </div>
    </div>
  );
}
