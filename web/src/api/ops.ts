import type { LogService, ServiceName } from "../types/api";
import { apiText, apiUpload } from "./client";

/** Restart a container service (needs Docker socket control on the backend). */
export async function restartService(service: ServiceName): Promise<void> {
  const response = await fetch(`/api/ops/services/${service}/restart`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "重启失败");
  }
}

export function fetchLogs(service: LogService, tail = 200): Promise<string> {
  return apiText(`/api/ops/logs/${service}?tail=${tail}`, "日志读取失败");
}

export function uploadImage(file: File): Promise<{ url: string; segment: unknown }> {
  return apiUpload<{ url: string; segment: unknown }>("/api/uploads/image", file, "图片上传失败");
}