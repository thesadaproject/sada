/** Ligne de prière : nom latin (EB Garamond) et nom arabe (Amiri) sur la même ligne, adhan, iqama facultative.
 *  Chourouk (`chourouk`) n'a ni adhan ni iqama : une seule heure, et il n'est jamais « la prochaine »
 *  (le compte à rebours ne le vise pas). Les heures sont des chiffres tabulaires de la même couleur sur
 *  toute la ligne, active ou non. Pure : tout vient des props. */
export type PrayerRowProps = {
  nom: string;
  arabe: string;
  /** Heure de l'adhan, déjà formatée (« 05:42 »). Pour Chourouk : l'heure du lever. */
  adhan: string;
  /** Heure de l'iqama ; absente quand la mosquée n'en publie pas : la colonne disparaît. */
  iqama?: string;
  chourouk?: boolean;
  /** La liste a une colonne iqama (même si cette ligne n'en a pas) : Chourouk garde alors son heure sous
   *  « Adhan » et la cellule iqama reste vide. Par défaut : vrai si `iqama` est fourni. */
  colonneIqama?: boolean;
  /** Prière visée par le compte à rebours (ignoré pour Chourouk). */
  suivante?: boolean;
  passee?: boolean;
  tv?: boolean;
};

export function PrayerRow({ nom, arabe, adhan, iqama, chourouk = false, colonneIqama, suivante = false, passee = false, tv = false }: PrayerRowProps) {
  const cible = suivante && !chourouk;
  const avecIqama = colonneIqama ?? (!chourouk && iqama !== undefined);
  const heure = `text-end tabular-nums leading-none ${tv ? "min-w-[11rem] text-[3.4rem]" : "min-w-[4.25rem] text-[1.45rem]"}`;
  return (
    <li
      aria-current={cible ? "true" : undefined}
      className={`grid items-center ${tv ? "gap-x-8 px-10" : "gap-x-3 px-4 py-3 sm:px-5"} ${
        avecIqama ? "grid-cols-[minmax(0,1fr)_auto_auto]" : "grid-cols-[minmax(0,1fr)_auto]"
      } ${passee && !cible ? "text-(--s-muted)" : "text-(--s-fg)"}`}
      style={cible ? { background: "var(--s-actif)", boxShadow: "inset 4px 0 0 var(--accent)" } : undefined}
    >
      <span className="flex min-w-0 items-baseline gap-x-3">
        <span className={`font-serif leading-tight ${tv ? "text-[3.2rem]" : "text-[1.4rem]"} ${chourouk ? "italic" : ""} ${cible ? "text-(--s-title)" : ""}`}>{nom}</span>
        <span lang="ar" dir="rtl" className={`sada-arabe truncate text-(--s-muted) ${tv ? "text-[2.6rem]" : "text-[1.2rem]"}`}>
          {arabe}
        </span>
      </span>
      <span className={`${heure} ${chourouk ? "font-normal" : "font-semibold"}`}>{adhan}</span>
      {avecIqama && (
        <span className={`${heure} font-semibold`} aria-hidden={chourouk || iqama === undefined ? true : undefined}>
          {chourouk ? "" : iqama}
        </span>
      )}
    </li>
  );
}

/** Liste de prières dans le style des listes de la console : une seule surface filetée de rayon 10,
 *  bandeau de tête (kicker en capitales espacées), lignes séparées par un filet. L'en-tête des colonnes
 *  n'apparaît qu'une fois, et seulement s'il y a des iqamas à distinguer des adhans.
 *  Sur TV (`tv`), la liste remplit la hauteur et répartit ses lignes également. */
export function PrayerList({ children, titre, entetes, tv = false }: {
  children: React.ReactNode;
  /** Titre du bandeau (« Aujourd'hui »). */
  titre?: string;
  /** [adhan, iqama] : fournir les deux libellés pour afficher l'en-tête (mosquée avec iqama). */
  entetes?: [string, string];
  tv?: boolean;
}) {
  const colonne = `text-end ${tv ? "min-w-[11rem]" : "min-w-[4.25rem]"}`;
  return (
    <div className={`flex w-full flex-col overflow-hidden rounded-[10px] border border-(--s-line) bg-(--s-card) ${tv ? "h-full" : ""}`}>
      {(titre || entetes) && (
        <div
          className={`flex items-baseline bg-(--s-head) font-semibold uppercase text-(--s-kicker) ${
            tv ? "gap-x-8 px-10 py-4 text-[1.2rem] tracking-[0.14em]" : "gap-x-3 px-4 py-2 text-[0.72rem] tracking-[0.14em] sm:px-5"
          }`}
        >
          <span className="min-w-0 flex-1">{titre}</span>
          {entetes && (
            <>
              <span aria-hidden className={colonne}>{entetes[0]}</span>
              <span aria-hidden className={colonne}>{entetes[1]}</span>
            </>
          )}
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
