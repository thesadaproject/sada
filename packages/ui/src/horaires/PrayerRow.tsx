import type { CSSProperties } from "react";

/** Ligne de prière : nom latin + nom arabe, adhan, iqama facultative.
 *  Chourouk (`chourouk`) n'a ni adhan ni iqama : une seule heure, et il n'est jamais
 *  « la prochaine » (le compte à rebours ne le vise pas). Pure : tout vient des props. */
export type PrayerRowProps = {
  nom: string;
  arabe: string;
  /** Heure de l'adhan, déjà formatée (« 05:42 »). Pour Chourouk : l'heure du lever. */
  adhan: string;
  /** Heure de l'iqama ; absente quand la mosquée n'en publie pas : la colonne disparaît. */
  iqama?: string;
  chourouk?: boolean;
  /** Prière visée par le compte à rebours (ignoré pour Chourouk). */
  suivante?: boolean;
  passee?: boolean;
  tv?: boolean;
};

export function PrayerRow({ nom, arabe, adhan, iqama, chourouk = false, suivante = false, passee = false, tv = false }: PrayerRowProps) {
  const cible = suivante && !chourouk;
  const avecIqama = !chourouk && iqama !== undefined;
  const style: CSSProperties = cible ? { background: "var(--accent)", color: "var(--accent-ink)", borderColor: "var(--accent)" } : {};
  return (
    <li
      aria-current={cible ? "true" : undefined}
      style={style}
      className={`grid items-center gap-x-3 rounded-xl border border-(--s-line) ${
        cible ? "" : "bg-(--s-card)"
      } ${tv ? "px-8 py-3" : "px-4 py-3"} ${passee && !cible ? "opacity-70" : ""} ${
        avecIqama ? "grid-cols-[minmax(0,1fr)_auto_auto]" : "grid-cols-[minmax(0,1fr)_auto]"
      }`}
    >
      <span className="min-w-0">
        <span className={`block font-serif leading-tight ${tv ? "text-[2.3rem]" : "text-[1.35rem]"} ${chourouk ? "italic" : ""}`}>{nom}</span>
        <span lang="ar" dir="rtl" className={`sada-arabe block truncate ${tv ? "text-[1.7rem]" : "text-[1.1rem]"} ${cible ? "" : "text-(--s-muted)"}`}>
          {arabe}
        </span>
      </span>
      <span className={`text-end font-semibold ${tv ? "min-w-40 text-[2.8rem]" : "min-w-16 text-[1.5rem]"} ${chourouk && !cible ? "font-normal text-(--s-muted)" : ""}`}>
        {adhan}
      </span>
      {avecIqama && (
        <span className={`text-end ${tv ? "min-w-40 text-[2.8rem]" : "min-w-16 text-[1.5rem]"} ${cible ? "" : "text-(--accent)"}`}>{iqama}</span>
      )}
    </li>
  );
}

/** Liste de prières à hauteur naturelle (jamais étirée). L'en-tête de colonnes n'apparaît qu'une fois,
 *  et seulement s'il y a des iqamas à distinguer des adhans. */
export function PrayerList({ children, entetes, tv = false }: {
  children: React.ReactNode;
  /** [adhan, iqama] : fournir les deux libellés pour afficher l'en-tête (mosquée avec iqama). */
  entetes?: [string, string];
  tv?: boolean;
}) {
  return (
    <div className="w-full">
      {entetes && (
        <div aria-hidden className={`mb-1 flex justify-end gap-x-3 text-[0.75rem] font-semibold uppercase tracking-[0.12em] text-(--s-muted) ${tv ? "px-8 text-[1.1rem]" : "px-4"}`}>
          <span className={`text-end ${tv ? "min-w-40" : "min-w-16"}`}>{entetes[0]}</span>
          <span className={`text-end ${tv ? "min-w-40" : "min-w-16"}`}>{entetes[1]}</span>
        </div>
      )}
      <ul className={`m-0 flex list-none flex-col p-0 ${tv ? "gap-3" : "gap-2"}`}>{children}</ul>
    </div>
  );
}

/** La prière visée par le compte à rebours : la première non passée, jamais Chourouk. */
export function cibleCompteARebours<T extends { chourouk?: boolean; passee?: boolean }>(prieres: T[]): T | undefined {
  return prieres.find((p) => !p.chourouk && !p.passee);
}
