import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Btn, Field, inputClass } from "@sada/ui";
import { api, ApiError } from "../api";
import { usePolling } from "../usePolling";
import { systeme } from "../systeme";

/** Getting started with the Sada Studio: download it for this computer's system, then pair it with the mosque
 *  (the code the application shows), and see it come online. The picture comes from the Sada Studio, not OBS. */

type Plateforme = "windows" | "mac_arm64" | "mac_x64" | "linux";
export type Telechargement = { version: string | null; page: string; assets: Record<Plateforme, string | null> };
export type Appareil = { id: number; name: string; online: boolean; revoked: boolean };

const PRINCIPAUX: Record<"windows" | "mac" | "linux", Plateforme[]> = {
  windows: ["windows"],
  mac: ["mac_arm64", "mac_x64"],
  linux: ["linux"],
};
const TOUS: Plateforme[] = ["windows", "mac_arm64", "mac_x64", "linux"];

export function EtapeStudio({ onAppareils }: { onAppareils?: (a: Appareil[]) => void }) {
  const { t } = useTranslation();
  const [dl, setDl] = useState<Telechargement | null>(null);
  const [appareils, setAppareils] = useState<Appareil[]>([]);
  const [code, setCode] = useState("");
  const [nom, setNom] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; texte: string } | null>(null);

  useEffect(() => {
    api.studioDownload().then(setDl).catch(() => setDl(null));
  }, []);

  const lire = async () => {
    try {
      const r = await api.studioDevices();
      const actifs: Appareil[] = (r?.devices ?? []).filter((d: Appareil) => !d.revoked);
      setAppareils(actifs);
      onAppareils?.(actifs);
    } catch { /* the list is a convenience: pairing still works */ }
  };
  // The device comes online a few seconds after it is paired: the list follows it.
  usePolling(lire, 5000);

  const relier = async () => {
    setEnvoi(true); setMessage(null);
    try {
      const r = await api.studioPair(code, nom);
      setMessage({ ok: true, texte: r.message });
      setCode(""); setNom("");
      await lire();
    } catch (e) {
      setMessage({ ok: false, texte: e instanceof ApiError ? e.message : t("common.error") });
    } finally { setEnvoi(false); }
  };

  const sys = systeme();
  // Unknown system (a phone, a tablet): every installer, the person picks.
  const principaux = sys ? PRINCIPAUX[sys] : TOUS.filter((p) => dl?.assets[p]);
  const autres = TOUS.filter((p) => !principaux.includes(p) && dl?.assets[p]);
  const lien = (p: Plateforme) => dl?.assets[p] ?? dl?.page ?? "https://github.com/thesadaproject/sada-studio/releases/latest";
  const enLigne = appareils.filter((a) => a.online);

  return (
    <div className="grid gap-5">
      <section className="grid gap-2">
        <h3 className="m-0 text-[1rem] font-semibold">{t("onboarding.dlTitle")}</h3>
        <p className="m-0 max-w-[75ch] text-[0.9rem] text-muted">{t("onboarding.dlHint")}</p>
        <div className="flex flex-wrap items-center gap-2.5">
          {principaux.map((p, i) => (
            <a key={p} href={lien(p)} rel="noopener"
               className={`inline-flex min-h-10 items-center rounded-[9px] border px-4 font-semibold no-underline ${
                 i === 0 ? "border-deep bg-deep text-white hover:bg-deeper" : "border-deep text-deep hover:bg-paper-2"}`}>
              {t(`onboarding.dlFor.${p}`)}
            </a>
          ))}
          {principaux.length === 0 && (
            // GitHub could not be read: the releases page has them all
            <a href={dl?.page ?? lien("windows")} rel="noopener"
               className="inline-flex min-h-10 items-center rounded-[9px] border border-deep bg-deep px-4 font-semibold text-white no-underline hover:bg-deeper">
              {t("onboarding.dlAll")}
            </a>
          )}
          {dl?.version && <span className="text-[0.85rem] text-muted">{t("onboarding.dlVersion", { v: dl.version })}</span>}
        </div>
        {principaux.length > 0 && (
          <p className="m-0 flex flex-wrap gap-x-3 gap-y-1 text-[0.85rem] text-muted">
            {autres.length > 0 && <span>{t("onboarding.dlOthers")}</span>}
            {autres.map((p) => <a key={p} href={lien(p)} rel="noopener" className="text-green underline underline-offset-2">{t(`onboarding.dlFor.${p}`)}</a>)}
            {dl?.page && <a href={dl.page} rel="noopener" className="text-green underline underline-offset-2">{t("onboarding.dlAll")}</a>}
          </p>
        )}
      </section>

      <section className="grid gap-2 border-t border-line pt-4">
        <h3 className="m-0 text-[1rem] font-semibold">{t("onboarding.pairStep")}</h3>
        <p className="m-0 max-w-[75ch] text-[0.9rem] text-muted">{t("onboarding.pairHelp")}</p>
        <form className="grid gap-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto] sm:items-end"
              onSubmit={(e) => { e.preventDefault(); void relier(); }}>
          <Field label={t("devices.code")}>
            <input className={`${inputClass} font-mono uppercase tracking-[0.15em]`} value={code} maxLength={9}
                   autoComplete="off" spellCheck={false} placeholder="ABCD-2345" onChange={(e) => setCode(e.target.value)} />
          </Field>
          <Field label={t("devices.name")}>
            <input className={inputClass} value={nom} maxLength={60} placeholder={t("devices.namePlaceholder")} onChange={(e) => setNom(e.target.value)} />
          </Field>
          <Btn type="submit" disabled={envoi || code.replace(/[\s-]/g, "").length < 8}>{envoi ? t("common.saving") : t("onboarding.pair")}</Btn>
        </form>
        {message && <p role="status" className={`m-0 text-[0.88rem] ${message.ok ? "text-green" : "text-[#7a1f20]"}`}>{message.texte}</p>}
        {appareils.length > 0 && (
          <ul className="m-0 grid list-none gap-1.5 p-0">
            {appareils.map((a) => (
              <li key={a.id} className="flex items-center gap-2 text-[0.92rem]">
                <span aria-hidden className={`inline-block size-2.5 rounded-full ${a.online ? "bg-green" : "bg-dot-off"}`} />
                <span className="font-semibold">{a.name}</span>
                <span className="text-muted">{a.online ? t("onboarding.deviceOnline") : t("onboarding.deviceWaiting")}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="m-0 text-[0.85rem] text-muted">{enLigne.length > 0 ? t("onboarding.pairedHint") : t("onboarding.pairLater")}</p>
      </section>
    </div>
  );
}
