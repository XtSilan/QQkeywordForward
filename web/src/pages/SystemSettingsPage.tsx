import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import {
  getOrderDedupSettings,
  getSmtpSettings,
  saveOrderDedupSettings,
  saveSmtpSettings,
} from "../api/settings";
import type { OrderDedupSettings, SmtpSettings } from "../types/api";

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

const DEFAULT_DEDUP: OrderDedupSettings = {
  enabled: true,
  similarity: 0.8,
  window_minutes: 60,
  max_push_per_order: 2,
  new_phone_repush: true,
  ad_filter_enabled: true,
  ad_keywords: "招工,日结,时薪,暑假工",
};

export function SystemSettingsPage({ onError }: { onError: (message: string) => void }) {
  const [smtp, setSmtp] = useState<SmtpSettings>(DEFAULT_SMTP);
  const [dedup, setDedup] = useState<OrderDedupSettings>(DEFAULT_DEDUP);

  useEffect(() => {
    void Promise.all([getSmtpSettings(), getOrderDedupSettings()])
      .then(([s, d]) => {
        // Responses omit secrets; the spread keeps whatever the user typed so far.
        setSmtp((value) => ({ ...value, ...s }));
        setDedup((value) => ({ ...value, ...d }));
      })
      .catch((reason) => onError(reason instanceof Error ? reason.message : "设置读取失败"));
  }, []);

  return (
    <section className="content">
      <div className="welcome-row">
        <div>
          <h2>系统设置</h2>
          <p>订单去重提醒和 SMTP 邮件配置。</p>
        </div>
      </div>

      <section className="panel form-panel settings-card">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">ORDER DEDUP</div>
            <h3>订单去重提醒</h3>
          </div>
          <span className="muted">按订单指纹跨群去重</span>
        </div>
        <form
          className="settings-form"
          onSubmit={(event) => {
            event.preventDefault();
            void saveOrderDedupSettings(dedup).catch((reason) =>
              onError(reason instanceof Error ? reason.message : "保存失败"),
            );
          }}
        >
          <label className="check-field">
            <input
              type="checkbox"
              checked={dedup.enabled}
              onChange={(event) => setDedup({ ...dedup, enabled: event.target.checked })}
            />
            启用订单去重
          </label>
          <label className="field">
            <span>相似度阈值</span>
            <input
              type="number"
              min={0.1}
              max={1}
              step={0.05}
              value={dedup.similarity}
              onChange={(event) =>
                setDedup({ ...dedup, similarity: Number(event.target.value) })
              }
            />
            <small>同目的地、同柜型吨位且正文 2-gram 相似度达到该值视为同一订单。</small>
          </label>
          <label className="field">
            <span>去重窗口（分钟）</span>
            <input
              type="number"
              min={1}
              max={1440}
              value={dedup.window_minutes}
              onChange={(event) =>
                setDedup({ ...dedup, window_minutes: Number(event.target.value) })
              }
            />
            <small>窗口内的重复顶单不再推送；超过窗口视为新订单。</small>
          </label>
          <label className="field">
            <span>每单最多推送次数</span>
            <input
              type="number"
              min={1}
              max={10}
              value={dedup.max_push_per_order}
              onChange={(event) =>
                setDedup({ ...dedup, max_push_per_order: Number(event.target.value) })
              }
            />
            <small>含首次推送；之后仅新联系电话可触发补推。</small>
          </label>
          <label className="check-field">
            <input
              type="checkbox"
              checked={dedup.new_phone_repush}
              onChange={(event) => setDedup({ ...dedup, new_phone_repush: event.target.checked })}
            />
            同单出现新电话时补推一次
          </label>
          <label className="check-field">
            <input
              type="checkbox"
              checked={dedup.ad_filter_enabled}
              onChange={(event) => setDedup({ ...dedup, ad_filter_enabled: event.target.checked })}
            />
            启用招工广告过滤
          </label>
          <label className="field">
            <span>广告关键词（逗号分隔）</span>
            <input
              value={dedup.ad_keywords}
              onChange={(event) => setDedup({ ...dedup, ad_keywords: event.target.value })}
            />
            <small>命中任一关键词的整段消息直接丢弃，不进入去重。</small>
          </label>
          <div className="callout field-wide">
            <ShieldCheck size={17} />
            <span>
              同一订单（日期+目的地+柜型+吨位+正文相似）在多群转发只推送一次；未送达的订单在顶单时会自动补发，不会因去重丢消息。
            </span>
          </div>
          <button className="button primary">保存去重设置</button>
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
    </section>
  );
}