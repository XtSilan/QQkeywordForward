import { Bot, RotateCcw } from "lucide-react";

import { StatusDot } from "./StatusDot";

export function ServiceRow({
  name,
  description,
  online,
  busy,
  onRestart,
}: {
  name: string;
  description: string;
  online: boolean;
  busy: boolean;
  onRestart: () => void;
}) {
  return (
    <div className="service-row">
      <div className="service-icon">
        <Bot size={17} />
      </div>
      <div className="service-copy">
        <strong>{name}</strong>
        <span>{description}</span>
      </div>
      <div className={online ? "service-status online-text" : "service-status"}>
        <StatusDot online={online} />
        {online ? "运行中" : "待连接"}
      </div>
      <button className="button ghost" onClick={onRestart} disabled={busy}>
        <RotateCcw size={15} />
        {busy ? "处理中" : "重启"}
      </button>
    </div>
  );
}