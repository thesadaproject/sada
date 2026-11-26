// @vitest-environment happy-dom
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { Provider } from "react-redux";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const liveIndicator = vi.fn();
const liveCommande = vi.fn();
vi.mock("./api", () => ({
  api: {
    liveIndicator: (...a: unknown[]) => liveIndicator(...a),
    liveCommande: (...a: unknown[]) => liveCommande(...a),
    regie: vi.fn().mockResolvedValue({ live: {}, commands: [] }),
  },
}));

import { FRESH_MS, onAir, onAirFromSlice, useEnDirect } from "./onAir";
import { makeStore } from "./store";
import { snapshotReceived } from "./store/liveSlice";
import { sendCommand } from "./store/liveThunks";

describe("onAir (same rule as live.on_air on the server)", () => {
  it("needs the orchestrator to answer", () => {
    expect(onAir({ ok: false, state: "KHUTBA", stream_on: true })).toBe(false);
    expect(onAir(null)).toBe(false);
  });
  it("is on air in a broadcast state even without stream_on, or with stream_on alone", () => {
    expect(onAir({ ok: true, state: "PRAYER", stream_on: false })).toBe(true);
    expect(onAir({ ok: true, state: "ENDED", stream_on: true })).toBe(true);
    expect(onAir({ ok: true, state: "IDLE", stream_on: false })).toBe(false);
    expect(onAir({ ok: true, state: "STOPPED" })).toBe(false);
  });
  it("only answers from the slice while it is fresh", () => {
    expect(onAirFromSlice({ ok: true, state: "KHUTBA" }, 1000, 1000 + FRESH_MS - 1)).toBe(true);
    expect(onAirFromSlice({ ok: true, state: "KHUTBA" }, 1000, 1000 + FRESH_MS)).toBeNull();
    expect(onAirFromSlice(null, 1000, 1000)).toBeNull();
    expect(onAirFromSlice({ ok: true, state: "KHUTBA" }, 0, 5)).toBeNull();
  });
});

describe("useEnDirect", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] }); liveIndicator.mockReset(); liveCommande.mockReset(); });
  afterEach(() => { vi.useRealTimers(); });

  const monter = () => {
    const store = makeStore();
    const wrapper = ({ children }: { children: ReactNode }) => <Provider store={store}>{children}</Provider>;
    return { store, ...renderHook(() => useEnDirect(1), { wrapper }) };
  };

  it("uses the route until the slice holds a fresh state, then the slice, then the route again", async () => {
    liveIndicator.mockResolvedValue({ on: false });
    const { store, result } = monter();
    await act(async () => { await Promise.resolve(); });
    expect(result.current).toBe(false);
    act(() => { store.dispatch(snapshotReceived({ data: { live: { ok: true, state: "KHUTBA" } }, seq: 0, at: Date.now() })); });
    expect(result.current).toBe(true);
    await act(async () => { vi.advanceTimersByTime(FRESH_MS + 1); });
    expect(result.current).toBe(false);          // stale: back to the route's answer
  });

  it("reads the route again right after a successful start", async () => {
    liveIndicator.mockResolvedValue({ on: false });
    const { store } = monter();
    await act(async () => { await Promise.resolve(); });
    expect(liveIndicator).toHaveBeenCalledTimes(1);
    liveCommande.mockResolvedValueOnce({ ok: true, message: "ok" });
    await act(async () => { await store.dispatch(sendCommand("start")); });
    expect(liveIndicator).toHaveBeenCalledTimes(2);
    liveCommande.mockResolvedValueOnce({ ok: true, message: "ok" });
    await act(async () => { await store.dispatch(sendCommand("skip")); });
    expect(liveIndicator).toHaveBeenCalledTimes(2);   // not a transport command
  });
});
