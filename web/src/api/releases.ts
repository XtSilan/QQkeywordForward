import { apiJson } from "./client";

/** Workflow-run status surfaced by /api/release-notes. */
export type CiStatus = "queued" | "in_progress" | "completed" | "unknown";

export type ReleaseNote = {
  sha: string;
  /** First 7 characters of `sha`, for compact display. */
  short_sha: string;
  /** Commit author date, ISO 8601. */
  time: string;
  title: string;
  body: string;
  /** null when Actions has no run for this commit (or the lookup failed). */
  ci_status: CiStatus | null;
  /** Set only when ci_status === "completed" (success / failure / …). */
  ci_conclusion: string | null;
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
