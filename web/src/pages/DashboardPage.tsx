import { Activity, Bell, KeyRound, MessageSquareText, Send, ShieldCheck, Users } from "lucide-react";

import { BroadcastActivity } from "../components/BroadcastActivity";
import { QuickAction } from "../components/QuickAction";
import { ServiceRow } from "../components/ServiceRow";
import { StatCard } from "../components/StatCard";
import { StatusDot } from "../components/StatusDot";
import type { Dashboard, ServiceName } from "../types/api";

export function DashboardPage({
  dashboard,
  action,
  restart,
}: {
  dashboard: Dashboard | null;
  action: string;
  restart: (service: ServiceName) => Promise<void>;
}) {
  const online = Boolean(dashboard?.napcat?.coreReady || dashboard?.napcat?.isLogin);
  return (
    <section className="content">
      <div className="welcome-row">
        <div>
          <h2>运行概览</h2>
          <p>从这里检查连接状态、服务和近期操作。</p>
        </div>
        <div className={online ? "status-chip good" : "status-chip warn"}>
          <StatusDot online={online} />
          {online ? "QQ 在线" : "等待 QQ 登录"}
        </div>
      </div>

      <div className="stat-grid">
        <StatCard
          icon={<Activity size={18} />}
          label="NapCat"
          value={online ? "在线" : "未连接"}
          detail={dashboard?.napcat?.loginPhase || "等待状态"}
          tone="green"
        />
        <StatCard
          icon={<MessageSquareText size={18} />}
          label="关键词命中"
          value={String(dashboard?.stats?.keyword_hits_today ?? 0)}
          detail="今日累计"
          tone="blue"
        />
        <StatCard
          icon={<Bell size={18} />}
          label="今日已发送"
          value={`${dashboard?.stats?.alerts_sent_today ?? 0} 条`}
          detail="关键词提醒转发"
          tone="violet"
        />
        <StatCard
          icon={<Users size={18} />}
          label="配置群聊"
          value={String(dashboard?.stats?.groups ?? 0)}
          detail="已同步群聊"
          tone="slate"
        />
      </div>

      <div className="dashboard-grid">
        <section className="panel service-panel">
          <div className="panel-heading">
            <div>
              <div className="panel-kicker">SERVICES</div>
              <h3>服务控制</h3>
            </div>
            <span className="muted">受控操作</span>
          </div>
          <ServiceRow
            name="NapCat"
            description="QQ 登录、OneBot 连接与账号状态"
            online={online}
            busy={action === "napcat"}
            onRestart={() => void restart("napcat")}
          />
          <ServiceRow
            name="NoneBot"
            description="关键词监听、通知队列与群发调度"
            online={Boolean(dashboard)}
            busy={action === "nonebot"}
            onRestart={() => void restart("nonebot")}
          />
          <div className="callout">
            <ShieldCheck size={17} />
            <span>
              关键词和通知设置保存后会热加载；修改连接地址、依赖或环境变量时才需要重启 NoneBot。
            </span>
          </div>
        </section>

        <section className="panel activity-panel">
          <div className="panel-heading">
            <div>
              <div className="panel-kicker">ACTIVITY</div>
              <h3>最近动态</h3>
            </div>
            <span className="muted">群发任务进度</span>
          </div>
          <BroadcastActivity />
        </section>
      </div>

      <section className="panel quick-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">NEXT</div>
            <h3>开始配置</h3>
          </div>
        </div>
        <div className="quick-grid">
          <QuickAction icon={<KeyRound size={17} />} title="添加关键词" detail="配置群级匹配规则" />
          <QuickAction icon={<Bell size={17} />} title="配置关键词提醒" detail="关键词、群聊和提醒地址" />
          <QuickAction icon={<Send size={17} />} title="创建群发任务" detail="选择群聊并安排发送" />
          <QuickAction icon={<ShieldCheck size={17} />} title="打开登录页" detail="查看二维码和登录状态" />
        </div>
      </section>
    </section>
  );
}