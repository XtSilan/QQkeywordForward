export function InfoRow({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="info-row">
      <span>{label}</span>
      <strong className={good ? "online-text" : ""}>{value}</strong>
    </div>
  );
}