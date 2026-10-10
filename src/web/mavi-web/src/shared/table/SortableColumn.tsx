import { SHELL_QUERIES, useMediaQuery } from '../overlay/useMediaQuery';
import type { ReactNode } from 'react';
import type { LedgerSort, SortDirection } from './ledgerSort';

/**
 * A sortable table header.
 *
 * The control is a real `<button>` inside the `<th>`, never a clickable header
 * cell: a `<th>` has no role that carries activation, so a click handler on one
 * is reachable by pointer and by nothing else. The cell keeps `aria-sort`,
 * which is where the state belongs (§23), and the glyph repeats it visually, so
 * the indicator is never colour alone.
 *
 * The button's accessible name is its visible label, per §23. The direction is
 * deliberately not folded into that name: it would change as the operator sorts,
 * and a control whose name changes under them is harder to re-find, not easier.
 * `aria-sort` announces the state on the cell that has it.
 */
export default function SortableColumn<Column extends string>({
  sort,
  column,
  firstDirection = 'asc',
  numeric = false,
  className,
  children,
}: {
  sort: LedgerSort<Column>;
  column: Column;
  /** Which way this column reads best when first activated (§16). */
  firstDirection?: SortDirection;
  /** Right-aligns the header to sit over a numeric column (§16). */
  numeric?: boolean;
  /** A Ledger's own column class (a column that folds at Tier B, §25). */
  className?: string;
  children: ReactNode;
}) {
  const active = sort.state.column === column;
  const ascending = sort.state.direction === 'asc';
  // §25 Tier C: the Ledger is a list and its header is not drawn — still the
  // cells' column names for assistive technology, but no tab stop a sighted
  // keyboard user would land on without seeing it (the order is the Sort
  // select's, where a Ledger offers one).
  const narrow = useMediaQuery(SHELL_QUERIES.narrow);

  return (
    <th
      scope="col"
      className={['is-sortable', numeric ? 'num' : '', className ?? ''].filter(Boolean).join(' ')}
      aria-sort={active ? (ascending ? 'ascending' : 'descending') : 'none'}
    >
      <button type="button" className="col-sort" tabIndex={narrow ? -1 : undefined} onClick={() => sort.activate(column, firstDirection)}>
        <span>{children}</span>
        <span className="col-sort__mark" aria-hidden="true">{active ? (ascending ? '▲' : '▼') : '↕'}</span>
      </button>
    </th>
  );
}
