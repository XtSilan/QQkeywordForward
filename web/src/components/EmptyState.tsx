import type { ReactNode } from "react";

/** Consistent "nothing here yet" block used by panels and tables. */
export function EmptyState({
  icon,
  title,
  hint,
}: {
  icon: ReactNode;
  title: string;
  hint: string;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <strong>{title}</strong>
      <span>{hint}</span>
    </div>
  );
}