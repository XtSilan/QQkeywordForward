import { StrictMode, useEffect, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity, Bell, Bot, CheckCircle2, ChevronRight, CircleAlert, FileText,
  KeyRound, LayoutDashboard, Menu, MessageSquareText, RefreshCw, RotateCcw,
  Send, Settings2, ShieldCheck, TerminalSquare, Users, X
} from "lucide-react";
import "./style.css";

type Dashboard = {
  config_revision: number;
  napcat: { ok?: boolean; isLogin?: boolean; coreReady?: boolean; loginPhase?: string; error?: string };
  nonebot: { service: string; config_reload: boolean };
};

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
        {active === "Dashboard" ? <DashboardPage dashboard={dashboard} action={action} restart={restart} /> : <PlaceholderPage active={active} />}
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
        <StatCard icon={<MessageSquareText size={18} />} label="关键词命中" value="0" detail="今日累计" tone="blue" />
        <StatCard icon={<Send size={18} />} label="群发任务" value="0" detail="等待执行" tone="violet" />
        <StatCard icon={<Users size={18} />} label="配置群聊" value="-" detail="同步后显示" tone="slate" />
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

function PlaceholderPage({ active }: { active: string }) {
  return <section className="content"><div className="placeholder panel"><div className="empty-icon"><Settings2 size={22} /></div><h2>{active}</h2><p>这一页的 API 和交互将在下一轮接入，当前导航和运行状态已经可用。</p></div></section>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
