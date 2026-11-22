import { useEffect, useRef, useState } from "react";

/** Calls `tick` every `ms` while the tab is visible. The timer stops when the tab is hidden and
 *  runs once more as soon as it comes back, so a background tab neither polls the server nor
 *  wakes the CPU. Calls never overlap: the next one is scheduled once the previous settled.
 *  `immediate: false` waits one period before the first call (the caller already has data). */
export function usePolling(
  tick: () => void | Promise<unknown>,
  ms: number,
  { enabled = true, immediate = true }: { enabled?: boolean; immediate?: boolean } = {},
) {
  // The latest closure is read through a ref: callers do not need to memoize `tick`.
  const latest = useRef(tick);
  useEffect(() => { latest.current = tick; }, [tick]);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let timer = 0;
    const schedule = () => {
      window.clearTimeout(timer);
      if (alive && !document.hidden) timer = window.setTimeout(run, ms);
    };
    const run = async () => {
      window.clearTimeout(timer);
      if (document.hidden) return;
      try { await latest.current(); } catch { /* the caller reports its own errors */ }
      schedule();
    };
    const onVisibility = () => { if (document.hidden) window.clearTimeout(timer); else run(); };
    document.addEventListener("visibilitychange", onVisibility);
    if (immediate) run(); else schedule();
    return () => {
      alive = false;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [ms, enabled, immediate]);
}

/** `Date.now()` refreshed every `ms` while the tab is visible (a live clock, a stopwatch). Only the
 *  component that calls it re-renders: keep it in a small leaf component. */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  usePolling(() => setNow(Date.now()), ms, { immediate: false });
  return now;
}
