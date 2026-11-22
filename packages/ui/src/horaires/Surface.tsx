import type { ReactNode } from "react";
import { accentStyle } from "../accent";

/** Cadre d'une page d'horaires : surface nuit ou ivoire, accent de la mosquée, hauteur naturelle.
 *  `tv` pose les grandes échelles (1920x1080) ; sans lui, mobile d'abord. */
export function Surface({ theme = "nuit", accent, tv = false, className = "", children }: {
  theme?: "nuit" | "ivoire";
  /** Couleur d'accent de la mosquée (#rrggbb) ; absente : l'or Sada. */
  accent?: string | null;
  tv?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div style={accentStyle(accent)} className={`sada-${theme} w-full ${tv ? "px-16 py-10" : "px-4 py-6"} ${className}`}>
      {children}
    </div>
  );
}
