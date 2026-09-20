/**
 * The loading presentation. A skeleton is offered only where the row height is
 * genuinely known (section 14); everywhere else a labelled spinner is honest
 * about not knowing what is coming.
 */
export default function LoadingState({
  label = 'Loading…',
  rows,
}: {
  label?: string;
  /** Render this many skeleton rows instead of the spinner. */
  rows?: number;
}) {
  if (rows && rows > 0) {
    return (
      <div className="skeleton" role="status" aria-label={label}>
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="skeleton__row" />
        ))}
      </div>
    );
  }

  return (
    <p className="loading-state" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </p>
  );
}
