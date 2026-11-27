import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { playMonitor, type MonitorState } from "../monitor";
import { Btn } from "@sada/ui";
import { BusyBtn } from "../BusyBtn";
import { api } from "../api";
import { currentSession } from "../session";
import { useConfirm } from "../confirmContext";
import { heureDuJour, nombre } from "../format";
import { usePolling, useNow } from "../usePolling";
import { useAppDispatch, useAppSelector } from "../store";
import {
  actionId, selectPending, selectReadAt, selectRetour, selectView,
  type Health, type Live, type Overlays, type SceneInfo, type Studio,
} from "../store/liveSlice";
import { changeTransition, fetchRegie, sendCommand, setOverlay, takeScene, takeover, toggleMute } from "../store/liveThunks";

/** Control room (“Régie”): the remote control of the Sada Studio, from any browser.
 *
 *  The server holds the state (scene, overlays, transition, mic, schedule); the Sada Studio draws the picture
 *  from it. Every click here changes that state, and the studio follows within a few seconds: nobody has to
 *  go to the PC of the mosque. One monitor: the programme while on air, otherwise the studio's picture on
 *  demand (the studio only streams it while somebody watches, and nothing of it reaches the public). */

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

const panneau = "rounded-[10px] bg-night p-4 text-night-ink";
const titreSection = "m-0 text-[0.75rem] font-semibold uppercase tracking-[0.12em] text-leaf";
const petit = "min-h-9 px-3 py-1.5 text-[0.9rem]";
const champ = "min-w-0 rounded-md border border-white/25 bg-white/10 px-2.5 py-1.5 text-[0.9rem] text-white placeholder:text-night-muted max-md:min-h-11";

/** The picture: WebRTC (HLS fallback) through the back office, muted by default. */
function Video({ which, available, onState }: {
  which: "source" | "program" | "preview"; available: boolean; onState: (s: MonitorState) => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [muet, setMuet] = useState(true);
  const [etat, setEtat] = useState<MonitorState>("connecting");
  const { t } = useTranslation();
  useEffect(() => {
    if (!available || !video.current) return;
    return playMonitor(which, video.current, (s) => { setEtat(s); onState(s); });
  }, [which, available, onState]);
  const enLigne = available && (etat === "webrtc" || etat === "hls");
  return (
    <>
      <video ref={video} autoPlay muted={muet} playsInline className={`size-full object-contain ${enLigne ? "" : "hidden"}`} />
      {enLigne && (
        <button type="button" onClick={() => setMuet((m) => !m)} aria-pressed={!muet}
                className="absolute right-2 bottom-2 z-20 inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-md border border-white/25 bg-black/60 px-2.5 text-[0.8rem] font-semibold text-white hover:bg-black/80 max-md:min-h-11">
          <svg aria-hidden="true" viewBox="0 0 20 20" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 8h3l4-3v10l-4-3H3z" />
            {muet ? <path d="M13 8l4 4M17 8l-4 4" /> : <path d="M13.5 7.5a3.5 3.5 0 0 1 0 5M15.5 5.5a6.5 6.5 0 0 1 0 9" />}
          </svg>
          {muet ? t("regie.soundOn") : t("regie.soundOff")}
        </button>
      )}
    </>
  );
}

/** A slate inside the monitor (nothing to show, or waiting for the studio). */
function Ardoise({ titre, texte, attente = false, children }: { titre: string; texte?: string; attente?: boolean; children?: React.ReactNode }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[repeating-linear-gradient(135deg,#0b1d18_0_14px,#0e231d_14px_28px)] p-4 text-center">
      <span className="inline-flex items-center gap-2 text-[0.98rem] font-semibold text-night-ink">
        <span className={`inline-block size-2 rounded-full ${attente ? "animate-pulse bg-gold" : "bg-dot-off"}`} />
        {titre}
      </span>
      {texte && <span className="max-w-[85%] text-[0.84rem] leading-snug text-night-muted">{texte}</span>}
      {children}
    </div>
  );
}

/** While the monitor shows the studio's picture: the request is renewed every 15 s, given back on close,
 *  and while the tab is hidden (nobody watches: the studio stops streaming). */
function useDemandeRetour(actif: boolean) {
  useEffect(() => {
    if (!actif) return;
    const demander = () => { if (!document.hidden) void api.regiePreview(true).catch(() => {}); };
    const rendre = () => void api.regiePreview(false).catch(() => {});
    demander();
    const id = window.setInterval(demander, 15_000);
    const vis = () => (document.hidden ? rendre() : demander());
    document.addEventListener("visibilitychange", vis);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", vis);
      rendre();
    };
  }, [actif]);
}

/** One monitor: a 16:9 picture with its title, its slates and its stream facts. */
function Ecran({ titre, sous, which, disponible, antenne = false, actions, ardoise }: {
  titre: string; sous: string; which: "source" | "program" | "preview"; disponible: boolean; antenne?: boolean;
  actions?: React.ReactNode;
  /** What to show while no picture plays (`enLigne` false). */
  ardoise: (connexion: boolean) => React.ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const monitors = useAppSelector(selectView)?.monitors ?? {};
  const [etat, setEtat] = useState<MonitorState>("connecting");
  // Another feed: its state starts over (adjusted while rendering, not in an effect).
  const [vu, setVu] = useState(which);
  if (vu !== which) { setVu(which); setEtat("connecting"); }
  const enLigne = disponible && (etat === "webrtc" || etat === "hls");
  const h = monitors[which]?.health ?? null;
  return (
    <figure className="m-0 min-w-0">
      <figcaption className="mb-1.5 flex min-h-8 items-center justify-between gap-2">
        <span className="flex min-w-0 items-baseline gap-2">
          <span className={`${titreSection} shrink-0 whitespace-nowrap`}>{titre}</span>
          <span className="truncate text-[0.8rem] text-night-muted">{sous}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {antenne && enLigne && (
            <span className="rounded bg-live px-1.5 py-0.5 text-[0.7rem] font-bold uppercase tracking-wider text-white">{t("regie.onAir")}</span>
          )}
          {actions}
        </span>
      </figcaption>
      <div className={`relative aspect-video overflow-hidden rounded-lg bg-black ring-2 ${antenne && enLigne ? "ring-live" : "ring-white/10"}`}>
        {disponible && <Video key={which} which={which} available={disponible} onState={setEtat} />}
        {!enLigne && ardoise(disponible)}
      </div>
      <p className="m-0 mt-1 flex min-h-[1.2rem] gap-3 text-[0.78rem] text-night-muted tabular-nums">
        {enLigne && <span>{etat === "webrtc" ? "WebRTC" : "HLS"}</span>}
        {enLigne && h?.online && h.kbps != null && <span>{t("regie.kbps", { n: nombre(h.kbps, i18n.language) })}</span>}
        {enLigne && h?.online && h.readers != null && antenne && <span>{t("regie.readers", { n: h.readers })}</span>}
      </p>
    </figure>
  );
}

/** Left: what the Sada Studio gives. On air, the stream it publishes; off air, its picture on demand (it only
 *  streams it while somebody watches, and nothing of it reaches the public). Without a studio, the raw input of
 *  a source the server composes itself (OBS, IP camera). */
function MoniteurStudio({ monitors, studio }: { monitors: Record<string, { available: boolean; health: Health }>; studio: Studio | null }) {
  const { t } = useTranslation();
  const [retour, setRetour] = useState(false);
  const mode: "stream" | "preview" | "source" | "none" = studio?.publishing
    ? "stream"
    : studio?.online ? "preview"
    : monitors.source?.available ? "source" : "none";
  const voirRetour = mode === "preview" && retour;
  useDemandeRetour(voirRetour);
  const which = mode === "preview" ? "preview" : "source";
  const disponible = mode === "preview" ? voirRetour && !!monitors.preview?.available : mode !== "none" && !!monitors.source?.available;
  const nom = studio?.name ?? "";
  return (
    <Ecran
      titre={mode === "source" || mode === "none" ? t("regie.preview") : t("regie.studioFeed")}
      sous={mode === "stream" ? t("regie.studioStreamHint", { name: nom }) : mode === "preview" ? t("regie.studioFeedHint", { name: nom }) : t("regie.previewHint")}
      which={which}
      disponible={disponible}
      actions={voirRetour && <Btn variante="light" className="min-h-8 px-2.5 py-1 text-[0.82rem]" onClick={() => setRetour(false)}>{t("regie.studioFeedStop")}</Btn>}
      ardoise={(connexion) =>
        mode === "preview" && !retour ? (
          <Ardoise titre={t("regie.studioFeedOff")} texte={t("regie.studioFeedOffHint")}>
            <Btn variante="leaf" className="mt-1 min-h-9 px-3 py-1.5 text-[0.9rem]" onClick={() => setRetour(true)}>{t("regie.studioFeedShow")}</Btn>
          </Ardoise>
        ) : mode === "preview" ? (
          <Ardoise titre={t("regie.studioFeedWaiting")} texte={t("regie.studioFeedWaitingHint")} attente />
        ) : (
          <Ardoise titre={connexion ? t("regie.connecting") : t("regie.offline")}
                   texte={mode === "none" ? t("regie.noStudioHint") : t("regie.offlineHint")} attente={connexion} />
        )
      }
    />
  );
}

/** Right: what is sent to the destinations, as the engine relays it. */
function MoniteurAntenne({ live, monitors }: { live: Live; monitors: Record<string, { available: boolean; health: Health }> }) {
  const { t } = useTranslation();
  const disponible = !!monitors.program?.available;
  return (
    <Ecran
      titre={t("regie.program")} sous={t("regie.programHint")} which="program" disponible={disponible} antenne
      ardoise={(connexion) =>
        !live.stream_on ? (
          <Ardoise titre={t("regie.nothingSent")} texte={t("regie.nothingSentHint")} />
        ) : (
          <Ardoise titre={connexion ? t("regie.connecting") : t("regie.programWaiting")} texte={t("regie.programWaitingHint")} attente />
        )
      }
    />
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
 *  re-render every second (the monitor holds live video). */
function LiveFacts({ live, lu }: { live: Live; lu: number }) {
  const { t } = useTranslation();
  const now = useNow(1000);
  const horlogeS = secondes(live.clock);
  const maintenant = horlogeS != null ? horlogeS + (now - lu) / 1000 : null;
  const debut = secondes(live.session?.started);
  // a live started before midnight and still on after it: the difference wraps around the day
  const duree = live.stream_on && maintenant != null && debut != null ? hms((((maintenant - debut) % 86400) + 86400) % 86400) : "—";
  return (
    <dl className="m-0 flex min-w-0 flex-wrap gap-x-5 gap-y-1 text-[0.9rem]">
      {[
        [t("regie.clock"), maintenant != null ? heureDuJour(maintenant) : "—"],
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

/** Which Sada Studio this page drives, and whether it is there: the first thing to know from afar. */
function StudioBar({ studios, publisher }: { studios: Studio[]; publisher: { source: string; text: string } | null }) {
  const { t, i18n } = useTranslation();
  const confirm = useConfirm();
  const dispatch = useAppDispatch();
  const pending = useAppSelector(selectPending);
  const s = studios[0] ?? null;
  const autre = publisher && publisher.source !== "device" ? publisher : null;
  const admin = currentSession()?.user.permissions.includes("admin");
  const pastille = !s ? "bg-dot-off" : s.publishing ? "bg-live" : s.online ? "bg-leaf" : "bg-dot-off";
  const etat = !s ? "" : s.publishing ? t("regie.studioLive") : s.online ? t("regie.studioOnline") : t("regie.studioOffline");
  return (
    <section className={`${panneau} flex flex-wrap items-center gap-x-5 gap-y-2 py-2.5`} aria-label={t("regie.studio")}>
      <span className={titreSection}>{t("regie.studio")}</span>
      {s ? (
        <>
          <span className="flex items-center gap-2 text-[0.95rem] text-white">
            <span className={`inline-block size-2 rounded-full ${pastille}`} />
            <span className="font-semibold">{s.name}</span>
            <span className="text-night-muted">{etat}</span>
          </span>
          {s.online && (
            <span className="flex gap-3 text-[0.82rem] text-night-muted">
              {s.camera != null && <span className={s.camera ? "" : "text-[#ff9b94]"}>{s.camera ? t("devices.cameraOk") : t("devices.cameraMissing")}</span>}
              {s.microphone != null && <span className={s.microphone ? "" : "text-[#ff9b94]"}>{s.microphone ? t("devices.micOk") : t("devices.micMissing")}</span>}
              {s.publishing && s.bitrate_kbps != null && <span className="tabular-nums">{t("regie.kbps", { n: nombre(s.bitrate_kbps, i18n.language) })}</span>}
            </span>
          )}
          {!s.online && <span className="text-[0.82rem] text-night-muted">{t("regie.studioOfflineHint")}</span>}
          {studios.length > 1 && <span className="text-[0.82rem] text-night-muted">{t("regie.studioOthers", { count: studios.length - 1 })}</span>}
        </>
      ) : (
        <span className="text-[0.9rem] text-night-muted">
          {t("regie.noStudio")}{" "}
          <Link to="/appareils" className="font-semibold text-leaf underline-offset-2 hover:underline">{t("regie.pairStudio")}</Link>
        </span>
      )}
      {autre && (
        <span className="ml-auto flex flex-wrap items-center gap-3 text-[0.88rem] text-gold">
          {t("devices.liveRunning", { source: autre.text })}
          {admin && (
            <BusyBtn variante="danger" className="min-h-8 px-2.5 py-1 text-[0.85rem]" busy={Boolean(pending.takeover)}
                     onClick={async () => {
                       if (!(await confirm({ message: t("devices.takeoverConfirm", { source: autre.text }), action: t("devices.takeover") }))) return;
                       await dispatch(takeover());
                     }}>
              {t("devices.takeover")}
            </BusyBtn>
          )}
        </span>
      )}
    </section>
  );
}

/** An eye that shows or hides one overlay. */
function Oeil({ visible, label, busy, onClick }: { visible: boolean; label: string; busy: boolean; onClick: () => void }) {
  return (
    <button type="button" aria-pressed={visible} aria-label={label} title={label} aria-busy={busy || undefined} onClick={busy ? undefined : onClick}
            className={`inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md border transition-colors max-md:size-11 ${
              visible ? "border-leaf bg-leaf/25 text-white" : "border-white/20 bg-white/5 text-night-muted hover:border-leaf"}`}>
      <svg aria-hidden="true" viewBox="0 0 20 20" className="size-4.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d="M1.5 10S4.5 4.5 10 4.5 18.5 10 18.5 10 15.5 15.5 10 15.5 1.5 10 1.5 10z" />
        <circle cx="10" cy="10" r="2.5" />
        {!visible && <path d="M3 17L17 3" />}
      </svg>
    </button>
  );
}

const COINS = ["tl", "tr", "bl", "br"] as const;

/** QR code, banner, logo: shown over every scene, drawn by the studio from the server's state. */
function Incrustations({ overlays }: { overlays: Partial<Overlays> }) {
  const { t } = useTranslation();
  const dispatch = useAppDispatch();
  const pending = useAppSelector(selectPending);
  const qr = overlays.qr ?? { visible: false, url: "", label: "", corner: "tr" as const };
  const banner = overlays.banner ?? { visible: false, title: "", subtitle: "" };
  const logo = overlays.logo ?? { visible: false };
  // Drafts: what is being typed; filled once from the server, then the server's value is only shown.
  const [qrD, setQrD] = useState({ url: qr.url, label: qr.label, corner: qr.corner });
  const [banD, setBanD] = useState({ title: banner.title, subtitle: banner.subtitle });
  const occupe = (k: string) => Boolean(pending[actionId("overlay", k)]);
  const qrChange = qrD.url !== qr.url || qrD.label !== qr.label || qrD.corner !== qr.corner;
  const banChange = banD.title !== banner.title || banD.subtitle !== banner.subtitle;
  const qrValide = /^https:\/\/\S+$/.test(qrD.url.trim());
  const show = (v: boolean) => (v ? t("regie.hide") : t("regie.show"));

  return (
    <section className={`${panneau} grid content-start gap-3`}>
      <h2 className={titreSection}>{t("regie.overlays")}</h2>

      <div className="flex items-center gap-2.5">
        <Oeil visible={logo.visible} label={`${show(logo.visible)} — ${t("regie.logo")}`} busy={occupe("logo")}
              onClick={() => void dispatch(setOverlay("logo", { visible: !logo.visible }))} />
        <span className="text-[0.92rem] font-semibold text-white">{t("regie.logo")}</span>
      </div>

      <div className="grid gap-2 border-t border-white/10 pt-3">
        <div className="flex items-center gap-2.5">
          <Oeil visible={banner.visible} label={`${show(banner.visible)} — ${t("regie.banner")}`} busy={occupe("banner")}
                onClick={() => void dispatch(setOverlay("banner", banner.visible ? { visible: false } : { visible: true, ...banD }))} />
          <span className="text-[0.92rem] font-semibold text-white">{t("regie.banner")}</span>
        </div>
        <input className={champ} placeholder={t("regie.bannerTitle")} value={banD.title} maxLength={120}
               onChange={(e) => setBanD({ ...banD, title: e.target.value })} />
        <input className={champ} placeholder={t("regie.bannerSubtitle")} value={banD.subtitle} maxLength={160}
               onChange={(e) => setBanD({ ...banD, subtitle: e.target.value })} />
        {banChange && (
          <BusyBtn variante="light" className={`${petit} justify-self-start`} busy={occupe("banner")} disabled={!banD.title.trim() && banner.visible}
                   onClick={() => void dispatch(setOverlay("banner", { ...banD }))}>
            {banner.visible ? t("regie.applyLive") : t("regie.apply")}
          </BusyBtn>
        )}
      </div>

      <div className="grid gap-2 border-t border-white/10 pt-3">
        <div className="flex items-center gap-2.5">
          <Oeil visible={qr.visible} label={`${show(qr.visible)} — ${t("regie.qr")}`} busy={occupe("qr")}
                onClick={() => {
                  if (qr.visible) void dispatch(setOverlay("qr", { visible: false }));
                  else if (qrValide) void dispatch(setOverlay("qr", { visible: true, ...qrD, url: qrD.url.trim() }));
                }} />
          <span className="text-[0.92rem] font-semibold text-white">{t("regie.qr")}</span>
        </div>
        <input type="url" className={champ} placeholder="https://…" value={qrD.url} maxLength={512} aria-label={t("regie.qrUrl")}
               onChange={(e) => setQrD({ ...qrD, url: e.target.value })} />
        <div className="flex gap-2">
          <input className={`${champ} flex-1`} placeholder={t("regie.qrLabel")} value={qrD.label} maxLength={60}
                 onChange={(e) => setQrD({ ...qrD, label: e.target.value })} />
          <select className={champ} value={qrD.corner} aria-label={t("regie.qrCorner")}
                  onChange={(e) => setQrD({ ...qrD, corner: e.target.value as (typeof COINS)[number] })}>
            {COINS.map((c) => <option key={c} value={c} className="text-ink">{t(`regie.corners.${c}`)}</option>)}
          </select>
        </div>
        {qrD.url.trim() !== "" && !qrValide && <p className="m-0 text-[0.8rem] text-[#ff9b94]">{t("regie.qrInvalid")}</p>}
        {qrChange && (
          <BusyBtn variante="light" className={`${petit} justify-self-start`} busy={occupe("qr")} disabled={qrD.url.trim() !== "" && !qrValide}
                   onClick={() => void dispatch(setOverlay("qr", { ...qrD, url: qrD.url.trim() }))}>
            {qr.visible ? t("regie.applyLive") : t("regie.apply")}
          </BusyBtn>
        )}
      </div>
    </section>
  );
}

function RegieEcran() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const dispatch = useAppDispatch();
  // What is shown: the confirmed state with the actions in flight on top (see store/liveSlice.ts).
  const vue = useAppSelector(selectView);
  const pending = useAppSelector(selectPending);
  const lu = useAppSelector(selectReadAt);
  const retour = useAppSelector(selectRetour);

  // State refreshed every 3 s, paused while the tab is hidden; the clock ticks in LiveFacts. A poll
  // that left before a command (or older than the last `rev`) is dropped by the slice.
  usePolling(() => dispatch(fetchRegie()), 3000);

  const enCours = (key: string, valeur?: string) => Boolean(pending[actionId(key, valeur)]);

  async function envoyer(key: string, corps: Record<string, string> = {}) {
    const c = vue?.commands.find((x) => x.key === key);
    if (!c) return;
    if (c.destructive && !(await confirm({ message: t(`dashboard.confirm.${key}`), action: t(`dashboard.cmd.${key}`) }))) return;
    await dispatch(sendCommand(key, corps));
  }

  if (!vue) return <p className="py-16 text-center text-muted">{t("common.loading")}</p>;
  const { live, commands: commandes, monitors: moniteurs, audio, publisher: editeur, scenes: infos, studios } = vue;
  const texteRetour = retour && (retour.texte ?? (retour.cle ? t(retour.cle) : ""));

  const horsService = live.ok === false;
  const etat = horsService
    ? t("dashboard.unreachable")
    : (live.state && t(`dashboard.state.${live.state}`, { defaultValue: live.state })) || t("dashboard.liveOff");
  const extend = commandes.find((c) => c.key === "extend")?.choices ?? [];
  const a = (key: string) => commandes.some((c) => c.key === key);
  const pastille = horsService ? "bg-dot-off" : live.stream_on ? "bg-live" : "bg-leaf";
  const enDirect = !!live.stream_on;
  const enPause = !!live.paused;
  const nomScene = (sc: SceneInfo) => (sc.custom ? sc.label || sc.id : t(`dashboard.choice.${sc.id}`, { defaultValue: sc.label || sc.id }));
  const genre = (sc: SceneInfo) => sc.scene_kind === "full" ? t("regie.sceneScreen") : sc.scene_kind === "banner" ? t("regie.sceneBanner") : t("regie.sceneCamera");
  const transition = live.transition === "cut" ? "cut" : "fade";
  // On air without the studio's picture (started before the studio was online, or it was stopped there): "Start"
  // stays, it orders the studio to publish again.
  const studioAttend = enDirect && !!studios[0]?.online && !studios[0].publishing;
  // Off air a scene only changes the picture (Studio and preview): it never starts a live, so no confirmation.
  async function prendre(sc: SceneInfo) {
    await dispatch(takeScene(sc.id));
  }

  return (
    <div className="grid gap-3">
      {/* Status strip: engine state, time on air, next session, automatic mode, the incoming mic. */}
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
                <div role="meter" aria-label={t("regie.audioLevel")} aria-valuemin={-60} aria-valuemax={0}
                     aria-valuenow={Math.round(Math.max(-60, Math.min(0, audio.muted ? -60 : audio.level_db)))}
                     className="h-2 w-24 overflow-hidden rounded-full bg-white/15">
                  <div className="h-full rounded-full transition-[width] duration-100"
                       style={{
                         width: `${Math.min(100, Math.max(0, ((audio.muted ? -60 : audio.level_db) + 60) / 60 * 100))}%`,
                         background: audio.muted ? "#9ca3af" : audio.level_db > -3 ? "#ef4444" : audio.level_db > -12 ? "#eab308" : "#22c55e",
                       }} />
                </div>
                <span className="text-[0.78rem] text-night-muted tabular-nums">{audio.muted ? "—" : `${Math.round(audio.level_db)} dB`}</span>
              </div>
            )}
            <BusyBtn variante={audio.muted ? "danger" : "light"} className="min-h-9 px-3 py-1 text-[0.85rem]" aria-pressed={audio.muted}
                     busy={enCours("mute")} onClick={() => void dispatch(toggleMute(!audio.muted))}>
              {audio.muted ? t("regie.micUnmute") : t("regie.micMute")}
            </BusyBtn>
          </div>
        )}
        {horsService && <p className="m-0 text-[0.9rem] text-night-muted">{t("dashboard.unreachableHint")}</p>}
      </section>

      <StudioBar studios={studios} publisher={editeur} />

      {/* Monitors: what the Sada Studio gives (left), what goes on air (right). */}
      <section className={`${panneau} grid gap-4 py-3 md:grid-cols-2`}>
        <MoniteurStudio monitors={moniteurs} studio={studios[0] ?? null} />
        <MoniteurAntenne live={live} monitors={moniteurs} />
      </section>

      <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_minmax(0,1fr)]">
        {/* Transport: start, pause/resume, extend, skip; stop and cancel apart, in red. */}
        <section className={`${panneau} grid content-start gap-2.5`}>
          <h2 className={titreSection}>{t("regie.transport")}</h2>
          <div className="flex flex-wrap gap-2">
            {a("start") && (!enDirect || studioAttend) && <BusyBtn variante="leaf" className={petit} busy={enCours("start")} onClick={() => envoyer("start")}>{t("dashboard.cmd.start")}</BusyBtn>}
            {a("pause") && enDirect && !enPause && <BusyBtn variante="light" className={petit} busy={enCours("pause")} onClick={() => envoyer("pause")}>{t("dashboard.cmd.pause")}</BusyBtn>}
            {a("resume") && enPause && <BusyBtn variante="leaf" className={petit} busy={enCours("resume")} onClick={() => envoyer("resume")}>{t("dashboard.cmd.resume")}</BusyBtn>}
            {enDirect && extend.map((m) => (
              <BusyBtn key={m} variante="light" className={petit} busy={enCours("extend", m)} onClick={() => envoyer("extend", { valeur: m })}>{t(`dashboard.choice.${m}`)}</BusyBtn>
            ))}
            {a("skip") && <BusyBtn variante="light" className={petit} busy={enCours("skip")} onClick={() => envoyer("skip")}>{t("regie.skip")}</BusyBtn>}
          </div>
          <div className="flex flex-wrap gap-2 border-t border-white/10 pt-2.5">
            {a("stop") && <BusyBtn variante="danger" className={petit} busy={enCours("stop")} onClick={() => envoyer("stop")}>{t("dashboard.cmd.stop")}</BusyBtn>}
            {a("cancel") && <BusyBtn variante="danger" className={petit} busy={enCours("cancel")} onClick={() => envoyer("cancel")}>{t("dashboard.cmd.cancel")}</BusyBtn>}
          </div>
          {retour && texteRetour && <p role="status" className={`m-0 text-[0.88rem] ${retour.ok ? "text-leaf" : "text-[#ff9b94]"}`}>{texteRetour}</p>}

          {live.tarawih && (a("tarawih") || a("next_reciter")) && (
            <div className="grid gap-2 border-t border-white/10 pt-2.5">
              <h3 className={titreSection}>
                {t("regie.tarawih")}{live.tarawih.night ? ` · ${t("regie.tarawihNight", { n: live.tarawih.night })}` : ""}
              </h3>
              <p className="m-0 text-[0.88rem] text-white">
                <span className="text-night-muted">{t("regie.tarawihReciter")}</span>{" "}
                {live.tarawih.reciter || <span className="text-night-muted">{t("regie.tarawihNobody")}</span>}
              </p>
              <div className="flex flex-wrap gap-2">
                {a("tarawih") && live.state !== "TARAWIH" && (
                  <BusyBtn variante="leaf" className={petit} busy={enCours("tarawih")} onClick={() => envoyer("tarawih")}>{t("dashboard.cmd.tarawih")}</BusyBtn>
                )}
                {a("next_reciter") && live.state === "TARAWIH" && live.tarawih.reciters.length > 0 && (
                  <BusyBtn variante="light" className={petit} busy={enCours("next_reciter")} onClick={() => envoyer("next_reciter")}>{t("dashboard.cmd.next_reciter")}</BusyBtn>
                )}
              </div>
              <p className="m-0 text-[0.76rem] leading-snug text-night-muted">{t("regie.tarawihHint")}</p>
            </div>
          )}
        </section>

        {/* Scenes: a click puts the scene on air at once, the studio follows; "Automatic" hands back to the schedule. */}
        <section className={`${panneau} grid content-start gap-2.5`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className={titreSection}>{t("regie.scenes")}</h2>
            <div className="flex items-center gap-1.5" role="group" aria-label={t("regie.transition")}>
              <span className="text-[0.8rem] text-night-muted">{t("regie.transition")}</span>
              {(["fade", "cut"] as const).map((m) => (
                <BusyBtn key={m} variante={transition === m ? "leaf" : "light"} className="min-h-8 px-2.5 py-1 text-[0.82rem]" aria-pressed={transition === m}
                         busy={enCours("transition") && transition === m} onClick={() => transition !== m && void dispatch(changeTransition(m))}>
                  {t(`regie.transitions.${m}`)}
                </BusyBtn>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-2">
            {infos.map((sc) => {
              const actif = (enDirect ? live.scene : live.preview_scene) === sc.id;
              const occupe = enCours("scene", sc.id);
              return (
                <button key={sc.id} type="button" aria-pressed={actif} aria-busy={occupe || undefined} disabled={horsService}
                        onClick={() => !actif && !occupe && void prendre(sc)}
                        className={`flex min-h-14 cursor-pointer flex-col items-start justify-center rounded-lg border px-2.5 py-1.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                          actif ? "border-live bg-live/20 text-white" : "border-white/15 bg-white/5 text-night-ink hover:border-leaf hover:bg-white/10"
                        }`}>
                  <span className="flex items-center gap-1.5 text-[0.92rem] leading-tight font-semibold">
                    {occupe && <span aria-hidden="true" className="inline-block size-3 animate-spin rounded-full border-2 border-current border-r-transparent" />}
                    {nomScene(sc)}
                  </span>
                  <span className={`text-[0.72rem] ${actif ? "text-[#ffb4ae]" : "text-night-muted"}`}>{actif ? t("regie.sceneActive") : genre(sc)}</span>
                </button>
              );
            })}
          </div>
          {a("auto") && (
            <div className="flex flex-wrap items-center gap-3 border-t border-white/10 pt-2.5">
              <BusyBtn variante={live.override ? "leaf" : "light"} className={petit} busy={enCours("auto")}
                       disabled={!live.override && !enCours("auto")} onClick={() => envoyer("auto")}>
                {live.override ? t("regie.autoResume") : t("regie.autoOn")}
              </BusyBtn>
              <span className="text-[0.8rem] text-night-muted">{live.override ? t("regie.manualHint") : t("regie.autoHint")}</span>
            </div>
          )}
        </section>

        <Incrustations key={live.overlays ? "pret" : "vide"} overlays={live.overlays ?? {}} />
      </div>
    </div>
  );
}

