/** Horloge : l'heure locale et les dates, déjà formatées par l'appelant (rien ne lit l'horloge ici). */
export function Clock({ heure, date, hijri, tv = false }: {
  heure: string;
  /** Date grégorienne (« dimanche 22 novembre 2026 »). */
  date?: string;
  /** Date hégirienne ; séparée de la précédente seulement si les deux existent. */
  hijri?: string;
  tv?: boolean;
}) {
  const dates = [date, hijri].filter(Boolean);
  return (
    <div className="text-center">
      <time className={`block font-serif leading-none text-(--accent) ${tv ? "text-[9rem]" : "text-[4rem]"}`}>{heure}</time>
      {dates.length > 0 && (
        <p className={`m-0 mt-2 text-(--s-muted) ${tv ? "text-[1.8rem]" : "text-[1rem]"}`}>
          {dates.map((d, i) => (
            <span key={i}>
              {i > 0 && <span aria-hidden> · </span>}
              {d}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
