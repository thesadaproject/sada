import { Cadran, Clock, Countdown, ErrorPage, Entete, MonthTable, PrayerList, PrayerRow, Surface, cibleCompteARebours } from "../index";
import { ARABE_LONG, BORDEAUX, Cadre, PRIERES, VERT, jours } from "../fixtures";
import type { Meta, StoryObj } from "@storybook/react-vite";

const DATE = "dimanche 22 novembre 2026";
const HIJRI = "20 Jou. I 1448";

/** Écran complet assemblé à partir des composants : les variantes ci-dessous ne changent que les props.
 *  Mobile = une page de la console (papier, « live » nuit, liste filetée) ; TV = l'écran nuit/or/ivoire. */
function Ecran({ tv = false, iqama = true, accent, titre = "Mosquée de la Paix" }: {
  tv?: boolean; iqama?: boolean; accent?: string; titre?: string;
}) {
  const prieres = PRIERES.map((p) => ({ ...p, iqama: iqama ? p.iqama : undefined }));
  const cible = cibleCompteARebours(prieres);
  const cadran = (
    <Cadran tv={tv}>
      <Clock kicker="Heure locale" heure="11:07" date={DATE} hijri={HIJRI} tv={tv} />
      {cible && <Countdown libelle="Prochaine prière" nom={cible.nom} arabe={cible.arabe} restant={4723} tv={tv} />}
    </Cadran>
  );
  const liste = (
    <PrayerList tv={tv} titre="Aujourd'hui">
      {prieres.map((p) => (
        <PrayerRow key={p.cle} {...p} suivante={p === cible} tv={tv} />
      ))}
    </PrayerList>
  );
  return (
    <Cadre tv={tv}>
      <Surface plein tv={tv} theme={tv ? "nuit" : "ivoire"} accent={accent} entete={<Entete mosquee={titre} tv={tv} />}>
        <h1 className="sr-only">{titre}</h1>
        {tv ? (
          <div className="grid flex-1 grid-cols-[2fr_3fr] items-stretch gap-16">
            {/* pt = hauteur du bandeau de la liste : le bloc horloge se centre sur les lignes, pas sur la carte. */}
            <div className="flex flex-col justify-center pt-[3.875rem]">{cadran}</div>
            {liste}
          </div>
        ) : (
          <div className="grid gap-4">{cadran}{liste}</div>
        )}
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

function Mois({ tv = false, accent, theme = "ivoire" }: { tv?: boolean; accent?: string; theme?: "nuit" | "ivoire" }) {
  return (
    <Cadre tv={tv}>
      <Surface plein tv={tv} accent={accent} theme={theme} entete={<Entete mosquee="Mosquée de la Paix" tv={tv} />}>
        <MonthTable
          surtitre="Horaires de prière"
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
export const MoisMobileBordeaux: S = { name: "Mois / mobile bordeaux", render: () => <Mois accent={BORDEAUX} /> };
export const MoisTv: S = { name: "Mois / TV", render: () => <Mois tv theme="nuit" /> };

function Erreur({ tv = false, accent }: { tv?: boolean; accent?: string }) {
  return (
    <Cadre tv={tv}>
      <Surface plein theme="nuit" tv={tv} accent={accent}>
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
