import type { ReactNode } from "react";
import { accentStyle } from "../accent";
import { Logo } from "../Logo";

/** Page d'horaires : une page de la console. `ivoire` = fond papier (mobile, mois) ; `nuit` = écran
 *  sombre aux couleurs nuit/ivoire/or de la console (TV). L'accent de la mosquée ne teinte que la ligne
 *  active et le bouton ; le cadre (fond, typo, filets, kicker) reste Sada.
 *  `plein` : la page occupe toute la hauteur de la fenêtre. `tv` pose les grandes échelles (1920x1080). */
export function Surface({ theme = "ivoire", accent, tv = false, plein = false, serre = false, entete, className = "", children }: {
  theme?: "nuit" | "ivoire";
  /** Couleur d'accent de la mosquée (#rrggbb) ; absente : l'or Sada. */
  accent?: string | null;
  tv?: boolean;
  plein?: boolean;
  /** Marges verticales réduites (écran mobile qui doit tenir sans défilement). */
  serre?: boolean;
  /** Barre du haut (voir Entete). */
  entete?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div style={accentStyle(accent)} className={`sada-${theme} flex w-full flex-col ${plein ? "min-h-screen" : ""} ${className}`}>
      {entete}
      <div className={`mx-auto flex w-full flex-1 flex-col ${tv ? "px-16 pt-10 pb-12" : (serre ? "max-w-[1100px] px-4 pt-4 pb-4" : "max-w-[1100px] px-4 pt-6 pb-16")}`}>{children}</div>
    </div>
  );
}

const ARABE = /[\u0600-\u06FF]/;

/** Barre du haut de la console : fond nuit, logo صدى en or, « Sadā » en EB Garamond, nom de la mosquée. */
export function Entete({ mosquee, logo, tv = false }: {
  mosquee?: string;
  /** Logo de la mosquée (URL), quand elle choisit de l'afficher. */
  logo?: string;
  tv?: boolean;
}) {
  const arabe = mosquee ? ARABE.test(mosquee) : false;
  return (
    <header className="bg-night text-night-ink shadow-[0_1px_0_rgba(0,0,0,0.2)]">
      <div className={`mx-auto flex items-center ${tv ? "gap-5 px-16 py-5" : "max-w-[1280px] gap-2.5 px-4 py-2"}`}>
        <Logo couleur="or" className={`w-auto shrink-0 ${tv ? "h-14" : "h-[26px]"}`} />
        {logo && <img src={logo} alt="" className={`w-auto shrink-0 rounded-[4px] object-contain ${tv ? "ms-4 h-14" : "ms-1 h-[26px]"}`} />}
        <span className="flex min-w-0 items-baseline gap-2">
          <span className={`font-serif leading-none text-white ${tv ? "text-[2.6rem]" : "text-[1.35rem]"}`}>Sadā</span>
          {mosquee && (
            <span
              {...(arabe ? { lang: "ar", dir: "rtl" } : {})}
              className={`min-w-0 truncate text-night-muted ${arabe ? "sada-arabe" : ""} ${tv ? "text-[1.6rem]" : "text-[0.82rem]"}`}
            >
              · {mosquee}
            </span>
          )}
        </span>
      </div>
    </header>
  );
}

/** Le « live » de la console : sur mobile, une carte nuit (rayon 10, marge 20) posée sur la page papier ;
 *  sur TV, la page est déjà nuit, la carte disparaît. */
export function Cadran({ tv = false, children }: { tv?: boolean; children: ReactNode }) {
  return tv ? (
    <div className="grid gap-10">{children}</div>
  ) : (
    <section className="sada-nuit grid gap-5 rounded-[10px] p-5">{children}</section>
  );
}
