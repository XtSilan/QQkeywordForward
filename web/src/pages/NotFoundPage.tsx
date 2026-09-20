import { Compass } from "lucide-react";
import { Link } from "react-router-dom";

/** Fallback route for URLs that match no page. */
export function NotFoundPage() {
  return (
    <section className="content">
      <div className="placeholder panel">
        <div className="empty-icon">
          <Compass size={22} />
        </div>
        <h2>页面不存在</h2>
        <p>这个地址没有对应的管理页面，请从左侧导航重新进入。</p>
        <Link className="button secondary" to="/">
          返回 Dashboard
        </Link>
      </div>
    </section>
  );
}