import type { BroadcastTask, MessageSegment } from "../types/api";
import { apiJson } from "./client";

export function listBroadcastTasks(limit?: number): Promise<BroadcastTask[]> {
  return apiJson<BroadcastTask[]>(`/api/broadcast-tasks${limit ? `?limit=${limit}` : ""}`);
}

export function createBroadcastTask(payload: {
  title: string;
  group_ids: string[];
  message: MessageSegment[];
  interval_seconds: number;
}): Promise<unknown> {
  return apiJson("/api/broadcast-tasks", { method: "POST", body: JSON.stringify(payload) });
}

export function pauseBroadcastTask(id: string): Promise<unknown> {
  return apiJson(`/api/broadcast-tasks/${id}/pause`, { method: "POST" });
}

export function resumeBroadcastTask(id: string): Promise<unknown> {
  return apiJson(`/api/broadcast-tasks/${id}/resume`, { method: "POST" });
}

export function cancelBroadcastTask(id: string): Promise<unknown> {
  return apiJson(`/api/broadcast-tasks/${id}/cancel`, { method: "POST" });
}

/** Adjust the per-group delay (seconds) of a queued/running/paused task. */
export function setBroadcastInterval(id: string, intervalSeconds: number): Promise<unknown> {
  return apiJson(`/api/broadcast-tasks/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ interval_seconds: intervalSeconds }),
  });
}

export function runBroadcastAction(id: string, action: "pause" | "resume" | "cancel"): Promise<unknown> {
  return apiJson(`/api/broadcast-tasks/${id}/${action}`, { method: "POST" });
}