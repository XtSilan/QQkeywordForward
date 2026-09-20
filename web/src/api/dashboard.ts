import type { Dashboard } from "../types/api";

/** Dashboard summary. Uses its own message so the UI can say "服务不可用". */
export async function getDashboard(): Promise<Dashboard> {
  const response = await fetch("/api/dashboard", { credentials: "include" });
  if (!response.ok) throw new Error("无法读取服务状态");
  return response.json();
}