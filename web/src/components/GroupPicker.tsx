import type { Group } from "../types/api";
import { GroupCard } from "./GroupCard";

export function GroupPicker({
  groups,
  selected,
  onChange,
}: {
  groups: Group[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  if (!groups.length) {
    return <div className="group-picker-empty">暂无群聊。请确认 NapCat 已登录并等待 OneBot 同步。</div>;
  }
  const visibleIds = groups.map((group) => group.group_id);
  const visibleSelected = visibleIds.filter((id) => selected.includes(id));
  const allSelected = visibleSelected.length === visibleIds.length;
  const toggleAll = () =>
    onChange(
      allSelected
        ? selected.filter((id) => !visibleIds.includes(id))
        : Array.from(new Set([...selected, ...visibleIds])),
    );
  return (
    <div className="group-picker-shell">
      <div className="group-picker-toolbar">
        <span>已选 {selected.length} 个群</span>
        <button type="button" className="button ghost compact-button" onClick={toggleAll}>
          {allSelected ? "取消全选" : "全选"}
        </button>
      </div>
      <div className="group-picker">
        {groups.map((group) => (
          <GroupCard
            key={group.group_id}
            group={group}
            selected={selected.includes(group.group_id)}
            onClick={() =>
              selected.includes(group.group_id)
                ? onChange(selected.filter((id) => id !== group.group_id))
                : onChange([...selected, group.group_id])
            }
          />
        ))}
      </div>
    </div>
  );
}