import type { BroadcastTask, BroadcastTaskDetail, MessageSegment } from "../types/api";
import { apiJson } from "./client";

export function listBroadcastTasks(limit?: number): Promise<BroadcastTask[]> {
  return apiJson<BroadcastTask[]>(`/api/broadcast-tasks${limit ? `?limit=${limit}` : ""}`);
}

export function getBroadcastTask(id: string): Promise<BroadcastTaskDetail> {
  return apiJson<BroadcastTaskDetail>(`/api/broadcast-tasks/${id}`);
}

export function createBroadcastTask(payload: {
  title: string;
  group_ids: string[];
  message: MessageSegment[];
  interval_seconds: number;
  /** 0 sends the schedule once. */
  loop_total: number;
  loop_interval_seconds: number;
}): Promise<unknown> {
  return apiJson("/api/broadcast-tasks", { method: "POST", body: JSON.stringify(payload) });
}

/**
 * Retune pacing. The round gap is accepted at any time; `interval_seconds`
 * re-spaces already queued sends, so the backend only takes it while paused.
 */
export function updateBroadcastIntervals(
  id: string,
  payload: { interval_seconds?: number; loop_interval_seconds?: number },
): Promise<unknown> {
  return apiJson(`/api/broadcast-tasks/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
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