import {
  Bot,
  CircleAlert,
  FileText,
  KeyRound,
  LayoutDashboard,
  Menu,
  RefreshCw,
  Send,
  Settings2,
  ShieldCheck,
  TerminalSquare,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { fetchAuthMe } from "./api/auth";
import { getDashboard } from "./api/dashboard";
import { restartService } from "./api/ops";
import { StatusDot } from "./components/StatusDot";
import { BroadcastPage } from "./pages/BroadcastPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { KeywordPage } from "./pages/KeywordPage";
import { LoginPage } from "./pages/LoginPage";
import { LogsPage } from "./pages/LogsPage";
import { NapCatPage } from "./pages/NapCatPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { SystemSettingsPage } from "./pages/SystemSettingsPage";
import type { Dashboard, ServiceName } from "./types/api";
import { usePoll } from "./hooks/usePoll";

/** Sidebar entries. The first element is both the label and the page key. */
const NAV_ITEMS = [
  ["Dashboard", LayoutDashboard],
  ["关键词", KeyRound],
  ["历史记录", FileText],
  ["群发任务", Send],
  ["登录与 NapCat", ShieldCheck],
  ["运行日志", TerminalSquare],
  ["系统设置", Settings2],
] as const;

type PageKey = (typeof NAV_ITEMS)[number][0];

const PAGE_KEYS = NAV_ITEMS.map(([label]) => label) as readonly string[];

export function App() {
  const [active, setActive] = useState<PageKey>("Dashboard");
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
    void fetchAuthMe()
      .then(setAuthenticated)
      .catch(() => setAuthenticated(false));
  }, []);

  usePoll(refresh, 5000);

  if (authenticated === false) return <LoginPage onLogin={() => setAuthenticated(true)} />;

  const restart = async (service: ServiceName) => {
    setAction(service);
    try {
      await restartService(service);
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
      {mobileOpen && (
        <button className="scrim" onClick={() => setMobileOpen(false)} aria-label="关闭导航" />
      )}
      <aside className={mobileOpen ? "sidebar open" : "sidebar"}>
        <div className="brand">
          <div className="brand-mark">
            <Bot size={20} />
          </div>
          <div>
            <strong>QQ Bot</strong>
            <span>Control Plane</span>
          </div>
          <button
            className="icon-button mobile-close"
            onClick={() => setMobileOpen(false)}
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </div>
        <div className="sidebar-caption">管理台</div>
        <nav>
          {NAV_ITEMS.map(([label, Icon]) => (
            <button
              key={label}
              className={active === label ? "nav-item active" : "nav-item"}
              onClick={() => {
                setActive(label);
                setMobileOpen(false);
              }}
            >
              <Icon size={17} />
              <span>{label}</span>
              {label === "运行日志" && <span className="nav-pill">LIVE</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="connection-row">
            <StatusDot online={napcatOnline} />
            <span>{napcatOnline ? "NapCat 已连接" : "NapCat 待连接"}</span>
          </div>
          <div className="connection-row">
            <StatusDot online={Boolean(dashboard)} />
            <span>{dashboard ? "WebUI 正常" : "WebUI 离线"}</span>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            onClick={() => setMobileOpen(true)}
            aria-label="打开导航"
          >
            <Menu size={19} />
          </button>
          <div>
            <div className="eyebrow">QQ 群管理机器人</div>
            <h1>{active}</h1>
          </div>
          <div className="topbar-actions">
            <span className="revision">配置版本 {dashboard?.config_revision ?? "-"}</span>
            <button className="button secondary" onClick={() => void refresh()}>
              <RefreshCw size={15} />
              刷新
            </button>
          </div>
        </header>

        {error && (
          <div className="alert error">
            <CircleAlert size={17} />
            <span>{error}</span>
            <button className="icon-button" onClick={() => setError("")} aria-label="关闭错误">
              <X size={16} />
            </button>
          </div>
        )}

        {active === "Dashboard" && (
          <DashboardPage dashboard={dashboard} action={action} restart={restart} />
        )}
        {active === "关键词" && <KeywordPage onError={setError} />}
        {active === "历史记录" && <HistoryPage onError={setError} />}
        {active === "登录与 NapCat" && <NapCatPage onError={setError} />}
        {active === "运行日志" && <LogsPage onError={setError} />}
        {active === "群发任务" && <BroadcastPage onError={setError} />}
        {active === "系统设置" && <SystemSettingsPage onError={setError} />}
        {!PAGE_KEYS.includes(active) && <PlaceholderPage active={active} />}
      </main>
    </div>
  );
}