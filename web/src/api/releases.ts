import { apiJson } from "./client";

export type ReleaseNote = {
  sha: string;
  /** Commit author date, ISO 8601. */
  time: string;
  title: string;
  body: string;
};

export type ReleaseNotesPayload = {
  items: ReleaseNote[];
  /** False when GitHub was unreachable or rate-limited; `items` may be stale. */
  ok: boolean;
};

/** Newest upstream commits, proxied and cached by the control plane. */
export function listReleaseNotes(): Promise<ReleaseNotesPayload> {
  return apiJson<ReleaseNotesPayload>("/api/release-notes");
}