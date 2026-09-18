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
type Destination = { id: number; kind: "qq" | "email"; address: string; display_name: string; enabled: number; group_ids: string[] };
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
        {active === "系统设置" && <SystemSettingsPage onError={setError} />}
        {!(["Dashboard", "关键词", "历史记录", "登录与 NapCat", "运行日志", "通知", "群发任务", "系统设置"] as string[]).includes(active) && <PlaceholderPage active={active} />}
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
        <BroadcastCountCard />
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

function BroadcastCountCard() {
  const [count, setCount] = useState("0");
  useEffect(() => { void apiJson<BroadcastTask[]>("/api/broadcast-tasks?limit=200").then((tasks) => setCount(String(tasks.filter((task) => ["queued", "running"].includes(task.status)).length))).catch(() => undefined); }, []);
  return <StatCard icon={<Send size={18} />} label="群发任务" value={count} detail="排队或执行中" tone="violet" />;
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

function GroupCard({ group, selected, onClick }: { group: Group; selected: boolean; onClick: () => void }) {
  const initial = (group.name || group.group_id).slice(0, 1).toUpperCase();
  return <button type="button" className={selected ? "group-card selected" : "group-card"} onClick={onClick}>
    {group.avatar_url ? <img src={group.avatar_url} alt="" /> : <span className="group-avatar-fallback">{initial}</span>}
    <span className="group-card-copy"><strong>{group.name || "未命名群"}</strong><small>{group.group_id}</small></span>
    <span className={selected ? "group-check checked" : "group-check"}>{selected ? "✓" : ""}</span>
  </button>;
}

function GroupPicker({ groups, selected, onChange, single = false }: { groups: Group[]; selected: string[]; onChange: (ids: string[]) => void; single?: boolean }) {
  if (!groups.length) return <div className="group-picker-empty">暂无群聊。请确认 NapCat 已登录并等待 OneBot 同步。</div>;
  return <div className="group-picker">{groups.map((group) => <GroupCard key={group.group_id} group={group} selected={selected.includes(group.group_id)} onClick={() => {
    if (single) onChange([group.group_id]);
    else onChange(selected.includes(group.group_id) ? selected.filter((id) => id !== group.group_id) : [...selected, group.group_id]);
  }} />)}</div>;
}

function KeywordPage({ onError }: { onError: (message: string) => void }) {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [text, setText] = useState("");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [keywordOpen, setKeywordOpen] = useState(false);
  const [keywordStep, setKeywordStep] = useState<1 | 2>(1);
  const [editingKeyword, setEditingKeyword] = useState<Keyword | null>(null);
  const [groupSearch, setGroupSearch] = useState("");
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

  const openKeyword = (keyword: Keyword | null = null) => {
    setEditingKeyword(keyword); setText(keyword?.display_text || ""); setGroupIds(keyword?.bindings.map((binding) => binding.group_id) || []); setEnabled(keyword ? keyword.bindings.some((binding) => Boolean(binding.enabled)) : true); setGroupSearch(""); setKeywordStep(1); setKeywordOpen(true);
  };
  const saveKeyword = async () => {
    if (!text.trim() || !groupIds.length) { onError("请输入关键词并至少选择一个应用群聊"); return; }
    setBusy(true);
    try {
      if (editingKeyword) {
        await apiJson(`/api/keywords/${editingKeyword.id}`, { method: "PATCH", body: JSON.stringify({ display_text: text, enabled }) });
        await apiJson("/api/keywords/bulk-apply", { method: "POST", body: JSON.stringify({ keyword_id: editingKeyword.id, group_ids: groupIds, enabled, cooldown_seconds: 60, replace_existing: true }) });
      } else {
        await apiJson("/api/keywords", { method: "POST", body: JSON.stringify({ display_text: text, group_ids: groupIds, enabled }) });
      }
      setKeywordOpen(false); setText(""); setGroupIds([]); await load();
    } catch (reason) { onError(reason instanceof Error ? reason.message : "关键词保存失败"); } finally { setBusy(false); }
  };

  const removeKeyword = async (id: number) => {
    try { await apiJson(`/api/keywords/${id}`, { method: "DELETE" }); await load(); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "删除失败"); }
  };

  return <section className="content">
    <div className="welcome-row"><div><h2>关键词规则</h2><p>添加关键词后，再选择应用群聊；每个关键词独立管理。</p></div><div className="row-actions"><button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />刷新</button><button className="button primary" onClick={() => openKeyword()}><KeyRound size={15} />添加关键词</button></div></div>
    {keywordOpen && <div className="wizard-overlay"><section className="panel wizard-card keyword-wizard"><div className="wizard-head"><div><div className="panel-kicker">STEP {keywordStep} OF 2</div><h3>{editingKeyword ? "编辑关键词" : "添加关键词"}</h3></div><button className="icon-button" onClick={() => setKeywordOpen(false)}><X size={16} /></button></div>{keywordStep === 1 ? <><p className="wizard-help">输入要匹配的普通文本，系统会自动按字面内容匹配。</p><label className="field"><span>关键词</span><input autoFocus value={text} onChange={(event) => setText(event.target.value)} placeholder="例如：报名、紧急通知" maxLength={200} /></label><label className="check-field"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />启用这个关键词</label><div className="wizard-actions"><button className="button primary" onClick={() => setKeywordStep(2)} disabled={!text.trim()}>下一步：选择应用群聊<ChevronRight size={15} /></button></div></> : <><p className="wizard-help">搜索并勾选要应用这个关键词的群聊，可一次选择多个。</p><label className="search-field"><span>⌕</span><input value={groupSearch} onChange={(event) => setGroupSearch(event.target.value)} placeholder="搜索群名称或群号" /></label><GroupPicker groups={groups.filter((group) => `${group.name} ${group.group_id}`.toLowerCase().includes(groupSearch.toLowerCase()))} selected={groupIds} onChange={setGroupIds} /><div className="wizard-actions"><button className="button secondary" onClick={() => setKeywordStep(1)}>上一步</button><button className="button primary" onClick={() => void saveKeyword()} disabled={busy || !groupIds.length}>{busy ? "保存中" : "保存关键词"}</button></div></>}</section></div>}
    <section className="panel table-panel"><div className="panel-heading"><div><div className="panel-kicker">CONFIGURED</div><h3>已配置关键词</h3></div><span className="muted">{keywords.length} 条</span></div>{keywords.length === 0 ? <div className="empty-state"><div className="empty-icon"><KeyRound size={22} /></div><strong>还没有关键词</strong><span>点击“添加关键词”开始配置。</span></div> : <div className="keyword-list">{keywords.map((keyword) => { const active = keyword.bindings.some((binding) => Boolean(binding.enabled)); const names = keyword.bindings.map((binding) => groups.find((group) => group.group_id === binding.group_id)?.name || binding.group_id); return <div className="keyword-row" key={keyword.id}><div className="keyword-main"><span className="keyword-badge">{keyword.display_text.slice(0, 1)}</span><div><strong>{keyword.display_text}</strong><small>应用群聊：{names.join("、") || "未绑定"}</small></div></div><span className="keyword-count">{names.length} 个群</span><label className="switch"><input type="checkbox" checked={active} onChange={() => void apiJson(`/api/keywords/${keyword.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !active }) }).then(load).catch((reason) => onError(reason instanceof Error ? reason.message : "关键词开关保存失败"))} /><span /></label><button className="button ghost compact-button" onClick={() => openKeyword(keyword)}>编辑</button><button className="icon-button danger-button" onClick={() => void removeKeyword(keyword.id)} aria-label={`删除 ${keyword.display_text}`}><X size={16} /></button></div>; })}</div>}</section>
  </section>;
}

function HistoryPage({ onError }: { onError: (message: string) => void }) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [groups, setGroups] = useState<Group[]>([]);
  const [selectedGroup, setSelectedGroup] = useState<string[]>([]);
  const load = async () => {
    try { const query = selectedGroup[0] ? `&group_id=${encodeURIComponent(selectedGroup[0])}` : ""; const data = await apiJson<{ items: HistoryItem[]; total: number }>(`/api/history?limit=100${query}`); setItems(data.items); setTotal(data.total); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "历史记录加载失败"); }
  };
  useEffect(() => { void apiJson<Group[]>("/api/groups").then(setGroups).catch((reason) => onError(reason instanceof Error ? reason.message : "群聊加载失败")); }, []);
  useEffect(() => { void load(); }, [selectedGroup]);
  return <section className="content">
    <div className="welcome-row"><div><h2>历史记录</h2><p>关键词命中会保留群、发送者和原始文本。</p></div><button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div>
    <section className="panel form-panel history-filter"><div className="panel-heading"><div><div className="panel-kicker">FILTER</div><h3>按群聊查看</h3></div><button className="button ghost" onClick={() => setSelectedGroup([])}>全部群聊</button></div><GroupPicker groups={groups} selected={selectedGroup} onChange={setSelectedGroup} single /></section>
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
    try { const response = await fetch(`/api/ops/logs/${service}?tail=200`, { credentials: "include" }); if (!response.ok) throw new Error("日志读取失败"); setLogs(await response.text()); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "日志读取失败"); }
  };
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 5000); return () => window.clearInterval(timer); }, [service]);
  return <section className="content"><div className="welcome-row"><div><h2>运行日志</h2><p>查看 NoneBot 和 NapCat 最近输出，日志来源由后端控制。</p></div><button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div><section className="panel logs-panel"><div className="log-tabs"><button className={service === "nonebot" ? "log-tab active" : "log-tab"} onClick={() => setService("nonebot")}>NoneBot</button><button className={service === "napcat" ? "log-tab active" : "log-tab"} onClick={() => setService("napcat")}>NapCat</button></div><pre className="log-output">{logs}</pre></section></section>;
}

function NotificationsPage({ onError }: { onError: (message: string) => void }) {
  const [items, setItems] = useState<Destination[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<1 | 2>(1);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [qqChecked, setQqChecked] = useState(false);
  const [emailChecked, setEmailChecked] = useState(false);
  const [qqAddress, setQqAddress] = useState("");
  const [qqName, setQqName] = useState("");
  const [emailAddress, setEmailAddress] = useState("");
  const [emailName, setEmailName] = useState("");
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const [groupSearch, setGroupSearch] = useState("");
  const load = async () => { try { const [destinations, groupData] = await Promise.all([apiJson<Destination[]>("/api/destinations"), apiJson<Group[]>("/api/groups")]); setItems(destinations); setGroups(groupData); } catch (reason) { onError(reason instanceof Error ? reason.message : "通知配置读取失败"); } };
  useEffect(() => { void load(); }, []);
  const reset = () => { setOpen(true); setStep(1); setEditingId(null); setQqChecked(false); setEmailChecked(false); setQqAddress(""); setQqName(""); setEmailAddress(""); setEmailName(""); setSelectedGroups([]); setGroupSearch(""); };
  const edit = (item: Destination) => { setOpen(true); setStep(1); setEditingId(item.id); setQqChecked(item.kind === "qq"); setEmailChecked(item.kind === "email"); setQqAddress(item.kind === "qq" ? item.address : ""); setQqName(item.kind === "qq" ? item.display_name : ""); setEmailAddress(item.kind === "email" ? item.address : ""); setEmailName(item.kind === "email" ? item.display_name : ""); setSelectedGroups(item.group_ids); setGroupSearch(""); };
  const save = async () => {
    try {
      if (!selectedGroups.length) throw new Error("请至少选择一个应用群聊");
      if (editingId !== null) {
        const kind = qqChecked ? "qq" : "email";
        const address = qqChecked ? qqAddress : emailAddress;
        const display_name = qqChecked ? qqName : emailName;
        await apiJson(`/api/destinations/${editingId}`, { method: "PUT", body: JSON.stringify({ kind, address, display_name, enabled: true, group_ids: selectedGroups }) });
      } else {
        const channels = []; if (qqChecked) channels.push({ kind: "qq", address: qqAddress, display_name: qqName }); if (emailChecked) channels.push({ kind: "email", address: emailAddress, display_name: emailName });
        if (!channels.length) throw new Error("请至少选择 QQ 或邮箱一种提醒方式");
        await apiJson("/api/notification-configs", { method: "POST", body: JSON.stringify({ channels, group_ids: selectedGroups }) });
      }
      setOpen(false); await load();
    } catch (reason) { onError(reason instanceof Error ? reason.message : "提醒配置保存失败"); }
  };
  const toggle = async (item: Destination) => { try { await apiJson(`/api/destinations/${item.id}`, { method: "PUT", body: JSON.stringify({ kind: item.kind, address: item.address, display_name: item.display_name, enabled: !Boolean(item.enabled), group_ids: item.group_ids }) }); await load(); } catch (reason) { onError(reason instanceof Error ? reason.message : "提醒开关保存失败"); } };
  const remove = async (id: number) => { try { await apiJson(`/api/destinations/${id}`, { method: "DELETE" }); await load(); } catch (reason) { onError(reason instanceof Error ? reason.message : "删除提醒失败"); } };
  const visibleGroups = groups.filter((group) => `${group.name} ${group.group_id}`.toLowerCase().includes(groupSearch.toLowerCase()));
  return <section className="content"><div className="welcome-row"><div><h2>提醒设置</h2><p>先选择 QQ/邮箱提醒方式，再选择应用群聊，保存后即可触发通知。</p></div><div className="row-actions"><button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />刷新</button><button className="button primary" onClick={reset}><Bell size={15} />添加提醒</button></div></div>
    {open && <div className="wizard-overlay"><section className="panel form-panel wizard-card"><div className="wizard-head"><div><div className="panel-kicker">STEP {step} OF 2</div><h3>{editingId === null ? "添加提醒" : "编辑提醒"}</h3></div><button className="icon-button" onClick={() => setOpen(false)}><X size={16} /></button></div>{step === 1 ? <><p className="wizard-help">选择提醒方式。勾选后填写对应地址和备注。</p><div className="channel-grid"><div className={qqChecked ? "channel-card selected" : "channel-card"} onClick={() => setQqChecked((value) => !value)}><div className="channel-title"><span className="channel-icon">Q</span><strong>QQ 好友</strong><input type="checkbox" checked={qqChecked} onChange={() => setQqChecked((value) => !value)} onClick={(event) => event.stopPropagation()} /></div>{qqChecked && <div className="channel-fields"><label className="field"><span>QQ 号</span><input value={qqAddress} onChange={(event) => setQqAddress(event.target.value)} placeholder="例如 2890207721" /></label><label className="field"><span>备注</span><input value={qqName} onChange={(event) => setQqName(event.target.value)} placeholder="例如管理员" /></label></div>}</div><div className={emailChecked ? "channel-card selected" : "channel-card"} onClick={() => setEmailChecked((value) => !value)}><div className="channel-title"><span className="channel-icon">@</span><strong>邮箱</strong><input type="checkbox" checked={emailChecked} onChange={() => setEmailChecked((value) => !value)} onClick={(event) => event.stopPropagation()} /></div>{emailChecked && <div className="channel-fields"><label className="field"><span>邮箱地址</span><input value={emailAddress} onChange={(event) => setEmailAddress(event.target.value)} placeholder="name@example.com" /></label><label className="field"><span>备注</span><input value={emailName} onChange={(event) => setEmailName(event.target.value)} placeholder="例如运营邮箱" /></label></div>}</div></div><div className="wizard-actions"><button className="button primary" onClick={() => setStep(2)} disabled={editingId === null && !qqChecked && !emailChecked}>下一步：选择应用群聊<ChevronRight size={15} /></button></div></> : <><p className="wizard-help">搜索并勾选需要接收提醒的群聊。</p><label className="search-field"><span>⌕</span><input value={groupSearch} onChange={(event) => setGroupSearch(event.target.value)} placeholder="搜索群名称或群号" /></label><GroupPicker groups={visibleGroups} selected={selectedGroups} onChange={setSelectedGroups} /><div className="wizard-actions"><button className="button secondary" onClick={() => setStep(1)}>上一步</button><button className="button primary" onClick={() => void save()} disabled={!selectedGroups.length}>保存提醒配置</button></div></>}</section></div>}
    <section className="panel table-panel"><div className="panel-heading"><div><div className="panel-kicker">CONFIGURED</div><h3>已配置提醒</h3></div><span className="muted">{items.length} 条</span></div>{items.length === 0 ? <div className="empty-state"><div className="empty-icon"><Bell size={22} /></div><strong>还没有提醒配置</strong><span>添加 QQ 或邮箱后，在这里管理应用群和开关。</span></div> : <div className="reminder-list">{items.map((item) => <div className="reminder-row" key={item.id}><div className="channel-icon">{item.kind === "qq" ? "Q" : "@"}</div><div className="reminder-main"><strong>{item.display_name || (item.kind === "qq" ? "QQ 好友" : "邮箱提醒")}</strong><span>{item.address}</span><small>应用群：{item.group_ids.map((id) => groups.find((group) => group.group_id === id)?.name || id).join("、") || "未绑定"}</small></div><label className="switch"><input type="checkbox" checked={Boolean(item.enabled)} onChange={() => void toggle(item)} /><span /></label><button className="button ghost compact-button" onClick={() => edit(item)}>编辑</button><button className="icon-button danger-button" onClick={() => void remove(item.id)} aria-label="删除提醒"><X size={16} /></button></div>)}</div>}</section>
  </section>;
}

function BroadcastPage({ onError }: { onError: (message: string) => void }) {
  const [tasks, setTasks] = useState<BroadcastTask[]>([]);
  const [title, setTitle] = useState("");
  const [groups, setGroups] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [groupOptions, setGroupOptions] = useState<Group[]>([]);
  const [interval, setInterval] = useState(12);
  const load = async () => { try { setTasks(await apiJson<BroadcastTask[]>("/api/broadcast-tasks")); } catch (reason) { onError(reason instanceof Error ? reason.message : "群发任务读取失败"); } };
  useEffect(() => { void load(); void apiJson<Group[]>("/api/groups").then(setGroupOptions).catch(() => undefined); }, []);
  const create = async (event: React.FormEvent) => { event.preventDefault(); try { const segments: MessageSegment[] = []; if (message) segments.push({ type: "text", data: { text: message } }); images.forEach((file) => segments.push({ type: "image", data: { file } })); await apiJson("/api/broadcast-tasks", { method: "POST", body: JSON.stringify({ title, group_ids: groups, message: segments, interval_seconds: interval }) }); setTitle(""); setGroups([]); setMessage(""); setImages([]); await load(); } catch (reason) { onError(reason instanceof Error ? reason.message : "群发任务创建失败"); } };
  const upload = async (file: File) => { const data = new FormData(); data.append("file", file); const response = await fetch("/api/uploads/image", { method: "POST", credentials: "include", body: data }); const body = await response.json(); if (!response.ok) throw new Error(body.detail || "图片上传失败"); setImages((current) => [...current, body.url]); };
  return <section className="content"><div className="welcome-row"><div><h2>群发任务</h2><p>按群聊卡片选择目标，正文支持换行和图片。每分钟最多 5 个群。</p></div><button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div><section className="panel form-panel"><div className="panel-heading"><div><div className="panel-kicker">NEW TASK</div><h3>创建群发任务</h3></div></div><form className="broadcast-form" onSubmit={(event) => void create(event)}><label className="field"><span>任务名称</span><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：活动通知" required /></label><div className="field field-wide"><span>目标群聊</span><GroupPicker groups={groupOptions} selected={groups} onChange={setGroups} /><small>点击一行群聊卡片进行选择。</small></div><label className="field field-wide"><span>消息内容</span><textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="支持换行" rows={4} /></label><label className="field"><span>插入图片</span><input type="file" accept="image/jpeg,image/png,image/gif,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file).catch((reason) => onError(reason instanceof Error ? reason.message : "图片上传失败")); }} />{images.map((image) => <span key={image} className="message-image"><img src={image} alt="待发送图片" /><button type="button" className="icon-button" onClick={() => setImages((current) => current.filter((item) => item !== image))}><X size={14} /></button></span>)}</label><label className="field"><span>群间延时（秒）</span><input type="number" min={12} max={60} value={interval} onChange={(event) => setInterval(Number(event.target.value))} /></label><button className="button primary"><Send size={15} />创建任务</button></form></section><section className="panel table-panel"><div className="panel-heading"><div><div className="panel-kicker">TASKS</div><h3>任务进度</h3></div><span className="muted">{tasks.length} 个任务</span></div>{tasks.length === 0 ? <div className="empty-state"><div className="empty-icon"><Send size={22} /></div><strong>暂无群发任务</strong><span>创建任务后，进度会显示在这里。</span></div> : <div className="table-wrap"><table><thead><tr><th>任务</th><th>状态</th><th>进度</th><th>创建时间</th></tr></thead><tbody>{tasks.map((task) => <tr key={task.id}><td><strong>{task.title}</strong><small>{task.id.slice(0, 8)}</small></td><td>{task.status}</td><td>{task.sent_count}/{task.total_count}{task.failed_count ? ` · 失败 ${task.failed_count}` : ""}</td><td className="nowrap">{new Date(task.created_at).toLocaleString("zh-CN", { hour12: false })}</td></tr>)}</tbody></table></div>}</section></section>;
}

function PlaceholderPage({ active }: { active: string }) {
  return <section className="content"><div className="placeholder panel"><div className="empty-icon"><Settings2 size={22} /></div><h2>{active}</h2><p>这一页的 API 和交互将在下一轮接入，当前导航和运行状态已经可用。</p></div></section>;
}

function SystemSettingsPage({ onError }: { onError: (message: string) => void }) {
  const [smtp, setSmtp] = useState({ host: "", port: 587, username: "", from_address: "", password: "", starttls: true, ssl: false, timeout: 15 });
  const [onebot, setOnebot] = useState({ enable: false, url: "", reconnectInterval: 5000, heartInterval: 30000, verifyCertificate: true, token: "" });
  useEffect(() => { void Promise.all([apiJson<any>("/api/settings/smtp"), apiJson<any>("/api/settings/onebot")]).then(([s, o]) => { setSmtp((v) => ({ ...v, ...s })); setOnebot((v) => ({ ...v, ...(o.websocket_client || {}) })); }).catch((e) => onError(e instanceof Error ? e.message : "设置读取失败")); }, []);
  const save = async (path: string, value: unknown) => { try { await apiJson(path, { method: "PUT", body: JSON.stringify(value) }); } catch (e) { onError(e instanceof Error ? e.message : "保存失败"); } };
  return <section className="content"><div className="welcome-row"><div><h2>系统设置</h2><p>SMTP 邮件和 NapCat OneBot 反向连接配置。</p></div></div><section className="panel form-panel settings-card"><div className="panel-heading"><div><div className="panel-kicker">SMTP</div><h3>邮件发送</h3></div><span className="muted">每项独立一行填写</span></div><form className="settings-form" onSubmit={(e) => { e.preventDefault(); void save("/api/settings/smtp", smtp); }}><label className="field"><span>主机</span><input value={smtp.host} onChange={(e) => setSmtp({ ...smtp, host: e.target.value })} /></label><label className="field"><span>端口</span><input type="number" value={smtp.port} onChange={(e) => setSmtp({ ...smtp, port: Number(e.target.value) })} /></label><label className="field"><span>用户名</span><input value={smtp.username} onChange={(e) => setSmtp({ ...smtp, username: e.target.value })} /></label><label className="field"><span>密码</span><input type="password" value={smtp.password} onChange={(e) => setSmtp({ ...smtp, password: e.target.value })} /></label><label className="field"><span>发件地址</span><input value={smtp.from_address} onChange={(e) => setSmtp({ ...smtp, from_address: e.target.value })} /></label><label className="check-field"><input type="checkbox" checked={smtp.starttls} onChange={(e) => setSmtp({ ...smtp, starttls: e.target.checked })} />启用 STARTTLS</label><button className="button primary">保存 SMTP</button></form></section><section className="panel form-panel settings-card"><div className="panel-heading"><div><div className="panel-kicker">ONEBOT</div><h3>反向 WebSocket</h3></div><span className="muted">保存后按需重启 NapCat</span></div><form className="settings-form" onSubmit={(e) => { e.preventDefault(); void save("/api/settings/onebot", onebot); }}><label className="check-field"><input type="checkbox" checked={onebot.enable} onChange={(e) => setOnebot({ ...onebot, enable: e.target.checked })} />启用连接</label><label className="field field-wide"><span>URL</span><input value={onebot.url} onChange={(e) => setOnebot({ ...onebot, url: e.target.value })} placeholder="ws://nonebot:8081/onebot/v11/ws" /></label><label className="field"><span>Token</span><input type="password" value={onebot.token} onChange={(e) => setOnebot({ ...onebot, token: e.target.value })} /></label><button className="button primary">保存 OneBot 配置</button></form></section></section>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
