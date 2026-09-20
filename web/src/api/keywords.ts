import type { ChannelDraft, Keyword } from "../types/api";
import { apiJson } from "./client";

export function listKeywords(): Promise<Keyword[]> {
  return apiJson<Keyword[]>("/api/keywords");
}

export function updateKeyword(
  id: number,
  payload: { display_text?: string; enabled?: boolean; cooldown_seconds?: number },
): Promise<unknown> {
  return apiJson(`/api/keywords/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteKeyword(id: number): Promise<unknown> {
  return apiJson(`/api/keywords/${id}`, { method: "DELETE" });
}

export function bulkToggleKeywords(keywordIds: number[], enabled: boolean): Promise<unknown> {
  return apiJson("/api/keywords/bulk-toggle", {
    method: "POST",
    body: JSON.stringify({ keyword_ids: keywordIds, enabled }),
  });
}

export function bulkDeleteKeywords(keywordIds: number[]): Promise<unknown> {
  return apiJson("/api/keywords/bulk-delete", {
    method: "POST",
    body: JSON.stringify({ keyword_ids: keywordIds, enabled: false }),
  });
}

/** Manual drag order (alphabetical=false) or A-Z (alphabetical=true). */
export function reorderKeywords(keywordIds: number[], alphabetical: boolean): Promise<unknown> {
  return apiJson("/api/keywords/reorder", {
    method: "POST",
    body: JSON.stringify({ keyword_ids: keywordIds, alphabetical }),
  });
}

/** Create several keywords at once, bound to groups and destinations. */
export function createKeywordConfig(payload: {
  keywords: string[];
  group_ids: string[];
  destination_ids: number[];
  enabled: boolean;
  cooldown_seconds: number;
}): Promise<unknown> {
  return apiJson("/api/keyword-configs", { method: "POST", body: JSON.stringify(payload) });
}

/** Replace a single keyword's group bindings. */
export function bulkApplyKeyword(payload: {
  keyword_id: number;
  group_ids: string[];
  enabled: boolean;
  cooldown_seconds: number;
  replace_existing: boolean;
}): Promise<unknown> {
  return apiJson("/api/keywords/bulk-apply", { method: "POST", body: JSON.stringify(payload) });
}

export function updateKeywordNotifications(
  id: number,
  destinationIds: number[],
): Promise<unknown> {
  return apiJson(`/api/keywords/${id}/notifications`, {
    method: "PUT",
    body: JSON.stringify({ destination_ids: destinationIds }),
  });
}

/** Create QQ/email destinations and immediately bind them to groups. */
export function createNotificationConfig(
  channels: ChannelDraft[],
  groupIds: string[],
): Promise<{ destination_ids: number[] }> {
  return apiJson("/api/notification-configs", {
    method: "POST",
    body: JSON.stringify({ channels, group_ids: groupIds }),
  });
}