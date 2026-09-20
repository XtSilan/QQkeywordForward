import type { NapCatStatus } from "../types/api";
import { apiJson } from "./client";

export function getNapCatStatus(): Promise<NapCatStatus> {
  return apiJson<NapCatStatus>("/api/ops/napcat/login");
}

export function requestQrCode(): Promise<{ qrcode?: string; qrcodeurl?: string }> {
  return apiJson("/api/ops/napcat/qrcode", { method: "POST" });
}

export function refreshQrCode(): Promise<{ qrcode?: string; qrcodeurl?: string }> {
  return apiJson("/api/ops/napcat/qrcode/refresh", { method: "POST" });
}

export function restartNapCat(): Promise<unknown> {
  return apiJson("/api/ops/napcat/restart", { method: "POST" });
}

/** Whether the bot is currently logged in, for the broadcast warning banner. */
export async function isBotOnline(): Promise<boolean> {
  const info = await apiJson<{ isLogin: boolean }>("/api/ops/napcat/login");
  return Boolean(info.isLogin);
}