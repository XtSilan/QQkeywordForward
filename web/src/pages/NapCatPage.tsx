import { RefreshCw, RotateCcw, ShieldCheck } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { getNapCatStatus, refreshQrCode, requestQrCode, restartNapCat } from "../api/napcat";
import { EmptyState } from "../components/EmptyState";
import { InfoRow } from "../components/InfoRow";
import { StatusDot } from "../components/StatusDot";
import type { NapCatStatus } from "../types/api";
import { usePoll } from "../hooks/usePoll";

export function NapCatPage({ onError }: { onError: (message: string) => void }) {
  const [status, setStatus] = useState<NapCatStatus | null>(null);
  const [qr, setQr] = useState("");
  const [qrImage, setQrImage] = useState("");
  const [busy, setBusy] = useState("");

  const load = async () => {
    try {
      setStatus(await getNapCatStatus());
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "NapCat 状态读取失败");
    }
  };

  usePoll(load, 2000);

  useEffect(() => {
    if (!qr) {
      setQrImage("");
      return;
    }
    void QRCode.toDataURL(qr, { width: 220, margin: 2 })
      .then(setQrImage)
      .catch(() => setQrImage(""));
  }, [qr]);

  const getQr = async () => {
    setBusy("qr");
    try {
      const data = await requestQrCode();
      setQr(data.qrcode || data.qrcodeurl || "");
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "二维码获取失败");
    } finally {
      setBusy("");
    }
  };

  const refreshQr = async () => {
    setBusy("refresh");
    try {
      const data = await refreshQrCode();
      setQr(data.qrcode || data.qrcodeurl || "");
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "二维码刷新失败");
    } finally {
      setBusy("");
    }
  };

  const restart = async () => {
    setBusy("restart");
    try {
      await restartNapCat();
      await load();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "NapCat 重启失败");
    } finally {
      setBusy("");
    }
  };

  const online = Boolean(status?.isLogin || status?.coreReady);

  return (
    <section className="content">
      <div className="welcome-row">
        <div>
          <h2>登录与 NapCat</h2>
          <p>二维码和登录状态由后端安全代理，不把 NapCat 凭据暴露给浏览器。</p>
        </div>
        <div className={online ? "status-chip good" : "status-chip warn"}>
          <StatusDot online={online} />
          {online ? "QQ 已登录" : status?.loginPhase || "等待状态"}
        </div>
      </div>

      <div className="napcat-grid">
        <section className="panel qr-panel">
          <div className="panel-heading">
            <div>
              <div className="panel-kicker">QR LOGIN</div>
              <h3>扫码登录</h3>
            </div>
            <button className="button secondary" onClick={() => void refreshQr()} disabled={busy !== ""}>
              <RefreshCw size={15} />
              刷新
            </button>
          </div>

          {qr ? (
            <div className="qr-content">
              <div className="qr-placeholder">
                {qrImage ? <img src={qrImage} alt="NapCat 登录二维码" /> : <span>二维码生成中</span>}
              </div>
              <code>{qr}</code>
              <span>请使用手机 QQ 扫描二维码并授权。</span>
            </div>
          ) : (
            <EmptyState
              icon={<ShieldCheck size={22} />}
              title="尚未获取二维码"
              hint="点击下方按钮从 NapCat 获取最新二维码。"
            />
          )}

          {!qr && (
            <button className="button primary full-button" onClick={() => void getQr()} disabled={busy !== ""}>
              <ShieldCheck size={15} />
              {busy === "qr" ? "获取中" : "获取二维码"}
            </button>
          )}
        </section>

        <section className="panel napcat-info-panel">
          <div className="panel-heading">
            <div>
              <div className="panel-kicker">NAPCAT STATUS</div>
              <h3>运行状态</h3>
            </div>
            <span className="muted">2 秒刷新</span>
          </div>
          <div className="info-list">
            <InfoRow label="登录状态" value={status?.isLogin ? "已登录" : "未登录"} good={Boolean(status?.isLogin)} />
            <InfoRow label="核心状态" value={status?.coreReady ? "已就绪" : "等待中"} good={Boolean(status?.coreReady)} />
            <InfoRow label="登录阶段" value={status?.loginPhase || "-"} />
            <InfoRow label="登录错误" value={status?.loginError || "无"} />
          </div>
          <div className="callout">
            <ShieldCheck size={17} />
            <span>二维码过期时点击刷新。修改 NapCat 或 OneBot 配置后，再使用重启按钮应用。</span>
          </div>
          <button className="button ghost full-button" onClick={() => void restart()} disabled={busy !== ""}>
            <RotateCcw size={15} />
            {busy === "restart" ? "重启中" : "重启 NapCat"}
          </button>
        </section>
      </div>
    </section>
  );
}