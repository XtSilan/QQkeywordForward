import type { Group } from "../types/api";
import { apiJson } from "./client";

export function listGroups(): Promise<Group[]> {
  return apiJson<Group[]>("/api/groups");
}

export function syncGroups(groups: Group[]): Promise<{ synced: number }> {
  return apiJson("/api/groups/sync", { method: "POST", body: JSON.stringify(groups) });
}