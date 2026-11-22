/** « HH:MM:SS » à partir d'un nombre de secondes (jamais négatif). */
export function formatRestant(secondes: number): string {
  const s = Math.max(0, Math.floor(secondes));
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

/** Compte à rebours vers la prochaine prière (jamais Chourouk : le choix se fait en amont, cf.
 *  cibleCompteARebours). Pur : `restant` est en secondes, l'appelant le fait avancer.
 *  Nom latin (EB Garamond) et arabe (Amiri) sur la même ligne. */
export function Countdown({ libelle, nom, arabe, restant, tv = false }: {
  /** « Prochaine prière » */
  libelle: string;
  nom: string;
  arabe?: string;
  restant: number;
  tv?: boolean;
}) {
  return (
    <div>
      <p className={`m-0 mb-2 font-semibold uppercase leading-none tracking-[0.12em] text-(--s-kicker) ${tv ? "text-[1.3rem]" : "text-[0.75rem]"}`}>{libelle}</p>
      <p className={`m-0 flex items-baseline gap-x-4 font-serif leading-tight text-(--s-title) ${tv ? "text-[4rem]" : "text-[1.55rem]"}`}>
        <span>{nom}</span>
        {arabe && (
          <span lang="ar" dir="rtl" className="sada-arabe text-(--s-muted)">
            {arabe}
          </span>
        )}
      </p>
      <p role="timer" className={`m-0 font-semibold leading-tight text-(--s-fg) ${tv ? "mt-2 text-[6.5rem]" : "text-[2.4rem]"}`}>
        {formatRestant(restant)}
      </p>
    </div>
  );
}
