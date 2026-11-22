/** Ligne de prière : nom latin (EB Garamond) et nom arabe (Amiri) sur la même ligne, puis l'heure de l'adhan.
 *  Une seule colonne d'heures. L'iqama n'a pas de colonne : elle suit l'heure en décalage discret (« +10 »)
 *  ou, si ce n'est pas un décalage simple, en petit (« iqama 20:30 »). Sans iqama : rien.
 *  Chourouk (`chourouk`) : l'heure seule, jamais « la prochaine ». Pure : tout vient des props. */
export type PrayerRowProps = {
  nom: string;
  arabe: string;
  /** Heure de l'adhan, déjà formatée (« 05:42 »). Pour Chourouk : l'heure du lever. */
  adhan: string;
  /** Heure de l'iqama (« 05:52 ») ; absente : rien n'est affiché. Ignorée pour Chourouk. */
  iqama?: string;
  chourouk?: boolean;
  /** Ligne d'information (Jumu'a) : comme Chourouk, sans iqama et jamais visée, mais en romain. */
  informatif?: boolean;
  /** Mot placé devant une iqama qui n'est pas un décalage simple (« iqama »). */
  libelleIqama?: string;
  /** Prière visée par le compte à rebours (ignoré pour Chourouk). */
  suivante?: boolean;
  passee?: boolean;
  tv?: boolean;
};

const minutes = (hhmm: string): number => {
  const [h, m] = hhmm.split(":");
  return Number(h) * 60 + Number(m);
};

/** « +10 » quand l'iqama suit l'adhan d'un décalage rond (5 à 60 minutes, multiple de 5) ; sinon `null` :
 *  l'appelant montre alors l'heure elle-même. */
export function decalageIqama(adhan: string, iqama: string): string | null {
  const d = minutes(iqama) - minutes(adhan);
  return d >= 5 && d <= 60 && d % 5 === 0 ? `+${d}` : null;
}

export function PrayerRow({ nom, arabe, adhan, iqama, chourouk = false, informatif = false, libelleIqama = "iqama", suivante = false, passee = false, tv = false }: PrayerRowProps) {
  const sansCible = chourouk || informatif;
  const cible = suivante && !sansCible;
  const decalage = iqama && !sansCible ? decalageIqama(adhan, iqama) : null;
  const badge = iqama && !sansCible ? (decalage ?? `${libelleIqama} ${iqama}`) : null;
  return (
    <li
      aria-current={cible ? "true" : undefined}
      className={`flex items-center ${tv ? "gap-x-8 px-10" : "gap-x-3 px-4 py-2.5 sm:px-5"} ${passee && !cible ? "text-(--s-muted)" : "text-(--s-fg)"}`}
      style={cible ? { background: "var(--s-actif)", boxShadow: "inset 4px 0 0 var(--accent)" } : undefined}
    >
      <span className="flex min-w-0 flex-1 items-baseline gap-x-3">
        <span className={`font-serif leading-tight ${tv ? "text-[3.2rem]" : "text-[1.4rem]"} ${chourouk ? "italic" : ""} ${cible ? "text-(--s-title)" : ""}`}>{nom}</span>
        <span lang="ar" dir="rtl" className={`sada-arabe truncate text-(--s-muted) ${tv ? "text-[2.6rem]" : "text-[1.2rem]"}`}>
          {arabe}
        </span>
      </span>
      {badge && (
        <span
          className={`whitespace-nowrap rounded-full border font-semibold leading-none ${tv ? "px-4 py-2 text-[1.6rem]" : "px-2 py-1 text-[0.72rem]"}`}
          style={{ color: "var(--s-kicker)", borderColor: "color-mix(in srgb, var(--s-kicker) 45%, transparent)" }}
          aria-label={`${libelleIqama} ${iqama}`}
        >
          {badge}
        </span>
      )}
      <span className={`text-end tabular-nums leading-none ${tv ? "min-w-[11rem] text-[3.4rem]" : "min-w-[4.25rem] text-[1.45rem]"} ${sansCible ? "font-normal" : "font-semibold"}`}>{adhan}</span>
    </li>
  );
}

/** Liste de prières dans le style des listes de la console : une seule surface filetée de rayon 10, bandeau de
 *  tête (kicker en capitales espacées), lignes séparées par un filet. Pas d'en-tête de colonnes : il n'y en a qu'une.
 *  Sur TV (`tv`), la liste remplit la hauteur et répartit ses lignes également. */
export function PrayerList({ children, titre, tv = false }: {
  children: React.ReactNode;
  /** Titre du bandeau (« Aujourd'hui »). */
  titre?: string;
  tv?: boolean;
}) {
  return (
    <div className={`flex w-full flex-col overflow-hidden rounded-[10px] border border-(--s-line) bg-(--s-card) ${tv ? "h-full" : ""}`}>
      {titre && (
        <div
          className={`flex items-baseline bg-(--s-head) font-semibold uppercase text-(--s-kicker) ${
            tv ? "gap-x-8 px-10 py-4 text-[1.2rem] tracking-[0.14em]" : "gap-x-3 px-4 py-2 text-[0.72rem] tracking-[0.14em] sm:px-5"
          }`}
        >
          {titre}
        </div>
      )}
      <ul className={`m-0 list-none divide-y divide-(--s-line) border-t border-(--s-line) p-0 ${tv ? "grid flex-1 [grid-auto-rows:1fr]" : ""}`}>
        {children}
      </ul>
    </div>
  );
}

/** La prière visée par le compte à rebours : la première non passée, jamais Chourouk. */
export function cibleCompteARebours<T extends { chourouk?: boolean; passee?: boolean }>(prieres: T[]): T | undefined {
  return prieres.find((p) => !p.chourouk && !p.passee);
}
