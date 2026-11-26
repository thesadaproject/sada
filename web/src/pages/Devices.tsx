import { useCallback, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { api } from "../api";
import { useConfirm } from "../confirmContext";
import { dateTime, nombre } from "../format";
import { Btn, Card, Field, Kicker, inputClass } from "@sada/ui";
import { BusyBtn } from "../BusyBtn";
import { usePolling } from "../usePolling";
import { useFenced } from "../fenced";

/** Studio devices: the mosque's PC that streams on its own. Pairing (the code shown on the device),
 *  the list with its state, renaming, key rotation, revocation, the day's incidents and the schedule
 *  the device is told to follow. Reserved to the people who manage the live. */

type Appareil = {
  id: number; name: string; online: boolean; revoked: boolean; revoked_at: string | null; created_at: string; created_by_name: string;
  last_seen_at: number | null; app_version: string; state: string; camera: boolean | null; microphone: boolean | null;
  bitrate_kbps: number | null; health: Record<string, boolean>; held: boolean; rotation_pending: boolean;
};
type Incident = { id: number; kind: string; title: string; todo: string; detail: string; opened_at: number; mailed: boolean };
type Creneau = { slot_id: string; type: string; title: string; starts_at: string; ends_at: string };
type Donnees = {
  devices: Appareil[]; incidents: Incident[];
  publisher: { source: string; label: string; since: number | null; text: string } | null;
  order: { command: string; source: string | null; code: string; current: (Creneau & { source: string }) | null; next: Creneau | null };
  slots: Creneau[]; settings: Record<string, number>; can_takeover: boolean;
  mail: { configured: boolean; email: string; subscribed: boolean };
  mosque: { name: string; slug: string };
};
type Message = { ok: boolean; texte: string } | null;


function depuis(ts: number | null, t: TFunction): string {
  if (ts == null) return t("devices.never");
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return t("devices.justNow");
  if (s < 5400) return t("devices.minutesAgo", { n: Math.round(s / 60) });
  if (s < 172800) return t("devices.hoursAgo", { n: Math.round(s / 3600) });
  return t("devices.daysAgo", { n: Math.round(s / 86400) });
}

export default function Devices() {
  const { t, i18n } = useTranslation();
  const confirm = useConfirm();
  const [erreur, setErreur] = useState(false);
  const [msg, setMsg] = useState<Message>(null);
  const [code, setCode] = useState("");
  const [nom, setNom] = useState("");
  const [renomme, setRenomme] = useState<{ id: number; nom: string } | null>(null);
  const [courriel, setCourriel] = useState<string | null>(null);
  // Server list + one optimistic layer per action in flight (fenced.ts): a late poll cannot bring
  // back a revoked device, and a failed action never takes back another one still in flight.
  const { data: d, enCours, reload, run } = useFenced<Donnees>(api.studioDevices);

  const charger = useCallback(
    () => reload().then((r) => { if (r) setErreur(false); }, () => setErreur(true)), [reload]);
  usePolling(charger, 15_000);

  /** Runs one action (`cle` = its own wait): applied at once, reverted alone if the server refuses. */
  async function agir(cle: string, f: () => Promise<{ message?: string }>,
                      { apres, optimiste }: { apres?: () => void; optimiste?: (x: Donnees) => Donnees } = {}) {
    setMsg(null);
    const res = await run(cle, f, { apply: optimiste });
    if (res.ok) {
      setMsg({ ok: true, texte: res.r.message ?? t("devices.saved") });
      apres?.();
    } else if (!res.skipped) {
      setMsg({ ok: false, texte: (res.error as any)?.message ?? t("common.error") });
    }
    await charger();
    return res.ok;
  }
  const majAppareil = (id: number, champs: Partial<Appareil>) => (x: Donnees): Donnees =>
    ({ ...x, devices: x.devices.map((a) => (a.id === id ? { ...a, ...champs } : a)) });

  if (erreur && !d) return <p className="text-muted">{t("common.error")}</p>;
  if (!d) return <p className="text-muted">{t("common.loading")}</p>;
  const actifs = d.devices.filter((x) => !x.revoked);
  const revoques = d.devices.filter((x) => x.revoked);

  return (
    <div className="grid gap-4">
      <header>
        <h1 className="m-0 font-serif text-[2.1rem] font-normal leading-[1.1] text-deeper">{t("devices.title")}</h1>
        <p className="mt-1 mb-0 max-w-[60ch] text-muted">{t("devices.intro", { mosque: d.mosque.name })}</p>
      </header>

      {d.publisher && (
        <div role="status" className="flex flex-wrap items-center gap-3 rounded-[10px] border border-live/40 bg-err-bg p-3 text-[0.95rem]">
          <span className="font-semibold">{t("devices.liveRunning", { source: d.publisher.text })}</span>
          <span className="text-muted">{t("devices.liveRunningHint")}</span>
          {d.can_takeover && (
            <BusyBtn variante="dangerGhost" className="ms-auto" busy={!!enCours("takeover")}
                 onClick={async () => {
                   if (await confirm({ message: t("devices.takeoverConfirm", { source: d.publisher!.text }), action: t("devices.takeover") }))
                     agir("takeover", () => api.studioTakeover(), { optimiste: (x) => ({ ...x, publisher: null }) });
                 }}>
              {t("devices.takeover")}
            </BusyBtn>
          )}
        </div>
      )}

      {msg && <p role="status" className={`m-0 text-[0.95rem] ${msg.ok ? "text-green" : "text-[#7f2122]"}`}>{msg.texte}</p>}

      {d.incidents.length > 0 && (
        <Card className="border-live/40">
          <Kicker>{t("devices.incidents")}</Kicker>
          <ul className="m-0 grid list-none gap-3 p-0">
            {d.incidents.map((i) => (
              <li key={i.id}>
                <p className="m-0 font-semibold text-[#7f2122]">{i.title}</p>
                {i.detail && <p className="m-0 text-[0.9rem]">{i.detail}</p>}
                <p className="m-0 text-[0.88rem] text-muted">{i.todo}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <Kicker>{t("devices.pairTitle")}</Kicker>
        <p className="mt-0 text-[0.92rem] text-muted">{t("devices.pairHelp", { mosque: d.mosque.name })}</p>
        <form className="grid gap-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto] sm:items-end"
              onSubmit={(e) => { e.preventDefault(); agir("pair", () => api.studioPair(code, nom), { apres: () => { setCode(""); setNom(""); } }); }}>
          <Field label={t("devices.code")}>
            <input className={`${inputClass} font-mono uppercase tracking-[0.15em]`} value={code} maxLength={9}
                   autoComplete="off" spellCheck={false} placeholder="ABCD-2345" onChange={(e) => setCode(e.target.value)} />
          </Field>
          <Field label={t("devices.name")}>
            <input className={inputClass} value={nom} maxLength={60} placeholder={t("devices.namePlaceholder")} onChange={(e) => setNom(e.target.value)} />
          </Field>
          <BusyBtn type="submit" busy={!!enCours("pair")} disabled={code.replace(/[\s-]/g, "").length < 8}>{t("devices.pair")}</BusyBtn>
        </form>
      </Card>

      <Card>
        <Kicker>{t("devices.list")}</Kicker>
        {actifs.length === 0 && <p className="m-0 text-muted">{t("devices.none")}</p>}
        <ul className="m-0 grid list-none gap-3 p-0">
          {actifs.map((a) => (
            <li key={a.id} className="grid gap-1 border-b border-line pb-3 last:border-b-0 last:pb-0">
              <div className="flex flex-wrap items-center gap-2">
                <span aria-hidden className={`inline-block size-2.5 rounded-full ${a.online ? "bg-green" : "bg-dot-off"}`} />
                {renomme?.id === a.id ? (
                  <form className="flex gap-2" onSubmit={(e) => {
                    e.preventDefault();
                    const tape = renomme.nom;
                    setRenomme(null);
                    // Refused: the form opens again with what was typed, the message says why.
                    void agir(`rename:${a.id}`, () => api.studioRename(a.id, tape), { optimiste: majAppareil(a.id, { name: tape.trim() }) })
                      .then((ok) => { if (!ok) setRenomme((r) => r ?? { id: a.id, nom: tape }); });
                  }}>
                    <input className={`${inputClass} !py-1.5`} value={renomme.nom} maxLength={60} autoFocus
                           aria-label={t("devices.name")} onChange={(e) => setRenomme({ id: a.id, nom: e.target.value })} />
                    <Btn type="submit" disabled={!renomme.nom.trim()}>{t("common.save")}</Btn>
                    <Btn variante="ghost" onClick={() => setRenomme(null)}>{t("devices.cancel")}</Btn>
                  </form>
                ) : (
                  <strong className="text-[1.05rem]">{a.name}</strong>
                )}
                <span className="rounded bg-paper-2 px-1.5 py-0.5 text-[0.78rem] font-semibold">
                  {a.held ? t("devices.held") : a.online ? (a.state === "live" ? t("devices.live") : t("devices.online")) : t("devices.offline")}
                </span>
              </div>
              <p className="m-0 text-[0.88rem] text-muted">
                {t("devices.lastSeen", { when: depuis(a.last_seen_at, t) })}
                {a.app_version && ` · ${t("devices.version", { v: a.app_version })}`}
                {a.bitrate_kbps ? ` · ${t("regie.kbps", { n: nombre(a.bitrate_kbps, i18n.language) })}` : ""}
              </p>
              {a.online && (
                <p className="m-0 text-[0.88rem]">
                  <span className={a.camera === false ? "font-semibold text-[#7f2122]" : ""}>{t(a.camera === false ? "devices.cameraMissing" : "devices.cameraOk")}</span>
                  {" · "}
                  <span className={a.microphone === false ? "font-semibold text-[#7f2122]" : ""}>{t(a.microphone === false ? "devices.micMissing" : "devices.micOk")}</span>
                  {Object.entries(a.health).filter(([, ok]) => !ok).map(([k]) => (
                    <span key={k} className="font-semibold text-[#7f2122]"> · {t(`devices.health.${k}`, { defaultValue: k })}</span>
                  ))}
                </p>
              )}
              <p className="m-0 text-[0.82rem] text-muted">{t("devices.createdBy", { who: a.created_by_name || "—", when: a.created_at.slice(0, 10) })}
                {a.rotation_pending && ` · ${t("devices.rotationPending")}`}</p>
              <div className="flex flex-wrap gap-2">
                <BusyBtn variante="ghost" className="min-h-9 px-3 py-1 text-[0.88rem]" busy={!!enCours(`rename:${a.id}`)} onClick={() => setRenomme({ id: a.id, nom: a.name })}>{t("devices.rename")}</BusyBtn>
                <BusyBtn variante="ghost" className="min-h-9 px-3 py-1 text-[0.88rem]" busy={!!enCours(`rotate:${a.id}`)} disabled={a.rotation_pending && !enCours(`rotate:${a.id}`)}
                     onClick={async () => {
                       if (await confirm({ message: t("devices.rotateConfirm", { name: a.name }), action: t("devices.rotate"), danger: false }))
                         agir(`rotate:${a.id}`, () => api.studioRotate(a.id), { optimiste: majAppareil(a.id, { rotation_pending: true }) });
                     }}>{t("devices.rotate")}</BusyBtn>
                <BusyBtn variante="dangerGhost" className="min-h-9 px-3 py-1 text-[0.88rem]" busy={!!enCours(`revoke:${a.id}`)}
                     onClick={async () => {
                       if (await confirm({ message: t("devices.revokeConfirm", { name: a.name }), action: t("devices.revoke") }))
                         agir(`revoke:${a.id}`, () => api.studioRevoke(a.id), { optimiste: majAppareil(a.id, { revoked: true }) });
                     }}>{t("devices.revoke")}</BusyBtn>
              </div>
            </li>
          ))}
        </ul>
        {revoques.length > 0 && (
          <details className="mt-3 text-[0.88rem] text-muted">
            <summary className="cursor-pointer">{t("devices.revokedList", { count: revoques.length })}</summary>
            <ul className="mt-1 mb-0">{revoques.map((a) => <li key={a.id}>{a.name} · {a.revoked_at?.slice(0, 10)}</li>)}</ul>
          </details>
        )}
      </Card>

      <Card>
        <Kicker>{t("devices.schedule")}</Kicker>
        <p className="mt-0 text-[0.92rem]">
          {d.order.command === "live"
            ? t("devices.orderLive", { title: d.order.current?.title ?? "" })
            : t("devices.orderStandby")}
        </p>
        {d.slots.length === 0 ? <p className="m-0 text-muted">{t("devices.noSlots")}</p> : (
          <ul className="m-0 grid list-none gap-1 p-0 text-[0.92rem]">
            {d.slots.map((s) => (
              <li key={s.slot_id}><strong>{dateTime(s.starts_at, i18n.language)}</strong> · {t(`devices.type.${s.type}`, { defaultValue: s.type })} · {s.title}</li>
            ))}
          </ul>
        )}
        <p className="mb-0 text-[0.82rem] text-muted">{t("devices.scheduleHint", { margin: Math.round(d.settings.start_margin_s / 60 * 10) / 10 })}</p>
      </Card>

      <Card>
        <Kicker>{t("devices.alerts")}</Kicker>
        {!d.mail.configured && <p className="mt-0 text-[0.88rem] text-muted">{t("devices.mailOff")}</p>}
        <form className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
              onSubmit={(e) => {
                e.preventDefault();
                const email = courriel ?? d.mail.email;
                agir("email", () => api.studioAlertPrefs({ email }), { optimiste: (x) => ({ ...x, mail: { ...x.mail, email } }) });
                setCourriel(null);
              }}>
          <Field label={t("devices.myEmail")} aide={t("devices.myEmailHelp")}>
            <input type="email" className={inputClass} value={courriel ?? d.mail.email} maxLength={200}
                   onChange={(e) => setCourriel(e.target.value)} />
          </Field>
          <BusyBtn type="submit" busy={!!enCours("email")} disabled={courriel === null && !enCours("email")}>{t("common.save")}</BusyBtn>
        </form>
        <label className="mt-3 flex items-center gap-2 text-[0.92rem]">
          <input type="checkbox" checked={d.mail.subscribed} aria-busy={!!enCours("subscribed") || undefined}
                 onChange={(e) => {
                   const subscribed = e.target.checked;
                   agir("subscribed", () => api.studioAlertPrefs({ subscribed }), { optimiste: (x) => ({ ...x, mail: { ...x.mail, subscribed } }) });
                 }} />
          {t("devices.subscribed")}
        </label>
      </Card>
    </div>
  );
}
