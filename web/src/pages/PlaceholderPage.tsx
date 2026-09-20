import { Settings2 } from "lucide-react";

export function PlaceholderPage({ active }: { active: string }) {
  return (
    <section className="content">
      <div className="placeholder panel">
        <div className="empty-icon">
          <Settings2 size={22} />
        </div>
        <h2>{active}</h2>
        <p>这一页的 API 和交互将在下一轮接入，当前导航和运行状态已经可用。</p>
      </div>
    </section>
  );
}