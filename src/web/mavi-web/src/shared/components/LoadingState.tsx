export default function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <p className="loading-state" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </p>
  );
}
