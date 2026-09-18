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
type Destination = { id: number; kind: "qq" | "email"; address: string; display_name: string; enabled: number };
type BroadcastTask = { id: string; title: string; status: string; total_count: number; sent_count: number; failed_count: number; interval_seconds: number; created_at: string };
type MessageSegment = { type: "text" | "image"; data: { text?: string; file?: string } };

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
  const response = await fetch("/api/dashboard", { credentials: "include" });
  if (!response.ok) throw new Error("无法读取服务状态");
  return response.json();
}

async function apiJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", headers: { "Content-Type": "application/json" }, ...options });
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
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
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
    void fetch("/api/auth/me", { credentials: "include" }).then((response) => setAuthenticated(response.ok)).catch(() => setAuthenticated(false));
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  if (authenticated === false) return <LoginPage onLogin={() => setAuthenticated(true)} />;

  const restart = async (service: "napcat" | "nonebot") => {
    setAction(service);
    try {
      const response = await fetch("/api/ops/services/" + service + "/restart", { method: "POST", credentials: "include" });
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
        {active === "通知" && <NotificationsPage onError={setError} />}
        {active === "群发任务" && <BroadcastPage onError={setError} />}
        {!(["Dashboard", "关键词", "历史记录", "登录与 NapCat", "运行日志", "通知", "群发任务"] as string[]).includes(active) && <PlaceholderPage active={active} />}
      </main>
    </div>
  );
}

function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const response = await fetch("/api/auth/login", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
    if (!response.ok) { setError("管理员 token 不正确"); return; }
    setToken(""); onLogin();
  };
  return <main className="main login-main"><section className="panel login-panel"><div className="brand-mark"><Bot size={22} /></div><h1>管理员登录</h1><p>请输入部署时配置的管理员 token。</p><form onSubmit={(event) => void submit(event)}><label className="field"><span>管理员 token</span><input type="password" value={token} onChange={(event) => setToken(event.target.value)} autoFocus required /></label><button className="button primary"><ShieldCheck size={15} />登录</button>{error && <div className="alert error">{error}</div>}</form></section></main>;
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

function NotificationsPage({ onError }: { onError: (message: string) => void }) {
  const [items, setItems] = useState<Destination[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [selectedGroup, setSelectedGroup] = useState("");
  const [qqEnabled, setQqEnabled] = useState(false);
  const [emailEnabled, setEmailEnabled] = useState(false);
  const [selectedDestinations, setSelectedDestinations] = useState<number[]>([]);
  const [kind, setKind] = useState<"qq" | "email">("qq");
  const [address, setAddress] = useState("");
  const [name, setName] = useState("");
  const load = async () => { try { const [destinations, groupData] = await Promise.all([apiJson<Destination[]>("/api/destinations"), apiJson<Group[]>("/api/groups")]); setItems(destinations); setGroups(groupData); if (!selectedGroup && groupData[0]) setSelectedGroup(groupData[0].group_id); } catch (reason) { onError(reason instanceof Error ? reason.message : "通知配置读取失败"); } };
  useEffect(() => { void load(); }, []);
  useEffect(() => { if (!selectedGroup) return; void apiJson<{ qq_enabled: boolean; email_enabled: boolean; destination_ids: number[] }>(`/api/groups/${selectedGroup}/notification-settings`).then((settings) => { setQqEnabled(settings.qq_enabled); setEmailEnabled(settings.email_enabled); setSelectedDestinations(settings.destination_ids); }).catch((reason) => onError(reason instanceof Error ? reason.message : "群通知设置读取失败")); }, [selectedGroup]);
  const add = async (event: React.FormEvent) => { event.preventDefault(); try { await apiJson("/api/destinations", { method: "POST", body: JSON.stringify({ kind, address, display_name: name }) }); setAddress(""); setName(""); await load(); } catch (reason) { onError(reason instanceof Error ? reason.message : "通知收件人保存失败"); } };
  const remove = async (id: number) => { try { await apiJson(`/api/destinations/${id}`, { method: "DELETE" }); await load(); } catch (reason) { onError(reason instanceof Error ? reason.message : "删除失败"); } };
  const saveGroupSettings = async () => { if (!selectedGroup) return; try { await apiJson(`/api/groups/${selectedGroup}/notification-settings`, { method: "PUT", body: JSON.stringify({ qq_enabled: qqEnabled, email_enabled: emailEnabled, destination_ids: selectedDestinations }) }); } catch (reason) { onError(reason instanceof Error ? reason.message : "群通知设置保存失败"); } };
  const toggleDestination = (id: number) => setSelectedDestinations((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  return <section className="content"><div className="welcome-row"><div><h2>通知设置</h2><p>先维护 QQ 好友或邮箱收件人，再在群级设置中启用。</p></div><button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div><section className="panel form-panel"><div className="panel-heading"><div><div className="panel-kicker">DESTINATION</div><h3>添加收件人</h3></div></div><form className="destination-form" onSubmit={(event) => void add(event)}><label className="field"><span>类型</span><select value={kind} onChange={(event) => setKind(event.target.value as "qq" | "email")}><option value="qq">QQ 好友</option><option value="email">邮箱</option></select></label><label className="field"><span>{kind === "qq" ? "QQ 号" : "邮箱地址"}</span><input value={address} onChange={(event) => setAddress(event.target.value)} placeholder={kind === "qq" ? "123456789" : "name@example.com"} /></label><label className="field"><span>备注</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：管理员" /></label><button className="button primary"><Bell size={15} />添加</button></form></section><section className="panel form-panel"><div className="panel-heading"><div><div className="panel-kicker">GROUP OVERRIDE</div><h3>群级通知开关</h3></div><span className="muted">每个群独立保存</span></div><div className="group-settings"><label className="field"><span>选择群聊</span><select value={selectedGroup} onChange={(event) => setSelectedGroup(event.target.value)}><option value="">请先同步群聊</option>{groups.map((group) => <option key={group.group_id} value={group.group_id}>{group.name || "未命名群"} · {group.group_id}</option>)}</select></label><label className="check-field"><input type="checkbox" checked={qqEnabled} onChange={(event) => setQqEnabled(event.target.checked)} />QQ 好友通知</label><label className="check-field"><input type="checkbox" checked={emailEnabled} onChange={(event) => setEmailEnabled(event.target.checked)} />邮件通知</label><div className="destination-checks">{items.map((item) => <label className="check-field" key={item.id}><input type="checkbox" checked={selectedDestinations.includes(item.id)} onChange={() => toggleDestination(item.id)} />{item.display_name || item.address} <small>{item.kind === "qq" ? "QQ" : "邮箱"}</small></label>)}</div><button className="button primary" onClick={() => void saveGroupSettings()} disabled={!selectedGroup}><Bell size={15} />保存群通知设置</button></div></section><section className="panel table-panel"><div className="panel-heading"><div><div className="panel-kicker">RECIPIENTS</div><h3>收件人列表</h3></div><span className="muted">{items.length} 个</span></div>{items.length === 0 ? <div className="empty-state"><div className="empty-icon"><Bell size={22} /></div><strong>还没有收件人</strong><span>添加 QQ 或邮箱后，命中通知才能投递。</span></div> : <div className="table-wrap"><table><thead><tr><th>类型</th><th>地址</th><th>备注</th><th /></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{item.kind === "qq" ? "QQ 好友" : "邮箱"}</td><td><strong>{item.address}</strong></td><td>{item.display_name || <span className="muted">-</span>}</td><td><button className="icon-button danger-button" onClick={() => void remove(item.id)} aria-label="删除收件人"><X size={16} /></button></td></tr>)}</tbody></table></div>}</section></section>;
}

function BroadcastPage({ onError }: { onError: (message: string) => void }) {
  const [tasks, setTasks] = useState<BroadcastTask[]>([]);
  const [title, setTitle] = useState("");
  const [groups, setGroups] = useState("");
  const [message, setMessage] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [groupOptions, setGroupOptions] = useState<Group[]>([]);
  const [interval, setInterval] = useState(12);
  const load = async () => { try { setTasks(await apiJson<BroadcastTask[]>("/api/broadcast-tasks")); } catch (reason) { onError(reason instanceof Error ? reason.message : "群发任务读取失败"); } };
  useEffect(() => { void load(); void apiJson<Group[]>("/api/groups").then(setGroupOptions).catch(() => undefined); }, []);
  const create = async (event: React.FormEvent) => { event.preventDefault(); try { const segments: MessageSegment[] = []; if (message) segments.push({ type: "text", data: { text: message } }); images.forEach((file) => segments.push({ type: "image", data: { file } })); await apiJson("/api/broadcast-tasks", { method: "POST", body: JSON.stringify({ title, group_ids: groups.split(/[,，\s]+/).filter(Boolean), message: segments, interval_seconds: interval }) }); setTitle(""); setGroups(""); setMessage(""); setImages([]); await load(); } catch (reason) { onError(reason instanceof Error ? reason.message : "群发任务创建失败"); } };
  const upload = async (file: File) => { const data = new FormData(); data.append("file", file); const response = await fetch("/api/uploads/image", { method: "POST", credentials: "include", body: data }); const body = await response.json(); if (!response.ok) throw new Error(body.detail || "图片上传失败"); setImages((current) => [...current, body.url]); };
  return <section className="content"><div className="welcome-row"><div><h2>群发任务</h2><p>选择已同步群聊，文本支持换行，也可以附加图片。每分钟最多 5 个群。</p></div><button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div><section className="panel form-panel"><div className="panel-heading"><div><div className="panel-kicker">NEW TASK</div><h3>创建群发任务</h3></div></div><form className="broadcast-form" onSubmit={(event) => void create(event)}><label className="field"><span>任务名称</span><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：活动通知" required /></label><label className="field field-wide"><span>目标群聊</span><select multiple value={groups.split(/[,，\s]+/).filter(Boolean)} onChange={(event) => setGroups(Array.from(event.target.selectedOptions, (option) => option.value).join(","))}>{groupOptions.map((group) => <option key={group.group_id} value={group.group_id}>{group.name || "未命名群"} · {group.group_id}</option>)}</select><small>按住 Ctrl/⌘ 可多选</small></label><label className="field field-wide"><span>消息内容</span><textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="支持换行" rows={4} /></label><label className="field"><span>插入图片</span><input type="file" accept="image/jpeg,image/png,image/gif,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file).catch((reason) => onError(reason instanceof Error ? reason.message : "图片上传失败")); }} />{images.map((image) => <span key={image} className="message-image"><img src={image} alt="待发送图片" /><button type="button" className="icon-button" onClick={() => setImages((current) => current.filter((item) => item !== image))}><X size={14} /></button></span>)}</label><label className="field"><span>群间延时（秒）</span><input type="number" min={12} max={60} value={interval} onChange={(event) => setInterval(Number(event.target.value))} /></label><button className="button primary"><Send size={15} />创建任务</button></form></section><section className="panel table-panel"><div className="panel-heading"><div><div className="panel-kicker">TASKS</div><h3>任务进度</h3></div><span className="muted">{tasks.length} 个任务</span></div>{tasks.length === 0 ? <div className="empty-state"><div className="empty-icon"><Send size={22} /></div><strong>暂无群发任务</strong><span>创建任务后，进度会显示在这里。</span></div> : <div className="table-wrap"><table><thead><tr><th>任务</th><th>状态</th><th>进度</th><th>创建时间</th></tr></thead><tbody>{tasks.map((task) => <tr key={task.id}><td><strong>{task.title}</strong><small>{task.id.slice(0, 8)}</small></td><td>{task.status}</td><td>{task.sent_count}/{task.total_count}{task.failed_count ? ` · 失败 ${task.failed_count}` : ""}</td><td className="nowrap">{new Date(task.created_at).toLocaleString("zh-CN", { hour12: false })}</td></tr>)}</tbody></table></div>}</section></section>;
}

function PlaceholderPage({ active }: { active: string }) {
  return <section className="content"><div className="placeholder panel"><div className="empty-icon"><Settings2 size={22} /></div><h2>{active}</h2><p>这一页的 API 和交互将在下一轮接入，当前导航和运行状态已经可用。</p></div></section>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
