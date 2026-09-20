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

/** Resume a paused task, optionally re-tuning the group delay in the same call. */
export function resumeBroadcastTask(id: string, intervalSeconds?: number): Promise<unknown> {
  return apiJson(`/api/broadcast-tasks/${id}/resume`, {
    method: "POST",
    body: JSON.stringify({ interval_seconds: intervalSeconds ?? null }),
  });
}

export function cancelBroadcastTask(id: string): Promise<unknown> {
  return apiJson(`/api/broadcast-tasks/${id}/cancel`, { method: "POST" });
}