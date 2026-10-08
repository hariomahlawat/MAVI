/**
 * The loading presentation. A skeleton is offered only where the row height is
 * genuinely known (section 14); everywhere else a labelled spinner is honest
 * about not knowing what is coming.
 *
 * A skeleton has the geometry of the content it precedes (section 36.3): each
 * row is drawn at the Ledger row pitch (`--table-row-h`), so that once the
 * row-pitch work binds the table to the same token (register row D4) the rows
 * that replace it land where it was (section 38). It is static — section 13
 * permits no shimmer.
 */

/**
 * The default row count, confirmed in S1a against the Ledgers as shipped: a
 * dense Videos or Processing Queue viewport at 1366×768 shows 12–14 rows, and
 * eight signals "a list is coming" at roughly two thirds of that without
 * painting a column of placeholder to the fold.
 */
export const DEFAULT_SKELETON_ROWS = 8;

const SKELETON_CLASS = {
  table: 'skeleton',
  ledger: 'skeleton skeleton--ledger',
  list: 'skeleton skeleton--list',
  compactList: 'skeleton skeleton--compact-list',
  keyValue: 'skeleton skeleton--kv',
} as const;

export default function LoadingState({
  label = 'Loading…',
  rows,
  pitch = 'table',
}: {
  label?: string;
  /**
   * Render skeleton rows instead of the spinner: a number, or `'default'` for
   * the confirmed eight.
   */
  rows?: number | 'default';
  /**
   * The geometry the skeleton precedes: table rows, a whole Ledger table
   * (its header region, then table rows), a result-list row with a thumbnail,
   * a compact list row, or a key/value row. Only `ledger` reserves a header:
   * a list or a key/value block has none, so nothing else assumes one.
   */
  pitch?: 'table' | 'ledger' | 'list' | 'compactList' | 'keyValue';
}) {
  const count = rows === 'default' ? DEFAULT_SKELETON_ROWS : rows;
  if (count && count > 0) {
    return (
      <div className={SKELETON_CLASS[pitch]} role="status">
        {/* A live region announces its content, not a name: the label is text
            inside it, hidden visually, so the load is actually said — once. */}
        <span className="visually-hidden">{label}</span>
        {/* A span, not a div, so the rows' alternating widths still count
            from the first row. */}
        {pitch === 'ledger' ? <span className="skeleton__head" aria-hidden="true" /> : null}
        {Array.from({ length: count }, (_, index) => (
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
