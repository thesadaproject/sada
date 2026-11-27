import { useState, type Dispatch, type SetStateAction } from "react";
import { useTranslation } from "react-i18next";
import { Btn, Field, Tabs, idOnglet, idPanneau, inputClass } from "@sada/ui";
import { api } from "../api";
import { useConfirm } from "../confirmContext";
import { EtapeStudio } from "./OnboardingStudio";

export type Entree = { mode: "camera" | "push"; url: string; push_rtmp: string; has_key?: boolean;
                       modes?: ("camera" | "push")[] };

/** Settings › Live › Connection: where the picture comes from. The Sada Studio (download, link, the PCs), OBS is
 *  no longer offered; the camera the server reads where it can (never hosted). An OBS stream key left from before
 *  is said, and can be revoked: anybody who still has it could publish. */
export function EntreeVideo({ entree, setEntree, onEdit, onKeyRevoked }: {
  entree: Entree; setEntree: Dispatch<SetStateAction<Entree>>;
  /** Something was changed (the page clears its own message). */
  onEdit?: () => void;
  /** The key is gone on the server: the page's saved copy of the input forgets it too. */
  onKeyRevoked?: () => void;
}) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [essai, setEssai] = useState<{ ok: boolean; detail: string } | null>(null);

  const revoquerCle = async () => {
    if (!(await confirm({ message: t("settings.keyRevokeConfirm"), action: t("settings.keyRevoke"), danger: true }))) return;
    try {
      await api.revokeStreamKey();
      setEntree((e) => ({ ...e, has_key: false }));
      onKeyRevoked?.();
      setEssai({ ok: true, detail: t("settings.keyRevoked") });
    } catch (err: any) {
      setEssai({ ok: false, detail: err.message });
    }
  };
  const testerEntree = async () => {
    setEssai(null);
    try {
      const r = await api.testInput(entree.mode, entree.url);
      setEssai({ ok: r.ok, detail: r.detail });
    } catch (err: any) {
      setEssai({ ok: false, detail: err.message });
    }
  };

  return (
    <div className="border-t border-line pt-3.5">
      <p className="m-0 mb-2 text-[0.75rem] font-semibold uppercase tracking-[0.12em] text-green">{t("settings.inputKicker")}</p>
      {/* A hosted platform offers the Sada Studio alone: no tabs when there is nothing to choose. */}
      {(entree.modes ?? ["push"]).length > 1 && <Tabs items={[{ cle: "push", label: t("settings.studioTab") },
                    { cle: "camera", label: t("onboarding.cameraTitle") }]}
        base="reglages-entree" label={t("settings.inputKicker")}
        valeur={entree.mode}
        onChange={(m) => { setEntree((e) => ({ ...e, mode: m === "push" ? "push" : "camera" })); setEssai(null); onEdit?.(); }} />}
      <div className="mt-3 grid gap-1.5"
        role="tabpanel" id={idPanneau("reglages-entree", entree.mode)} aria-labelledby={idOnglet("reglages-entree", entree.mode)}>
        {entree.mode === "camera" ? (
          <Field label={t("onboarding.cameraUrl")} aide={t("onboarding.cameraUrlHelp")}>
            <div className="flex gap-2">
              <input className={`${inputClass} font-mono text-[0.85rem]`} value={entree.url} spellCheck={false}
                placeholder="rtsp://…" onChange={(e) => { setEntree((x) => ({ ...x, url: e.target.value })); setEssai(null); onEdit?.(); }} />
              <Btn variante="ghost" onClick={testerEntree}>{t("onboarding.test")}</Btn>
            </div>
          </Field>
        ) : (
          <EtapeStudio contexte="settings" />
        )}
        {entree.mode === "push" && entree.has_key && (
          <div role="note" className="mt-2 grid gap-2 rounded-[9px] border border-warn/40 bg-warn-bg px-3 py-2.5 text-[0.88rem] text-warn">
            <span>{t("settings.keyLeft")}</span>
            <div><Btn variante="dangerGhost" onClick={revoquerCle}>{t("settings.keyRevoke")}</Btn></div>
          </div>
        )}
        {essai && <span className={`text-[0.86rem] ${essai.ok ? "text-green" : "text-muted"}`}>{essai.detail}</span>}
      </div>
    </div>
  );
}
