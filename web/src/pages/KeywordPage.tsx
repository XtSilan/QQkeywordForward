import { ChevronRight, KeyRound, RefreshCw, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  bulkApplyKeyword,
  bulkDeleteKeywords,
  bulkToggleKeywords,
  createKeywordConfig,
  createNotificationConfig,
  deleteKeyword,
  listKeywords,
  reorderKeywords,
  updateKeyword,
  updateKeywordNotifications,
} from "../api/keywords";
import { listGroups } from "../api/groups";
import { listDestinations } from "../api/notifications";
import { DestinationPicker } from "../components/DestinationPicker";
import { EmptyState } from "../components/EmptyState";
import { GroupPicker } from "../components/GroupPicker";
import { parseList } from "../lib/parse";
import type { Destination, Group, Keyword } from "../types/api";

/** How many bound group names to show before collapsing into "+N 个". */
const GROUP_NAME_PREVIEW = 3;

type WizardStep = 1 | 2 | 3;

export function KeywordPage({ onError }: { onError: (message: string) => void }) {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [destinations, setDestinations] = useState<Destination[]>([]);

  const [text, setText] = useState("");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [destinationIds, setDestinationIds] = useState<number[]>([]);
  const [newQqAddresses, setNewQqAddresses] = useState("");
  const [newEmailAddresses, setNewEmailAddresses] = useState("");
  const [newDestinationName, setNewDestinationName] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [keywordOpen, setKeywordOpen] = useState(false);
  const [keywordStep, setKeywordStep] = useState<WizardStep>(1);
  const [editingKeyword, setEditingKeyword] = useState<Keyword | null>(null);
  const [groupSearch, setGroupSearch] = useState("");
  const [keywordSearch, setKeywordSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [dragId, setDragId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [keywordData, groupData, destinationData] = await Promise.all([
        listKeywords(),
        listGroups(),
        listDestinations(),
      ]);
      setKeywords(keywordData);
      setGroups(groupData);
      setDestinations(destinationData.filter((item) => Boolean(item.enabled)));
      setSelectedIds((current) => current.filter((id) => keywordData.some((item) => item.id === id)));
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "关键词加载失败");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const openKeyword = (keyword: Keyword | null = null) => {
    setEditingKeyword(keyword);
    setText(keyword?.display_text || "");
    setGroupIds(keyword?.bindings.map((binding) => binding.group_id) || []);
    setDestinationIds(keyword?.destination_ids || []);
    setNewQqAddresses("");
    setNewEmailAddresses("");
    setNewDestinationName("");
    setEnabled(keyword ? keyword.bindings.some((binding) => Boolean(binding.enabled)) : true);
    setGroupSearch("");
    setKeywordStep(1);
    setKeywordOpen(true);
  };

  const saveKeyword = async () => {
    const parsed = parseList(text);
    if (!parsed.length || !groupIds.length) {
      onError("请输入关键词并至少选择一个应用群聊");
      return;
    }
    if (editingKeyword && parsed.length !== 1) {
      onError("编辑已有关键词时请只保留一个关键词；新增时可以一次输入多个");
      return;
    }
    setBusy(true);
    try {
      const channels = [
        ...parseList(newQqAddresses).map((address, index) => ({
          kind: "qq" as const,
          address,
          display_name: newDestinationName || `QQ 提醒 ${index + 1}`,
        })),
        ...parseList(newEmailAddresses).map((address, index) => ({
          kind: "email" as const,
          address,
          display_name: newDestinationName || `邮箱提醒 ${index + 1}`,
        })),
      ];
      let finalDestinationIds = [...destinationIds];
      if (channels.length) {
        const created = await createNotificationConfig(channels, groupIds);
        finalDestinationIds = Array.from(new Set([...finalDestinationIds, ...created.destination_ids]));
      }
      if (!finalDestinationIds.length) throw new Error("请至少选择或填写一个 QQ/邮箱提醒地址");

      if (editingKeyword) {
        await updateKeyword(editingKeyword.id, { display_text: parsed[0], enabled });
        await bulkApplyKeyword({
          keyword_id: editingKeyword.id,
          group_ids: groupIds,
          enabled,
          cooldown_seconds: 60,
          replace_existing: true,
        });
        await updateKeywordNotifications(editingKeyword.id, finalDestinationIds);
      } else {
        await createKeywordConfig({
          keywords: parsed,
          group_ids: groupIds,
          destination_ids: finalDestinationIds,
          enabled,
          cooldown_seconds: 60,
        });
      }
      setKeywordOpen(false);
      setText("");
      setGroupIds([]);
      setDestinationIds([]);
      setNewQqAddresses("");
      setNewEmailAddresses("");
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "关键词保存失败");
    } finally {
      setBusy(false);
    }
  };

  const removeKeyword = async (id: number) => {
    try {
      await deleteKeyword(id);
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "删除失败");
    }
  };

  const toggleKeywordEnabled = async (keyword: Keyword, active: boolean) => {
    try {
      await updateKeyword(keyword.id, { enabled: !active });
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "关键词开关保存失败");
    }
  };

  const visibleGroups = groups.filter((group) =>
    `${group.name} ${group.group_id}`.toLowerCase().includes(groupSearch.toLowerCase()),
  );
  const filteredKeywords = keywords.filter((keyword) =>
    keyword.display_text.toLowerCase().includes(keywordSearch.toLowerCase()),
  );
  const allFilteredSelected =
    filteredKeywords.length > 0 && filteredKeywords.every((keyword) => selectedIds.includes(keyword.id));
  const toggleAll = () =>
    setSelectedIds(allFilteredSelected ? [] : filteredKeywords.map((keyword) => keyword.id));
  const toggleOne = (id: number) =>
    setSelectedIds((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );

  const bulkToggle = async (nextEnabled: boolean) => {
    if (!selectedIds.length) return;
    try {
      await bulkToggleKeywords(selectedIds, nextEnabled);
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "批量操作失败");
    }
  };

  const bulkDelete = async () => {
    if (!selectedIds.length) return;
    if (!window.confirm(`确认删除选中的 ${selectedIds.length} 个关键词？`)) return;
    try {
      await bulkDeleteKeywords(selectedIds);
      setSelectedIds([]);
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "批量删除失败");
    }
  };

  const reorderAz = async () => {
    try {
      await reorderKeywords([], true);
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "A-Z 排序失败");
    }
  };

  const dropRow = async (targetId: number) => {
    if (dragId === null || dragId === targetId) {
      setDragId(null);
      return;
    }
    const ordered = [...filteredKeywords];
    const fromIndex = ordered.findIndex((item) => item.id === dragId);
    const toIndex = ordered.findIndex((item) => item.id === targetId);
    if (fromIndex === -1 || toIndex === -1) {
      setDragId(null);
      return;
    }
    const [moved] = ordered.splice(fromIndex, 1);
    ordered.splice(toIndex, 0, moved);
    const newIds = ordered.map((item) => item.id);
    // Optimistically reorder locally so the drop feels instant; the request
    // below persists it.
    setKeywords((current) => {
      const selected = current.filter((item) => newIds.includes(item.id));
      const rest = current.filter((item) => !newIds.includes(item.id));
      const map = new Map(selected.map((item) => [item.id, item]));
      const reordered = newIds.map((id) => map.get(id)!);
      return [...reordered, ...rest];
    });
    setDragId(null);
    try {
      await reorderKeywords(newIds, false);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "排序保存失败");
    }
  };

  const canSubmitWizard =
    !busy && (destinationIds.length > 0 || Boolean(newQqAddresses.trim()) || Boolean(newEmailAddresses.trim()));

  return (
    <section className="content">
      <div className="welcome-row">
        <div>
          <h2>关键词规则</h2>
          <p>一次输入多个关键词，再统一选择群聊和提醒地址。</p>
        </div>
        <div className="row-actions">
          <button className="button secondary" onClick={() => void load()}>
            <RefreshCw size={15} />
            刷新
          </button>
          <button className="button primary" onClick={() => openKeyword()}>
            <KeyRound size={15} />
            添加关键词
          </button>
        </div>
      </div>

      {keywordOpen && (
        <div className="wizard-overlay">
          <section className="panel wizard-card keyword-wizard">
            <div className="wizard-head">
              <div>
                <div className="panel-kicker">STEP {keywordStep} OF 3</div>
                <h3>{editingKeyword ? "编辑关键词" : "添加关键词"}</h3>
              </div>
              <button className="icon-button" onClick={() => setKeywordOpen(false)}>
                <X size={16} />
              </button>
            </div>

            {keywordStep === 1 && (
              <>
                <p className="wizard-help">
                  每行一个，也可以使用中文逗号、英文逗号或空格分隔。Shift + Enter 可继续换行。
                </p>
                <label className="field">
                  <span>关键词列表</span>
                  <textarea
                    autoFocus
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                    placeholder={editingKeyword ? "例如：报名" : "报名\n紧急通知，活动通知"}
                    rows={7}
                  />
                </label>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(event) => setEnabled(event.target.checked)}
                  />
                  启用这些关键词
                </label>
                <div className="wizard-actions">
                  <button
                    className="button primary"
                    onClick={() => setKeywordStep(2)}
                    disabled={!parseList(text).length}
                  >
                    下一步：选择应用群聊
                    <ChevronRight size={15} />
                  </button>
                </div>
              </>
            )}

            {keywordStep === 2 && (
              <>
                <p className="wizard-help">搜索并勾选这些关键词要监听的群聊。</p>
                <label className="search-field">
                  <span>⌕</span>
                  <input
                    value={groupSearch}
                    onChange={(event) => setGroupSearch(event.target.value)}
                    placeholder="搜索群名称或群号"
                  />
                </label>
                <GroupPicker groups={visibleGroups} selected={groupIds} onChange={setGroupIds} />
                <div className="wizard-actions">
                  <button className="button secondary" onClick={() => setKeywordStep(1)}>
                    上一步
                  </button>
                  <button
                    className="button primary"
                    onClick={() => setKeywordStep(3)}
                    disabled={!groupIds.length}
                  >
                    下一步：选择提醒
                    <ChevronRight size={15} />
                  </button>
                </div>
              </>
            )}

            {keywordStep === 3 && (
              <>
                <p className="wizard-help">
                  勾选已有提醒地址，或直接填写新的 QQ/邮箱。多个地址可用换行、逗号或空格分隔。
                </p>
                <DestinationPicker
                  destinations={destinations}
                  selected={destinationIds}
                  onChange={setDestinationIds}
                />
                <div className="inline-destination-form">
                  <label className="field">
                    <span>新增 QQ 号（可多个）</span>
                    <textarea
                      rows={3}
                      value={newQqAddresses}
                      onChange={(event) => setNewQqAddresses(event.target.value)}
                      placeholder="2890207721, 123456789"
                    />
                  </label>
                  <label className="field">
                    <span>新增邮箱（可多个）</span>
                    <textarea
                      rows={3}
                      value={newEmailAddresses}
                      onChange={(event) => setNewEmailAddresses(event.target.value)}
                      placeholder="name@example.com ops@example.com"
                    />
                  </label>
                  <label className="field destination-note">
                    <span>备注（选填）</span>
                    <input
                      value={newDestinationName}
                      onChange={(event) => setNewDestinationName(event.target.value)}
                      placeholder="例如：管理员"
                    />
                  </label>
                </div>
                <div className="wizard-actions">
                  <button className="button secondary" onClick={() => setKeywordStep(2)}>
                    上一步
                  </button>
                  <button
                    className="button primary"
                    onClick={() => void saveKeyword()}
                    disabled={!canSubmitWizard}
                  >
                    {busy ? "保存中" : "保存关键词与提醒"}
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      )}

      <section className="panel table-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">CONFIGURED</div>
            <h3>已配置关键词</h3>
          </div>
          <span className="muted">
            {keywords.length} 条
            {filteredKeywords.length !== keywords.length ? ` · 筛选后 ${filteredKeywords.length} 条` : ""}
          </span>
        </div>

        {keywords.length === 0 ? (
          <EmptyState
            icon={<KeyRound size={22} />}
            title="还没有关键词"
            hint="点击“添加关键词”开始配置。"
          />
        ) : (
          <>
            <div className="list-toolbar">
              <label className="search-field">
                <span>⌕</span>
                <input
                  value={keywordSearch}
                  onChange={(event) => setKeywordSearch(event.target.value)}
                  placeholder="搜索关键词"
                />
              </label>
              {selectedIds.length > 0 ? (
                <div className="bulk-actions">
                  <span className="muted">已选 {selectedIds.length} 项</span>
                  <button className="button secondary compact-button" onClick={() => void bulkToggle(true)}>
                    批量启用
                  </button>
                  <button className="button secondary compact-button" onClick={() => void bulkToggle(false)}>
                    批量禁用
                  </button>
                  <button className="button danger compact-button" onClick={() => void bulkDelete()}>
                    批量删除
                  </button>
                  <button className="button ghost compact-button" onClick={() => setSelectedIds([])}>
                    取消选择
                  </button>
                </div>
              ) : (
                <div className="bulk-actions">
                  <label className="check-field compact-check">
                    <input
                      type="checkbox"
                      checked={allFilteredSelected}
                      onChange={toggleAll}
                      disabled={filteredKeywords.length === 0}
                    />
                    全选当前
                  </label>
                  <button
                    className="button ghost compact-button"
                    onClick={() => void reorderAz()}
                    title="按 A-Z 重新排序"
                  >
                    A-Z 排序
                  </button>
                </div>
              )}
            </div>

            <div className="keyword-list">
              {filteredKeywords.map((keyword) => (
                <KeywordRow
                  key={keyword.id}
                  keyword={keyword}
                  groups={groups}
                  selected={selectedIds.includes(keyword.id)}
                  dragging={dragId === keyword.id}
                  dragEnabled={!keywordSearch}
                  onDragStart={() => setDragId(keyword.id)}
                  onDragOver={(event) => {
                    if (dragId !== null && dragId !== keyword.id) event.preventDefault();
                  }}
                  onDrop={() => void dropRow(keyword.id)}
                  onDragEnd={() => setDragId(null)}
                  onToggleSelect={() => toggleOne(keyword.id)}
                  onToggleEnabled={() =>
                    void toggleKeywordEnabled(
                      keyword,
                      keyword.bindings.some((binding) => Boolean(binding.enabled)),
                    )
                  }
                  onEdit={() => openKeyword(keyword)}
                  onDelete={() => void removeKeyword(keyword.id)}
                />
              ))}
            </div>
          </>
        )}
      </section>
    </section>
  );
}

function KeywordRow({
  keyword,
  groups,
  selected,
  dragging,
  dragEnabled,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onToggleSelect,
  onToggleEnabled,
  onEdit,
  onDelete,
}: {
  keyword: Keyword;
  groups: Group[];
  selected: boolean;
  dragging: boolean;
  dragEnabled: boolean;
  onDragStart: () => void;
  onDragOver: (event: React.DragEvent) => void;
  onDrop: () => void;
  onDragEnd: () => void;
  onToggleSelect: () => void;
  onToggleEnabled: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const active = keyword.bindings.some((binding) => Boolean(binding.enabled));
  const names = keyword.bindings.map(
    (binding) => groups.find((group) => group.group_id === binding.group_id)?.name || binding.group_id,
  );
  const notifyCount = keyword.destination_ids?.length || 0;
  const preview =
    names.length > GROUP_NAME_PREVIEW
      ? `${names.slice(0, GROUP_NAME_PREVIEW).join("、")}... +${names.length - GROUP_NAME_PREVIEW} 个`
      : names.join("、") || "未绑定";

  return (
    <div
      className={`keyword-row${selected ? " selected" : ""}${dragging ? " dragging" : ""}`}
      draggable={dragEnabled}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
    >
      <span className="drag-handle" title="拖拽排序">
        ⠿
      </span>
      <label className="row-check" onClick={(event) => event.stopPropagation()}>
        <input type="checkbox" checked={selected} onChange={onToggleSelect} />
      </label>
      <div className="keyword-main">
        <span className="keyword-badge">{keyword.display_text.slice(0, 1)}</span>
        <div>
          <strong>{keyword.display_text}</strong>
          <small title={names.join("、") || "未绑定"}>
            应用群聊：{preview} · 提醒 {notifyCount} 个
          </small>
        </div>
      </div>
      <span className="keyword-count">{names.length} 个群</span>
      <label className="switch" onClick={(event) => event.stopPropagation()}>
        <input type="checkbox" checked={active} onChange={onToggleEnabled} />
        <span />
      </label>
      <button className="button ghost compact-button" onClick={onEdit}>
        编辑
      </button>
      <button
        className="icon-button danger-button"
        onClick={onDelete}
        aria-label={`删除 ${keyword.display_text}`}
      >
        <X size={16} />
      </button>
    </div>
  );
}