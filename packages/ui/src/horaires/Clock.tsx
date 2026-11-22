/** Horloge : l'heure locale et les dates, déjà formatées par l'appelant (rien ne lit l'horloge ici).
 *  Comme le « live » de la console : kicker en or, heure en EB Garamond, dates en texte atténué. */
export function Clock({ heure, date, hijri, kicker, tv = false }: {
  heure: string;
  /** Date grégorienne (« dimanche 22 novembre 2026 »). */
  date?: string;
  /** Date hégirienne, mois abrégé (« 20 Jou. I 1448 ») ; séparée de la précédente seulement si les deux existent. */
  hijri?: string;
  /** Petit titre au-dessus de l'heure (« Heure locale »). */
  kicker?: string;
  tv?: boolean;
}) {
  const dates = [date, hijri].filter(Boolean);
  return (
    <div>
      {kicker && (
        <p className={`m-0 mb-2 font-semibold uppercase leading-none tracking-[0.12em] text-(--s-kicker) ${tv ? "text-[1.3rem]" : "text-[0.75rem]"}`}>{kicker}</p>
      )}
      <time className={`block font-serif leading-none text-(--s-title) ${tv ? "text-[11rem]" : "text-[4rem]"}`}>{heure}</time>
      {dates.length > 0 && (
        <p className={`m-0 flex flex-col text-(--s-muted) md:flex-row ${tv ? "mt-4 text-[2rem]" : "mt-2 text-[0.95rem]"}`}>
          {dates.map((d, i) => (
            <span key={i} className="whitespace-nowrap">
              {i > 0 && <span aria-hidden className="hidden whitespace-pre md:inline"> · </span>}
              {d}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
