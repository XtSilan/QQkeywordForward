import { CircleAlert, ImagePlus, RefreshCw, Send, X } from "lucide-react";
import { useEffect, useState } from "react";

import { cancelBroadcastTask, createBroadcastTask, listBroadcastTasks, pauseBroadcastTask, resumeBroadcastTask } from "../api/broadcast";
import { listGroups } from "../api/groups";
import { isBotOnline } from "../api/napcat";
import { uploadImage } from "../api/ops";
import { EmptyState } from "../components/EmptyState";
import { GroupPicker } from "../components/GroupPicker";
import { BROADCAST_STATUS_LABEL, type BroadcastTask, type Group, type MessageSegment } from "../types/api";
import { usePoll } from "../hooks/usePoll";
import { useLiveSnapshot } from "../lib/live";

/** Backend rejects anything outside this window; mirror it in the UI. */
const MIN_INTERVAL_SECONDS = 1;
const MAX_INTERVAL_SECONDS = 60;
/** Prefilled delay; the floor is 1s but 2s is the safer everyday default. */
const DEFAULT_INTERVAL_SECONDS = 2;

export function BroadcastPage({ onError }: { onError: (message: string) => void }) {
  const live = useLiveSnapshot();
  const [tasks, setTasks] = useState<BroadcastTask[]>([]);
  const [title, setTitle] = useState("");
  const [groups, setGroups] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [groupOptions, setGroupOptions] = useState<Group[]>([]);
  const [interval, setIntervalValue] = useState(DEFAULT_INTERVAL_SECONDS);
  const [botOnline, setBotOnline] = useState<boolean | null>(null);

  const load = async () => {
    try {
      setTasks(await listBroadcastTasks());
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "群发任务读取失败");
    }
  };

  useEffect(() => {
    void load();
    void listGroups().then(setGroupOptions).catch(() => undefined);
  }, []);

  // Progress arrives over the shared SSE stream, so the table ticks by itself.
  useEffect(() => {
    if (live) setTasks(live.tasks);
  }, [live]);

  const checkBot = () =>
    isBotOnline()
      .then(setBotOnline)
      .catch(() => setBotOnline(null));
  usePoll(checkBot, 5000);

  const pause = async (id: string) => {
    try {
      await pauseBroadcastTask(id);
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "暂停失败");
    }
  };

  const cancel = async (id: string) => {
    try {
      await cancelBroadcastTask(id);
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "取消失败");
    }
  };

  /** "Pause, retune, confirm": saves the new delay and resumes in one step. */
  const resumeWithDelay = async (id: string, seconds: number) => {
    if (seconds < MIN_INTERVAL_SECONDS || seconds > MAX_INTERVAL_SECONDS) {
      onError(`群间延时需在 ${MIN_INTERVAL_SECONDS}-${MAX_INTERVAL_SECONDS} 秒之间`);
      return;
    }
    try {
      await resumeBroadcastTask(id, seconds);
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "继续失败");
    }
  };

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const segments: MessageSegment[] = [];
      if (message) segments.push({ type: "text", data: { text: message } });
      images.forEach((file) => segments.push({ type: "image", data: { file } }));
      await createBroadcastTask({ title, group_ids: groups, message: segments, interval_seconds: interval });
      setTitle("");
      setGroups([]);
      setMessage("");
      setImages([]);
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "群发任务创建失败");
    }
  };

  const upload = async (file: File) => {
    const body = await uploadImage(file);
    setImages((current) => [...current, body.url]);
  };

  return (
    <section className="content">
      <div className="welcome-row">
        <div>
          <h2>群发任务</h2>
          <p>按群间延时逐个发送；进度实时刷新，无需手动重载。</p>
        </div>
        <button className="button secondary" onClick={() => void load()}>
          <RefreshCw size={15} />
          刷新
        </button>
      </div>

      {botOnline === false && (
        <div className="callout warning">
          <CircleAlert size={17} />
          <span>
            Bot 未连接（NapCat 未登录或反向 WS 未就绪）。新建任务会保持排队，登录恢复后自动发送。
          </span>
        </div>
      )}

      <section className="panel form-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">NEW TASK</div>
            <h3>创建群发任务</h3>
          </div>
        </div>
        <form className="broadcast-form" onSubmit={(event) => void create(event)}>
          <div className="field-row">
            <label className="field">
              <span>任务名称</span>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="例如：活动通知"
                required
              />
            </label>
            <label className="field">
              <span>群间延时（秒）</span>
              <input
                type="number"
                min={MIN_INTERVAL_SECONDS}
                max={MAX_INTERVAL_SECONDS}
                value={interval}
                onChange={(event) => setIntervalValue(Number(event.target.value))}
              />
            </label>
          </div>

          <div className="field-section">
            <span className="field-label">目标群聊</span>
            <GroupPicker groups={groupOptions} selected={groups} onChange={setGroups} />
          </div>

          <label className="field">
            <span>消息内容</span>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="支持换行；图片会按顺序附在文本之后发送。"
              rows={5}
            />
          </label>

          <div className="field-section">
            <span className="field-label">附加图片</span>
            <div className="image-preview">
              <label className="image-upload">
                <ImagePlus size={15} />
                上传图片
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/gif,image/webp"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) {
                      void upload(file).catch((reason) =>
                        onError(reason instanceof Error ? reason.message : "图片上传失败"),
                      );
                    }
                  }}
                />
              </label>
              <small className="muted">支持 jpg / png / gif / webp，可多次添加。</small>
              {images.map((image) => (
                <span key={image} className="message-image">
                  <img src={image} alt="待发送图片" />
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => setImages((current) => current.filter((item) => item !== image))}
                  >
                    <X size={14} />
                  </button>
                </span>
              ))}
            </div>
          </div>

          <div className="form-footer">
            <button className="button primary">
              <Send size={15} />
              创建任务
            </button>
          </div>
        </form>
      </section>

      <section className="panel table-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">TASKS</div>
            <h3>任务进度</h3>
          </div>
          <span className="muted">{tasks.length} 个任务</span>
        </div>

        {tasks.length === 0 ? (
          <EmptyState icon={<Send size={22} />} title="暂无群发任务" hint="创建任务后，进度会显示在这里。" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>任务</th>
                  <th>状态</th>
                  <th>进度</th>
                  <th>群间延时</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => {
                  const percent = Math.min(
                    100,
                    Math.round((task.sent_count / Math.max(task.total_count, 1)) * 100),
                  );
                  return (
                    <tr key={task.id}>
                      <td>
                        <strong>{task.title}</strong>
                        <small>{task.id.slice(0, 8)}</small>
                      </td>
                      <td>
                        <span className={`status-badge status-${task.status}`}>
                          {BROADCAST_STATUS_LABEL[task.status] || task.status}
                        </span>
                      </td>
                      <td className="progress-cell">
                        <span>
                          {task.sent_count}/{task.total_count}
                          {task.failed_count ? ` · 失败 ${task.failed_count}` : ""}
                        </span>
                        <div className="progress-bar">
                          <div className="progress-fill" style={{ width: `${percent}%` }} />
                        </div>
                      </td>
                      <td className="nowrap">{task.interval_seconds} 秒</td>
                      <td className="nowrap">
                        {new Date(task.created_at).toLocaleString("zh-CN", { hour12: false })}
                      </td>
                      <td className="nowrap task-actions">
                        <TaskActions
                          task={task}
                          onPause={pause}
                          onCancel={cancel}
                          onResumeWithDelay={resumeWithDelay}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}

/**
 * Row controls. Changing the delay is only offered on a paused task: you pause,
 * retune, then confirm, which resumes and re-spaces the remaining groups at once.
 */
function TaskActions({
  task,
  onPause,
  onCancel,
  onResumeWithDelay,
}: {
  task: BroadcastTask;
  onPause: (id: string) => Promise<void>;
  onCancel: (id: string) => Promise<void>;
  onResumeWithDelay: (id: string, seconds: number) => Promise<void>;
}) {
  const [delay, setDelay] = useState(task.interval_seconds);

  if (["queued", "running"].includes(task.status)) {
    return (
      <>
        <button className="button secondary compact-button" onClick={() => void onPause(task.id)}>
          暂停
        </button>
        <button className="button danger compact-button" onClick={() => void onCancel(task.id)}>
          取消
        </button>
      </>
    );
  }

  if (task.status === "paused") {
    return (
      <>
        <label className="inline-input">
          <span>延时</span>
          <input
            type="number"
            min={MIN_INTERVAL_SECONDS}
            max={MAX_INTERVAL_SECONDS}
            value={delay}
            onChange={(event) => setDelay(Number(event.target.value))}
          />
          秒
        </label>
        <button
          className="button primary compact-button"
          onClick={() => void onResumeWithDelay(task.id, delay)}
        >
          确定并继续
        </button>
        <button className="button danger compact-button" onClick={() => void onCancel(task.id)}>
          取消
        </button>
      </>
    );
  }

  return <span className="muted">—</span>;
}