import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../api";
import { liste } from "../format";
import { Btn, Card, Field, Kicker, Title, inputClass } from "@sada/ui";
import { Apercu, CalcFields } from "../PrayerFields";
import { calcDepuis, calcVersServeur, type Calc } from "../prayerForm";
import { EtapeStudio, type Appareil } from "./OnboardingStudio";

/** Mise en route : quatre écrans, un seul formulaire à la fois.
 *  1. d'où vient l'image : Sada Studio sur le PC de la mosquée (télécharger, relier), ou une caméra RTSP que le
 *     moteur lit (installation non hébergée). OBS n'est plus proposé ici (il reste dans Réglages),
 *  2. où le direct est publié,
 *  3. d'où viennent les horaires de prière (Mawaqit, calculés, ou plus tard : rien n'est enregistré),
 *  4. récapitulatif. Rien d'autre : les réglages fins restent dans Réglages, et le compartiment
 *  des rediffusions appartient à la plateforme (son propre écran), pas à la mosquée. */

type Cible = { id?: number; label: string; url: string; enabled: boolean };
type Mode = "camera" | "push";
type Entree = { mode: Mode; url: string; push_rtmp: string; configured: boolean; modes?: Mode[] };

const ETAPES = ["entree", "destinations", "prayer", "fin"] as const;
const DERNIERE = ETAPES.length - 1;
type ChoixHoraires = "mawaqit" | "compute" | "later";

export default function Onboarding() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [etape, setEtape] = useState(0);
  const [mode, setMode] = useState<Mode>("push");
  // The Sada Studio only, until the server says otherwise: a hosted platform never offers the camera (its server
  // cannot reach into a mosque's network), and it must not show for a moment while the settings load.
  const [modes, setModes] = useState<Mode[]>(["push"]);
  const [appareils, setAppareils] = useState<Appareil[]>([]);
  const [adresse, setAdresse] = useState("");
  const [cibles, setCibles] = useState<Cible[]>([]);
  const [essai, setEssai] = useState<{ ok: boolean; detail: string } | null>(null);
  const [test, setTest] = useState(false);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState("");
  const [horaires, setHoraires] = useState<ChoixHoraires>("later");
  const [urlMawaqit, setUrlMawaqit] = useState("");
  const [calc, setCalc] = useState<Calc>(calcDepuis({}));

  useEffect(() => {
    api.settings().then((r) => {
      const e: Entree = r.input;
      // A camera already set up stays chosen; otherwise the Sada Studio is the way in.
      setMode(e.mode === "camera" && e.configured ? "camera" : e.modes && !e.modes.includes("push") ? "camera" : "push");
      // The Sada Studio first.
      if (e.modes?.length) setModes([...e.modes].sort((a, b) => (a === "push" ? -1 : b === "push" ? 1 : 0)));
      setAdresse(e.url);
      setCibles(liste<any>(r.targets));
      // What is already chosen (the wizard may be reopened) is shown as chosen.
      setUrlMawaqit(r.prayer?.mawaqit_url ?? "");
      setCalc(calcDepuis(r.prayer?.calc));
      setHoraires(r.prayer?.source === "mawaqit" ? "mawaqit" : r.prayer?.source === "computed" ? "compute" : "later");
    }).catch((e) => setErreur(e instanceof ApiError ? e.message : t("common.error")));
  }, [t]);

  const tester = async () => {
    setTest(true); setEssai(null); setErreur("");
    try {
      const r = await api.testInput(mode, adresse);
      setEssai({ ok: r.ok, detail: r.detail });
    } catch (e) {
      setErreur(e instanceof ApiError ? e.message : t("common.error"));
    } finally { setTest(false); }
  };

  const enregistrerEntree = async () => {
    const r = await api.saveInput(mode, adresse);
    setAdresse(r.input.url);
  };

  const suivant = async () => {
    setEnvoi(true); setErreur("");
    try {
      if (etape === 0) await enregistrerEntree();
      if (etape === 1) await api.destinations(cibles.map(({ id, label, url, enabled }) => ({ id, label, url, enabled })));
      // "Later" saves nothing (no row is created): the step is optional, like the replays one.
      if (etape === 2 && horaires === "mawaqit") await api.prayerSave({ source: "mawaqit", mawaqit_url: urlMawaqit });
      if (etape === 2 && horaires === "compute") await api.prayerSave({ source: "computed", calc: calcVersServeur(calc) });
      setEtape((n) => Math.min(n + 1, DERNIERE));
    } catch (e) {
      setErreur(e instanceof ApiError ? e.message : t("common.error"));
    } finally { setEnvoi(false); }
  };

  /** Terminée ou passée : le back-office ne la repropose plus, tout reste dans Réglages. */
  const terminer = async () => {
    try { await api.onboardingDone(); } catch { /* sans importance : on sort quand même */ }
    nav("/");
  };

  const maj = (i: number, champ: keyof Cible, valeur: string | boolean) =>
    setCibles((liste) => liste.map((c, j) => (j === i ? { ...c, [champ]: valeur } : c)));

  const entree = (
    <Card>
      <Kicker>{t("onboarding.inputKicker")}</Kicker>
      <Title>{t("onboarding.inputTitle")}</Title>
      {modes.length > 1 && <div className="mb-4 grid gap-2.5 sm:grid-cols-2">
        {modes.map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => { setMode(m); setEssai(null); }}
            className={`cursor-pointer rounded-[9px] border p-3 text-left ${mode === m ? "border-leaf bg-leaf/10" : "border-line bg-white hover:bg-paper-2"}`}
          >
            <span className="block font-semibold">{m === "push" ? t("onboarding.studioTitle") : t("onboarding.cameraTitle")}</span>
            <span className="mt-0.5 block text-[0.85rem] text-muted">{m === "push" ? t("onboarding.studioHint") : t("onboarding.cameraHint")}</span>
          </button>
        ))}
      </div>}

      {mode === "camera" ? (
        <div className="grid gap-3">
          <Field label={t("onboarding.cameraUrl")} aide={t("onboarding.cameraUrlHelp")}>
            <input className={`${inputClass} font-mono text-[0.88rem]`} value={adresse}
                   onChange={(e) => { setAdresse(e.target.value); setEssai(null); }} placeholder="rtsp://…" />
          </Field>
          <div className="flex items-center gap-2.5">
            <Btn variante="ghost" onClick={tester} disabled={test}>{test ? t("onboarding.testing") : t("onboarding.test")}</Btn>
            {essai && <span className={`text-[0.88rem] ${essai.ok ? "text-green" : "text-muted"}`}>{essai.detail}</span>}
          </div>
        </div>
      ) : (
        <EtapeStudio onAppareils={setAppareils} />
      )}
    </Card>
  );

  const destinations = (
    <Card>
      <Kicker>{t("onboarding.destKicker")}</Kicker>
      <Title>{t("onboarding.destTitle")}</Title>
      <p className="mt-0 mb-3 max-w-[80ch] text-[0.9rem] text-muted">{t("onboarding.destHint")}</p>
      {cibles.length === 0 && <p className="m-0 mb-3 text-[0.9rem] text-muted">{t("onboarding.destNone")}</p>}
      <div className="grid gap-2.5">
        {cibles.map((c, i) => (
          <div key={i} className="grid items-center gap-2 sm:grid-cols-[minmax(6rem,9rem)_1fr_auto_auto]">
            <input className={inputClass} value={c.label} placeholder={t("onboarding.destLabel")}
                   onChange={(e) => maj(i, "label", e.target.value)} aria-label={t("onboarding.destLabel")} />
            <input className={`${inputClass} font-mono text-[0.82rem]`} value={c.url} placeholder="rtmps://…"
                   onChange={(e) => maj(i, "url", e.target.value)} aria-label={t("onboarding.destUrl")} />
            <label className="flex items-center gap-1.5 text-[0.88rem] whitespace-nowrap">
              <input type="checkbox" checked={c.enabled} onChange={(e) => maj(i, "enabled", e.target.checked)} />
              {t("onboarding.destEnabled")}
            </label>
            <Btn variante="dangerGhost" onClick={() => setCibles((l) => l.filter((_, j) => j !== i))}>
              {t("onboarding.destRemove")}
            </Btn>
          </div>
        ))}
      </div>
      <div className="mt-3">
        <Btn variante="ghost" onClick={() => setCibles((l) => [...l, { label: "", url: "", enabled: true }])}>
          + {t("onboarding.destAdd")}
        </Btn>
      </div>
    </Card>
  );

  const choixHoraires: ChoixHoraires[] = ["mawaqit", "compute", "later"];
  const prayer = (
    <Card>
      <Kicker>{t("prayer.onb.kicker")}</Kicker>
      <Title>{t("prayer.onb.title")}</Title>
      <p className="mt-0 mb-3 max-w-[80ch] text-[0.9rem] text-muted">{t("prayer.onb.hint")}</p>
      <div role="radiogroup" aria-label={t("prayer.onb.title")} className="mb-4 grid gap-2.5 sm:grid-cols-3">
        {choixHoraires.map((c) => (
          <button key={c} type="button" role="radio" aria-checked={horaires === c} onClick={() => { setHoraires(c); setErreur(""); }}
            className={`cursor-pointer rounded-[9px] border p-3 text-left ${horaires === c ? "border-leaf bg-leaf/10" : "border-line bg-white hover:bg-paper-2"}`}>
            <span className="block font-semibold">{t(`prayer.onb.${c}`)}</span>
            <span className="mt-0.5 block text-[0.85rem] text-muted">{t(`prayer.onb.${c}Hint`)}</span>
          </button>
        ))}
      </div>
      {horaires === "mawaqit" && (
        <Field label={t("prayer.mawaqitUrl")}>
          <input className={inputClass} value={urlMawaqit} onChange={(e) => setUrlMawaqit(e.target.value)}
                 placeholder={t("prayer.mawaqitPlaceholder")} inputMode="url" />
        </Field>
      )}
      {horaires === "compute" && (
        <div className="grid gap-3">
          <CalcFields calc={calc} setCalc={setCalc} />
          <Apercu calc={calc} jours={2} />
        </div>
      )}
    </Card>
  );

  const resumeHoraires = horaires === "mawaqit" ? t("prayer.onb.summaryMawaqit")
    : horaires === "compute" ? t("prayer.onb.summaryComputed", { methode: t(`prayer.methods.${calc.method}`) })
    : t("prayer.onb.summaryLater");

  const resumeStudio = appareils.length
    ? t("onboarding.summaryStudio", { noms: appareils.map((a) => a.name).join(", ") })
    : t("onboarding.summaryStudioNone");

  const fin = (
    <Card>
      <Kicker>{t("onboarding.doneKicker")}</Kicker>
      <Title>{t("onboarding.doneTitle")}</Title>
      <p className="mt-0 mb-3 max-w-[80ch] text-[0.92rem]">{t("onboarding.doneBody")}</p>
      <p className="m-0 mb-4 font-mono text-[0.85rem] text-muted">
        {t("onboarding.summary", { entree: mode === "push" ? resumeStudio : adresse, n: cibles.filter((c) => c.enabled).length })}
        {" · "}{resumeHoraires}
      </p>
      <Btn variante="leaf" onClick={terminer}>{t("onboarding.finish")}</Btn>
    </Card>
  );

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-1.5">
        {ETAPES.map((cle, i) => (
          <span key={cle} className={`rounded-full px-2.5 py-1 text-[0.82rem] font-semibold ${
            i === etape ? "bg-leaf text-night" : i < etape ? "bg-leaf/15 text-green" : "bg-paper-2 text-muted"}`}>
            {i + 1}. {t(`onboarding.step_${cle}`)}
          </span>
        ))}
      </div>

      {etape === 0 && entree}
      {etape === 1 && destinations}
      {etape === 2 && prayer}
      {etape === 3 && fin}

      {erreur && <p className="m-0 rounded-lg bg-err-bg px-3 py-2 text-[0.9rem] text-[#7a1f20]">{erreur}</p>}

      {etape < DERNIERE && (
        <div className="flex items-center gap-2">
          {etape > 0 && <Btn variante="ghost" onClick={() => { setEtape(etape - 1); setErreur(""); }}>← {t("onboarding.back")}</Btn>}
          <Btn onClick={suivant} disabled={envoi}>{envoi ? t("common.saving") : t("onboarding.next")}</Btn>
          <button type="button" onClick={terminer} className="ml-2 cursor-pointer border-0 bg-transparent text-[0.88rem] text-muted underline underline-offset-4">
            {t("onboarding.skip")}
          </button>
        </div>
      )}
    </div>
  );
}
