import type {
  AutoLoginSettings,
  OrderDedupSettings,
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

export function getAutoLoginSettings(): Promise<AutoLoginSettings> {
  return apiJson<AutoLoginSettings>("/api/settings/auto-login");
}

export function saveAutoLoginSettings(value: AutoLoginSettings): Promise<unknown> {
  return apiJson("/api/settings/auto-login", {
    method: "PUT",
    body: JSON.stringify(value),
  });
}

export function getOrderDedupSettings(): Promise<OrderDedupSettings> {
  return apiJson<OrderDedupSettings>("/api/settings/order-dedup");
}

export function saveOrderDedupSettings(value: OrderDedupSettings): Promise<unknown> {
  return apiJson("/api/settings/order-dedup", {
    method: "PUT",
    body: JSON.stringify(value),
  });
}