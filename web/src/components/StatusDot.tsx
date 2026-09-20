export function StatusDot({ online }: { online: boolean }) {
  return <span className={online ? "status-dot online" : "status-dot"} />;
}