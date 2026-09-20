import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

export function QuickAction({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return (
    <button className="quick-action">
      <div className="quick-icon">{icon}</div>
      <div>
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
      <ChevronRight size={16} />
    </button>
  );
}