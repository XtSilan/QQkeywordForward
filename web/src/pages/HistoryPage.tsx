import { FileText, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { listGroups } from "../api/groups";
import { listHistory } from "../api/history";
import { EmptyState } from "../components/EmptyState";
import { GroupPicker } from "../components/GroupPicker";
import { NOTIFY_STATUS_LABEL, type Group, type HistoryItem } from "../types/api";

export function HistoryPage({ onError }: { onError: (message: string) => void }) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [groups, setGroups] = useState<Group[]>([]);
  const [selectedGroup, setSelectedGroup] = useState<string[]>([]);

  const load = async () => {
    try {
      const data = await listHistory(selectedGroup[0]);
      setItems(data.items);
      setTotal(data.total);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "历史记录加载失败");
    }
  };

  useEffect(() => {
    void listGroups()
      .then(setGroups)
      .catch((reason) => onError(reason instanceof Error ? reason.message : "群聊加载失败"));
  }, []);

  useEffect(() => {
    void load();
  }, [selectedGroup]);

  return (
    <section className="content">
      <div className="welcome-row">
        <div>
          <h2>历史记录</h2>
          <p>关键词命中会保留群、发送者和原始文本。</p>
        </div>
        <button className="button secondary" onClick={() => void load()}>
          <RefreshCw size={15} />
          刷新
        </button>
      </div>

      <section className="panel form-panel history-filter">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">FILTER</div>
            <h3>按群聊查看</h3>
          </div>
          <button className="button ghost" onClick={() => setSelectedGroup([])}>
            全部群聊
          </button>
        </div>
        <GroupPicker groups={groups} selected={selectedGroup} onChange={setSelectedGroup} single />
      </section>

      <section className="panel table-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">HISTORY</div>
            <h3>关键词命中</h3>
          </div>
          <span className="muted">共 {total} 条</span>
        </div>

        {items.length === 0 ? (
          <EmptyState
            icon={<FileText size={22} />}
            title="暂无命中记录"
            hint="机器人识别到关键词后会显示在这里。"
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>群聊</th>
                  <th>发送者</th>
                  <th>命中</th>
                  <th>消息</th>
                  <th>提醒状态</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td className="nowrap">
                      {new Date(item.hit_at).toLocaleString("zh-CN", { hour12: false })}
                    </td>
                    <td>
                      <strong>{item.group_name || "未命名群"}</strong>
                      <small>{item.group_id}</small>
                    </td>
                    <td>
                      {item.sender_name || "未知"}
                      <small>{item.sender_id}</small>
                    </td>
                    <td>
                      <span className="keyword-tag">{item.keyword_text_snapshot}</span>
                    </td>
                    <td className="message-cell">{item.message_text || "（非文本消息）"}</td>
                    <td className="nowrap">
                      <span className={`notify-status ${item.notify_status}`}>
                        {NOTIFY_STATUS_LABEL[item.notify_status] || item.notify_status}
                      </span>
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