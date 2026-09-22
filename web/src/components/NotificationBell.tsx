import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/** Repo the update history is read from. */
const REPO = "XtSilan/QQkeywordForward";
/** How many recent commits the panel lists. */
const PAGE_SIZE = 15;
/** GitHub is unreachable on some networks; fail with a hint instead of hanging. */
const TIMEOUT_MS = 8000;

type Update = { sha: string; time: string; title: string; body: string };
type CommitItem = {
  sha?: unknown;
  commit?: { message?: unknown; author?: { date?: unknown } };
};

/** A commit message is "title line + body"; both become one update entry. */
function parseCommit(item: CommitItem): Update | null {
  const sha = typeof item.sha === "string" ? item.sha : "";
  const message = typeof item.commit?.message === "string" ? item.commit.message : "";
  const date = typeof item.commit?.author?.date === "string" ? item.commit.author.date : "";
  if (!sha || !message.trim()) return null;
  const lines = message.split("\n");
  return {
    sha,
    time: date,
    title: (lines[0] ?? "").trim(),
    body: lines.slice(1).join("\n").trim(),
  };
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  if (!value || Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

/**
 * Topbar bell listing the newest GitHub commits. The request is lazy (first
 * open) and every failure path degrades to a short hint, so an unreachable
 * GitHub never affects the rest of the console.
 */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [updates, setUpdates] = useState<Update[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const shellRef = useRef<HTMLDivElement>(null);

  // Closing resets the failure flag so reopening retries the request.
  useEffect(() => {
    if (!open) setFailed(false);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (shellRef.current && !shellRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open || updates !== null || failed) return;
    let cancelled = false;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
    setLoading(true);
    void (async () => {
      try {
        const response = await fetch(
          `https://api.github.com/repos/${REPO}/commits?per_page=${PAGE_SIZE}`,
          { signal: controller.signal, headers: { Accept: "application/vnd.github+json" } },
        );
        if (!response.ok) throw new Error("unexpected status");
        const payload: unknown = await response.json();
        const list = Array.isArray(payload)
          ? payload.map((item) => parseCommit(item as CommitItem)).filter((item): item is Update => item !== null)
          : [];
        if (!cancelled) setUpdates(list);
      } catch {
        if (!cancelled) setFailed(true);
      } finally {
        window.clearTimeout(timer);
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, updates, failed]);

  return (
    <div className="notif-shell" ref={shellRef}>
      <button
        type="button"
        className="icon-button notif-trigger"
        onClick={() => setOpen((current) => !current)}
        aria-label="更新记录"
        aria-expanded={open}
      >
        <Bell size={17} />
      </button>
      {open && (
        <div className="notif-panel">
          <div className="notif-head">更新记录</div>
          {loading && <p className="notif-hint">加载中…</p>}
          {!loading && failed && <p className="notif-hint">暂时无法获取更新信息。</p>}
          {!loading && !failed && updates?.length === 0 && <p className="notif-hint">暂无更新记录。</p>}
          {updates && updates.length > 0 && (
            <ol className="notif-list">
              {updates.map((update) => (
                <li key={update.sha}>
                  <span className="notif-time">{formatTime(update.time)}</span>
                  <strong>{update.title}</strong>
                  {update.body && <p>{update.body}</p>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}