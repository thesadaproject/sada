import { LOGO_PATH, LOGO_TRANSFORM, LOGO_VIEWBOX } from "./logo-data";

/** Le mot صدى, tracé de assets/logo/sada-mark-*.svg (jamais le croissant de static/emblem.svg).
 *  `couleur` : « or » (sur nuit), « encre » (sur ivoire) ou « courant » (currentColor). */
export function Logo({ couleur = "or", className = "", titre = "صدى" }: {
  couleur?: "or" | "encre" | "courant";
  className?: string;
  titre?: string;
}) {
  const fill = couleur === "or" ? "#E2C27A" : couleur === "encre" ? "#12261E" : "currentColor";
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox={LOGO_VIEWBOX} role="img" aria-label={titre} className={className}>
      <path transform={LOGO_TRANSFORM} fill={fill} d={LOGO_PATH} />
    </svg>
  );
}
