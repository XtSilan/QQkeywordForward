import { CheckCircle2, Send } from "lucide-react";
import { useEffect, useState } from "react";

import { listBroadcastTasks } from "../api/broadcast";
import { useLiveSnapshot } from "../lib/live";
import { BROADCAST_STATUS_LABEL, type BroadcastTask } from "../types/api";
import { EmptyState } from "./EmptyState";
import { StatCard } from "./StatCard";

/** Dashboard stat: how many tasks are queued or currently sending. */
export function BroadcastCountCard() {
  const live = useLiveSnapshot();
  const [tasks, setTasks] = useState<BroadcastTask[]>([]);

  useEffect(() => {
    void listBroadcastTasks(200)
      .then(setTasks)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (live) setTasks(live.tasks);
  }, [live]);

  const active = tasks.filter((task) => ["queued", "running"].includes(task.status)).length;
  return <StatCard icon={<Send size={18} />} label="群发任务" value={String(active)} detail="排队或执行中" tone="violet" />;
}

/** Dashboard panel: recent broadcast tasks with a live progress bar. */
export function BroadcastActivity() {
  const live = useLiveSnapshot();
  const [tasks, setTasks] = useState<BroadcastTask[]>([]);

  useEffect(() => {
    void listBroadcastTasks(10)
      .then(setTasks)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (live) setTasks(live.tasks.slice(0, 10));
  }, [live]);

  if (!tasks.length) {
    return (
      <EmptyState
        icon={<CheckCircle2 size={22} />}
        title="暂无任务"
        hint="创建群发任务后进度会显示在这里。"
      />
    );
  }

  return (
    <div className="activity-list">
      {tasks.map((task) => {
        const total = Math.max(task.total_count, 1);
        const percent = Math.min(100, Math.round((task.sent_count / total) * 100));
        const failed = task.failed_count ? ` · 失败 ${task.failed_count}` : "";
        return (
          <div className="activity-item" key={task.id}>
            <div className="activity-row">
              <strong>{task.title}</strong>
              <span className={`status-badge status-${task.status}`}>
                {BROADCAST_STATUS_LABEL[task.status] || task.status}
              </span>
            </div>
            <div className="activity-meta">
              <span>
                {task.sent_count}/{task.total_count}
                {failed}
              </span>
              <span className="muted">
                {new Date(task.created_at).toLocaleString("zh-CN", { hour12: false })}
              </span>
            </div>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${percent}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}