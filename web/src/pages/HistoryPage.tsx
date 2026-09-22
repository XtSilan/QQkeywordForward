import { ChevronLeft, ChevronRight, FileText, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { listHistory } from "../api/history";
import { EmptyState } from "../components/EmptyState";
import { NOTIFY_STATUS_LABEL, type HistoryItem } from "../types/api";
import { useLiveSnapshot } from "../lib/live";

/** Rows per request; pagination is done server-side via limit/offset. */
const PAGE_SIZE = 20;

/** Read the 1-based page number from `?page=`, ignoring anything unusable. */
function readPage(raw: string | null): number {
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 1 ? parsed : 1;
}

/** The `YYYY-MM-DD` shape produced by `<input type="date">`. */
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** Read `?date=`; anything unusable means "the whole history". */
function readDate(raw: string | null): string {
  return raw && DATE_PATTERN.test(raw) ? raw : "";
}

/**
 * UTC bounds covering the picked *local* calendar day. The API filters on UTC
 * instants, so the browser's timezone is what decides where a day begins.
 */
function dayBounds(date: string): { since?: string; until?: string } {
  if (!DATE_PATTERN.test(date)) return {};
  const [year, month, day] = date.split("-").map(Number);
  return {
    since: new Date(year, month - 1, day).toISOString(),
    until: new Date(year, month - 1, day + 1).toISOString(),
  };
}

export function HistoryPage({ onError }: { onError: (message: string) => void }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = readPage(searchParams.get("page"));
  const date = readDate(searchParams.get("date"));
  const live = useLiveSnapshot();

  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [pageDraft, setPageDraft] = useState(String(page));

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Keep the page in the URL so back/forward and refreshes stay consistent.
  const goToPage = (next: number, replace = false) => {
    const params = new URLSearchParams(searchParams);
    if (next <= 1) params.delete("page");
    else params.set("page", String(next));
    setSearchParams(params, { replace });
  };

  const load = async () => {
    try {
      const data = await listHistory({
        ...dayBounds(date),
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "历史记录加载失败");
    }
  };

  useEffect(() => {
    void load();
  }, [page, date]);

  // The jump box mirrors the page that is actually loaded.
  useEffect(() => setPageDraft(String(page)), [page]);

  // A new hit changes the row count, so the current page is refetched.
  const liveHits = live?.hits.total;
  useEffect(() => {
    if (liveHits === undefined) return;
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveHits]);

  // Filtering or new records can leave the requested page past the end.
  useEffect(() => {
    if (total > 0 && page > pageCount) goToPage(pageCount, true);
  }, [total, page, pageCount]);

  /** Picking a day drops back to page 1; clearing it restores the full list. */
  const selectDate = (next: string) => {
    const params = new URLSearchParams(searchParams);
    if (next && DATE_PATTERN.test(next)) params.set("date", next);
    else params.delete("date");
    params.delete("page");
    setSearchParams(params, { replace: true });
  };

  const clearFilters = () => {
    const params = new URLSearchParams(searchParams);
    params.delete("date");
    params.delete("page");
    setSearchParams(params, { replace: true });
  };

  const jumpToPage = () => {
    const wanted = Number(pageDraft);
    if (!Number.isFinite(wanted)) {
      setPageDraft(String(page));
      return;
    }
    goToPage(Math.min(Math.max(1, Math.trunc(wanted)), pageCount));
  };

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
            <h3>筛选历史</h3>
          </div>
          <button className="button ghost" onClick={clearFilters}>
            全部历史
          </button>
        </div>
        <div className="history-date">
          <label className="field">
            <span>按日期筛选</span>
            <input
              type="date"
              value={date}
              onChange={(event) => selectDate(event.target.value)}
            />
          </label>
          <span className="muted">
            {date ? `只显示 ${date} 当天的命中（按本机时区）` : "未选日期时显示全部历史"}
          </span>
        </div>
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
          <>
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

            <div className="pager">
              <span className="muted">
                第 {page} / {pageCount} 页
              </span>
              <div className="pager-actions">
                <button
                  className="button ghost"
                  disabled={page <= 1}
                  onClick={() => goToPage(page - 1)}
                >
                  <ChevronLeft size={15} />
                  上一页
                </button>
                <label className="pager-jump">
                  <span>跳至</span>
                  <input
                    type="number"
                    min={1}
                    max={pageCount}
                    value={pageDraft}
                    onChange={(event) => setPageDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        jumpToPage();
                      }
                    }}
                  />
                  <span>页</span>
                </label>
                <button
                  className="button ghost"
                  disabled={page >= pageCount}
                  onClick={() => goToPage(page + 1)}
                >
                  下一页
                  <ChevronRight size={15} />
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </section>
  );
}