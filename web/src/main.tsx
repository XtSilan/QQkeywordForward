import { StrictMode, useEffect, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import QRCode from "qrcode";
import {
  Activity, Bell, Bot, CheckCircle2, ChevronRight, CircleAlert, FileText,
  KeyRound, LayoutDashboard, Menu, MessageSquareText, RefreshCw, RotateCcw,
  Send, Settings2, ShieldCheck, TerminalSquare, Users, X
} from "lucide-react";
import "./style.css";

type Dashboard = {
  config_revision: number;
  napcat: { ok?: boolean; isLogin?: boolean; coreReady?: boolean; loginPhase?: string; loginError?: string; error?: string };
  nonebot: { service: string; config_reload: boolean };
  stats?: { groups: number; keyword_hits_today: number };
};

type Group = { group_id: string; name: string; avatar_url: string; enabled: number };
type Keyword = { id: number; display_text: string; group_count: number; bindings: { group_id: string; enabled: number; cooldown_seconds: number }[] };
type HistoryItem = { id: number; group_id: string; group_name: string; sender_id: string; sender_name: string; keyword_text_snapshot: string; message_text: string; hit_at: string; notify_status: string };

const navItems = [
  ["Dashboard", LayoutDashboard],
  ["关键词", KeyRound],
  ["通知", Bell],
  ["历史记录", FileText],
  ["群发任务", Send],
  ["登录与 NapCat", ShieldCheck],
  ["运行日志", TerminalSquare],
  ["系统设置", Settings2]
] as const;

async function getDashboard(): Promise<Dashboard> {
  const response = await fetch("/api/dashboard");
  if (!response.ok) throw new Error("无法读取服务状态");
  return response.json();
}

async function apiJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "请求失败");
  return body as T;
}

function StatusDot({ online }: { online: boolean }) {
  return <span className={online ? "status-dot online" : "status-dot"} />;
}

function App() {
  const [active, setActive] = useState("Dashboard");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [action, setAction] = useState("");

  const refresh = async () => {
    try {
      setDashboard(await getDashboard());
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "服务不可用");
    }
  };

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const restart = async (service: "napcat" | "nonebot") => {
    setAction(service);
    try {
      const response = await fetch("/api/ops/services/" + service + "/restart", { method: "POST" });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail || "重启失败");
      }
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重启失败");
    } finally {
      setAction("");
    }
  };

  const napcatOnline = Boolean(dashboard?.napcat?.coreReady || dashboard?.napcat?.isLogin);

  return (
    <div className="app-shell">
      {mobileOpen && <button className="scrim" onClick={() => setMobileOpen(false)} aria-label="关闭导航" />}
      <aside className={mobileOpen ? "sidebar open" : "sidebar"}>
        <div className="brand">
          <div className="brand-mark"><Bot size={20} /></div>
          <div><strong>QQ Bot</strong><span>Control Plane</span></div>
          <button className="icon-button mobile-close" onClick={() => setMobileOpen(false)} aria-label="关闭"><X size={18} /></button>
        </div>
        <div className="sidebar-caption">管理台</div>
        <nav>
          {navItems.map(([label, Icon]) => (
            <button key={label} className={active === label ? "nav-item active" : "nav-item"} onClick={() => { setActive(label); setMobileOpen(false); }}>
              <Icon size={17} /><span>{label}</span>{label === "运行日志" && <span className="nav-pill">LIVE</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="connection-row"><StatusDot online={napcatOnline} /><span>{napcatOnline ? "NapCat 已连接" : "NapCat 待连接"}</span></div>
          <div className="connection-row"><StatusDot online={Boolean(dashboard)} /><span>{dashboard ? "WebUI 正常" : "WebUI 离线"}</span></div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="打开导航"><Menu size={19} /></button>
          <div><div className="eyebrow">QQ 群管理机器人</div><h1>{active}</h1></div>
          <div className="topbar-actions">
            <span className="revision">配置版本 {dashboard?.config_revision ?? "-"}</span>
            <button className="button secondary" onClick={() => void refresh()}><RefreshCw size={15} />刷新</button>
          </div>
        </header>
        {error && <div className="alert error"><CircleAlert size={17} /><span>{error}</span><button className="icon-button" onClick={() => setError("")} aria-label="关闭错误"><X size={16} /></button></div>}
        {active === "Dashboard" && <DashboardPage dashboard={dashboard} action={action} restart={restart} />}
        {active === "关键词" && <KeywordPage onError={setError} />}
        {active === "历史记录" && <HistoryPage onError={setError} />}
        {active === "登录与 NapCat" && <NapCatPage onError={setError} />}
        {active === "运行日志" && <LogsPage onError={setError} />}
        {!(["Dashboard", "关键词", "历史记录", "登录与 NapCat", "运行日志"] as string[]).includes(active) && <PlaceholderPage active={active} />}
      </main>
    </div>
  );
}

function DashboardPage({ dashboard, action, restart }: { dashboard: Dashboard | null; action: string; restart: (service: "napcat" | "nonebot") => Promise<void> }) {
  const online = Boolean(dashboard?.napcat?.coreReady || dashboard?.napcat?.isLogin);
  return (
    <section className="content">
      <div className="welcome-row">
        <div><h2>运行概览</h2><p>从这里检查连接状态、服务和近期操作。</p></div>
        <div className={online ? "status-chip good" : "status-chip warn"}><StatusDot online={online} />{online ? "QQ 在线" : "等待 QQ 登录"}</div>
      </div>
      <div className="stat-grid">
        <StatCard icon={<Activity size={18} />} label="NapCat" value={online ? "在线" : "未连接"} detail={dashboard?.napcat?.loginPhase || "等待状态"} tone="green" />
        <StatCard icon={<MessageSquareText size={18} />} label="关键词命中" value={String(dashboard?.stats?.keyword_hits_today ?? 0)} detail="今日累计" tone="blue" />
        <StatCard icon={<Send size={18} />} label="群发任务" value="0" detail="等待执行" tone="violet" />
        <StatCard icon={<Users size={18} />} label="配置群聊" value={String(dashboard?.stats?.groups ?? 0)} detail="已同步群聊" tone="slate" />
      </div>
      <div className="dashboard-grid">
        <section className="panel service-panel">
          <div className="panel-heading"><div><div className="panel-kicker">SERVICES</div><h3>服务控制</h3></div><span className="muted">受控操作</span></div>
          <ServiceRow name="NapCat" description="QQ 登录、OneBot 连接与账号状态" online={online} busy={action === "napcat"} onRestart={() => void restart("napcat")} />
          <ServiceRow name="NoneBot" description="关键词监听、通知队列与群发调度" online={Boolean(dashboard)} busy={action === "nonebot"} onRestart={() => void restart("nonebot")} />
          <div className="callout"><ShieldCheck size={17} /><span>关键词和通知设置保存后会热加载；修改连接地址、依赖或环境变量时才需要重启 NoneBot。</span></div>
        </section>
        <section className="panel activity-panel">
          <div className="panel-heading"><div><div className="panel-kicker">ACTIVITY</div><h3>最近动态</h3></div><button className="text-button">查看全部<ChevronRight size={15} /></button></div>
          <div className="empty-state"><div className="empty-icon"><CheckCircle2 size={22} /></div><strong>暂无动态</strong><span>关键词命中和任务发送后会显示在这里。</span></div>
        </section>
      </div>
      <section className="panel quick-panel">
        <div className="panel-heading"><div><div className="panel-kicker">NEXT</div><h3>开始配置</h3></div></div>
        <div className="quick-grid">
          <QuickAction icon={<KeyRound size={17} />} title="添加关键词" detail="配置群级匹配规则" />
          <QuickAction icon={<Bell size={17} />} title="设置通知" detail="添加 QQ 好友或邮箱" />
          <QuickAction icon={<Send size={17} />} title="创建群发任务" detail="选择群聊并安排发送" />
          <QuickAction icon={<ShieldCheck size={17} />} title="打开登录页" detail="查看二维码和登录状态" />
        </div>
      </section>
    </section>
  );
}

function StatCard({ icon, label, value, detail, tone }: { icon: ReactNode; label: string; value: string; detail: string; tone: string }) {
  return <div className="stat-card"><div className={"stat-icon " + tone}>{icon}</div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>;
}

function ServiceRow({ name, description, online, busy, onRestart }: { name: string; description: string; online: boolean; busy: boolean; onRestart: () => void }) {
  return <div className="service-row"><div className="service-icon"><Bot size={17} /></div><div className="service-copy"><strong>{name}</strong><span>{description}</span></div><div className={online ? "service-status online-text" : "service-status"}><StatusDot online={online} />{online ? "运行中" : "待连接"}</div><button className="button ghost" onClick={onRestart} disabled={busy}><RotateCcw size={15} />{busy ? "处理中" : "重启"}</button></div>;
}

function QuickAction({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <button className="quick-action"><div className="quick-icon">{icon}</div><div><strong>{title}</strong><span>{detail}</span></div><ChevronRight size={16} /></button>;
}

function KeywordPage({ onError }: { onError: (message: string) => void }) {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [text, setText] = useState("");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [keywordData, groupData] = await Promise.all([
        apiJson<Keyword[]>("/api/keywords"),
        apiJson<Group[]>("/api/groups"),
      ]);
      setKeywords(keywordData);
      setGroups(groupData);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "关键词加载失败");
    }
  };
  useEffect(() => { void load(); }, []);

  const addKeyword = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    try {
      await apiJson("/api/keywords", { method: "POST", body: JSON.stringify({ display_text: text, group_ids: groupIds, enabled }) });
      setText("");
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "关键词保存失败");
    } finally { setBusy(false); }
  };

  const removeKeyword = async (id: number) => {
    try { await apiJson(`/api/keywords/${id}`, { method: "DELETE" }); await load(); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "删除失败"); }
  };

  return <section className="content">
    <div className="welcome-row"><div><h2>关键词规则</h2><p>输入普通文本即可，系统会按字面匹配。</p></div><button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div>
    <section className="panel form-panel">
      <div className="panel-heading"><div><div className="panel-kicker">NEW RULE</div><h3>添加关键词</h3></div><span className="muted">不需要填写正则</span></div>
      <form className="keyword-form" onSubmit={(event) => void addKeyword(event)}>
        <label className="field"><span>关键词</span><input value={text} onChange={(event) => setText(event.target.value)} placeholder="例如：报名、紧急通知" maxLength={200} /></label>
        <label className="field"><span>应用群聊</span><select multiple value={groupIds} onChange={(event) => setGroupIds(Array.from(event.target.selectedOptions, (option) => option.value))}>{groups.map((group) => <option key={group.group_id} value={group.group_id}>{group.name || "未命名群"} · {group.group_id}</option>)}</select><small>暂未同步群聊时可先保存规则，后续批量应用。</small></label>
        <label className="check-field"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /><span>保存后启用</span></label>
        <button className="button primary" disabled={busy}><KeyRound size={15} />{busy ? "保存中" : "保存关键词"}</button>
      </form>
    </section>
    <section className="panel table-panel"><div className="panel-heading"><div><div className="panel-kicker">RULES</div><h3>已配置关键词</h3></div><span className="muted">{keywords.length} 条</span></div>
      {keywords.length === 0 ? <div className="empty-state"><div className="empty-icon"><KeyRound size={22} /></div><strong>还没有关键词</strong><span>添加第一条规则后会显示在这里。</span></div> : <div className="table-wrap"><table><thead><tr><th>关键词</th><th>应用群聊</th><th>状态</th><th aria-label="操作" /></tr></thead><tbody>{keywords.map((keyword) => <tr key={keyword.id}><td><strong>{keyword.display_text}</strong><small>字面匹配 · 忽略大小写</small></td><td>{keyword.group_count ? `${keyword.group_count} 个群` : <span className="muted">未绑定</span>}</td><td><span className="status-chip good compact"><StatusDot online />已启用</span></td><td><button className="icon-button danger-button" onClick={() => void removeKeyword(keyword.id)} aria-label={`删除 ${keyword.display_text}`}><X size={16} /></button></td></tr>)}</tbody></table></div>}
    </section>
  </section>;
}

function HistoryPage({ onError }: { onError: (message: string) => void }) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const load = async () => {
    try { const data = await apiJson<{ items: HistoryItem[]; total: number }>("/api/history?limit=100"); setItems(data.items); setTotal(data.total); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "历史记录加载失败"); }
  };
  useEffect(() => { void load(); }, []);
  return <section className="content">
    <div className="welcome-row"><div><h2>历史记录</h2><p>关键词命中会保留群、发送者和原始文本。</p></div><button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div>
    <section className="panel table-panel"><div className="panel-heading"><div><div className="panel-kicker">HISTORY</div><h3>关键词命中</h3></div><span className="muted">共 {total} 条</span></div>
      {items.length === 0 ? <div className="empty-state"><div className="empty-icon"><FileText size={22} /></div><strong>暂无命中记录</strong><span>机器人识别到关键词后会显示在这里。</span></div> : <div className="table-wrap"><table><thead><tr><th>时间</th><th>群聊</th><th>发送者</th><th>命中</th><th>消息</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td className="nowrap">{new Date(item.hit_at).toLocaleString("zh-CN", { hour12: false })}</td><td><strong>{item.group_name || "未命名群"}</strong><small>{item.group_id}</small></td><td>{item.sender_name || "未知"}<small>{item.sender_id}</small></td><td><span className="keyword-tag">{item.keyword_text_snapshot}</span></td><td className="message-cell">{item.message_text || "（非文本消息）"}</td></tr>)}</tbody></table></div>}
    </section>
  </section>;
}

function NapCatPage({ onError }: { onError: (message: string) => void }) {
  const [status, setStatus] = useState<Dashboard["napcat"] | null>(null);
  const [qr, setQr] = useState("");
  const [qrImage, setQrImage] = useState("");
  const [busy, setBusy] = useState("");
  const load = async () => {
    try { setStatus(await apiJson<Dashboard["napcat"]>("/api/ops/napcat/login")); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "NapCat 状态读取失败"); }
  };
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 2000); return () => window.clearInterval(timer); }, []);
  useEffect(() => { if (!qr) { setQrImage(""); return; } void QRCode.toDataURL(qr, { width: 220, margin: 2 }).then(setQrImage).catch(() => setQrImage("")); }, [qr]);
  const getQr = async () => {
    setBusy("qr");
    try { const data = await apiJson<{ qrcode?: string; qrcodeurl?: string }>("/api/ops/napcat/qrcode", { method: "POST" }); setQr(data.qrcode || data.qrcodeurl || ""); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "二维码获取失败"); }
    finally { setBusy(""); }
  };
  const refreshQr = async () => {
    setBusy("refresh");
    try { const data = await apiJson<{ qrcode?: string; qrcodeurl?: string }>("/api/ops/napcat/qrcode/refresh", { method: "POST" }); setQr(data.qrcode || data.qrcodeurl || ""); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "二维码刷新失败"); }
    finally { setBusy(""); }
  };
  const restart = async () => {
    setBusy("restart");
    try { await apiJson("/api/ops/napcat/restart", { method: "POST" }); await load(); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "NapCat 重启失败"); }
    finally { setBusy(""); }
  };
  const online = Boolean(status?.isLogin || status?.coreReady);
  return <section className="content">
    <div className="welcome-row"><div><h2>登录与 NapCat</h2><p>二维码和登录状态由后端安全代理，不把 NapCat 凭据暴露给浏览器。</p></div><div className={online ? "status-chip good" : "status-chip warn"}><StatusDot online={online} />{online ? "QQ 已登录" : status?.loginPhase || "等待状态"}</div></div>
    <div className="napcat-grid"><section className="panel qr-panel"><div className="panel-heading"><div><div className="panel-kicker">QR LOGIN</div><h3>扫码登录</h3></div><button className="button secondary" onClick={() => void refreshQr()} disabled={busy !== ""}><RefreshCw size={15} />刷新</button></div>
      {qr ? <div className="qr-content"><div className="qr-placeholder">{qrImage ? <img src={qrImage} alt="NapCat 登录二维码" /> : <span>二维码生成中</span>}</div><code>{qr}</code><span>请使用手机 QQ 扫描二维码并授权。</span></div> : <div className="empty-state"><div className="empty-icon"><ShieldCheck size={22} /></div><strong>尚未获取二维码</strong><span>点击下方按钮从 NapCat 获取最新二维码。</span></div>}
      {!qr && <button className="button primary full-button" onClick={() => void getQr()} disabled={busy !== ""}><ShieldCheck size={15} />{busy === "qr" ? "获取中" : "获取二维码"}</button>}
    </section><section className="panel napcat-info-panel"><div className="panel-heading"><div><div className="panel-kicker">NAPCAT STATUS</div><h3>运行状态</h3></div><span className="muted">2 秒刷新</span></div><div className="info-list"><InfoRow label="登录状态" value={status?.isLogin ? "已登录" : "未登录"} good={Boolean(status?.isLogin)} /><InfoRow label="核心状态" value={status?.coreReady ? "已就绪" : "等待中"} good={Boolean(status?.coreReady)} /><InfoRow label="登录阶段" value={status?.loginPhase || "-"} /><InfoRow label="登录错误" value={status?.loginError || "无"} /></div><div className="callout"><ShieldCheck size={17} /><span>二维码过期时点击刷新。修改 NapCat 或 OneBot 配置后，再使用重启按钮应用。</span></div><button className="button ghost full-button" onClick={() => void restart()} disabled={busy !== ""}><RotateCcw size={15} />{busy === "restart" ? "重启中" : "重启 NapCat"}</button></section></div>
  </section>;
}

function InfoRow({ label, value, good }: { label: string; value: string; good?: boolean }) { return <div className="info-row"><span>{label}</span><strong className={good ? "online-text" : ""}>{value}</strong></div>; }

function LogsPage({ onError }: { onError: (message: string) => void }) {
  const [service, setService] = useState<"nonebot" | "napcat">("nonebot");
  const [logs, setLogs] = useState("正在加载日志...");
  const load = async () => {
    try { const response = await fetch(`/api/ops/logs/${service}?tail=200`); if (!response.ok) throw new Error("日志读取失败"); setLogs(await response.text()); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "日志读取失败"); }
  };
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 5000); return () => window.clearInterval(timer); }, [service]);
  return <section className="content"><div className="welcome-row"><div><h2>运行日志</h2><p>查看 NoneBot 和 NapCat 最近输出，日志来源由后端控制。</p></div><button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div><section className="panel logs-panel"><div className="log-tabs"><button className={service === "nonebot" ? "log-tab active" : "log-tab"} onClick={() => setService("nonebot")}>NoneBot</button><button className={service === "napcat" ? "log-tab active" : "log-tab"} onClick={() => setService("napcat")}>NapCat</button></div><pre className="log-output">{logs}</pre></section></section>;
}

function PlaceholderPage({ active }: { active: string }) {
  return <section className="content"><div className="placeholder panel"><div className="empty-icon"><Settings2 size={22} /></div><h2>{active}</h2><p>这一页的 API 和交互将在下一轮接入，当前导航和运行状态已经可用。</p></div></section>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
