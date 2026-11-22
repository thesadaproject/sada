import { ErrorPage, Surface } from "@sada/ui";
import type { Boot } from "./boot";

/** 404 (mosquée inconnue, non publiée, publiée sur Mawaqit) et 422 (mois mal écrit) : le cadre nuit de Sada,
 *  le message dans la langue de la mosquée, un lien vers sadakhutbah.org. Le code HTTP vient du serveur. */
export function Erreur({ boot, tv }: { boot: Boot; tv: boolean }) {
  const e = boot.error!;
  const site = { href: `https://${e.site}`, label: e.site };
  const mawaqit = e.mawaqit_url.startsWith("https://") ? { href: e.mawaqit_url, label: boot.labels.page.mawaqit_button } : undefined;
  return (
    <Surface plein theme="nuit" tv={tv}>
      <ErrorPage
        tv={tv}
        titre={e.title}
        message={e.text}
        lien={mawaqit ?? site}
        lienSecondaire={mawaqit ? site : undefined}
      />
    </Surface>
  );
}
