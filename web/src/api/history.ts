import type { HistoryList } from "../types/api";
import { apiJson } from "./client";

export type HistoryQuery = {
  groupId?: string | undefined;
  /** Inclusive lower bound (UTC instant); omit to list all history. */
  since?: string | undefined;
  /** Exclusive upper bound (UTC instant). */
  until?: string | undefined;
  limit: number;
  offset: number;
};

export function listHistory(query: HistoryQuery): Promise<HistoryList> {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.groupId) params.set("group_id", query.groupId);
  if (query.since) params.set("since", query.since);
  if (query.until) params.set("until", query.until);
  return apiJson(`/api/history?${params.toString()}`);
}