import { Logo } from "../Logo";

/** Page d'erreur publique (mosquée inconnue, non publiée, requête refusée) : logo, message, un lien. */
export function ErrorPage({ titre, message, lien, tv = false }: {
  titre: string;
  message: string;
  lien?: { href: string; label: string };
  tv?: boolean;
}) {
  return (
    <main className={`mx-auto flex flex-col items-center text-center ${tv ? "max-w-4xl gap-8 py-24" : "max-w-md gap-5 py-12"}`}>
      <Logo className={tv ? "w-96" : "w-44"} />
      <h1 className={`m-0 font-serif font-normal ${tv ? "text-[4rem]" : "text-[2rem]"}`}>{titre}</h1>
      <p className={`m-0 text-(--s-muted) ${tv ? "text-[2rem]" : "text-[1.05rem]"}`}>{message}</p>
      {lien && (
        <a
          href={lien.href}
          className={`inline-flex min-h-11 items-center rounded-[9px] px-5 font-semibold no-underline ${tv ? "text-[1.6rem]" : ""}`}
          style={{ background: "var(--accent)", color: "var(--accent-ink)" }}
        >
          {lien.label}
        </a>
      )}
    </main>
  );
}
