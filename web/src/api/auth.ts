import { apiJson } from "./client";

export async function fetchAuthMe(): Promise<boolean> {
  const response = await fetch("/api/auth/me", { credentials: "include" });
  return response.ok;
}

export async function login(token: string): Promise<boolean> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  return response.ok;
}