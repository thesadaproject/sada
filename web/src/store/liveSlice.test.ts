import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  commandFailed, commandStarted, commandSucceeded, initialState, liveReducer, liveReset, optimisticPatch,
  selectView, snapshotReceived, type LiveState, type Snapshot,
} from "./liveSlice";

const base = (live: Snapshot["live"], extra: Partial<Snapshot> = {}): Partial<Snapshot> => ({
  live, commands: [], monitors: {}, publisher: null, scenes: [], ...extra,
});

function loaded(live: Snapshot["live"], rev?: number): LiveState {
  return liveReducer(initialState, snapshotReceived({ data: { ...base(live), ...(rev != null ? { rev } : {}) }, seq: 0, at: 1 }));
}

const view = (s: LiveState) => selectView({ live: s });

describe("live slice", () => {
  it("drops a poll that started before a command (write fence, no rev)", () => {
    let s = loaded({ stream_on: false, paused: false });
    const pollSeq = s.seq; // the poll leaves now
    s = liveReducer(s, commandStarted({ id: "start", patch: optimisticPatch("start", {}, view(s)) }));
    s = liveReducer(s, commandSucceeded({ id: "start", retour: { ok: true }, data: { live: { stream_on: true } }, at: 2 }));
    // The poll comes back after the command, carrying the state read before it.
    s = liveReducer(s, snapshotReceived({ data: base({ stream_on: false }), seq: pollSeq, at: 3 }));
    expect(view(s)?.live.stream_on).toBe(true);
    // A poll that started after the command is applied.
    s = liveReducer(s, snapshotReceived({ data: base({ stream_on: false }), seq: s.seq, at: 4 }));
    expect(view(s)?.live.stream_on).toBe(false);
  });

  it("drops a poll while a command started after it is in flight", () => {
    let s = loaded({ paused: false });
    const pollSeq = s.seq;
    s = liveReducer(s, commandStarted({ id: "pause", patch: { live: { paused: true } } }));
    s = liveReducer(s, snapshotReceived({ data: base({ paused: false, scene: "x" }), seq: pollSeq, at: 2 }));
    expect(s.server?.live.scene).toBeUndefined();
    expect(view(s)?.live.paused).toBe(true);
  });

  it("still takes the telemetry of a stale poll", () => {
    let s = loaded({ paused: false });
    const pollSeq = s.seq;
    s = liveReducer(s, commandStarted({ id: "pause", patch: { live: { paused: true } } }));
    const monitors = { source: { available: true, health: { online: true, kbps: 900 } } };
    s = liveReducer(s, snapshotReceived({
      data: base({ paused: false }, { monitors, audio: { mic_on: true, muted: false, level_db: -12 } }), seq: pollSeq, at: 2,
    }));
    expect(s.server?.monitors).toEqual(monitors);
    expect(s.server?.audio.level_db).toBe(-12);
    expect(view(s)?.live.paused).toBe(true);
  });

  it("ignores a state older than the last known rev", () => {
    let s = loaded({ scene: "khutba" }, 10);
    s = liveReducer(s, snapshotReceived({ data: { ...base({ scene: "priere" }), rev: 9 }, seq: s.seq, at: 2 }));
    expect(view(s)?.live.scene).toBe("khutba");
    s = liveReducer(s, snapshotReceived({ data: base({ scene: "priere", rev: 11 }), seq: s.seq, at: 3 }));
    expect(view(s)?.live.scene).toBe("priere");
    expect(s.rev).toBe(11);
  });

  it("ignores a command answer older than the last known rev", () => {
    let s = loaded({ scene: "khutba" }, 10);
    s = liveReducer(s, commandStarted({ id: "scene:dars", patch: { live: { scene: "dars" } } }));
    s = liveReducer(s, snapshotReceived({ data: { ...base({ scene: "dars" }), rev: 12 }, seq: s.seq, at: 2 }));
    s = liveReducer(s, commandSucceeded({ id: "scene:dars", retour: { ok: true }, data: { live: { scene: "khutba", rev: 11 } }, at: 3 }));
    expect(view(s)?.live.scene).toBe("dars");
    expect(s.rev).toBe(12);
  });

  it("shows the optimistic state at once, then the confirmed one, with no other frame", () => {
    let s = loaded({ scene: "khutba", override: false }, 1);
    s = liveReducer(s, commandStarted({ id: "scene:priere", patch: optimisticPatch("scene", { valeur: "priere" }, view(s)) }));
    expect(view(s)?.live).toMatchObject({ scene: "priere", override: true });
    expect(s.server?.live.scene).toBe("khutba");
    s = liveReducer(s, commandSucceeded({
      id: "scene:priere", retour: { ok: true, texte: "ok" }, data: { live: { scene: "priere", override: true, rev: 2 } }, at: 2,
    }));
    expect(view(s)?.live).toMatchObject({ scene: "priere", override: true });
    expect(s.server?.live.scene).toBe("priere");
    expect(s.pending).toEqual({});
    expect(s.rev).toBe(2);
    expect(s.retour).toEqual({ ok: true, texte: "ok" });
  });

  it("confirms the patch itself when the answer has no state (mute)", () => {
    let s = loaded({ mic: true, mic_muted: false });
    const patch = { audio: { muted: true, mic_on: false }, live: { mic_muted: true } };
    s = liveReducer(s, commandStarted({ id: "mute", patch }));
    expect(view(s)?.audio.muted).toBe(true);
    s = liveReducer(s, commandSucceeded({ id: "mute", retour: { ok: true, cle: "regie.micMuted" }, data: null, at: 2 }));
    expect(s.server?.audio.muted).toBe(true);
    expect(view(s)?.audio.muted).toBe(true);
  });

  it("falls back to the server state on failure, straight from the optimistic one", () => {
    let s = loaded({ stream_on: true, paused: false });
    s = liveReducer(s, commandStarted({ id: "pause", patch: optimisticPatch("pause", {}, view(s)) }));
    expect(view(s)?.live.paused).toBe(true);
    const server = s.server;
    s = liveReducer(s, commandFailed({ id: "pause", retour: { ok: false, texte: "injoignable" } }));
    expect(view(s)?.live.paused).toBe(false);
    expect(s.server).toBe(server);
    expect(s.retour).toEqual({ ok: false, texte: "injoignable" });
  });

  it("tracks pending per action, and a failure only removes its own", () => {
    let s = loaded({ stream_on: true, paused: false, scene: "khutba" });
    s = liveReducer(s, commandStarted({ id: "pause", patch: { live: { paused: true } } }));
    s = liveReducer(s, commandStarted({ id: "scene:dars", patch: { live: { scene: "dars" } } }));
    expect(Object.keys(s.pending).sort()).toEqual(["pause", "scene:dars"]);
    s = liveReducer(s, commandFailed({ id: "scene:dars", retour: { ok: false, cle: "common.error" } }));
    expect(Object.keys(s.pending)).toEqual(["pause"]);
    expect(view(s)?.live).toMatchObject({ paused: true, scene: "khutba" });
  });

  it("applies the patches in the order they were sent", () => {
    let s = loaded({ scene: "khutba" });
    s = liveReducer(s, commandStarted({ id: "scene:dars", patch: { live: { scene: "dars" } } }));
    s = liveReducer(s, commandStarted({ id: "scene:priere", patch: { live: { scene: "priere" } } }));
    expect(view(s)?.live.scene).toBe("priere");
  });

  it("forgets the previous mosque on reset and keeps the fence moving", () => {
    let s = loaded({ scene: "khutba" }, 5);
    const { seq, epoch } = s;
    s = liveReducer(s, liveReset());
    expect(s.server).toBeNull();
    expect(s.rev).toBeNull();
    expect(s.pending).toEqual({});
    // The thunks compare the epoch to drop the previous mosque's answers; seq keeps fencing.
    expect(s.epoch).toBe(epoch + 1);
    expect(s.seq).toBeGreaterThan(seq);
  });

  it("computes the next reciter from the state shown", () => {
    const v = { live: { tarawih: { reciters: ["A", "B"], reciter: "B" } } } as unknown as Snapshot;
    expect(optimisticPatch("next_reciter", {}, v).live?.tarawih?.reciter).toBe("A");
  });
});

// The thunks against a mocked API: the full round trip, fence included.
const regie = vi.fn();
const liveCommande = vi.fn();
vi.mock("../api", () => ({
  api: {
    regie: (...a: unknown[]) => regie(...a),
    liveCommande: (...a: unknown[]) => liveCommande(...a),
    regieMute: vi.fn(),
    studioTakeover: vi.fn(),
    dashboard: vi.fn(),
  },
}));

describe("live thunks", () => {
  beforeEach(() => { regie.mockReset(); liveCommande.mockReset(); });

  it("a poll in flight during a command does not undo it", async () => {
    const { makeStore } = await import("./index");
    const { fetchRegie, sendCommand } = await import("./liveThunks");
    const store = makeStore();
    regie.mockResolvedValueOnce({ live: { stream_on: false }, commands: [{ key: "start", destructive: false, choices: [] }] });
    await store.dispatch(fetchRegie());

    let lirePoll!: (v: unknown) => void;
    regie.mockReturnValueOnce(new Promise((r) => { lirePoll = r; }));
    const poll = store.dispatch(fetchRegie());          // leaves before the click
    liveCommande.mockResolvedValueOnce({ ok: true, message: "ok", live: { stream_on: true } });
    const envoi = store.dispatch(sendCommand("start"));
    expect(selectView(store.getState())?.live.stream_on).toBe(true);   // at once
    expect(store.getState().live.pending.start).toBeDefined();
    await envoi;
    lirePoll({ live: { stream_on: false }, commands: [] });           // comes back late, stale
    await poll;
    expect(selectView(store.getState())?.live.stream_on).toBe(true);
    expect(store.getState().live.pending).toEqual({});
  });

  it("a failed command goes back to the server state and realigns", async () => {
    const { makeStore } = await import("./index");
    const { fetchRegie, sendCommand } = await import("./liveThunks");
    const store = makeStore();
    regie.mockResolvedValue({ live: { stream_on: true, paused: false }, commands: [] });
    await store.dispatch(fetchRegie());
    liveCommande.mockRejectedValueOnce(new Error("injoignable"));
    const ok = await store.dispatch(sendCommand("pause"));
    expect(ok).toBe(false);
    expect(selectView(store.getState())?.live.paused).toBe(false);
    expect(store.getState().live.retour).toEqual({ ok: false, texte: "injoignable" });
    expect(regie).toHaveBeenCalledTimes(2);                            // realignment poll
  });

  it("a second click on the same action in flight is ignored", async () => {
    const { makeStore } = await import("./index");
    const { fetchRegie, sendCommand } = await import("./liveThunks");
    const store = makeStore();
    regie.mockResolvedValue({ live: {}, commands: [] });
    await store.dispatch(fetchRegie());
    let fin!: (v: unknown) => void;
    liveCommande.mockReturnValueOnce(new Promise((r) => { fin = r; }));
    const a = store.dispatch(sendCommand("skip"));
    expect(await store.dispatch(sendCommand("skip"))).toBe(false);
    fin({ ok: true, message: "ok" });
    expect(await a).toBe(true);
    expect(liveCommande).toHaveBeenCalledTimes(1);
  });
});
