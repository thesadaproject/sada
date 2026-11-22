/** Tableau du mois : un jour par ligne, une colonne par prière (nom latin + arabe en sous-titre).
 *  Pur : l'appelant fournit libellés et heures formatés. Hauteur naturelle ; sur mobile le tableau
 *  défile dans son propre cadre, jamais la page. */
export type MonthColumn = { cle: string; nom: string; arabe: string };
export type MonthDay = {
  /** « 22 » */
  jour: string;
  /** « dim. » */
  semaine: string;
  /** Jour hégirien facultatif ; la colonne n'existe que si au moins un jour en porte un. */
  hijri?: string;
  /** heures par clé de colonne ; une clé absente s'affiche « — ». */
  heures: Record<string, string>;
  aujourdhui?: boolean;
  vendredi?: boolean;
};

export function MonthTable({ titre, sousTitre, colonnes, jours, enteteJour = "Jour", enteteHijri = "Hégire", tv = false }: {
  titre: string;
  sousTitre?: string;
  colonnes: MonthColumn[];
  jours: MonthDay[];
  enteteJour?: string;
  enteteHijri?: string;
  tv?: boolean;
}) {
  const avecHijri = jours.some((j) => j.hijri);
  const cell = tv ? "px-4 py-3 text-[1.6rem]" : "px-2.5 py-2 text-[0.95rem]";
  return (
    <section>
      <h1 className={`m-0 font-serif font-normal ${tv ? "text-[3.4rem]" : "text-[1.9rem]"}`}>{titre}</h1>
      {sousTitre && (
        <p lang="ar" dir="rtl" className={`sada-arabe m-0 text-(--s-muted) ${tv ? "text-[2rem]" : "text-[1.1rem]"}`}>
          {sousTitre}
        </p>
      )}
      <div className="mt-4 overflow-x-auto rounded-xl border border-(--s-line)">
        <table className="w-full border-collapse text-center">
          <thead>
            <tr>
              <th scope="col" className={`${cell} text-start font-semibold text-(--s-muted)`}>{enteteJour}</th>
              {avecHijri && <th scope="col" className={`${cell} font-semibold text-(--s-muted)`}>{enteteHijri}</th>}
              {colonnes.map((c) => (
                <th key={c.cle} scope="col" className={`${cell} font-semibold`}>
                  <span className="block">{c.nom}</span>
                  <span lang="ar" dir="rtl" className="sada-arabe block text-[0.85em] font-normal text-(--s-muted)">{c.arabe}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {jours.map((j) => (
              <tr
                key={j.jour}
                aria-current={j.aujourdhui ? "date" : undefined}
                style={j.aujourdhui ? { background: "var(--accent)", color: "var(--accent-ink)" } : undefined}
                className={`border-t border-(--s-line) ${j.vendredi && !j.aujourdhui ? "bg-(--s-card) font-semibold" : ""}`}
              >
                <th scope="row" className={`${cell} text-start font-semibold whitespace-nowrap`}>
                  {j.semaine} {j.jour}
                </th>
                {avecHijri && <td className={`${cell} ${j.aujourdhui ? "" : "text-(--s-muted)"}`}>{j.hijri ?? ""}</td>}
                {colonnes.map((c) => (
                  <td key={c.cle} className={cell}>{j.heures[c.cle] ?? "—"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
