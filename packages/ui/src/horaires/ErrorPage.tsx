import { Logo } from "../Logo";

/** Page d'erreur publique (mosquée inconnue, non publiée, requête refusée) : pleine hauteur, comme la page
 *  de connexion de la console (logo, « Sadā » en EB Garamond), puis le titre, le message et un lien.
 *  À poser dans une Surface `plein` : la page occupe toute la fenêtre, contenu centré. */
export function ErrorPage({ titre, message, lien, tv = false }: {
  titre: string;
  message: string;
  lien?: { href: string; label: string };
  tv?: boolean;
}) {
  return (
    <main className={`mx-auto flex w-full flex-1 flex-col items-center justify-center text-center ${tv ? "max-w-4xl gap-6" : "max-w-md gap-4"}`}>
      <div className="mb-2 flex flex-col items-center gap-3">
        <Logo couleur="or" className={`w-auto ${tv ? "h-28" : "h-16"}`} />
        <p className={`m-0 font-serif leading-none text-white ${tv ? "text-[4.5rem]" : "text-[2rem]"}`}>Sadā</p>
      </div>
      <h1 className={`m-0 font-serif font-normal leading-[1.15] text-(--s-title) ${tv ? "text-[4rem]" : "text-[1.55rem]"}`}>{titre}</h1>
      <p className={`m-0 text-(--s-muted) ${tv ? "text-[2rem]" : "text-[1rem]"}`}>{message}</p>
      {lien && (
        <a
          href={lien.href}
          className={`mt-2 inline-flex min-h-11 items-center justify-center rounded-[9px] border border-(--accent) bg-(--accent) px-5 py-2.5 font-semibold text-(--accent-ink) no-underline ${tv ? "min-h-16 px-10 text-[1.6rem]" : ""}`}
        >
          {lien.label}
        </a>
      )}
    </main>
  );
}
