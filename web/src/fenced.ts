/** A page's server data with a write fence and one optimistic layer per action in flight — the same
 *  model as the live slice (store/liveSlice.ts), for pages that keep their data locally.
 *
 *  - `server`: the last state the server gave (a read, or the full state an action answered).
 *  - `pending`: one layer per action in flight, keyed by the caller (`revoke:3`, `decision:valide`…),
 *    each with the change it applies at once. What is shown is `server` + every layer, in the order
 *    they were sent. A failed action only removes its own layer: another one in flight stays shown.
 *  - `seq` is bumped when an action starts and when it settles. A read carries the `seq` seen when it
 *    left; if it changed since, the read may predate a write and is dropped.
 *  - `merge` decides how a newer read replaces the previous one (default: it does). Habillage uses it
 *    to never step a version counter back.
 *
 *  `fencedReducer` is pure (tested on its own); `useFenced` wires it to a page. */
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

export type Apply<T> = (x: T) => T;
export type Layer<T> = { seq: number; apply?: Apply<T> };
export type FencedState<T> = { server: T | null; seq: number; pending: Record<string, Layer<T>> };
export type FencedAction<T> =
  | { type: "loaded"; data: T; seq: number }
  | { type: "started"; id: string; apply?: Apply<T> }
  | { type: "succeeded"; id: string; data?: T | null }
  | { type: "failed"; id: string }
  | { type: "reset" };
export type Merge<T> = (prev: T | null, next: T) => T;

export function initialFenced<T>(): FencedState<T> {
  return { server: null, seq: 0, pending: {} };
}

const remplace = <T,>(_prev: T | null, next: T) => next;

export function fencedReducer<T>(merge: Merge<T> = remplace) {
  return (state: FencedState<T>, a: FencedAction<T>): FencedState<T> => {
    switch (a.type) {
      case "loaded":
        // Left before an action started or settled: it may not hold that action's effect.
        if (a.seq !== state.seq) return state;
        return { ...state, server: merge(state.server, a.data) };
      case "started": {
        const seq = state.seq + 1;
        return { ...state, seq, pending: { ...state.pending, [a.id]: { seq, apply: a.apply } } };
      }
      case "succeeded": {
        const layer = state.pending[a.id];
        const { [a.id]: _done, ...pending } = state.pending;
        let server = state.server;
        if (a.data) server = merge(server, a.data);
        else if (layer?.apply && server) server = layer.apply(server);   // the write held: its change is confirmed
        return { server, seq: state.seq + 1, pending };
      }
      case "failed": {
        const { [a.id]: _failed, ...pending } = state.pending;
        return { ...state, seq: state.seq + 1, pending };
      }
      case "reset":
        return { server: null, seq: state.seq + 1, pending: {} };
    }
  };
}

/** What the page shows: the server state with every action in flight on top. */
export function fencedView<T>(s: FencedState<T>): T | null {
  if (!s.server) return null;
  const layers: Layer<T>[] = Object.values(s.pending);
  let v: T = s.server;
  for (const l of layers.sort((x, y) => x.seq - y.seq)) if (l.apply) v = l.apply(v);
  return v;
}

export type RunResult<R> = { ok: true; r: R } | { ok: false; error: unknown; skipped?: boolean };

/** `load` reads the page's data. `reload()` resolves to the data read, or null when the read was
 *  stale and dropped; it rejects when the request fails (the page reports it). `run(id, send, opts)`
 *  applies `apply` at once, sends, then settles: `confirmed(r)` turns the answer into the full state
 *  when the server sends one. A second `run` with an id still in flight is skipped. */
export function useFenced<T>(load: () => Promise<T>, merge?: Merge<T>) {
  const reducer = useMemo(() => fencedReducer<T>(merge), [merge]);
  const [state, dispatch] = useReducer(reducer, undefined, initialFenced<T>);
  // Mirrors of the reducer's counter and pending ids, readable synchronously by the async calls.
  const seq = useRef(0);
  const enVol = useRef(new Set<string>());
  const epoch = useRef(0);
  const loadRef = useRef(load);
  useEffect(() => { loadRef.current = load; }, [load]);

  const reload = useCallback(async (): Promise<T | null> => {
    const depart = seq.current, e = epoch.current;
    const data = await loadRef.current();
    if (e !== epoch.current || depart !== seq.current) return null;
    dispatch({ type: "loaded", data, seq: depart });
    return data;
  }, []);

  const run = useCallback(async <R,>(id: string, send: () => Promise<R>,
    opts: { apply?: Apply<T>; confirmed?: (r: R) => T | null | undefined } = {}): Promise<RunResult<R>> => {
    if (enVol.current.has(id)) return { ok: false, error: null, skipped: true };
    const e = epoch.current;
    enVol.current.add(id);
    seq.current += 1;
    dispatch({ type: "started", id, apply: opts.apply });
    try {
      const r = await send();
      if (e === epoch.current) {
        enVol.current.delete(id);
        seq.current += 1;
        dispatch({ type: "succeeded", id, data: opts.confirmed?.(r) ?? null });
      }
      return { ok: true, r };
    } catch (error) {
      if (e === epoch.current) {
        enVol.current.delete(id);
        seq.current += 1;
        dispatch({ type: "failed", id });
      }
      return { ok: false, error };
    }
  }, []);

  /** Another record is opened: forget everything; answers about the previous one are dropped. */
  const reset = useCallback(() => {
    epoch.current += 1;
    seq.current += 1;
    enVol.current.clear();
    dispatch({ type: "reset" });
  }, []);

  const data = useMemo(() => fencedView(state), [state]);
  const pending = state.pending;
  /** Is this action (or, with a trailing ":", any action of this group) in flight? */
  const enCours = useCallback((id: string) =>
    id.endsWith(":") ? Object.keys(pending).some((k) => k.startsWith(id)) : Boolean(pending[id]), [pending]);

  return { data, server: state.server, pending, enCours, reload, run, reset };
}
