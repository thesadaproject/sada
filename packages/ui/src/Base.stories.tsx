import { Btn, Card, Field, Kicker, Logo, Pill, Segmented, Table, Tabs, Title, inputClass } from "./index";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta = { title: "Base/Console" };
export default meta;

const onglets = [{ cle: "a", label: "Sermons", compte: 12 }, { cle: "b", label: "Clips" }, { cle: "c", label: "Réglages", eteint: true }];

export const Galerie: StoryObj = {
  render: () => (
    <div className="grid max-w-3xl gap-4 bg-paper p-6">
      <Logo couleur="encre" className="w-40" />
      <Card>
        <Kicker>Bouton</Kicker>
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
      <Tabs items={onglets} valeur="a" onChange={() => {}} />
      <Segmented items={onglets} valeur="b" onChange={() => {}} />
      <Card><Table entetes={["Titre", "Durée"]}><tr><td className="px-2 py-2">Khutba</td><td className="px-2 py-2">32:10</td></tr></Table></Card>
      <div className="bg-night p-4"><Logo couleur="or" className="w-40" /></div>
    </div>
  ),
};
