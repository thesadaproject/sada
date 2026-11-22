import { Btn, Card, Entete, Field, Kicker, Logo, Pill, Segmented, Table, Tabs, Title, inputClass } from "./index";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta = { title: "Base/Console" };
export default meta;

const onglets = [{ cle: "a", label: "Sermons", compte: 12 }, { cle: "b", label: "Clips" }, { cle: "c", label: "Réglages", eteint: true }];

/** Galerie pleine largeur : la barre du haut de la console, puis la page (max 1100 px comme `main`). */
export const Galerie: StoryObj = {
  render: () => (
    <div className="min-h-screen w-full bg-paper">
      <Entete mosquee="Mosquée de la Paix" />
      <div className="mx-auto grid w-full max-w-[1100px] grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-4 px-4 pt-6 pb-16">
        <Card>
          <Kicker>Boutons</Kicker>
          <Title>Charte de la console</Title>
          <div className="flex flex-wrap gap-2">
            {(["plein", "ghost", "leaf", "danger", "dangerGhost"] as const).map((v) => <Btn key={v} variante={v}>{v}</Btn>)}
            <Btn disabled>inactif</Btn>
          </div>
        </Card>
        <Card>
          <Field label="Nom" aide="Aide du champ"><input className={inputClass} defaultValue="Mosquée de la Paix" /></Field>
          <div className="mt-3 flex gap-2"><Pill statut="publie" label="Publié" /><Pill statut="a_valider" label="À valider" /><Pill statut="echec" label="Échec" /></div>
        </Card>
        <div className="col-span-full"><Tabs items={onglets} valeur="a" onChange={() => {}} /></div>
        <div className="col-span-full"><Segmented items={onglets} valeur="b" onChange={() => {}} /></div>
        <Card><Table entetes={["Titre", "Durée"]}><tr><td className="px-2 py-2">Khutba</td><td className="px-2 py-2">32:10</td></tr></Table></Card>
        <div className="flex items-center gap-6 rounded-[10px] bg-night p-5"><Logo couleur="or" className="h-16 w-auto" /><span className="font-serif text-[2rem] text-white">Sadā</span></div>
      </div>
    </div>
  ),
};
