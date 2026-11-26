import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { playMonitor, type MonitorState } from "../monitor";
import { Btn } from "@sada/ui";
import { BusyBtn } from "../BusyBtn";
import { currentSession } from "../session";
import { useConfirm } from "../confirmContext";
import { nombre } from "../format";
import { usePolling, useNow } from "../usePolling";
import { useAppDispatch, useAppSelector } from "../store";
import {
  actionId, selectConfirmed, selectPending, selectReadAt, selectRetour, selectView,
  type Health, type Live, type SceneInfo,
} from "../store/liveSlice";
import { fetchRegie, sendCommand, takeover, toggleMute } from "../store/liveThunks";

/** Control room (“Régie”): two monitors, the scene grid and the transport of the live.
 *
 *  Preview = raw feed of the mosque, Programme = what goes on air. Both are played through the back
 *  office (WebRTC, HLS fallback), which only serves the mosque of the session to the `live` right. */

/** Full screen (the feed is hidden) or drawn over the camera: the server says it with `scene_kind`;
 *  an older server does not, and only the khutba and the dars keep the camera then. */
function pleinEcran(sc: string, scenes: SceneInfo[]): boolean {
  const k = scenes.find((x) => x.id === sc)?.scene_kind;
  if (k) return k === "full";
  return sc !== "khutba" && sc !== "dars";
}

/** "HH:MM:SS" -> seconds of the day. */
function secondes(h?: string | null): number | null {
  const m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(h ?? "");
  return m ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3] ?? 0) : null;
}

function hms(s: number): string {
  const v = Math.max(0, Math.floor(s));
  const h = Math.floor(v / 3600), m = Math.floor((v % 3600) / 60), r = v % 60;
  return `${h > 0 ? `${h}:` : ""}${String(m).padStart(h > 0 ? 2 : 1, "0")}:${String(r).padStart(2, "0")}`;
}

/** One monitor: 16:9 picture, muted by default, a clean “offline” slate when nothing is received. */
/** Studio mode: the scene staged in the preview, before it is sent on air. */
type Prepa = { scene: string; plein: boolean };

function Moniteur({ which, titre, sousTitre, available, sante, antenne, prepa, actions }: {
  which: "source" | "program"; titre: string; sousTitre: string; available: boolean; sante: Health; antenne: boolean;
  prepa?: Prepa | null; actions?: React.ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const video = useRef<HTMLVideoElement>(null);
  const [muet, setMuet] = useState(true);
  const [etat, setEtat] = useState<MonitorState>("connecting");
  useEffect(() => {
    if (!available || !video.current) return;
    return playMonitor(which, video.current, setEtat);
  }, [which, available]);
  const enLigne = available && (etat === "webrtc" || etat === "hls");
  return (
    <figure className="m-0 min-w-0">
      <figcaption className="mb-1.5 flex items-center justify-between gap-2">
        <span className="flex items-baseline gap-2">
          <span className="text-[0.75rem] font-semibold uppercase tracking-[0.12em] text-leaf">{titre}</span>
          <span className="truncate text-[0.8rem] text-night-muted">{sousTitre}</span>
        </span>
        {antenne && enLigne && (
          <span className="rounded bg-live px-1.5 py-0.5 text-[0.7rem] font-bold uppercase tracking-wider text-white">
            {t("regie.onAir")}
          </span>
        )}
      </figcaption>
      <div className={`relative aspect-video overflow-hidden rounded-lg bg-black ring-2 ${antenne && enLigne ? "ring-live" : "ring-white/10"}`}>
        <video ref={video} autoPlay muted={muet} playsInline className={`size-full object-contain ${enLigne ? "" : "hidden"}`} />
        {prepa && (
          // Full screens hide the feed; a banner scene is drawn over it, as on air.
          <img src={`/api/v1/live/regie/scene/${prepa.scene}.png`} alt=""
               className={`absolute inset-0 z-10 size-full object-contain ${prepa.plein ? "bg-black" : ""}`} />
        )}
        {enLigne ? (
          <>
            <button
              type="button"
              onClick={() => setMuet((m) => !m)}
              aria-pressed={!muet}
              className="absolute right-2 bottom-2 z-20 inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-md border border-white/25 bg-black/60 px-2.5 text-[0.8rem] font-semibold text-white hover:bg-black/80 max-md:min-h-11"
            >
              <svg aria-hidden="true" viewBox="0 0 20 20" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 8h3l4-3v10l-4-3H3z" />
                {muet ? <path d="M13 8l4 4M17 8l-4 4" /> : <path d="M13.5 7.5a3.5 3.5 0 0 1 0 5M15.5 5.5a6.5 6.5 0 0 1 0 9" />}
              </svg>
              {muet ? t("regie.soundOn") : t("regie.soundOff")}
            </button>
          </>
        ) : prepa ? null : (
          <div className="flex size-full flex-col items-center justify-center gap-1.5 bg-[repeating-linear-gradient(135deg,#0b1d18_0_14px,#0e231d_14px_28px)] text-center">
            <span className="inline-flex items-center gap-2 text-[0.95rem] font-semibold text-night-ink">
              <span className={`inline-block size-2 rounded-full ${available && etat === "connecting" ? "animate-pulse bg-gold" : "bg-dot-off"}`} />
              {available && etat === "connecting" ? t("regie.connecting") : t("regie.offline")}
            </span>
            <span className="max-w-[80%] text-[0.8rem] text-night-muted">{t("regie.offlineHint")}</span>
          </div>
        )}
      </div>
      <div className="mt-1 flex min-h-[1.2rem] items-center gap-3">
      <p className="m-0 flex gap-3 text-[0.78rem] text-night-muted tabular-nums">
        {enLigne && <span>{etat === "webrtc" ? "WebRTC" : "HLS"}</span>}
        {sante?.online ? (
          <>
            {sante.kbps != null && <span>{t("regie.kbps", { n: nombre(sante.kbps, i18n.language) })}</span>}
            {sante.readers != null && <span>{t("regie.readers", { n: sante.readers })}</span>}
          </>
        ) : !enLigne && <span>&nbsp;</span>}
      </p>
      {actions && <div className="ml-auto flex gap-2">{actions}</div>}
      </div>
    </figure>
  );
}

/** Narrower than an unfolded foldable or a tablet: a phone. The control room asks for a wider
 *  screen there, without forbidding it (soft block). */
const ETROIT = "(max-width: 599px)";

function useEtroit(): boolean {
  const [v, setV] = useState(() => window.matchMedia(ETROIT).matches);
  useEffect(() => {
    const mq = window.matchMedia(ETROIT);
    const f = () => setV(mq.matches);
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, []);
  return v;
}

export default function Regie() {
  const etroit = useEtroit();
  const [forcer, setForcer] = useState(() => sessionStorage.getItem("regie.mobile") === "1");
  const { t } = useTranslation();
  if (etroit && !forcer) {
    return (
      <div className="mx-auto grid max-w-sm gap-3 rounded-[10px] bg-night p-5 text-night-ink">
        <h1 className="m-0 text-[1.1rem] font-bold text-white">{t("regie.narrowTitle")}</h1>
        <p className="m-0 text-[0.92rem] leading-snug">{t("regie.narrowText")}</p>
        <Btn variante="light" className="justify-self-start" onClick={() => { sessionStorage.setItem("regie.mobile", "1"); setForcer(true); }}>
          {t("regie.narrowAnyway")}
        </Btn>
      </div>
    );
  }
  return <RegieEcran />;
}

/** The status strip's facts. The one-second tick lives here, so the rest of the page does not
 *  re-render every second (the monitors hold live video). */
function LiveFacts({ live, lu }: { live: Live; lu: number }) {
  const { t } = useTranslation();
  const now = useNow(1000);
  const horlogeS = secondes(live.clock);
  const maintenant = horlogeS != null ? horlogeS + (now - lu) / 1000 : null;
  const debut = secondes(live.session?.started);
  const duree = live.stream_on && maintenant != null && debut != null ? hms(maintenant - debut) : "—";
  return (
    <dl className="m-0 flex min-w-0 flex-wrap gap-x-5 gap-y-1 text-[0.9rem]">
      {[
        [t("regie.clock"), maintenant != null ? hms(maintenant % 86400) : "—"],
        [t("regie.onAirFor"), duree],
        [t("regie.next"), live.next_session ?? "—"],
        [t("regie.mode"), live.override ? t("regie.manual") : t("regie.auto")],
      ].map(([k, v]) => (
        <div key={k} className="flex items-baseline gap-1.5">
          <dt className="text-night-muted">{k}</dt>
          <dd className="m-0 font-semibold text-white tabular-nums">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function RegieEcran() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const dispatch = useAppDispatch();
  // What is shown: the confirmed state with the actions in flight on top (see store/liveSlice.ts).
  const vue = useAppSelector(selectView);
  const confirme = useAppSelector(selectConfirmed);
  const pending = useAppSelector(selectPending);
  const lu = useAppSelector(selectReadAt);
  const retour = useAppSelector(selectRetour);
  const [nom, setNom] = useState("");
  const [mention, setMention] = useState("");
  const [prepa, setPrepa] = useState<string | null>(null);

  // State refreshed every 3 s, paused while the tab is hidden; the clock ticks in LiveFacts. A poll
  // that left before a command (or older than the last `rev`) is dropped by the slice.
  usePolling(() => dispatch(fetchRegie()), 3000);

  // The staged scene leaves the preview once the server confirms it on air, not when the click leaves.
  const sceneConfirmee = confirme?.live.scene ?? null;
  const prisePending = Object.keys(pending).some((k) => k.startsWith("scene:"));
  // Adjusted while rendering (React's pattern for state derived from props), not in an effect.
  if (prepa && sceneConfirmee === prepa && !prisePending) setPrepa(null);

  const enCours = (key: string, valeur?: string) => Boolean(pending[actionId(key, valeur)]);

  async function envoyer(key: string, corps: Record<string, string> = {}) {
    const c = vue?.commands.find((x) => x.key === key);
    if (!c) return;
    if (c.destructive && !(await confirm({ message: t(`dashboard.confirm.${key}`), action: t(`dashboard.cmd.${key}`) }))) return;
    await dispatch(sendCommand(key, corps));
  }

  if (!vue) return <p className="py-16 text-center text-muted">{t("common.loading")}</p>;
  const { live, commands: commandes, monitors: moniteurs, audio, publisher: editeur, scenes: infos } = vue;
  const texteRetour = retour && (retour.texte ?? (retour.cle ? t(retour.cle) : ""));

  const horsService = live.ok === false;
  const etat = horsService
    ? t("dashboard.unreachable")
    : (live.state && t(`dashboard.state.${live.state}`, { defaultValue: live.state })) || t("dashboard.liveOff");
  const scenes = commandes.find((c) => c.key === "scene")?.choices ?? [];
  const extend = commandes.find((c) => c.key === "extend")?.choices ?? [];
  const a = (key: string) => commandes.some((c) => c.key === key);
  const pastille = horsService ? "bg-dot-off" : live.stream_on ? "bg-live" : "bg-leaf";
  const panneau = "rounded-[10px] bg-night p-4 text-night-ink";
  const enDirect = !!live.stream_on;
  const enPause = !!live.paused;
  const plein = (sc: string) => pleinEcran(sc, infos);
  const petit = "min-h-9 px-3 py-1.5 text-[0.9rem]";

  return (
    <div className="grid gap-3">
      {/* Status strip: engine state, time on air, next session, automatic mode. */}
      <section className={`${panneau} flex flex-wrap items-center gap-x-6 gap-y-2 py-3 lg:flex-nowrap`}>
        <p className="m-0 flex items-center gap-2.5 text-[1.25rem] font-bold leading-none text-white">
          <span className={`inline-block size-2.5 shrink-0 rounded-full ${pastille} ${live.stream_on ? "animate-pulse" : ""}`} />
          {etat}
        </p>
        {!horsService && <LiveFacts live={live} lu={lu} />}
        {!horsService && (
          <div className="ml-auto flex items-center gap-3">
            {audio.level_db !== null && (
              <div className="flex items-center gap-2" title={t("regie.audioLevel")}>
                <div
                  role="meter"
                  aria-label={t("regie.audioLevel")}
                  aria-valuemin={-60}
                  aria-valuemax={0}
                  aria-valuenow={Math.round(Math.max(-60, Math.min(0, audio.muted ? -60 : audio.level_db)))}
                  className="h-2 w-24 overflow-hidden rounded-full bg-white/15"
                >
                  <div
                    className="h-full rounded-full transition-[width] duration-100"
                    style={{
                      width: `${Math.min(100, Math.max(0, ((audio.muted ? -60 : audio.level_db) + 60) / 60 * 100))}%`,
                      background: audio.muted ? "#9ca3af" : audio.level_db > -3 ? "#ef4444" : audio.level_db > -12 ? "#eab308" : "#22c55e",
                    }}
                  />
                </div>
                <span className="text-[0.78rem] text-night-muted tabular-nums">
                  {audio.muted ? "—" : `${Math.round(audio.level_db)} dB`}
                </span>
              </div>
            )}
            <BusyBtn
              variante={audio.muted ? "danger" : "light"}
              className="min-h-9 px-3 py-1 text-[0.85rem]"
              aria-pressed={audio.muted}
              busy={enCours("mute")}
              onClick={() => void dispatch(toggleMute(!audio.muted))}
            >
              {audio.muted ? t("regie.micUnmute") : t("regie.micMute")}
            </BusyBtn>
          </div>
        )}
        {horsService && <p className="m-0 text-[0.9rem] text-night-muted">{t("dashboard.unreachableHint")}</p>}
      </section>

      {/* Exclusivity: a second source cannot publish; only an administrator may take the stream over. */}
      {editeur && (
        <section role="status" className="flex flex-wrap items-center gap-3 rounded-[10px] border border-gold/60 bg-gold/15 px-4 py-2.5 text-[0.92rem] text-white">
          <span className="font-semibold">{t("devices.liveRunning", { source: editeur.text })}</span>
          <span className="text-night-muted">{t("devices.liveRunningHint")}</span>
          {currentSession()?.user.permissions.includes("admin") && (
            <BusyBtn variante="danger" className="ml-auto min-h-9 px-3 py-1 text-[0.88rem]" busy={enCours("takeover")}
                 onClick={async () => {
                   if (!(await confirm({ message: t("devices.takeoverConfirm", { source: editeur.text }), action: t("devices.takeover") }))) return;
                   await dispatch(takeover());
                 }}>
              {t("devices.takeover")}
            </BusyBtn>
          )}
        </section>
      )}

      {/* Monitors: preview (the mosque's raw feed) and programme (what goes on air). */}
      <section className={`${panneau} grid gap-4 py-3 md:grid-cols-2`}>
          <Moniteur which="source" titre={t("regie.preview")}
                    sousTitre={prepa ? t("regie.staged", { scene: t(`dashboard.choice.${prepa}`) }) : t("regie.previewHint")}
                    available={!!moniteurs.source?.available} sante={moniteurs.source?.health ?? null} antenne={false}
                    prepa={prepa ? { scene: prepa, plein: plein(prepa) } : null}
                    actions={prepa && (
                      <>
                        <Btn variante="light" className="min-h-8 px-2.5 py-1 text-[0.85rem]" onClick={() => setPrepa(null)}>{t("regie.unstage")}</Btn>
                        <BusyBtn variante="leaf" className="min-h-8 px-2.5 py-1 text-[0.85rem]" busy={enCours("scene", prepa)} onClick={() => envoyer("scene", { valeur: prepa })}>{t("regie.take")}</BusyBtn>
                      </>
                    )} />
        <Moniteur which="program" titre={t("regie.program")} sousTitre={t("regie.programHint")}
                  available={!!moniteurs.program?.available} sante={moniteurs.program?.health ?? null} antenne={!!live.stream_on} />
      </section>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)_minmax(0,0.85fr)]">
        {/* Scenes: the screens of the mosque; the active one is outlined, a click puts it on air. */}
        <section className={`${panneau} md:col-span-2 xl:col-span-1`}>
          <h2 className="m-0 mb-2.5 text-[0.75rem] font-semibold uppercase tracking-[0.12em] text-leaf">{t("regie.scenes")}</h2>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-2">
            {scenes.map((sc) => {
              const actif = live.scene === sc;
              const prete = prepa === sc;
              return (
                <button key={sc} type="button" aria-pressed={prete} aria-busy={enCours("scene", sc) || undefined}
                        onClick={() => setPrepa(prete || actif ? null : sc)}
                        className={`flex min-h-12 cursor-pointer flex-col items-start justify-center rounded-lg border px-2.5 py-1.5 text-left transition-colors disabled:cursor-not-allowed ${
                          actif ? "border-live bg-live/20 text-white"
                            : prete ? "border-leaf bg-leaf/20 text-white"
                            : "border-white/15 bg-white/5 text-night-ink hover:border-leaf hover:bg-white/10"
                        }`}>
                  <span className="text-[0.9rem] leading-tight font-semibold">{t(`dashboard.choice.${sc}`)}</span>
                  <span className={`text-[0.72rem] ${actif ? "text-[#ffb4ae]" : prete ? "text-leaf" : "text-night-muted"}`}>
                    {actif ? t("regie.sceneActive") : prete ? t("regie.sceneStaged") : plein(sc) ? t("regie.sceneScreen") : t("regie.sceneCamera")}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        {/* Transport: start, pause/resume, extend, skip, automatic; stop and cancel apart, in red. */}
        <section className={`${panneau} grid content-start gap-2.5`}>
          <h2 className="m-0 text-[0.75rem] font-semibold uppercase tracking-[0.12em] text-leaf">{t("regie.transport")}</h2>
          <div className="flex flex-wrap gap-2">
            {/* The transport follows the state: start only off air, pause or resume depending on the pause. */}
            {a("start") && !enDirect && <BusyBtn variante="leaf" className={petit} busy={enCours("start")} onClick={() => envoyer("start")}>{t("dashboard.cmd.start")}</BusyBtn>}
            {a("pause") && enDirect && !enPause && <BusyBtn variante="light" className={petit} busy={enCours("pause")} onClick={() => envoyer("pause")}>{t("dashboard.cmd.pause")}</BusyBtn>}
            {a("resume") && enPause && <BusyBtn variante="leaf" className={petit} busy={enCours("resume")} onClick={() => envoyer("resume")}>{t("dashboard.cmd.resume")}</BusyBtn>}
            {extend.map((m) => (
              <BusyBtn key={m} variante="light" className={petit} busy={enCours("extend", m)} onClick={() => envoyer("extend", { valeur: m })}>{t(`dashboard.choice.${m}`)}</BusyBtn>
            ))}
            {a("skip") && <BusyBtn variante="light" className={petit} busy={enCours("skip")} onClick={() => envoyer("skip")}>{t("regie.skip")}</BusyBtn>}
            {a("auto") && (
              <BusyBtn variante={live.override || enCours("auto") ? "leaf" : "light"} className={petit} busy={enCours("auto")}
                       disabled={!live.override && !enCours("auto")} onClick={() => envoyer("auto")}>
                {live.override ? t("regie.autoResume") : t("regie.autoOn")}
              </BusyBtn>
            )}
          </div>
          <div className="flex flex-wrap gap-2 border-t border-white/10 pt-2.5">
            {a("stop") && <BusyBtn variante="danger" className={petit} busy={enCours("stop")} onClick={() => envoyer("stop")}>{t("dashboard.cmd.stop")}</BusyBtn>}
            {a("cancel") && <BusyBtn variante="danger" className={petit} busy={enCours("cancel")} onClick={() => envoyer("cancel")}>{t("dashboard.cmd.cancel")}</BusyBtn>}
          </div>
          {retour && texteRetour && <p role="status" className={`m-0 text-[0.88rem] ${retour.ok ? "text-leaf" : "text-[#ff9b94]"}`}>{texteRetour}</p>}
        </section>

        {live.tarawih && (a("tarawih") || a("next_reciter")) && (
          <section className={`${panneau} grid content-start gap-2`}>
            <h2 className="m-0 text-[0.75rem] font-semibold uppercase tracking-[0.12em] text-leaf">
              {t("regie.tarawih")}{live.tarawih.night ? ` · ${t("regie.tarawihNight", { n: live.tarawih.night })}` : ""}
            </h2>
            <p className="m-0 text-[0.88rem] text-white">
              <span className="text-night-muted">{t("regie.tarawihReciter")}</span>{" "}
              {live.tarawih.reciter || <span className="text-night-muted">{t("regie.tarawihNobody")}</span>}
            </p>
            {live.tarawih.reciters.length > 0 && (
              <ol className="m-0 flex flex-wrap gap-x-3 gap-y-1 pl-4 text-[0.8rem] text-night-muted">
                {live.tarawih.reciters.map((n) => <li key={n} className={n === live.tarawih?.reciter ? "text-white" : ""}>{n}</li>)}
              </ol>
            )}
            <div className="flex flex-wrap gap-2">
              {a("tarawih") && live.state !== "TARAWIH" && (
                <BusyBtn variante="leaf" className={petit} busy={enCours("tarawih")} onClick={() => envoyer("tarawih")}>{t("dashboard.cmd.tarawih")}</BusyBtn>
              )}
              {a("next_reciter") && live.state === "TARAWIH" && live.tarawih.reciters.length > 0 && (
                <BusyBtn variante="light" className={petit} busy={enCours("next_reciter")} onClick={() => envoyer("next_reciter")}>{t("dashboard.cmd.next_reciter")}</BusyBtn>
              )}
            </div>
            <p className="m-0 text-[0.76rem] leading-snug text-night-muted">{t("regie.tarawihHint")}</p>
          </section>
        )}

        {a("janaza") && (
          <section className={`${panneau} grid content-start gap-2`}>
            <h2 className="m-0 text-[0.75rem] font-semibold uppercase tracking-[0.12em] text-leaf">{t("dashboard.janaza")}</h2>
            {live.janaza_name && (
              <p className="m-0 text-[0.88rem] text-white">
                <span className="text-night-muted">{t("regie.janazaShown")}</span> {live.janaza_name}{live.janaza_info ? ` · ${live.janaza_info}` : ""}
              </p>
            )}
            <input className="rounded-md border border-white/25 bg-white/10 px-2.5 py-1.5 text-[0.9rem] text-white placeholder:text-night-muted max-md:min-h-11"
                   placeholder={t("dashboard.janazaName")} value={nom} maxLength={80} onChange={(e) => setNom(e.target.value)} />
            <input className="rounded-md border border-white/25 bg-white/10 px-2.5 py-1.5 text-[0.9rem] text-white placeholder:text-night-muted max-md:min-h-11"
                   placeholder={t("dashboard.janazaInfo")} value={mention} maxLength={60} onChange={(e) => setMention(e.target.value)} />
            <BusyBtn variante="leaf" className={`${petit} justify-self-start`} busy={enCours("janaza")} disabled={!nom.trim()}
                 onClick={() => envoyer("janaza", { name: nom.trim(), info: mention.trim() })}>
              {t("dashboard.janazaSend")}
            </BusyBtn>
            <p className="m-0 text-[0.76rem] leading-snug text-night-muted">{t("regie.janazaHint")}</p>
          </section>
        )}
      </div>
    </div>
  );
}
