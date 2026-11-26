// @vitest-environment happy-dom
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fencedReducer, fencedView, initialFenced, useFenced, type FencedState } from "./fenced";

type D = { a: number; b: number; nom: string };
const r = fencedReducer<D>();
const base: D = { a: 0, b: 0, nom: "x" };
const charge = (): FencedState<D> => r(initialFenced<D>(), { type: "loaded", data: base, seq: 0 });

/** A promise resolved or rejected from the test. */
function differe<T>() {
  let resolve!: (v: T) => void, reject!: (e: unknown) => void;
  const promise = new Promise<T>((ok, ko) => { resolve = ok; reject = ko; });
  return { promise, resolve, reject };
}

describe("fencedReducer", () => {
  it("drops a read that left before an action started or settled", () => {
    let s = charge();
    const depart = s.seq;
    s = r(s, { type: "started", id: "A", apply: (x) => ({ ...x, a: 1 }) });
    s = r(s, { type: "loaded", data: { ...base, nom: "vieux" }, seq: depart });
    expect(s.server?.nom).toBe("x");
    s = r(s, { type: "succeeded", id: "A" });
    s = r(s, { type: "loaded", data: { ...base, nom: "vieux" }, seq: depart + 1 });   // left mid-flight
    expect(fencedView(s)?.a).toBe(1);
    s = r(s, { type: "loaded", data: { ...base, a: 1, nom: "neuf" }, seq: s.seq });   // left after
    expect(fencedView(s)?.nom).toBe("neuf");
  });

  it("1a: the failure of one action never takes back another one still in flight", () => {
    let s = charge();
    s = r(s, { type: "started", id: "A", apply: (x) => ({ ...x, a: 1 }) });
    s = r(s, { type: "started", id: "B", apply: (x) => ({ ...x, b: 2 }) });
    expect(fencedView(s)).toMatchObject({ a: 1, b: 2 });
    s = r(s, { type: "failed", id: "A" });
    expect(fencedView(s)).toMatchObject({ a: 0, b: 2 });
    expect(Object.keys(s.pending)).toEqual(["B"]);
    s = r(s, { type: "succeeded", id: "B" });
    expect(fencedView(s)).toMatchObject({ a: 0, b: 2 });
    expect(s.server).toMatchObject({ a: 0, b: 2 });
  });

  it("1a, other order: B fails after A succeeded, A stays", () => {
    let s = charge();
    s = r(s, { type: "started", id: "A", apply: (x) => ({ ...x, a: 1 }) });
    s = r(s, { type: "started", id: "B", apply: (x) => ({ ...x, b: 2 }) });
    s = r(s, { type: "succeeded", id: "A" });
    s = r(s, { type: "failed", id: "B" });
    expect(fencedView(s)).toMatchObject({ a: 1, b: 0 });
  });

  it("a full state answered replaces the server state, other layers stay on top", () => {
    let s = charge();
    s = r(s, { type: "started", id: "A", apply: (x) => ({ ...x, a: 1 }) });
    s = r(s, { type: "started", id: "B", apply: (x) => ({ ...x, b: 2 }) });
    s = r(s, { type: "succeeded", id: "A", data: { a: 1, b: 0, nom: "serveur" } });
    expect(fencedView(s)).toEqual({ a: 1, b: 2, nom: "serveur" });
  });

  it("applies layers in the order they were sent", () => {
    let s = charge();
    s = r(s, { type: "started", id: "A", apply: (x) => ({ ...x, nom: "premier" }) });
    s = r(s, { type: "started", id: "B", apply: (x) => ({ ...x, nom: "second" }) });
    expect(fencedView(s)?.nom).toBe("second");
  });

  it("reset forgets everything and fences reads that left before", () => {
    let s = charge();
    const depart = s.seq;
    s = r(s, { type: "started", id: "A", apply: (x) => ({ ...x, a: 1 }) });
    s = r(s, { type: "reset" });
    expect(s.server).toBeNull();
    expect(s.pending).toEqual({});
    s = r(s, { type: "loaded", data: base, seq: depart });
    expect(s.server).toBeNull();
  });

  it("uses the merge rule on reads and answers", () => {
    const max = fencedReducer<{ v: number }>((prev, next) => (prev && next.v < prev.v ? prev : next));
    let s = max(initialFenced(), { type: "loaded", data: { v: 5 }, seq: 0 });
    s = max(s, { type: "loaded", data: { v: 3 }, seq: s.seq });
    expect(s.server?.v).toBe(5);
    s = max(s, { type: "started", id: "x" });
    s = max(s, { type: "succeeded", id: "x", data: { v: 4 } });
    expect(s.server?.v).toBe(5);
  });
});

describe("useFenced", () => {
  it("1a end to end: A fails while B is in flight, B stays shown, then is confirmed", async () => {
    let serveur: D = { ...base };
    const { result } = renderHook(() => useFenced<D>(async () => ({ ...serveur })));
    await act(async () => { await result.current.reload(); });
    const A = differe<void>(), B = differe<void>();
    let ra!: Promise<unknown>, rb!: Promise<unknown>;
    act(() => {
      ra = result.current.run("A", () => A.promise, { apply: (x) => ({ ...x, a: 1 }) });
      rb = result.current.run("B", () => B.promise, { apply: (x) => ({ ...x, b: 2 }) });
    });
    expect(result.current.data).toMatchObject({ a: 1, b: 2 });
    expect(result.current.enCours("A") && result.current.enCours("B")).toBe(true);
    await act(async () => { A.reject(new Error("refusé")); await ra; });
    expect(result.current.data).toMatchObject({ a: 0, b: 2 });
    expect(result.current.enCours("A")).toBe(false);
    expect(result.current.enCours("B")).toBe(true);
    serveur = { ...serveur, b: 2 };
    await act(async () => { B.resolve(); await rb; });
    expect(result.current.data).toMatchObject({ a: 0, b: 2 });
  });

  it("a read in flight during an action is dropped (reload resolves to null)", async () => {
    const lecture = differe<D>();
    let premier = true;
    const { result } = renderHook(() => useFenced<D>(() => (premier ? Promise.resolve(base) : lecture.promise)));
    await act(async () => { await result.current.reload(); });
    premier = false;
    let lu!: Promise<D | null>, envoi!: Promise<unknown>;
    act(() => {
      lu = result.current.reload();
      envoi = result.current.run("A", async () => undefined, { apply: (x) => ({ ...x, a: 1 }) });
    });
    await act(async () => { await envoi; lecture.resolve({ ...base, nom: "vieux" }); expect(await lu).toBeNull(); });
    expect(result.current.data).toMatchObject({ a: 1, nom: "x" });
  });

  it("a second run of an action in flight is skipped; groups answer with a trailing colon", async () => {
    const { result } = renderHook(() => useFenced<D>(async () => base));
    await act(async () => { await result.current.reload(); });
    const A = differe<void>();
    let premier!: Promise<unknown>, second!: Promise<{ ok: boolean; skipped?: boolean }>;
    act(() => {
      premier = result.current.run("decision:valide", () => A.promise);
      second = result.current.run("decision:valide", () => Promise.resolve()) as Promise<{ ok: boolean; skipped?: boolean }>;
    });
    expect(await second).toMatchObject({ ok: false, skipped: true });
    expect(result.current.enCours("decision:")).toBe(true);
    await act(async () => { A.resolve(); await premier; });
    expect(result.current.enCours("decision:")).toBe(false);
  });
});
