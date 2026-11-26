/** State of the live (Régie, Dashboard): the server's confirmed state, an optimistic layer on top.
 *
 *  - `server` is the last state the server confirmed (poll, or the full state a command answers).
 *  - `pending` holds one entry per action in flight (`scene:khutba`, `pause`, `mute`…), each with the
 *    patch it applies at once. The view is `server` + every pending patch, in the order they were
 *    sent: a click changes the screen right away and a late poll cannot take it back.
 *  - Polls carry the `seq` read when they started. Any command started or settled since then makes
 *    the poll stale: the server may have read its state before the command applied it. When the
 *    server sends `rev` (monotone, see CONTRACT.md), a state older than the last known `rev` is
 *    dropped as well.
 *  - Success: the pending entry leaves and the answer's state becomes `server`, in the same action.
 *    Failure: the pending entry leaves, the view falls back to `server` (no intermediate frame).
 *
 *  Pure reducers only: the async work (fetch, commands) lives in `liveThunks.ts`. */
import { createSelector, createSlice, type PayloadAction } from "@reduxjs/toolkit";

export type Health = { online: boolean; kbps?: number | null; readers?: number } | null;
export type Live = {
  ok?: boolean; state?: string; scene?: string | null; clock?: string | null;
  session?: { n?: number | null; total?: number; planned?: string | null; started?: string | null } | null;
  has_sessions?: boolean; next_session?: string | null; stream_on?: boolean; override?: boolean; paused?: boolean;
  last_reason?: string; error?: string | null; janaza_name?: string | null; janaza_info?: string | null;
  mic?: boolean; mic_muted?: boolean; audio_level_db?: number | null;
  tarawih?: { night?: number | null; mode?: string; reciters: string[]; reciter?: string | null } | null;
  rev?: number;
  compositing?: "studio" | "server";
};
export type AudioState = { mic_on: boolean; muted: boolean; level_db: number | null };
export type Commande = { key: string; destructive: boolean; choices: string[] };
export type SceneInfo = { id: string; kind?: string; scene_kind?: "camera" | "banner" | "full"; custom?: boolean; label?: string };
export type Publisher = { source: string; label: string; text: string } | null;
export type Monitors = Record<string, { available: boolean; health: Health }>;

/** What the server confirmed. Every part is optional in a snapshot: the Dashboard has no monitors. */
export type Snapshot = {
  live: Live;
  commands: Commande[];
  monitors: Monitors;
  publisher: Publisher;
  audio: AudioState;
  scenes: SceneInfo[];
};

/** What an action changes at once, before the server answers. */
export type Patch = { live?: Partial<Live>; audio?: Partial<AudioState>; publisher?: null };

export type Pending = { seq: number; patch: Patch };
/** Feedback line: a server text, or an i18n key when there is no text. */
export type Retour = { ok: boolean; texte?: string; cle?: string };

export type LiveState = {
  server: Snapshot | null;
  /** Last `rev` received (null: the server does not send one yet). */
  rev: number | null;
  /** Bumped when a command starts and when it settles: the write fence of the polls. */
  seq: number;
  /** Date.now() of the last accepted state (the clock of the strip counts from it). */
  readAt: number;
  pending: Record<string, Pending>;
  retour: Retour | null;
  /** Bumped when the mosque changes: answers of the previous mosque are dropped. */
  epoch: number;
};

export const initialState: LiveState = { server: null, rev: null, seq: 0, readAt: 0, pending: {}, retour: null, epoch: 0 };

const EMPTY: Snapshot = {
  live: {}, commands: [], monitors: {}, publisher: null,
  audio: { mic_on: false, muted: false, level_db: null }, scenes: [],
};

/** Identifier of an action in flight: the command, and its value when it has one (`extend:10`). */
export function actionId(key: string, valeur?: string | null): string {
  return valeur ? `${key}:${valeur}` : key;
}

function revOf(s: Partial<Snapshot> & { rev?: unknown }): number | null {
  const r = s.rev ?? s.live?.rev;
  return typeof r === "number" && Number.isFinite(r) ? r : null;
}

/** The audio block of a snapshot: given as such, or read from the live state. */
function audioOf(s: Partial<Snapshot>): AudioState | undefined {
  if (s.audio) return s.audio;
  if (!s.live) return undefined;
  return {
    mic_on: Boolean(s.live.mic),
    muted: Boolean(s.live.mic_muted),
    level_db: typeof s.live.audio_level_db === "number" ? s.live.audio_level_db : null,
  };
}

function olderRev(state: LiveState, rev: number | null): boolean {
  return rev != null && state.rev != null && rev < state.rev;
}

function applyPatch(s: Snapshot, p: Patch): Snapshot {
  return {
    ...s,
    live: p.live ? { ...s.live, ...p.live } : s.live,
    audio: p.audio ? { ...s.audio, ...p.audio } : s.audio,
    publisher: p.publisher === null ? null : s.publisher,
  };
}

function merge(state: LiveState, s: Partial<Snapshot> & { rev?: unknown }, at: number) {
  const base = state.server ?? EMPTY;
  const audio = audioOf(s);
  state.server = {
    live: s.live ?? base.live,
    commands: s.commands ?? base.commands,
    monitors: s.monitors ?? base.monitors,
    publisher: s.publisher !== undefined ? s.publisher : base.publisher,
    audio: audio ?? base.audio,
    scenes: s.scenes ?? base.scenes,
  };
  const rev = revOf(s);
  if (rev != null) state.rev = Math.max(rev, state.rev ?? rev);
  state.readAt = at;
}

const slice = createSlice({
  name: "live",
  initialState,
  reducers: {
    /** A poll (or a page load) answered. `seq` is the fence read when it started. */
    snapshotReceived(state, a: PayloadAction<{ data: Partial<Snapshot> & { rev?: unknown }; seq: number; at: number }>) {
      const { data, seq, at } = a.payload;
      const stale = seq < state.seq || olderRev(state, revOf(data));
      if (stale && state.server) {
        // Telemetry only: the monitors' health and the audio level are not touched by commands.
        if (data.monitors) state.server.monitors = data.monitors;
        const level = audioOf(data)?.level_db;
        if (level !== undefined) state.server.audio.level_db = level;
        return;
      }
      merge(state, data, at);
    },
    /** The poll failed: keep what is shown, or mark the live unreachable when nothing was ever read. */
    snapshotFailed(state) {
      if (!state.server) state.server = { ...EMPTY, live: { ok: false } };
    },
    commandStarted(state, a: PayloadAction<{ id: string; patch: Patch }>) {
      state.seq += 1;
      state.pending[a.payload.id] = { seq: state.seq, patch: a.payload.patch };
      state.retour = null;
    },
    /** The server accepted. `data`: the full state it answered, when it sends one; without it the
     *  patch itself becomes confirmed (the write succeeded, the next poll realigns the rest). */
    commandSucceeded(state, a: PayloadAction<{ id: string; retour: Retour; data?: (Partial<Snapshot> & { rev?: unknown }) | null; at: number }>) {
      const { id, data, at } = a.payload;
      const p = state.pending[id];
      state.seq += 1;
      delete state.pending[id];
      if (data && (data.live || data.audio) && !olderRev(state, revOf(data))) merge(state, data, at);
      else if (p && state.server) state.server = applyPatch(state.server, p.patch);
      state.retour = a.payload.retour;
    },
    commandFailed(state, a: PayloadAction<{ id: string; retour: Retour }>) {
      state.seq += 1;
      delete state.pending[a.payload.id];
      state.retour = a.payload.retour;
    },
    retourCleared(state) {
      state.retour = null;
    },
    /** Another mosque (or none) is open: forget everything, keep the fences moving forward. */
    liveReset(state) {
      return { ...initialState, seq: state.seq + 1, epoch: state.epoch + 1 };
    },
  },
});

export const { snapshotReceived, snapshotFailed, commandStarted, commandSucceeded, commandFailed, retourCleared, liveReset } = slice.actions;
export const liveReducer = slice.reducer;

type WithLive = { live: LiveState };

const selectServer = (s: WithLive) => s.live.server;
const selectPendingMap = (s: WithLive) => s.live.pending;

/** What the screen shows: the confirmed state with every action in flight applied on top. */
export const selectView = createSelector([selectServer, selectPendingMap], (server, pending): Snapshot | null => {
  if (!server) return null;
  return Object.values(pending)
    .sort((x, y) => x.seq - y.seq)
    .reduce((s, p) => applyPatch(s, p.patch), server);
});

export const selectConfirmed = selectServer;
export const selectPending = selectPendingMap;
export const selectReadAt = (s: WithLive) => s.live.readAt;
export const selectRetour = (s: WithLive) => s.live.retour;

/** The patch an action applies at once, from the state shown when it is sent. Commands without a
 *  visible consequence (extend, skip) have an empty patch: only their button shows the wait. */
export function optimisticPatch(key: string, corps: Record<string, string>, view: Snapshot | null): Patch {
  const v = view?.live ?? {};
  switch (key) {
    case "scene": return { live: { scene: corps.valeur ?? v.scene, override: true } };
    case "start": return { live: { stream_on: true, paused: false, override: true } };
    case "pause": return { live: { paused: true, override: true } };
    case "resume": return { live: { paused: false } };
    case "auto": return { live: { override: false, paused: false } };
    case "stop": return { live: { override: true } };
    case "cancel": return { live: { override: false } };
    case "tarawih": return { live: { state: "TARAWIH", override: false, paused: false } };
    case "janaza": return { live: { state: "JANAZA", override: true, janaza_name: corps.name || null, janaza_info: (corps.name && corps.info) || null } };
    case "next_reciter": {
      const tw = v.tarawih;
      if (!tw || tw.reciters.length === 0) return {};
      const i = tw.reciter && tw.reciters.includes(tw.reciter) ? (tw.reciters.indexOf(tw.reciter) + 1) % tw.reciters.length : 0;
      return { live: { tarawih: { ...tw, reciter: tw.reciters[i] } } };
    }
    default: return {};
  }
}
