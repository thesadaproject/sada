/** Tableau du mois, dans le style des listes de la console : une surface blanche filetée de rayon 10,
 *  bandeau de tête sur fond papier-2, lignes séparées par un filet, date en marge (jour de la semaine en
 *  capitales minuscules, numéro en EB Garamond), Vendredi en gras, aujourd'hui teinté de l'accent.
 *  Pur : l'appelant fournit libellés et heures formatés.
 *  Sans débordement à 390 px : colonnes fixes, une heure « HH:MM » par cellule ; la date hégirienne
 *  (mois abrégé) est collée sous le numéro du jour, dans la même cellule (pas de colonne séparée). */
export type MonthColumn = { cle: string; nom: string; arabe: string };
export type MonthDay = {
  /** « 22 » */
  jour: string;
  /** « dim. » */
  semaine: string;
  /** Date hégirienne courte, mois abrégé (« 11 Jou. I »). */
  hijri?: string;
  /** heures par clé de colonne ; une clé absente s'affiche « — ». */
  heures: Record<string, string>;
  aujourdhui?: boolean;
  vendredi?: boolean;
  /** Horaires de Jumu'a (vendredi), un par ligne dans la colonne `colonneJumua`. */
  jumua?: string[];
  /** Repère discret sous la date (« Nuit 27 ») : nuits impaires des dix dernières nuits, jamais une nuit unique. */
  repere?: string;
};

export function MonthTable({ surtitre, titre, sousTitre, colonnes, jours, enteteJour = "Jour", colonneJumua = "dhuhr", legende, detail, actions, tv = false, compact = false }: {
  /** Petit titre en capitales vertes au-dessus du titre (« Horaires de prière »). */
  surtitre?: string;
  titre: string;
  sousTitre?: string;
  /** Ligne sous le titre (« Joumada al-oula - Joumada ath-thania 1448 »). */
  detail?: string;
  colonnes: MonthColumn[];
  jours: MonthDay[];
  enteteJour?: string;
  /** Clé de la colonne où les horaires de Jumu'a remplacent l'heure du vendredi. */
  colonneJumua?: string;
  /** Légende sous le tableau (voir Legende). */
  legende?: React.ReactNode;
  /** Sous le titre, avant le tableau (menu « Télécharger » en mobile). */
  actions?: React.ReactNode;
  tv?: boolean;
  /** Téléphone : une semaine à la fois, titre et lignes resserrés pour tenir dans 390x844 sans défilement. */
  compact?: boolean;
}) {
  const cell = tv ? "px-4 py-3 text-[1.7rem]" : `px-0.5 ${compact ? "py-1" : "py-1.5"} text-[0.85rem] md:px-3 md:py-2 md:text-[0.95rem]`;
  const tete = tv ? "px-4 py-3" : `px-0.5 ${compact ? "py-1" : "py-2"} md:px-3`;
  return (
    <section>
      {surtitre && (
        <p className={`m-0 mb-2 font-semibold uppercase leading-none tracking-[0.12em] text-(--s-kicker) ${tv ? "text-[1.3rem]" : "text-[0.75rem]"}`}>{surtitre}</p>
      )}
      <h1 className={`m-0 font-serif font-normal text-(--s-title) ${tv ? "text-[4rem] leading-[1.1]" : "text-[2.1rem] leading-[1.1]"}`}>{titre}</h1>
      {detail && <p className={`m-0 text-(--s-muted) ${tv ? "mt-1 text-[1.8rem]" : "mt-1 text-[0.95rem]"}`}>{detail}</p>}
      {sousTitre && (
        <p lang="ar" dir="rtl" className={`sada-arabe m-0 text-(--s-muted) ${tv ? "text-[2.2rem]" : "text-[1.2rem]"}`}>
          {sousTitre}
        </p>
      )}
      {actions}
      <div className={`${compact ? "mt-2" : "mt-4"} overflow-hidden rounded-[10px] border border-(--s-line) bg-(--s-card)`}>
        <table className="w-full table-fixed border-collapse text-center">
          <colgroup>
            <col className={tv ? "w-[14rem]" : "w-[4.4rem] md:w-[9rem]"} />
            {colonnes.map((c) => <col key={c.cle} />)}
          </colgroup>
          <thead>
            <tr className="bg-(--s-head)">
              <th scope="col" className={`${tete} text-start text-[0.72rem] font-semibold uppercase tracking-[0.14em] text-(--s-kicker) ${tv ? "pl-8 text-[1.2rem]" : "pl-3 md:pl-5"}`}>{enteteJour}</th>
              {colonnes.map((c) => (
                <th key={c.cle} scope="col" className={`${tete} font-semibold text-(--s-fg)`}>
                  <span className={`block leading-tight ${tv ? "font-serif text-[1.9rem] font-normal" : "font-serif text-[0.72rem] font-normal tracking-tight md:text-[1rem] md:tracking-normal"}`}>{c.nom}</span>
                  <span lang="ar" dir="rtl" className={`sada-arabe block font-normal text-(--s-muted) ${tv ? "text-[1.5rem]" : "text-[0.8rem] md:text-[0.95rem]"}`}>{c.arabe}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-(--s-line)">
            {jours.map((j) => (
              <tr
                key={j.jour}
                aria-current={j.aujourdhui ? "date" : undefined}
                style={j.aujourdhui ? { background: "var(--s-actif)" } : undefined}
                className={`border-t border-(--s-line) ${j.vendredi && !j.aujourdhui ? "bg-(--s-head) font-semibold" : ""}`}
              >
                <th
                  scope="row"
                  style={j.aujourdhui ? { boxShadow: "inset 4px 0 0 var(--accent)" } : j.repere ? { boxShadow: "inset 3px 0 0 color-mix(in srgb, var(--accent) 55%, transparent)" } : undefined}
                  className={`${cell} text-start font-normal ${tv ? "pl-8" : "pl-3 md:pl-5"}`}
                >
                  <span className="flex items-baseline gap-x-1.5">
                    <span className={`font-serif leading-none tabular-nums text-(--s-title) ${tv ? "text-[2.4rem]" : "text-[1.2rem]"}`}>{j.jour}</span>
                    <span className={`font-semibold uppercase leading-none tracking-[0.1em] text-(--s-muted) ${tv ? "text-[1.1rem]" : "text-[0.58rem]"}`}>{j.semaine}</span>
                  </span>
                  {j.hijri && <span className={`block whitespace-nowrap font-normal leading-tight text-(--s-muted) ${tv ? "text-[1.15rem]" : "text-[0.66rem] md:text-[0.78rem]"}`}>{j.hijri}</span>}
                  {j.repere && <span className={`block font-semibold leading-tight text-(--s-kicker) ${tv ? "text-[1.1rem]" : "text-[0.62rem]"}`}>{j.repere}</span>}
                </th>
                {colonnes.map((c) => (
                  <td key={c.cle} className={`${cell} tabular-nums`}>
                    {c.cle === colonneJumua && j.jumua && j.jumua.length > 0 ? (
                      <span className="flex flex-col items-center leading-tight">{j.jumua.map((h) => <span key={h}>{h}</span>)}</span>
                    ) : (
                      (j.heures[c.cle] ?? "—")
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {legende}
    </section>
  );
}

/** Légende du tableau : repères (vendredi, nuits impaires) et note. Aucune nuit n'est désignée : la note dit
 *  seulement où Laylat al-Qadr est recherchée. Chaque élément est facultatif. */
export function Legende({ vendredi, nuitsImpaires, note, nuitsImpairesNote, tv = false, compact = false }: {
  vendredi?: string;
  nuitsImpaires?: string;
  note?: string;
  nuitsImpairesNote?: string;
  tv?: boolean;
  /** Téléphone : texte et marges réduits. */
  compact?: boolean;
}) {
  const taille = tv ? "text-[1.4rem]" : compact ? "text-[0.74rem] leading-snug" : "text-[0.82rem]";
  if (!vendredi && !nuitsImpaires && !note) return null;
  return (
    <div className={`${compact ? "mt-2" : "mt-4"} grid gap-1 text-(--s-muted) ${taille}`}>
      <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1 p-0">
        {vendredi && (
          <li className="flex items-center gap-2">
            <span aria-hidden className="inline-block h-3 w-5 rounded-[3px] border border-(--s-line) bg-(--s-head)" />
            {vendredi}
          </li>
        )}
        {nuitsImpaires && (
          <li className="flex items-center gap-2">
            <span aria-hidden className="inline-block h-3 w-1 rounded-[2px]" style={{ background: "color-mix(in srgb, var(--accent) 55%, transparent)" }} />
            {nuitsImpaires}
          </li>
        )}
      </ul>
      {note && <p className="m-0">{note}</p>}
      {nuitsImpairesNote && <p className="m-0">{nuitsImpairesNote}</p>}
    </div>
  );
}
