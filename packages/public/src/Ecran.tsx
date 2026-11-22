import { useCallback, useEffect, useMemo, useState } from "react";
import { Cadran, Clock, Countdown, PrayerList, PrayerRow } from "@sada/ui";
import type { Boot, Jour } from "./boot";
import { PRIERES, maintenantDans, secondes, suivant } from "./logique";

const VIDE: Jour = { date: "", gregorian: "", hijri: "", times: {}, iqama: {}, jumua: [] };

/** L'écran du jour : horloge, compte à rebours, liste des prières. Pas de bouton, pas de lien sur télévision.
 *  Les deux premiers jours viennent de la page ; à minuit (heure de la mosquée) le jour suivant s'affiche
 *  aussitôt, puis l'API publique `days` rafraîchit (et toutes les 30 minutes, pour les modifications). */
export function Ecran({ boot, tv }: { boot: Boot; tv: boolean }) {
  const [jours, setJours] = useState<Jour[]>(boot.days);
  const [t, setT] = useState(() => maintenantDans(boot.timezone));

  useEffect(() => {
    const id = setInterval(() => setT(maintenantDans(boot.timezone)), 250);
    return () => clearInterval(id);
  }, [boot.timezone]);

  const charger = useCallback(
    (depuis: string) =>
      fetch(`${boot.api}/prayer-times/days?from=${depuis}`, { headers: { Accept: "application/json" } })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
        .then((d: { days: Jour[] }) => setJours(d.days))
        .catch(() => undefined), // on garde ce qui est affiché ; la prochaine tentative suit
    [boot.api],
  );

  const aujourdhui = jours[0] ?? VIDE;
  useEffect(() => {
    if (aujourdhui.date && t.iso !== aujourdhui.date) {
      setJours((j) => (j[1]?.date === t.iso ? [j[1], VIDE] : j));
      void charger(t.iso);
    }
  }, [t.iso, aujourdhui.date, charger]);
  useEffect(() => {
    const id = setInterval(() => void charger(maintenantDans(boot.timezone).iso), 30 * 60 * 1000);
    return () => clearInterval(id);
  }, [boot.timezone, charger]);

  const prochain = useMemo(() => suivant(jours, t.s), [jours, t.s]);
  const lignes = PRIERES.filter((p) => aujourdhui.times[p.cle]);
  const jumua = aujourdhui.jumua.join(" · ");
  const nomCible = prochain ? PRIERES.find((p) => p.cle === prochain.cle) : undefined;
  const heure = `${String(Math.floor(t.s / 3600)).padStart(2, "0")}:${String(Math.floor(t.s / 60) % 60).padStart(2, "0")}`;

  const cadran = (
    <Cadran tv={tv}>
      <Clock kicker="Heure locale" heure={heure} date={aujourdhui.gregorian} hijri={aujourdhui.hijri ? `${aujourdhui.hijri} H` : undefined} tv={tv} />
      {prochain && nomCible ? (
        <div>
          <Countdown
            libelle={prochain.genre === "iqama" ? "Iqama dans" : prochain.jour === 1 ? "Prochaine prière · demain" : "Prochaine prière"}
            nom={nomCible.nom}
            arabe={nomCible.arabe}
            restant={prochain.a - t.s}
            tv={tv}
          />
        </div>
      ) : (
        <p className={`m-0 text-(--s-muted) ${tv ? "text-[2rem]" : ""}`}>Pas d'horaire à venir</p>
      )}
    </Cadran>
  );

  const liste =
    lignes.length === 0 && !jumua ? (
      <p role="status" className={`m-0 text-(--s-muted) ${tv ? "text-[2rem]" : ""}`}>Aucun horaire saisi pour ce jour.</p>
    ) : (
      <PrayerList tv={tv} titre="Aujourd'hui">
        {lignes.map((p) => {
          const a = aujourdhui.times[p.cle];
          const cible = prochain?.jour === 0 && prochain.cle === p.cle;
          return (
            <PrayerRow
              key={p.cle}
              nom={p.nom}
              arabe={p.arabe}
              adhan={a}
              iqama={aujourdhui.iqama[p.cle]}
              chourouk={p.cle === "sunrise"}
              suivante={cible}
              passee={secondes(a) <= t.s}
              tv={tv}
            />
          );
        })}
        {jumua && aujourdhui.jumua.length > 0 && (
          <PrayerRow
            nom="Jumu'a"
            arabe="الجمعة"
            adhan={jumua}
            informatif
            passee={secondes(aujourdhui.jumua[aujourdhui.jumua.length - 1]) <= t.s}
            tv={tv}
          />
        )}
      </PrayerList>
    );

  const mois = (boot.today || aujourdhui.date).slice(0, 7);
  return (
    <>
      <h1 className="sr-only">{boot.name}</h1>
      <p className="sr-only" role="status" aria-live="polite">
        {prochain && nomCible ? `${prochain.genre === "iqama" ? "Iqama de " : "Prochaine prière : "}${nomCible.nom}` : ""}
      </p>
      {tv ? (
        <div className="grid flex-1 grid-cols-[2fr_3fr] items-stretch gap-16">
          {/* pt = hauteur du bandeau de la liste : le bloc horloge se centre sur les lignes, pas sur la carte. */}
          <div className="flex flex-col justify-center pt-[3.875rem]">{cadran}</div>
          {liste}
        </div>
      ) : (
        <div className="grid gap-4">
          {cadran}
          {liste}
          <nav aria-label="Calendriers" className="mt-2 flex flex-wrap gap-3">
            <a className="inline-flex min-h-11 items-center rounded-[9px] border border-(--s-line) bg-(--s-card) px-5 font-semibold text-(--s-fg) no-underline" href={`?month=${mois}`}>
              Calendrier du mois
            </a>
            <a className="inline-flex min-h-11 items-center rounded-[9px] border border-(--s-line) bg-(--s-card) px-5 font-semibold text-(--s-fg) no-underline" href={`${boot.api}/prayer-times/export?format=pdf&month=${mois}`} download>
              Calendrier PDF
            </a>
          </nav>
        </div>
      )}
    </>
  );
}
