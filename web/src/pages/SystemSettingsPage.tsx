import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import {
  getDuplicateCoolingSettings,
  getOneBotSettings,
  getSmtpSettings,
  saveDuplicateCoolingSettings,
  saveOneBotSettings,
  saveSmtpSettings,
} from "../api/settings";
import type { DuplicateCoolingSettings, OneBotSettings, SmtpSettings } from "../types/api";

const DEFAULT_SMTP: SmtpSettings = {
  host: "",
  port: 587,
  username: "",
  from_address: "",
  password: "",
  starttls: true,
  ssl: false,
  timeout: 15,
};

const DEFAULT_ONEBOT: OneBotSettings = {
  enable: false,
  url: "",
  reconnectInterval: 5000,
  heartInterval: 30000,
  verifyCertificate: true,
  token: "",
};

const DEFAULT_COOLING: DuplicateCoolingSettings = { threshold: 2, cooldown_minutes: 10 };

export function SystemSettingsPage({ onError }: { onError: (message: string) => void }) {
  const [smtp, setSmtp] = useState<SmtpSettings>(DEFAULT_SMTP);
  const [onebot, setOnebot] = useState<OneBotSettings>(DEFAULT_ONEBOT);
  const [duplicateCooling, setDuplicateCooling] = useState<DuplicateCoolingSettings>(DEFAULT_COOLING);

  useEffect(() => {
    void Promise.all([getSmtpSettings(), getOneBotSettings(), getDuplicateCoolingSettings()])
      .then(([s, o, d]) => {
        // Responses omit secrets (password/token); the spread keeps whatever the
        // user has typed so far.
        setSmtp((value) => ({ ...value, ...s }));
        setOnebot((value) => ({ ...value, ...(o.websocket_client || {}) }));
        setDuplicateCooling((value) => ({ ...value, ...d }));
      })
      .catch((reason) => onError(reason instanceof Error ? reason.message : "设置读取失败"));
  }, []);

  return (
    <section className="content">
      <div className="welcome-row">
        <div>
          <h2>系统设置</h2>
          <p>重复消息降噪、SMTP 邮件和 NapCat OneBot 配置。</p>
        </div>
      </div>

      <section className="panel form-panel settings-card">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">ANTI-SPAM</div>
            <h3>重复消息过滤</h3>
          </div>
          <span className="muted">按完整正文跨所有群计数</span>
        </div>
        <form
          className="settings-form"
          onSubmit={(event) => {
            event.preventDefault();
            void saveDuplicateCoolingSettings(duplicateCooling).catch((reason) =>
              onError(reason instanceof Error ? reason.message : "保存失败"),
            );
          }}
        >
          <label className="field">
            <span>第几条开始过滤</span>
            <input
              type="number"
              min={2}
              max={100}
              value={duplicateCooling.threshold}
              onChange={(event) =>
                setDuplicateCooling({ ...duplicateCooling, threshold: Number(event.target.value) })
              }
            />
            <small>默认第 2 条：首次正常提醒，后续相同正文立即过滤。</small>
          </label>
          <label className="field">
            <span>过滤时长（分钟）</span>
            <input
              type="number"
              min={1}
              max={1440}
              value={duplicateCooling.cooldown_minutes}
              onChange={(event) =>
                setDuplicateCooling({ ...duplicateCooling, cooldown_minutes: Number(event.target.value) })
              }
            />
            <small>重复发送的 QQ 账号也会冷却相同时长。</small>
          </label>
          <div className="callout field-wide">
            <ShieldCheck size={17} />
            <span>
              同一段正文在不同群重复出现也会过滤；触发重复过滤的账号在冷却期间发送的其他关键词消息也会被过滤。其他账号以及正文不同的柜子信息不受影响。
            </span>
          </div>
          <button className="button primary">保存过滤设置</button>
        </form>
      </section>

      <section className="panel form-panel settings-card">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">SMTP</div>
            <h3>邮件发送</h3>
          </div>
          <span className="muted">每项独立一行填写</span>
        </div>
        <form
          className="settings-form"
          onSubmit={(event) => {
            event.preventDefault();
            void saveSmtpSettings(smtp).catch((reason) =>
              onError(reason instanceof Error ? reason.message : "保存失败"),
            );
          }}
        >
          <label className="field">
            <span>主机</span>
            <input value={smtp.host} onChange={(event) => setSmtp({ ...smtp, host: event.target.value })} />
          </label>
          <label className="field">
            <span>端口</span>
            <input
              type="number"
              value={smtp.port}
              onChange={(event) => setSmtp({ ...smtp, port: Number(event.target.value) })}
            />
          </label>
          <label className="field">
            <span>用户名</span>
            <input
              value={smtp.username}
              onChange={(event) => setSmtp({ ...smtp, username: event.target.value })}
            />
          </label>
          <label className="field">
            <span>密码</span>
            <input
              type="password"
              value={smtp.password}
              onChange={(event) => setSmtp({ ...smtp, password: event.target.value })}
            />
          </label>
          <label className="field">
            <span>发件地址</span>
            <input
              value={smtp.from_address}
              onChange={(event) => setSmtp({ ...smtp, from_address: event.target.value })}
            />
          </label>
          <label className="check-field">
            <input
              type="checkbox"
              checked={smtp.starttls}
              onChange={(event) => setSmtp({ ...smtp, starttls: event.target.checked })}
            />
            启用 STARTTLS
          </label>
          <button className="button primary">保存 SMTP</button>
        </form>
      </section>

      <section className="panel form-panel settings-card">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">ONEBOT</div>
            <h3>反向 WebSocket</h3>
          </div>
          <span className="muted">保存后按需重启 NapCat</span>
        </div>
        <form
          className="settings-form"
          onSubmit={(event) => {
            event.preventDefault();
            void saveOneBotSettings(onebot).catch((reason) =>
              onError(reason instanceof Error ? reason.message : "保存失败"),
            );
          }}
        >
          <label className="check-field">
            <input
              type="checkbox"
              checked={onebot.enable}
              onChange={(event) => setOnebot({ ...onebot, enable: event.target.checked })}
            />
            启用连接
          </label>
          <label className="field field-wide">
            <span>URL</span>
            <input
              value={onebot.url}
              onChange={(event) => setOnebot({ ...onebot, url: event.target.value })}
              placeholder="ws://nonebot:8081/onebot/v11/ws"
            />
          </label>
          <label className="field">
            <span>Token</span>
            <input
              type="password"
              value={onebot.token}
              onChange={(event) => setOnebot({ ...onebot, token: event.target.value })}
            />
          </label>
          <button className="button primary">保存 OneBot 配置</button>
        </form>
      </section>
    </section>
  );
}