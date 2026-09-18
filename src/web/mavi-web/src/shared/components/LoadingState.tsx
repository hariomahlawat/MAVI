export default function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return <p className="loading-state" role="status">{label}</p>;
}
