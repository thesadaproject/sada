import { useEffect, useState } from "react";
import { Entete, Surface } from "@sada/ui";
import type { Boot } from "./boot";
import { Ecran } from "./Ecran";
import { Erreur } from "./Erreur";
import { Mois } from "./Mois";

const TV = "(min-width: 1100px) and (orientation: landscape)";

/** Écran de télévision : paysage et assez large. Sinon, la mise en page mobile (une page de la console). */
function useTv(): boolean {
  const [tv, setTv] = useState(() => window.matchMedia(TV).matches);
  useEffect(() => {
    const m = window.matchMedia(TV);
    const f = () => setTv(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("tv", tv);
    // Sur télévision le pointeur disparaît après quelques secondes d'inactivité ; il n'y a aucun bouton.
    if (!tv) return;
    let t: ReturnType<typeof setTimeout>;
    const html = document.documentElement;
    const reveil = () => {
      html.classList.remove("inactif");
      clearTimeout(t);
      t = setTimeout(() => html.classList.add("inactif"), 3000);
    };
    reveil();
    const evts = ["mousemove", "mousedown", "touchstart", "keydown"] as const;
    evts.forEach((e) => document.addEventListener(e, reveil, { passive: true }));
    return () => {
      clearTimeout(t);
      html.classList.remove("inactif");
      evts.forEach((e) => document.removeEventListener(e, reveil));
    };
  }, [tv]);
  return tv;
}

export function App({ boot }: { boot: Boot }) {
  const tv = useTv();
  if (boot.view === "error" && boot.error) return <Erreur boot={boot} tv={tv} />;
  return (
    <Surface
      plein
      serre={boot.view === "screen"}
      tv={tv}
      theme={tv ? "nuit" : "ivoire"}
      accent={boot.accent}
      entete={<Entete mosquee={boot.name} logo={boot.logo || undefined} tv={tv} />}
    >
      {boot.view === "month" ? <Mois boot={boot} tv={tv} /> : <Ecran boot={boot} tv={tv} />}
    </Surface>
  );
}
