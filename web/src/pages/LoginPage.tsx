import { Bot, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { login } from "../api/auth";

export function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!(await login(token))) {
      setError("管理员 token 不正确");
      return;
    }
    setToken("");
    onLogin();
  };

  return (
    <main className="main login-main">
      <section className="panel login-panel">
        <div className="brand-mark">
          <Bot size={22} />
        </div>
        <h1>管理员登录</h1>
        <p>请输入部署时配置的管理员 token。</p>
        <form onSubmit={(event) => void submit(event)}>
          <label className="field">
            <span>管理员 token</span>
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              autoFocus
              required
            />
          </label>
          <button className="button primary">
            <ShieldCheck size={15} />
            登录
          </button>
          {error && <div className="alert error">{error}</div>}
        </form>
      </section>
    </main>
  );
}