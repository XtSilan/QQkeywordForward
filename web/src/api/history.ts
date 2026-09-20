import type { HistoryList } from "../types/api";
import { apiJson } from "./client";

export function listHistory(
  groupId: string | undefined,
  limit: number,
  offset: number,
): Promise<HistoryList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (groupId) params.set("group_id", groupId);
  return apiJson(`/api/history?${params.toString()}`);
}