/**
 * Single shared connection to the backend SSE stream (`/api/events`).
 *
 * One `EventSource` is reused by every page so navigating between them does not
 * churn connections, and it is closed once the last subscriber unsubscribes.
 */
import { useEffect, useState } from "react";

import type { BroadcastTask } from "../types/api";

export type LiveSnapshot = {
  revision: number;
  groups: number;
  hits: { total: number; today: number; latest_id: number };
  tasks: BroadcastTask[];
};

type Listener = (snapshot: LiveSnapshot) => void;

let source: EventSource | null = null;
let latest: LiveSnapshot | null = null;
const listeners = new Set<Listener>();

function connect(): void {
  if (source) return;
  source = new EventSource("/api/events");
  source.addEventListener("snapshot", (event) => {
    latest = JSON.parse((event as MessageEvent).data) as LiveSnapshot;
    listeners.forEach((listener) => listener(latest!));
  });
}

/** Subscribe to the shared stream. Returns the unsubscribe function. */
export function subscribeLive(listener: Listener): () => void {
  listeners.add(listener);
  connect();
  if (latest) listener(latest);
  return () => {
    listeners.delete(listener);
    if (!listeners.size && source) {
      source.close();
      source = null;
    }
  };
}

/** Latest server snapshot, or null until the first event arrives. */
export function useLiveSnapshot(): LiveSnapshot | null {
  const [value, setValue] = useState<LiveSnapshot | null>(latest);
  useEffect(() => subscribeLive(setValue), []);
  return value;
}