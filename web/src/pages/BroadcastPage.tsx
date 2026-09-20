import { CircleAlert, RefreshCw, Send, X } from "lucide-react";
import { useEffect, useState } from "react";

import { createBroadcastTask, listBroadcastTasks, setBroadcastInterval, runBroadcastAction } from "../api/broadcast";
import { listGroups } from "../api/groups";
import { isBotOnline } from "../api/napcat";
import { uploadImage } from "../api/ops";
import { EmptyState } from "../components/EmptyState";
import { GroupPicker } from "../components/GroupPicker";
import { BROADCAST_STATUS_LABEL, type BroadcastTask, type Group, type MessageSegment } from "../types/api";
import { usePoll } from "../hooks/usePoll";

/** Backend rejects anything outside this window; mirror it in the UI. */
const MIN_INTERVAL_SECONDS = 5;
const MAX_INTERVAL_SECONDS = 60;

export function BroadcastPage({ onError }: { onError: (message: string) => void }) {
  const [tasks, setTasks] = useState<BroadcastTask[]>([]);
  const [title, setTitle] = useState("");
  const [groups, setGroups] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [groupOptions, setGroupOptions] = useState<Group[]>([]);
  const [interval, setIntervalValue] = useState(MIN_INTERVAL_SECONDS);
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

  const checkBot = () =>
    isBotOnline()
      .then(setBotOnline)
      .catch(() => setBotOnline(null));
  usePoll(checkBot, 5000);

  const patch = async (id: string, action: "pause" | "resume" | "cancel") => {
    try {
      await runBroadcastAction(id, action);
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "操作失败");
    }
  };

  const patchInterval = async (id: string, value: number) => {
    if (value < MIN_INTERVAL_SECONDS || value > MAX_INTERVAL_SECONDS) return;
    try {
      await setBroadcastInterval(id, value);
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "调速失败");
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
          <p>群间延迟最低 5 秒，系统仍限制每分钟最多发送 5 个群。</p>
        </div>
        <button className="button secondary" onClick={() => void load()}>
          <RefreshCw size={15} />
          刷新
        </button>
      </div>

      <section className="panel form-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">NEW TASK</div>
            <h3>创建群发任务</h3>
          </div>
        </div>
        <form className="broadcast-form" onSubmit={(event) => void create(event)}>
          <label className="field">
            <span>任务名称</span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="例如：活动通知"
              required
            />
          </label>
          <div className="field field-wide">
            <span>目标群聊</span>
            <GroupPicker groups={groupOptions} selected={groups} onChange={setGroups} />
            <small>可逐个选择，也可一键全选。</small>
          </div>
          <label className="field field-wide">
            <span>消息内容</span>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="支持换行"
              rows={4}
            />
          </label>
          <label className="field">
            <span>插入图片</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file).catch((reason) => onError(reason instanceof Error ? reason.message : "图片上传失败"));
              }}
            />
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
          <button className="button primary">
            <Send size={15} />
            创建任务
          </button>
        </form>
      </section>

      {botOnline === false && (
        <div className="callout warning">
          <CircleAlert size={17} />
          <span>
            Bot 未连接（NapCat 未登录或反向 WS 未就绪）。新建任务会保持排队，登录恢复后自动发送。
          </span>
        </div>
      )}

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
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
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
                    <td>
                      {task.sent_count}/{task.total_count}
                      {task.failed_count ? ` · 失败 ${task.failed_count}` : ""}
                    </td>
                    <td className="nowrap">
                      {new Date(task.created_at).toLocaleString("zh-CN", { hour12: false })}
                    </td>
                    <td className="nowrap task-actions">
                      <TaskActions task={task} onAction={patch} onInterval={patchInterval} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}

function TaskActions({
  task,
  onAction,
  onInterval,
}: {
  task: BroadcastTask;
  onAction: (id: string, action: "pause" | "resume" | "cancel") => Promise<void>;
  onInterval: (id: string, value: number) => Promise<void>;
}) {
  const adjustable = ["queued", "running", "paused"].includes(task.status);
  return (
    <>
      {["queued", "running"].includes(task.status) ? (
        <>
          <button className="button secondary compact-button" onClick={() => void onAction(task.id, "pause")}>
            暂停
          </button>
          <button className="button danger compact-button" onClick={() => void onAction(task.id, "cancel")}>
            取消
          </button>
        </>
      ) : task.status === "paused" ? (
        <>
          <button className="button primary compact-button" onClick={() => void onAction(task.id, "resume")}>
            继续
          </button>
          <button className="button danger compact-button" onClick={() => void onAction(task.id, "cancel")}>
            取消
          </button>
        </>
      ) : (
        <span className="muted">—</span>
      )}
      {adjustable && (
        <label className="inline-input">
          <span>间隔</span>
          <input
            type="number"
            min={MIN_INTERVAL_SECONDS}
            max={MAX_INTERVAL_SECONDS}
            defaultValue={task.interval_seconds}
            onBlur={(event) => {
              const value = Number(event.target.value);
              if (value !== task.interval_seconds) void onInterval(task.id, value);
            }}
          />
        </label>
      )}
    </>
  );
}