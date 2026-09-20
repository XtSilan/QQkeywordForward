import type { Destination } from "../types/api";
import { apiJson } from "./client";

export function listDestinations(): Promise<Destination[]> {
  return apiJson<Destination[]>("/api/destinations");
}

export function updateDestination(
  id: number,
  payload: { kind: "qq" | "email"; address: string; display_name: string; enabled: boolean; group_ids: string[] },
): Promise<unknown> {
  return apiJson(`/api/destinations/${id}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function deleteDestination(id: number): Promise<unknown> {
  return apiJson(`/api/destinations/${id}`, { method: "DELETE" });
}