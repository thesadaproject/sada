/** Async side of the live slice: polls and commands. Each command applies its patch at once, sends,
 *  then settles with the server's answer (full state + rev) or falls back to the confirmed state. */
import { api } from "../api";
import {
  actionId, commandFailed, type OverlayKind, type OverlaysPatch, commandStarted, commandSucceeded, optimisticPatch, selectView,
  snapshotFailed, snapshotReceived, type Patch, type Snapshot,
} from "./liveSlice";
import type { AppThunk } from "./index";

type Data = Partial<Snapshot> & { rev?: unknown };

/** The Régie payload as the slice reads it. */
export function fromRegie(d: any): Data {
  return {
    live: d?.live ?? {},
    commands: d?.commands ?? [],
    monitors: d?.monitors ?? {},
    publisher: d?.publisher ?? null,
    ...(d?.audio ? {
      audio: {
        mic_on: Boolean(d.audio.mic_on),
        muted: Boolean(d.audio.muted),
        level_db: typeof d.audio.level_db === "number" ? d.audio.level_db : null,
      },
    } : {}),
    scenes: Array.isArray(d?.scenes) ? d.scenes : [],
    studios: Array.isArray(d?.studios) ? d.studios : [],
    ...(d?.preview ? { preview: { requested: Boolean(d.preview.requested) } } : {}),
    ...(d?.rev !== undefined ? { rev: d.rev } : {}),
  };
}

/** One poll of the Régie. The fence is read before the request leaves. */
export const fetchRegie = (): AppThunk<Promise<void>> => async (dispatch, getState) => {
  const { seq, epoch } = getState().live;
  try {
    const d = await api.regie();
    if (getState().live.epoch !== epoch) return;
    dispatch(snapshotReceived({ data: fromRegie(d), seq, at: Date.now() }));
  } catch {
    if (getState().live.epoch === epoch) dispatch(snapshotFailed());
  }
};

/** The Dashboard's payload: its live part goes through the slice, fenced like a poll; the rest
 *  (counters, latest khutbas, command log) is returned to the page. Throws when the request fails. */
export const fetchDashboard = (): AppThunk<Promise<any>> => async (dispatch, getState) => {
  const { seq, epoch } = getState().live;
  const d = await api.dashboard();
  if (getState().live.epoch === epoch) {
    dispatch(snapshotReceived({
      data: { live: d?.live ?? {}, commands: d?.live_commands ?? [], ...(d?.rev !== undefined ? { rev: d.rev } : {}) },
      seq, at: Date.now(),
    }));
  }
  return d;
};

function stateOf(r: any): Data | null {
  if (!r || typeof r !== "object") return null;
  if (r.live && typeof r.live === "object") return { live: r.live, ...(r.rev !== undefined ? { rev: r.rev } : {}) };
  return null;
}

function erreur(e: unknown) {
  const m = (e as { message?: unknown })?.message;
  return typeof m === "string" && m ? { ok: false, texte: m } : { ok: false, cle: "common.error" };
}

/** What the Sada Studio was told along with a control-room command (`studio` in the answer). Off air with no
 *  studio online, or another source holding the stream, the engine goes on air without the studio's picture:
 *  said in red, the command itself succeeded. */
function studioRetour(r: any): { ok?: boolean; cle?: string } | null {
  switch (r?.studio) {
    case "ordered": return { cle: "regie.studioOrdered" };
    case "stopped": return { cle: "regie.studioStopped" };
    case "no_studio": return { ok: false, cle: "regie.studioNotThere" };
    case "busy": return { ok: false, cle: "regie.studioBusy" };
    default: return null;
  }
}

/** Generic runner: optimistic patch, request, reconcile. Resolves to true on success. */
const run = (id: string, patch: Patch, send: () => Promise<any>, ok: (r: any) => { ok?: boolean; texte?: string; cle?: string }):
  AppThunk<Promise<boolean>> => async (dispatch, getState) => {
  const epoch = getState().live.epoch;
  dispatch(commandStarted({ id, patch }));
  try {
    const r = await send();
    if (getState().live.epoch !== epoch) return true;
    dispatch(commandSucceeded({ id, retour: { ok: true, ...ok(r) }, data: stateOf(r), at: Date.now() }));
    return true;
  } catch (e) {
    if (getState().live.epoch !== epoch) return false;
    dispatch(commandFailed({ id, retour: erreur(e) }));
    // Realign on the server's state; the fence above already drops polls that left before.
    void dispatch(fetchRegie());
    return false;
  }
};

/** A live command (`/live/{key}`): scene, start, pause, resume, extend, skip, auto, stop, cancel,
 *  tarawih, next_reciter, janaza. A second click on the same action in flight is ignored. */
export const sendCommand = (key: string, corps: Record<string, string> = {}): AppThunk<Promise<boolean>> =>
  async (dispatch, getState) => {
    const id = actionId(key, corps.valeur);
    if (getState().live.pending[id]) return false;
    const patch = optimisticPatch(key, corps, selectView(getState()));
    return dispatch(run(id, patch, () => api.liveCommande(key, corps), (r) => studioRetour(r) ?? (r?.message ? { texte: r.message } : {})));
  };

/** Takes a scene on air (built-in or `custom:<slug>`), with the transition currently shown. */
export const takeScene = (scene: string): AppThunk<Promise<boolean>> => async (dispatch, getState) => {
  const id = actionId("scene", scene);
  if (getState().live.pending[id]) return false;
  const transition = selectView(getState())?.live.transition ?? undefined;
  return dispatch(run(id, { live: selectView(getState())?.live.stream_on ? { scene, override: true } : { preview_scene: scene } }, () => api.regieScene(scene, transition ?? undefined), (r) => studioRetour(r) ?? {}));
};

/** Fade or cut for the next scene changes (saved for the mosque). */
export const changeTransition = (mode: string): AppThunk<Promise<boolean>> => async (dispatch, getState) => {
  if (getState().live.pending.transition) return false;
  return dispatch(run("transition", { live: { transition: mode } }, () => api.regieTransition(mode), () => ({})));
};

/** One overlay: shown, hidden or edited; the Sada Studio draws it from the server's state. */
export const setOverlay = <K extends OverlayKind>(kind: K, patch: OverlaysPatch[K] & object): AppThunk<Promise<boolean>> =>
  async (dispatch, getState) => {
    const id = actionId("overlay", kind);
    if (getState().live.pending[id]) return false;
    return dispatch(run(id, { overlays: { [kind]: patch } }, () => api.regieOverlay(kind, patch as Record<string, unknown>), () => ({})));
  };

/** Mute / unmute the incoming microphone: shown at once, the server mirrors it. */
export const toggleMute = (muted: boolean): AppThunk<Promise<boolean>> => async (dispatch, getState) => {
  if (getState().live.pending.mute) return false;
  const audio = selectView(getState())?.audio;
  const patch: Patch = {
    audio: { muted, mic_on: muted ? false : (audio?.mic_on ?? false) },
    live: { mic_muted: muted },
  };
  return dispatch(run("mute", patch, () => api.regieMute(muted), () => ({ cle: muted ? "regie.micMuted" : "regie.micLive" })));
};

/** An administrator takes the stream over from the publisher in place. */
export const takeover = (): AppThunk<Promise<boolean>> => async (dispatch, getState) => {
  if (getState().live.pending.takeover) return false;
  return dispatch(run("takeover", { publisher: null }, () => api.studioTakeover(), (r) => (r?.message ? { texte: r.message } : {})));
};
