import { apiJson } from "./client";

export type Health = {
  ok: boolean;
  revision: number;
  /** git short SHA (or "dev") baked into the running image at build time */
  version?: string;
  build_time?: string;
};

export function getHealth(): Promise<Health> {
  return apiJson<Health>("/api/health");
}
