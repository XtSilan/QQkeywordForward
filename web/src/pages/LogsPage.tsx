import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { fetchLogs } from "../api/ops";
import type { LogService } from "../types/api";
import { usePoll } from "../hooks/usePoll";

export function LogsPage({ onError }: { onError: (message: string) => void }) {
  const [service, setService] = useState<LogService>("nonebot");
  const [logs, setLogs] = useState("正在加载日志...");
  const preRef = useRef<HTMLPreElement>(null);

  const load = async () => {
    try {
      setLogs(await fetchLogs(service, 200));
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "日志读取失败");
    }
  };

  usePoll(load, 5000, [service]);

  // 日志更新后自动滚到底部
  useEffect(() => {
    const el = preRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  return (
    <section className="content">
      <div className="welcome-row">
        <div>
          <h2>运行日志</h2>
          <p>查看 NoneBot 和 NapCat 最近输出，日志来源由后端控制。</p>
        </div>
        <button className="button secondary" onClick={() => void load()}>
          <RefreshCw size={15} />
          刷新
        </button>
      </div>

      <section className="panel logs-panel">
        <div className="log-tabs">
          <button
            className={service === "nonebot" ? "log-tab active" : "log-tab"}
            onClick={() => setService("nonebot")}
          >
            NoneBot
          </button>
          <button
            className={service === "napcat" ? "log-tab active" : "log-tab"}
            onClick={() => setService("napcat")}
          >
            NapCat
          </button>
        </div>
        <pre ref={preRef} className="log-output">{logs}</pre>
      </section>
    </section>
  );
}