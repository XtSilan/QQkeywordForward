import type { Group } from "../types/api";

export function GroupCard({
  group,
  selected,
  onClick,
}: {
  group: Group;
  selected: boolean;
  onClick: () => void;
}) {
  const initial = (group.name || group.group_id).slice(0, 1).toUpperCase();
  return (
    <button
      type="button"
      className={selected ? "group-card selected" : "group-card"}
      onClick={onClick}
    >
      {group.avatar_url ? (
        <img src={group.avatar_url} alt="" />
      ) : (
        <span className="group-avatar-fallback">{initial}</span>
      )}
      <span className="group-card-copy">
        <strong>{group.name || "未命名群"}</strong>
        <small>{group.group_id}</small>
      </span>
      <span className={selected ? "group-check checked" : "group-check"}>{selected ? "✓" : ""}</span>
    </button>
  );
}