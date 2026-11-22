/** « HH:MM:SS » à partir d'un nombre de secondes (jamais négatif). */
export function formatRestant(secondes: number): string {
  const s = Math.max(0, Math.floor(secondes));
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

/** Compte à rebours vers la prochaine prière (jamais Chourouk : le choix se fait en amont, cf.
 *  cibleCompteARebours). Pur : `restant` est en secondes, l'appelant le fait avancer. */
export function Countdown({ libelle, nom, arabe, restant, tv = false }: {
  /** « Prochaine prière » */
  libelle: string;
  nom: string;
  arabe?: string;
  restant: number;
  tv?: boolean;
}) {
  return (
    <div className="text-center">
      <p className={`m-0 font-semibold uppercase tracking-[0.12em] text-(--s-muted) ${tv ? "text-[1.3rem]" : "text-[0.75rem]"}`}>{libelle}</p>
      <p className={`m-0 mt-1 font-serif ${tv ? "text-[3.4rem]" : "text-[1.6rem]"}`}>
        {nom}
        {arabe && (
          <span lang="ar" dir="rtl" className="sada-arabe ms-3 text-(--s-muted)">
            {arabe}
          </span>
        )}
      </p>
      <p role="timer" className={`m-0 font-semibold leading-tight ${tv ? "text-[5rem]" : "text-[2.4rem]"}`}>
        {formatRestant(restant)}
      </p>
    </div>
  );
}
