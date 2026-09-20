import { useEffect } from "react";

/**
 * Run `callback` immediately, then every `intervalMs`.
 *
 * Replaces the repeated `useEffect` + `setInterval` + cleanup boilerplate.
 * The callback is intentionally not a dependency: it closes over the values
 * from the render that (re)started the poll, which is what the call sites want.
 *
 * @param deps Restart the poll when these change (e.g. the selected log source).
 */
export function usePoll(callback: () => void | Promise<void>, intervalMs: number, deps: unknown[] = []) {
  useEffect(() => {
    void callback();
    const timer = window.setInterval(() => void callback(), intervalMs);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}