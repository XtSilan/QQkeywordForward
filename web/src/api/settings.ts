import type {
  DuplicateCoolingSettings,
  OneBotSettings,
  OneBotSettingsResponse,
  SmtpSettings,
  SmtpSettingsResponse,
} from "../types/api";
import { apiJson } from "./client";

export function getSmtpSettings(): Promise<SmtpSettingsResponse> {
  return apiJson<SmtpSettingsResponse>("/api/settings/smtp");
}

export function saveSmtpSettings(value: SmtpSettings): Promise<unknown> {
  return apiJson("/api/settings/smtp", { method: "PUT", body: JSON.stringify(value) });
}

export function getOneBotSettings(): Promise<OneBotSettingsResponse> {
  return apiJson<OneBotSettingsResponse>("/api/settings/onebot");
}

export function saveOneBotSettings(value: OneBotSettings): Promise<unknown> {
  return apiJson("/api/settings/onebot", { method: "PUT", body: JSON.stringify(value) });
}

export function getDuplicateCoolingSettings(): Promise<DuplicateCoolingSettings> {
  return apiJson<DuplicateCoolingSettings>("/api/settings/duplicate-message-cooling");
}

export function saveDuplicateCoolingSettings(value: DuplicateCoolingSettings): Promise<unknown> {
  return apiJson("/api/settings/duplicate-message-cooling", {
    method: "PUT",
    body: JSON.stringify(value),
  });
}