/** The « on air » flag of the top bar.
 *
 *  Semantics — the same as the server's `live.on_air` (sada/backoffice/live.py), which the
 *  `/live/indicator` route answers: the orchestrator answers (`ok`) AND (the engine is in a state of
 *  the broadcast — BEFORE, KHUTBA, PRAYER, INTERMISSION, JANAZA, DARS, TARAWIH — OR `stream_on`).
 *  `stream_on` alone is narrower: it is `scene is not None` in the engine, and says nothing when the
 *  status is unreachable. `on_air` is what « the mosque broadcasts » means to the top bar, so it is
 *  the one mirrored here, on the confirmed state (not the optimistic one: the flag informs, it is not
 *  a control).
 *
 *  Source: the live slice when it holds a state read less than `FRESH_MS` ago (the Régie polls it
 *  every 3 s, the Dashboard loads it), else the light `/live/indicator` route every 20 s. */
import { useEffect, useState } from "react";
import { api } from "./api";
import { useAppSelector } from "./store";
import { selectConfirmed, selectReadAt, selectTransportSeq, type Live } from "./store/liveSlice";

export const ON_AIR_STATES = new Set(["BEFORE", "KHUTBA", "PRAYER", "INTERMISSION", "JANAZA", "DARS", "TARAWIH"]);
export const FRESH_MS = 10_000;

export function onAir(live: Live | null | undefined): boolean {
  return Boolean(live?.ok) && (ON_AIR_STATES.has(live?.state ?? "") || Boolean(live?.stream_on));
}

/** The slice's answer when it is fresh at `now`, else null (the route decides). */
export function onAirFromSlice(live: Live | null | undefined, readAt: number, now: number): boolean | null {
  if (!live || !readAt || now - readAt >= FRESH_MS) return null;
  return onAir(live);
}

export function useEnDirect(mosqueId: number): boolean {
  const [route, setRoute] = useState(false);
  const live = useAppSelector(selectConfirmed)?.live;
  const readAt = useAppSelector(selectReadAt);
  const transport = useAppSelector(selectTransportSeq);
  // The `readAt` whose freshness ran out: set by one timer at its expiry (no ticking clock
  // re-rendering the bar). A new read is fresh at once, with no frame on the route's value.
  const [perime, setPerime] = useState(0);
  useEffect(() => {
    if (!readAt) return;
    const id = window.setTimeout(() => setPerime(readAt), Math.max(0, readAt + FRESH_MS - Date.now()));
    return () => window.clearTimeout(id);
  }, [readAt]);

  // The route, every 20 s, at once on another mosque and right after a start/stop/cancel succeeded.
  useEffect(() => {
    let actif = true;
    const lire = () => {
      if (document.visibilityState === "hidden") return;
      api.liveIndicator().then((r) => actif && setRoute(!!r?.on)).catch(() => {});
    };
    lire();
    const id = window.setInterval(lire, 20_000);
    return () => { actif = false; window.clearInterval(id); };
  }, [mosqueId, transport]);

  const tranche = readAt && perime !== readAt ? onAirFromSlice(live, readAt, readAt) : null;
  return tranche ?? route;
}
