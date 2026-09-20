/** Thin fetch wrapper: same-origin, cookie-authenticated JSON calls. */

export async function apiJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "请求失败");
  return body as T;
}

/** For endpoints that return text rather than JSON (e.g. log streams). */
export async function apiText(path: string, fallbackMessage: string): Promise<string> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) throw new Error(fallbackMessage);
  return response.text();
}

/** For multipart uploads, which must not set a JSON Content-Type. */
export async function apiUpload<T>(path: string, file: File, fallbackMessage: string): Promise<T> {
  const data = new FormData();
  data.append("file", file);
  const response = await fetch(path, { method: "POST", credentials: "include", body: data });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || fallbackMessage);
  return body as T;
}