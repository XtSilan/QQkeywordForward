import type { Destination } from "../types/api";

export function DestinationPicker({
  destinations,
  selected,
  onChange,
}: {
  destinations: Destination[];
  selected: number[];
  onChange: (ids: number[]) => void;
}) {
  if (!destinations.length) {
    return <div className="group-picker-empty">暂无可用提醒地址，请先到“提醒地址”添加 QQ 或邮箱。</div>;
  }
  return (
    <div className="destination-picker">
      {destinations.map((destination) => {
        const checked = selected.includes(destination.id);
        return (
          <button
            type="button"
            key={destination.id}
            className={checked ? "destination-card selected" : "destination-card"}
            onClick={() =>
              onChange(
                checked
                  ? selected.filter((id) => id !== destination.id)
                  : [...selected, destination.id],
              )
            }
          >
            <span className="channel-icon">{destination.kind === "qq" ? "Q" : "@"}</span>
            <span className="destination-copy">
              <strong>
                {destination.display_name || (destination.kind === "qq" ? "QQ 好友" : "邮箱")}
              </strong>
              <small>{destination.address}</small>
            </span>
            <span className={checked ? "group-check checked" : "group-check"}>{checked ? "✓" : ""}</span>
          </button>
        );
      })}
    </div>
  );
}