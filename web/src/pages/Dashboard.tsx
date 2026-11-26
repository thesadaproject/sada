import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api, ApiError, type Traitement } from "../api";
import { currentSession } from "../session";
import { Btn, Card, Pill } from "@sada/ui";
import { useAppDispatch, useAppSelector } from "../store";
import { selectView, type Live } from "../store/liveSlice";
import { fetchDashboard } from "../store/liveThunks";
import { dateTime, mmss, parseDay } from "../format";

/** States in which the mosque is on the air (same list as the server's `ON_AIR_STATES`). */
const A_L_ANTENNE = new Set(["BEFORE", "KHUTBA", "PRAYER", "INTERMISSION", "JANAZA", "DARS", "TARAWIH"]);

type Seance = NonNullable<Live["day"]>[number];

/** Length of a run, when it has both ends: minutes:seconds. */
function duree(it: Traitement): string {
  if (!it.debut || !it.fin) return "";
  const s = (Date.parse(it.fin) - Date.parse(it.debut)) / 1000;
  return Number.isFinite(s) && s >= 0 ? mmss(s) : "";
}

/** The server's error may quote a machine path (recording, output folder): the screen never shows
 *  one. `mot` is the stand-in word, translated by the caller. */
function sansChemin(texte: string, mot: string): string {
  return texte
    .replace(/[A-Za-z]:\\[^\s"']+/g, mot)
    .replace(/\/(?:home|mnt|tmp|var|usr|opt|srv|root|data)\/[^\s"',;:)]*/g, mot)
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** "HH:MM[:SS]" -> minutes since midnight, null when it is not a time. */
function minutes(h?: string | null): number | null {
  const m = /^(\d{1,2}):(\d{2})/.exec(h ?? "");
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

/** Minutes from the engine's clock to a planned time today ("2 h 05", "12 min"); "" when past or unknown. */
function dans(horloge?: string | null, prevu?: string | null): string {
  const a = minutes(horloge), b = minutes(prevu);
  if (a === null || b === null || b <= a) return "";
  const n = b - a;
  return n < 60 ? `${n} min` : `${Math.floor(n / 60)} h ${String(n % 60).padStart(2, "0")}`;
}

/** "HH:MM" of an "HH:MM:SS" clock. */
const hm = (h?: string | null) => (h ? h.slice(0, 5) : "");

/** Dashboard: today first (state of the live, next session, the day's programme), then what waits
 *  for a human (clips to review), then the archive and what happened after and during the live.
 *  Read only: the live is driven from the Régie, this page leads there. */
export default function Dashboard() {
  const { t, i18n } = useTranslation();
  const dispatch = useAppDispatch();
  /** Counters, latest sessions and command log; the live part lives in the store (store/liveSlice.ts). */
  const [d, setD] = useState<any>(null);
  const [erreur, setErreur] = useState(false);
  const vue = useAppSelector(selectView);
  /** null = panel hidden (no route yet on this back end). */
  const [traitements, setTraitements] = useState<Traitement[] | null>(null);
  const [relanceEnCours, setRelanceEnCours] = useState<string | null>(null);
  const [retourTraitement, setRetourTraitement] = useState<{ ok: boolean; texte: string } | null>(null);
  const [tourTraitements, setTourTraitements] = useState(0);
  const traitementsRef = useRef<Traitement[] | null>(null);

  useEffect(() => {
    dispatch(fetchDashboard()).then(setD).catch(() => setErreur(true));
  }, [dispatch]);

  /** Runs after the live, polled fast (10 s) while one waits or runs, slowly (60 s) otherwise.
   *  An older back end does not serve the route yet: 404 keeps the panel hidden, without an error. */
  useEffect(() => {
    let vivant = true;
    let minuteur = 0;
    const boucle = async () => {
      let items = traitementsRef.current;
      try {
        const r = await api.traitements();
        if (!vivant) return;
        items = Array.isArray(r?.items) ? r.items : [];
        traitementsRef.current = items;
        setTraitements(items);
      } catch (e) {
        if (!vivant) return;
        if (e instanceof ApiError && e.status === 404) {
          traitementsRef.current = null;
          setTraitements(null);
          minuteur = window.setTimeout(boucle, 60_000);   // retries once the route exists
          return;
        }
        // Any other hiccup: keep the last known list and try again shortly.
      }
      const enCours = items?.some((i) => i.etat === "attente" || i.etat === "en_cours") ?? false;
      minuteur = window.setTimeout(boucle, enCours ? 10_000 : 60_000);
    };
    boucle();
    return () => { vivant = false; window.clearTimeout(minuteur); };
  }, [tourTraitements]);

  /** Asks the server to run one processing again (failed or finished run). */
  async function relancer(it: Traitement) {
    const cle = `${it.run}:${it.session}`;
    setRelanceEnCours(cle);
    setRetourTraitement(null);
    const mot = t("dashboard.processing.hiddenPath");
    try {
      const r = await api.relancerTraitement(it.run, it.session);
      setRetourTraitement({ ok: true, texte: sansChemin(r?.message || t("dashboard.processing.relaunched"), mot) });
      setTourTraitements((n) => n + 1);            // reads the queue again right away
    } catch (e: any) {
      // The server's own message is already user-facing ("Relance impossible : …"): keep it,
      // and fall back to our sentence only when it has none.
      const brut = String(e?.message ?? "").trim();
      setRetourTraitement({
        ok: false,
        texte: brut ? sansChemin(brut, mot) : t("dashboard.processing.relaunchFailed", { message: t("common.error") }),
      });
    } finally {
      setRelanceEnCours(null);
    }
  }

  if (erreur) return <p className="py-16 text-center text-muted">{t("common.error")}</p>;
  if (!d || !vue) return <p className="py-16 text-center text-muted">{t("common.loading")}</p>;

  const droits = currentSession()?.user.permissions ?? [];
  const peutPublier = droits.includes("publish");
  const peutAssigner = droits.includes("assign");
  const peutRegie = droits.includes("live");   // same right as the Régie's route and the top bar's entry

  const compteurs: Compteur[] = [
    { cle: "pending", n: d.counts.pending, to: "/clips", icone: <IcoClip />, urgent: d.counts.pending > 0 },
    // “Ready to publish” only appears to those who can publish.
    ...(peutPublier ? [{ cle: "ready", n: d.counts.ready, to: "/publications", icone: <IcoEnvoi /> }] : []),
    { cle: "sermons", n: d.counts.sermons, to: "/khutbas", icone: <IcoArchive /> },
    ...(d.counts.dars ? [{ cle: "dars", n: d.counts.dars, to: "/dars", icone: <IcoLivre /> }] : []),
  ];

  return (
    <div className="grid gap-5">
      <Aujourdhui live={vue.live} peutRegie={peutRegie} />

      <div className="grid grid-cols-2 gap-3 min-[640px]:grid-cols-[repeat(auto-fit,minmax(210px,1fr))] min-[640px]:gap-4">
        {compteurs.map((c) => <CarteCompteur key={c.cle} c={c} />)}
      </div>

      <div className="grid items-start gap-5 min-[1000px]:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Card className="p-0!">
          <EnTete titre={t("dashboard.recent")} lien={{ to: "/khutbas", label: t("dashboard.seeAll") }} />
          {d.recent.length === 0 ? (
            <Vide icone={<IcoArchive />} texte={t("dashboard.recentEmpty")} />
          ) : (
            <ul className="m-0 list-none p-0">
              {d.recent.map((k: any) => <LigneSeance key={k.id} k={k} langue={i18n.language} />)}
            </ul>
          )}
        </Card>

        <div className="grid content-start gap-5">
          {/* Runs after the live: stays hidden when this back end does not serve the route. */}
          {traitements && (
            <Card className="p-0!">
              <EnTete titre={t("dashboard.processing.title")} />
              {traitements.length === 0 ? (
                <Vide icone={<IcoEngrenage />} texte={t("dashboard.processing.empty")} />
              ) : (
                <ul className="m-0 list-none p-0">
                  {traitements.map((it) => {
                    const dureeTxt = duree(it);
                    const cle = `${it.run}:${it.session}`;
                    return (
                      <li key={cle} className="border-t border-line px-5 py-3 first:border-t-0">
                        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
                          <span className="min-w-0">
                            <span className="block truncate text-[0.95rem] font-semibold text-ink">{it.label}</span>
                            <span className="block text-[0.85rem] text-muted">
                              {jourCourt(it.date, i18n.language)}
                              {dureeTxt && ` · ${t("dashboard.processing.duration", { d: dureeTxt })}`}
                            </span>
                          </span>
                          <span className="flex items-center gap-2">
                            <Pill statut={it.etat}
                                  label={t(`dashboard.processing.state.${it.etat}`, { defaultValue: it.etat })} />
                            {peutAssigner && (it.etat === "echec" || it.etat === "termine") && (
                              <Btn variante={it.etat === "echec" ? "dangerGhost" : "ghost"}
                                   disabled={relanceEnCours === cle}
                                   className="min-h-8 px-2.5 py-1 text-[0.85rem] max-md:min-h-11 pointer-coarse:min-h-11"
                                   onClick={() => relancer(it)}>
                                {t("dashboard.processing.relaunch")}
                              </Btn>
                            )}
                          </span>
                        </div>
                        {it.erreur && (
                          <p className="m-0 mt-1 break-words text-[0.85rem] text-[#7a1f20]">
                            {sansChemin(it.erreur, t("dashboard.processing.hiddenPath"))}
                          </p>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
              {retourTraitement && (
                <p role="status" className={`m-0 border-t border-line px-5 py-2.5 text-[0.9rem] ${retourTraitement.ok ? "text-green" : "text-[#7a1f20]"}`}>
                  {retourTraitement.texte}
                </p>
              )}
            </Card>
          )}

          <Card className="p-0!">
            <EnTete titre={t("dashboard.commands")} />
            {d.commands.length === 0 ? (
              <Vide icone={<IcoJournal />} texte={t("dashboard.noCommands")} />
            ) : (
              <ol className="m-0 list-none px-5 py-3">
                {d.commands.map((c: any) => {
                  const cle = String(c.action ?? "").replace("live.", "");
                  return (
                    <li key={c.id} className="relative border-l border-line pb-3 pl-4 last:pb-0">
                      <span aria-hidden className="absolute -left-[4.5px] top-1.5 size-2 rounded-full bg-green" />
                      <span className="block text-[0.93rem] font-semibold text-ink">
                        {t(`dashboard.cmd.${cle}`, { defaultValue: cle })}
                      </span>
                      <span className="block text-[0.83rem] text-muted">
                        {c.who ?? "—"}{c.at ? ` · ${horodatage(c.at, i18n.language)}` : ""}
                      </span>
                    </li>
                  );
                })}
              </ol>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ aujourd'hui */

/** The day at a glance, on the night background of the live screens: where the live stands, when the
 *  next session starts, and the programme of the day. */
function Aujourdhui({ live: v, peutRegie }: { live: Live; peutRegie: boolean }) {
  const { t, i18n } = useTranslation();
  const horsService = v.ok === false;
  const antenne = !horsService && (A_L_ANTENNE.has(v.state ?? "") || !!v.stream_on);
  const imminent = !horsService && !antenne && (v.state === "ARMED" || v.state === "BEFORE");
  const etat = horsService
    ? t("dashboard.unreachable")
    : (v.state && t(`dashboard.state.${v.state}`, { defaultValue: v.state })) || t("dashboard.liveOff");
  const debut = v.session?.started ? hm(v.session.started) : "";
  const prochaine = v.next_session ?? null;
  const rebours = dans(v.clock, prochaine);

  let phrase: ReactNode = null;
  if (horsService) phrase = t("dashboard.unreachableHint");
  else if (antenne) phrase = debut ? t("dashboard.onAirSince", { h: debut }) : null;
  else if (prochaine) phrase = <>{t("dashboard.nextAt")} <strong className="font-semibold text-white">{prochaine}</strong>{rebours && <> · {t("dashboard.inDelay", { d: rebours })}</>}</>;
  else phrase = v.has_sessions ? t("dashboard.noSession") : t("dashboard.noSessionToday");

  const [maintenant] = useState(() => new Date());   // the page is reloaded each day: its date is enough
  const aujourdhui = new Intl.DateTimeFormat(i18n.language, { weekday: "long", day: "numeric", month: "long" }).format(maintenant);
  const pastille = antenne ? "bg-[#e0594f]" : imminent ? "bg-leaf" : "bg-dot-off";

  return (
    <section className="relative overflow-hidden rounded-2xl bg-night text-night-ink shadow-[0_18px_40px_-24px_rgba(11,26,20,0.65)]">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(90%_120%_at_100%_0%,rgba(226,194,122,0.14),transparent_60%)]" />
      <Etoile />
      <div className="relative grid gap-6 p-6 min-[900px]:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] min-[900px]:p-7">
        <div className="flex min-w-0 flex-col">
          <p className="m-0 text-[0.75rem] font-semibold uppercase tracking-[0.14em] text-leaf">
            {t("dashboard.today")} · <span className="normal-case tracking-normal">{aujourdhui}</span>
          </p>
          <h1 className="m-0 mt-3 flex items-center gap-3 font-serif text-[2.35rem] font-normal leading-[1.05] text-white">
            <span className="relative inline-flex size-3 shrink-0">
              {antenne && <span className="absolute inline-flex size-full animate-ping rounded-full bg-[#e0594f] opacity-60" />}
              <span className={`relative inline-flex size-3 rounded-full ${pastille}`} />
            </span>
            {etat}
          </h1>
          {phrase && <p className="m-0 mt-2.5 text-[1.02rem] text-night-muted">{phrase}</p>}
          {!horsService && v.error && <p className="m-0 mt-1.5 text-[0.9rem] text-live-off">{v.error}</p>}

          {!horsService && (
            <dl className="m-0 mt-5 flex flex-wrap gap-2">
              <Puce label={t("dashboard.sceneOnAir")}
                    valeur={v.scene ? t(`dashboard.choice.${v.scene}`, { defaultValue: v.scene }) : "—"} />
              {antenne && prochaine && <Puce label={t("regie.next")} valeur={prochaine} />}
              <Puce label={t("regie.mode")} valeur={v.override ? t("regie.manual") : t("regie.auto")} />
            </dl>
          )}

          <div className="mt-auto pt-6">
            {/* The live is driven from the Régie only: this panel reads, the button leads there. */}
            {peutRegie && (
              <Link to="/regie"
                    className="inline-flex min-h-11 items-center gap-2 rounded-[9px] border border-leaf bg-leaf px-4 py-2.5 font-semibold text-night no-underline transition-colors hover:bg-leaf-2">
                {t("dashboard.openRegie")}
                <span aria-hidden="true">→</span>
              </Link>
            )}
          </div>
        </div>

        <Programme jour={horsService ? [] : (v.day ?? [])} horloge={v.clock} prochaine={prochaine} />
      </div>
    </section>
  );
}

function Puce({ label, valeur }: { label: string; valeur: string }) {
  return (
    <div className="flex items-baseline gap-1.5 rounded-full bg-white/[0.07] px-3 py-1 text-[0.88rem] ring-1 ring-white/10">
      <dt className="text-night-muted">{label}</dt>
      <dd className="m-0 font-semibold text-white">{valeur}</dd>
    </div>
  );
}

/** The sessions of the day on a rail: done ones dimmed with their real times, the live one in red,
 *  the next one with its countdown. */
function Programme({ jour, horloge, prochaine }: { jour: Seance[]; horloge?: string | null; prochaine: string | null }) {
  const { t } = useTranslation();
  const suivante = jour.find((s) => s.status === "pending");
  return (
    <div className="rounded-xl bg-white/[0.04] p-4 ring-1 ring-white/10 min-[900px]:p-5">
      <p className="m-0 mb-3 flex items-baseline justify-between gap-3 text-[0.75rem] font-semibold uppercase tracking-[0.14em] text-night-muted">
        {t("dashboard.programme")}
        {horloge && <span className="normal-case tracking-normal tabular-nums" title={t("regie.clock")}>{hm(horloge)}</span>}
      </p>
      {jour.length === 0 ? (
        <p className="m-0 text-[0.95rem] text-night-muted">{t("dashboard.noSessionToday")}</p>
      ) : (
        <ol className="m-0 list-none p-0">
          {jour.map((s, i) => {
            const enDirect = s.status === "live";
            const passee = s.status === "done" || s.status === "skipped" || s.status === "janaza";
            const estSuivante = s === suivante;
            const genre = t(`dashboard.kind.${s.kind}`, { defaultValue: s.kind });
            const detail = [s.title, s.speaker].filter(Boolean).join(" · ");
            let statut: ReactNode;
            if (enDirect) statut = <span className="font-semibold text-[#f08a80]">{s.started ? t("dashboard.onAirSince", { h: hm(s.started) }) : t("dashboard.dayStatus.live")}</span>;
            else if (s.status === "done") statut = s.started && s.ended ? `${hm(s.started)} – ${hm(s.ended)}` : t("dashboard.dayStatus.done");
            else if (estSuivante) {
              const r = dans(horloge, s.planned || prochaine);
              statut = <span className="text-leaf">{r ? t("dashboard.inDelay", { d: r }) : t("dashboard.dayStatus.pending")}</span>;
            } else statut = t(`dashboard.dayStatus.${s.status}`, { defaultValue: s.status });
            return (
              <li key={`${i}-${s.planned}`} className="relative grid grid-cols-[3.4rem_1rem_minmax(0,1fr)] items-start gap-x-2 pb-3.5 last:pb-0">
                <span className={`pt-px text-right font-semibold tabular-nums ${passee ? "text-night-muted" : "text-white"}`}>
                  {s.planned || "—"}
                </span>
                <span aria-hidden className="relative flex h-full justify-center">
                  {i < jour.length - 1 && <span className="absolute top-3 bottom-[-0.9rem] w-px bg-white/15" />}
                  <span className={`relative mt-1.5 size-2.5 rounded-full ring-4 ring-night ${enDirect ? "bg-[#e0594f]" : estSuivante ? "bg-leaf" : passee ? "bg-white/30" : "bg-white/55"}`} />
                </span>
                <span className={`min-w-0 ${passee ? "opacity-70" : ""}`}>
                  <span className="block truncate font-semibold text-white">{genre}{detail && <span className="font-normal text-night-muted"> · {detail}</span>}</span>
                  <span className="block text-[0.86rem] text-night-muted">{statut}</span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

/** Eight-pointed star (khatam), drawn as two squares: the watermark of the panel. */
function Etoile() {
  return (
    <svg aria-hidden viewBox="0 0 100 100" className="pointer-events-none absolute -right-16 -top-20 size-[22rem] text-leaf opacity-[0.07]"
         fill="none" stroke="currentColor" strokeWidth="0.6">
      <rect x="20" y="20" width="60" height="60" />
      <rect x="20" y="20" width="60" height="60" transform="rotate(45 50 50)" />
      <circle cx="50" cy="50" r="18" />
      <circle cx="50" cy="50" r="42" />
    </svg>
  );
}

/* ------------------------------------------------------------------ compteurs */

type Compteur = { cle: string; n: number; to: string; icone: ReactNode; urgent?: boolean };

function CarteCompteur({ c }: { c: Compteur }) {
  const { t, i18n } = useTranslation();
  return (
    <Link to={c.to} className="group no-underline">
      <section className={`flex h-full flex-col items-start gap-2.5 rounded-xl border p-3.5 min-[640px]:flex-row min-[640px]:gap-3.5 min-[640px]:p-4.5 transition-[border-color,box-shadow] hover:shadow-[0_8px_24px_-16px_rgba(18,38,30,0.45)] ${c.urgent ? "border-leaf bg-[#fffaf0] hover:border-leaf-2" : "border-line bg-white hover:border-green/40"}`}>
        <span className={`grid size-9 shrink-0 place-items-center rounded-lg min-[640px]:size-10 ${c.urgent ? "bg-leaf/30 text-deeper" : "bg-paper-2 text-green"}`}>
          {c.icone}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-serif text-[2.1rem] leading-none text-deeper tabular-nums">
            {new Intl.NumberFormat(i18n.language).format(c.n ?? 0)}
          </span>
          <span className="mt-1.5 block text-[0.92rem] font-semibold text-ink">{t(`dashboard.${c.cle}`)}</span>
          <span className="block text-[0.84rem] text-muted">{t(`dashboard.hint.${c.cle}`)}</span>
        </span>
      </section>
    </Link>
  );
}

/* ------------------------------------------------------------------ listes */

function EnTete({ titre, lien }: { titre: string; lien?: { to: string; label: string } }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line px-5 pt-4 pb-3">
      <h2 className="m-0 font-serif text-[1.4rem] font-normal leading-tight text-deeper">{titre}</h2>
      {lien && <Link to={lien.to} className="text-[0.88rem] font-semibold text-green no-underline hover:underline">{lien.label} →</Link>}
    </div>
  );
}

function Vide({ icone, texte }: { icone: ReactNode; texte: string }) {
  return (
    <div className="flex items-center gap-3 px-5 py-5 text-[0.93rem] text-muted">
      <span className="grid size-9 shrink-0 place-items-center rounded-full bg-paper-2 text-green">{icone}</span>
      <p className="m-0">{texte}</p>
    </div>
  );
}

/** A past session: its day as a calendar leaf, then what it was, who spoke and how long. */
function LigneSeance({ k, langue }: { k: any; langue: string }) {
  const { t } = useTranslation();
  const jour = parseDay(String(k.date ?? "").slice(0, 10));
  const ok = !Number.isNaN(jour.getTime());
  const genre = t(`dashboard.kind.${k.kind || "khutba"}`, { defaultValue: k.kind || "khutba" });
  const quoi = (k.title || k.label || genre) as string;
  const qui = [k.imam || k.speaker, k.duration_s ? mmss(k.duration_s) : ""].filter(Boolean).join(" · ");
  return (
    <li className="border-t border-line first:border-t-0">
      <Link to={`/khutbas/${k.id}`} className="group flex items-center gap-4 px-5 py-3 no-underline transition-colors hover:bg-paper/70">
        <span className="grid w-12 shrink-0 overflow-hidden rounded-lg border border-line text-center">
          <span className="bg-deep py-0.5 text-[0.68rem] font-semibold uppercase tracking-wide text-white">
            {ok ? new Intl.DateTimeFormat(langue, { month: "short" }).format(jour).replace(".", "") : "—"}
          </span>
          <span className="bg-white py-1 font-serif text-[1.35rem] leading-none text-deeper">{ok ? jour.getDate() : "?"}</span>
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.98rem] font-semibold text-ink">{quoi}</span>
          <span className="block truncate text-[0.86rem] text-muted">
            {ok && new Intl.DateTimeFormat(langue, { weekday: "long" }).format(jour)}
            {quoi !== genre && ` · ${genre}`}
            {qui && ` · ${qui}`}
          </span>
        </span>
        <span aria-hidden className="text-muted transition-transform group-hover:translate-x-0.5">→</span>
      </Link>
    </li>
  );
}

function jourCourt(iso: string, langue: string): string {
  const d = parseDay(String(iso ?? "").slice(0, 10));
  return Number.isNaN(d.getTime()) ? String(iso ?? "") : new Intl.DateTimeFormat(langue, { weekday: "short", day: "numeric", month: "short" }).format(d);
}

function horodatage(iso: string, langue: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso).slice(0, 10) : dateTime(iso, langue);
}

/* ------------------------------------------------------------------ icônes */

const ico = "size-[1.2rem]";
const trait = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round" } as const;

function IcoClip() {
  return <svg aria-hidden viewBox="0 0 24 24" className={ico} {...trait}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m10 9 5 3-5 3z" /></svg>;
}
function IcoEnvoi() {
  return <svg aria-hidden viewBox="0 0 24 24" className={ico} {...trait}><path d="M4 12 20 4l-6 16-3-7z" /><path d="m11 13 9-9" /></svg>;
}
function IcoArchive() {
  return <svg aria-hidden viewBox="0 0 24 24" className={ico} {...trait}><rect x="3" y="4" width="18" height="5" rx="1" /><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9" /><path d="M10 13h4" /></svg>;
}
function IcoLivre() {
  return <svg aria-hidden viewBox="0 0 24 24" className={ico} {...trait}><path d="M12 6c-2-1.5-5-2-8-1.5v13c3-.5 6 0 8 1.5 2-1.5 5-2 8-1.5v-13c-3-.5-6 0-8 1.5z" /><path d="M12 6v13" /></svg>;
}
function IcoEngrenage() {
  return <svg aria-hidden viewBox="0 0 24 24" className={ico} {...trait}><circle cx="12" cy="12" r="3" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" /></svg>;
}
function IcoJournal() {
  return <svg aria-hidden viewBox="0 0 24 24" className={ico} {...trait}><path d="M8 6h12M8 12h12M8 18h12" /><circle cx="4" cy="6" r="1" /><circle cx="4" cy="12" r="1" /><circle cx="4" cy="18" r="1" /></svg>;
}
