import { X } from "lucide-react";
import { useEffect, useState } from "react";

/** Repo the version announcement is read from. */
const REPO = "XtSilan/QQkeywordForward";
/** Per-device memo of the commit whose announcement has already been dismissed. */
const DISMISS_KEY = "qq-kf.announcement.sha";
/** GitHub is unreachable on some networks; give up quietly instead of blocking. */
const TIMEOUT_MS = 8000;

type Announcement = { sha: string; title: string; body: string };
type CommitItem = { sha?: unknown; commit?: { message?: unknown } };

/** A commit message is "title line + body"; the body is our announcement text. */
function parse(message: string, sha: string): Announcement {
  const lines = message.split("\n");
  return {
    sha,
    title: (lines[0] ?? "").trim(),
    body: lines.slice(1).join("\n").trim(),
  };
}

/**
 * Shows the newest GitHub commit as a one-off announcement. Each device sees it
 * once per commit: dismissing stores the sha, so a later commit pops again.
 * Every failure path (offline, timeout, rate limit, unexpected payload) is
 * silent — the dashboard must work with or without GitHub.
 */
export function AnnouncementModal() {
  const [announcement, setAnnouncement] = useState<Announcement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
    void (async () => {
      try {
        const response = await fetch(`https://api.github.com/repos/${REPO}/commits?per_page=1`, {
          signal: controller.signal,
          headers: { Accept: "application/vnd.github+json" },
        });
        if (!response.ok) return;
        const payload: unknown = await response.json();
        const commit = Array.isArray(payload) ? (payload[0] as CommitItem | undefined) : undefined;
        const sha = typeof commit?.sha === "string" ? commit.sha : "";
        const message = typeof commit?.commit?.message === "string" ? commit.commit.message : "";
        if (!sha || !message.trim()) return;
        if (window.localStorage.getItem(DISMISS_KEY) === sha) return;
        setAnnouncement(parse(message, sha));
      } catch {
        // Unreachable GitHub is expected, not an error worth surfacing.
      } finally {
        window.clearTimeout(timer);
      }
    })();
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, []);

  if (!announcement) return null;

  const dismiss = () => {
    window.localStorage.setItem(DISMISS_KEY, announcement.sha);
    setAnnouncement(null);
  };

  return (
    <div className="announcement-overlay" onClick={dismiss}>
      <div className="announcement-panel" onClick={(event) => event.stopPropagation()}>
        <div className="announcement-head">
          <div>
            <div className="panel-kicker">RELEASE NOTE</div>
            <h3>{announcement.title}</h3>
          </div>
          <button className="icon-button" onClick={dismiss} aria-label="关闭公告">
            <X size={18} />
          </button>
        </div>
        {announcement.body && <div className="announcement-body">{announcement.body}</div>}
        <div className="announcement-foot">
          <button className="button primary" onClick={dismiss}>
            我知道了
          </button>
        </div>
      </div>
    </div>
  );
}