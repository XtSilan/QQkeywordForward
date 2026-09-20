import { CircleAlert, ImagePlus, RefreshCw, Send, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  cancelBroadcastTask,
  createBroadcastTask,
  getBroadcastTask,
  listBroadcastTasks,
  pauseBroadcastTask,
  resumeBroadcastTask,
  updateBroadcastIntervals,
} from "../api/broadcast";
import { listGroups } from "../api/groups";
import { isBotOnline } from "../api/napcat";
import { uploadImage } from "../api/ops";
import { EmptyState } from "../components/EmptyState";
import { GroupPicker } from "../components/GroupPicker";
import {
  BROADCAST_STATUS_LABEL,
  type BroadcastTask,
  type BroadcastTaskDetail,
  type Group,
  type MessageSegment,
} from "../types/api";
import { usePoll } from "../hooks/usePoll";
import { useLiveSnapshot } from "../lib/live";

/** Backend rejects anything outside this window; mirror it in the UI. */
const MIN_INTERVAL_SECONDS = 1;
const MAX_INTERVAL_SECONDS = 60;
/** Prefilled delay; the floor is 1s but 2s is the safer everyday default. */
const DEFAULT_INTERVAL_SECONDS = 2;

/** Mirrors app/schemas/broadcast.py for the auto-loop controls. */
const MIN_LOOP_INTERVAL_SECONDS = 5;
const MAX_LOOP_INTERVAL_SECONDS = 86400;
const MAX_LOOP_TOTAL = 50;
const DEFAULT_LOOP_TOTAL = 3;
const DEFAULT_LOOP_INTERVAL_SECONDS = 60;

export function BroadcastPage({ onError }: { onError: (message: string) => void }) {
  const live = useLiveSnapshot();
  const [tasks, setTasks] = useState<BroadcastTask[]>([]);
  const [title, setTitle] = useState("");
  const [groups, setGroups] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [groupOptions, setGroupOptions] = useState<Group[]>([]);
  const [interval, setIntervalValue] = useState(DEFAULT_INTERVAL_SECONDS);
  const [loopEnabled, setLoopEnabled] = useState(false);
  const [loopTotal, setLoopTotal] = useState(DEFAULT_LOOP_TOTAL);
  const [loopInterval, setLoopInterval] = useState(DEFAULT_LOOP_INTERVAL_SECONDS);
  const [botOnline, setBotOnline] = useState<boolean | null>(null);
  const [failDetail, setFailDetail] = useState<BroadcastTaskDetail | null>(null);
  const [failDetailLoading, setFailDetailLoading] = useState(false);

  const load = async () => {
    try {
      setTasks(await listBroadcastTasks());
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "群发任务读取失败");
    }
  };

  useEffect(() => {
    void load();
    void listGroups().then((all) => setGroupOptions(all.filter((g) => g.enabled))).catch(() => undefined);
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

  const openFailDetail = async (taskId: string) => {
    setFailDetailLoading(true);
    try {
      setFailDetail(await getBroadcastTask(taskId));
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "加载失败详情出错");
    } finally {
      setFailDetailLoading(false);
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

  /** The round gap can be retuned while running: it only gates the next round. */
  const saveLoopInterval = async (id: string, seconds: number) => {
    if (seconds < MIN_LOOP_INTERVAL_SECONDS || seconds > MAX_LOOP_INTERVAL_SECONDS) {
      onError(`轮间隔需在 ${MIN_LOOP_INTERVAL_SECONDS}-${MAX_LOOP_INTERVAL_SECONDS} 秒之间`);
      return;
    }
    try {
      await updateBroadcastIntervals(id, { loop_interval_seconds: seconds });
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "轮间隔保存失败");
    }
  };

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const segments: MessageSegment[] = [];
      if (message) segments.push({ type: "text", data: { text: message } });
      images.forEach((file) => segments.push({ type: "image", data: { file } }));
      await createBroadcastTask({
        title,
        group_ids: groups,
        message: segments,
        interval_seconds: interval,
        loop_total: loopEnabled ? loopTotal : 0,
        loop_interval_seconds: loopInterval,
      });
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
          <p>按群间延时逐个发送；可开启自动循环，进度实时刷新。</p>
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

          <label className="check-field">
            <input
              type="checkbox"
              checked={loopEnabled}
              onChange={(event) => setLoopEnabled(event.target.checked)}
            />
            自动循环发送
          </label>

          {loopEnabled && (
            <div className="field-row">
              <label className="field">
                <span>循环次数（含首轮）</span>
                <input
                  type="number"
                  min={1}
                  max={MAX_LOOP_TOTAL}
                  value={loopTotal}
                  onChange={(event) => setLoopTotal(Number(event.target.value))}
                />
                <small>1 轮等于不循环，上限 {MAX_LOOP_TOTAL} 轮。</small>
              </label>
              <label className="field">
                <span>每轮间隔（秒）</span>
                <input
                  type="number"
                  min={MIN_LOOP_INTERVAL_SECONDS}
                  max={MAX_LOOP_INTERVAL_SECONDS}
                  value={loopInterval}
                  onChange={(event) => setLoopInterval(Number(event.target.value))}
                />
                <small>上一轮发完后，等多久开始下一轮。</small>
              </label>
            </div>
          )}

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
                  const looping = task.loop_total > 1;
                  // A looping task shows round progress; the bar follows the
                  // round in flight so it restarts instead of creeping to 100%.
                  const doneInRound = looping ? task.round_sent : task.sent_count;
                  const percent = Math.min(
                    100,
                    Math.round((doneInRound / Math.max(task.total_count, 1)) * 100),
                  );
                  return (
                    <tr key={task.id}>
                      <td>
                        <strong>{task.title}</strong>
                        <small>{task.id.slice(0, 8)}</small>
                        {looping && (
                          <small className="muted">
                            循环 {task.loop_total} 轮 · 轮间隔 {task.loop_interval_seconds} 秒
                          </small>
                        )}
                      </td>
                      <td>
                        <span
                          className={`status-badge status-${task.status}${task.failed_count ? " clickable" : ""}`}
                          onClick={task.failed_count ? () => void openFailDetail(task.id) : undefined}
                          role={task.failed_count ? "button" : undefined}
                          tabIndex={task.failed_count ? 0 : undefined}
                          onKeyDown={
                            task.failed_count
                              ? (e) => { if (e.key === "Enter") void openFailDetail(task.id); }
                              : undefined
                          }
                        >
                          {looping && task.status === "running"
                            ? "循环中"
                            : BROADCAST_STATUS_LABEL[task.status] || task.status}
                        </span>
                      </td>
                      <td className="progress-cell">
                        {looping ? (
                          <>
                            <span>
                              第 {task.loop_current}/{task.loop_total} 轮 · 本轮 {task.round_sent}/
                              {task.total_count}
                            </span>
                            <small className="muted">
                              累计 {task.sent_count} 条
                              {task.failed_count ? ` · 失败 ${task.failed_count}` : ""}
                            </small>
                          </>
                        ) : (
                          <span>
                            {task.sent_count}/{task.total_count}
                            {task.failed_count ? ` · 失败 ${task.failed_count}` : ""}
                          </span>
                        )}
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
                          onSaveLoopInterval={saveLoopInterval}
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

      {failDetail && (
        <FailDetailPanel
          detail={failDetail}
          loading={failDetailLoading}
          onClose={() => setFailDetail(null)}
          groupOptions={groupOptions}
        />
      )}
    </section>
  );
}

/** Modal showing per-group failure details for a broadcast task. */
function FailDetailPanel({
  detail,
  loading,
  onClose,
  groupOptions,
}: {
  detail: BroadcastTaskDetail;
  loading: boolean;
  onClose: () => void;
  groupOptions: Group[];
}) {
  const groupName = (gid: string) =>
    groupOptions.find((g) => g.group_id === gid)?.name || gid;
  const failed = detail.groups.filter((g) => g.status === "failed");

  return (
    <div className="fail-detail-overlay" onClick={onClose}>
      <div className="fail-detail-panel" onClick={(e) => e.stopPropagation()}>
        <div className="fail-detail-header">
          <h3>失败详情 · {detail.title}</h3>
          <button className="icon-button" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        {loading ? (
          <p className="muted">加载中…</p>
        ) : failed.length === 0 ? (
          <p className="muted">没有失败的群。</p>
        ) : (
          <div className="fail-detail-body">
            <p className="muted">
              共 {detail.total_count} 个群，成功 {detail.sent_count}，失败{" "}
              {detail.failed_count}。
            </p>
            <table className="fail-detail-table">
              <thead>
                <tr>
                  <th>群名</th>
                  <th>群 ID</th>
                  <th>错误原因</th>
                </tr>
              </thead>
              <tbody>
                {failed.map((g) => (
                  <tr key={g.group_id}>
                    <td>{groupName(g.group_id)}</td>
                    <td className="muted">{g.group_id}</td>
                    <td className="fail-reason">
                      {extractErrorMessage(g.error_text) || "未知错误"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/** Extract the human-readable QQ error from NapCat's nested error_text. */
function extractErrorMessage(text: string | null): string {
  if (!text) return "";
  // NapCat wraps: "ActionFailed(..., message='EventChecker Failed: ... errMsg: "xxx"', ...)"
  const match = text.match(/"errMsg":\s*"([^"]+)"/);
  if (match) return match[1];
  // Fallback: try message='...' pattern
  const match2 = text.match(/message='([^']+)'/);
  if (match2) return match2[1].slice(0, 120);
  return text.slice(0, 120);
}

/**
 * Row controls. Changing the group delay is only offered on a paused task: you
 * pause, retune, then confirm, which resumes and re-spaces the remaining groups
 * at once. A looping task additionally gets a round-gap editor, which is safe
 * while the task is still sending because it only gates the next round.
 */
function TaskActions({
  task,
  onPause,
  onCancel,
  onResumeWithDelay,
  onSaveLoopInterval,
}: {
  task: BroadcastTask;
  onPause: (id: string) => Promise<void>;
  onCancel: (id: string) => Promise<void>;
  onResumeWithDelay: (id: string, seconds: number) => Promise<void>;
  onSaveLoopInterval: (id: string, seconds: number) => Promise<void>;
}) {
  const [delay, setDelay] = useState(task.interval_seconds);
  const [loopDelay, setLoopDelay] = useState(task.loop_interval_seconds);
  const loopControl =
    task.loop_total > 1 ? (
      <LoopIntervalControl
        value={loopDelay}
        onChange={setLoopDelay}
        onSave={() => onSaveLoopInterval(task.id, loopDelay)}
      />
    ) : null;

  if (["queued", "running"].includes(task.status)) {
    return (
      <>
        <button className="button secondary compact-button" onClick={() => void onPause(task.id)}>
          暂停
        </button>
        {loopControl}
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
        {loopControl}
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

/** Round-gap editor shared by the running and paused rows of a looping task. */
function LoopIntervalControl({
  value,
  onChange,
  onSave,
}: {
  value: number;
  onChange: (seconds: number) => void;
  onSave: () => Promise<void>;
}) {
  return (
    <>
      <label className="inline-input">
        <span>轮间隔</span>
        <input
          type="number"
          min={MIN_LOOP_INTERVAL_SECONDS}
          max={MAX_LOOP_INTERVAL_SECONDS}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        秒
      </label>
      <button className="button secondary compact-button" onClick={() => void onSave()}>
        保存间隔
      </button>
    </>
  );
}