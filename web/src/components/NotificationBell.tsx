import { Bell, CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { listReleaseNotes, type ReleaseNote } from "../api/releases";

function formatTime(value: string): string {
  const parsed = new Date(value);
  if (!value || Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

/** Compact badge: ✓ success · ✗ failure · ◌ in progress · nothing if no run. */
function CiBadge({ note }: { note: ReleaseNote }) {
  if (note.ci_status === null) return null;
  if (note.ci_status === "completed") {
    const ok = note.ci_conclusion === "success";
    const Icon = ok ? CheckCircle2 : XCircle;
    return (
      <span
        className={`notif-ci ${ok ? "ok" : "fail"}`}
        title={ok ? "Actions 成功" : `Actions ${note.ci_conclusion || "失败"}`}
      >
        <Icon size={12} />
        <span>{ok ? "通过" : note.ci_conclusion || "失败"}</span>
      </span>
    );
  }
  if (note.ci_status === "in_progress" || note.ci_status === "queued") {
    return (
      <span className="notif-ci running" title="Actions 进行中">
        <CircleDashed size={12} className="notif-ci-spin" />
        <span>{note.ci_status === "queued" ? "排队中" : "进行中"}</span>
      </span>
    );
  }
  return (
    <span className="notif-ci unknown" title="Actions 状态未知">
      <CircleDashed size={12} />
      <span>未知</span>
    </span>
  );
}

/**
 * Topbar bell listing the newest upstream commits. The request is lazy (first
 * open) and goes through our own backend, which owns the GitHub call and its
 * cache — see app/api/releases.py. Every failure degrades to a short hint, so
 * an unreachable GitHub never affects the rest of the console.
 */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [updates, setUpdates] = useState<ReleaseNote[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const shellRef = useRef<HTMLDivElement>(null);

  // Closing resets the failure flag so reopening retries the request.
  useEffect(() => {
    if (!open) setError(false);
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
    if (!open || updates !== null || error) return;
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const payload = await listReleaseNotes();
        if (cancelled) return;
        setUpdates(payload.items);
        setError(payload.ok === false);
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, updates, error]);

  const empty = !updates || updates.length === 0;

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
          {!loading && empty && error && <p className="notif-hint">暂时无法获取更新信息。</p>}
          {!loading && empty && !error && <p className="notif-hint">暂无更新记录。</p>}
          {!empty && (
            <ol className="notif-list">
              {updates.map((update) => (
                <li key={update.sha}>
                  <div className="notif-meta">
                    <span className="notif-time">{formatTime(update.time)}</span>
                    <code className="notif-sha" title={update.sha}>
                      {update.short_sha}
                    </code>
                    <CiBadge note={update} />
                  </div>
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
