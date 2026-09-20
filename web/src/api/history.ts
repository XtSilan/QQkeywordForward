import type { HistoryItem } from "../types/api";
import { apiJson } from "./client";

export function listHistory(groupId?: string, limit = 100): Promise<{ items: HistoryItem[]; total: number }> {
  const query = groupId ? `&group_id=${encodeURIComponent(groupId)}` : "";
  return apiJson(`/api/history?limit=${limit}${query}`);
}