import { Clock, Countdown, ErrorPage, MonthTable, PrayerList, PrayerRow, Surface, cibleCompteARebours } from "../index";
import { ARABE_LONG, BORDEAUX, Cadre, PRIERES, VERT, jours } from "../fixtures";
import type { Meta, StoryObj } from "@storybook/react-vite";

/** Écran complet assemblé à partir des composants : les variantes ci-dessous ne changent que les props. */
function Ecran({ tv = false, iqama = true, accent, titre = "Mosquée de la Paix" }: {
  tv?: boolean; iqama?: boolean; accent?: string; titre?: string;
}) {
  const prieres = PRIERES.map((p) => ({ ...p, iqama: iqama ? p.iqama : undefined }));
  const cible = cibleCompteARebours(prieres);
  return (
    <Cadre tv={tv}>
      <Surface tv={tv} accent={accent} className={tv ? "min-h-[1080px]" : ""}>
        <div className={tv ? "grid grid-cols-[2fr_3fr] items-center gap-16" : "flex flex-col gap-6"}>
          <div className={`flex flex-col ${tv ? "gap-10" : "gap-6"}`}>
            <h1 lang="ar" dir="rtl" className={`sada-arabe m-0 text-center font-normal ${tv ? "text-[3rem]" : "text-[1.4rem]"}`}>{titre}</h1>
            <Clock heure="11:07" date="dimanche 22 novembre 2026" hijri="20 Joumada al-oula 1448" tv={tv} />
            {cible && <Countdown libelle="Prochaine prière" nom={cible.nom} arabe={cible.arabe} restant={4723} tv={tv} />}
          </div>
          <PrayerList tv={tv} entetes={iqama ? ["Adhan", "Iqama"] : undefined}>
            {prieres.map((p) => (
              <PrayerRow key={p.cle} {...p} suivante={p === cible} tv={tv} />
            ))}
          </PrayerList>
        </div>
      </Surface>
    </Cadre>
  );
}

const meta: Meta = { title: "Horaires/Écran" };
export default meta;
type S = StoryObj;

export const MobileAvecIqama: S = { render: () => <Ecran /> };
export const MobileSansIqama: S = { render: () => <Ecran iqama={false} /> };
export const MobileAccentBordeaux: S = { render: () => <Ecran accent={BORDEAUX} /> };
export const MobileAccentVert: S = { render: () => <Ecran accent={VERT} /> };
export const MobileArabeLong: S = { render: () => <Ecran titre={ARABE_LONG} /> };
export const TvAvecIqama: S = { render: () => <Ecran tv /> };
export const TvSansIqama: S = { render: () => <Ecran tv iqama={false} /> };
export const TvAccentBordeaux: S = { render: () => <Ecran tv accent={BORDEAUX} /> };
export const TvAccentVert: S = { render: () => <Ecran tv accent={VERT} /> };
export const TvArabeLong: S = { render: () => <Ecran tv titre={ARABE_LONG} /> };

function Mois({ tv = false, accent, theme = "nuit" }: { tv?: boolean; accent?: string; theme?: "nuit" | "ivoire" }) {
  return (
    <Cadre tv={tv}>
      <Surface tv={tv} accent={accent} theme={theme}>
        <MonthTable
          titre="Novembre 2026"
          sousTitre="نوفمبر ٢٠٢٦"
          colonnes={PRIERES.map(({ cle, nom, arabe }) => ({ cle, nom, arabe }))}
          jours={jours(30)}
          tv={tv}
        />
      </Surface>
    </Cadre>
  );
}
export const MoisMobile: S = { name: "Mois / mobile", render: () => <Mois /> };
export const MoisMobileIvoire: S = { name: "Mois / mobile ivoire bordeaux", render: () => <Mois theme="ivoire" accent={BORDEAUX} /> };
export const MoisTv: S = { name: "Mois / TV", render: () => <Mois tv /> };

function Erreur({ tv = false, accent }: { tv?: boolean; accent?: string }) {
  return (
    <Cadre tv={tv}>
      <Surface tv={tv} accent={accent} className={tv ? "min-h-[1080px]" : "min-h-[700px]"}>
        <ErrorPage
          tv={tv}
          titre="Mosquée introuvable"
          message="Cette adresse ne correspond à aucune mosquée publiée sur Sada."
          lien={{ href: "https://sadakhutbah.org", label: "Aller sur sadakhutbah.org" }}
        />
      </Surface>
    </Cadre>
  );
}
export const ErreurMobile: S = { name: "Erreur / mobile", render: () => <Erreur /> };
export const ErreurMobileVert: S = { name: "Erreur / mobile vert", render: () => <Erreur accent={VERT} /> };
export const ErreurTv: S = { name: "Erreur / TV", render: () => <Erreur tv /> };
