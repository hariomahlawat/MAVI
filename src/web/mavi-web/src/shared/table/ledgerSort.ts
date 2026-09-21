import { useCallback, useState } from 'react';

/**
 * Client-side Ledger sorting (§16, and open decision 5 closed in UI-3).
 *
 * §27.1 promotion: Cameras and Videos want the same thing — re-order the rows
 * of an inventory the API already returns whole. The semantics are identical
 * ("order these rows by this column"), the interaction contract is identical
 * (activate a column to sort by it, activate it again to reverse), and the
 * accessibility contract is identical (`aria-sort` on the header cell, a real
 * button inside it). The two are not expected to pull apart: neither inventory
 * is paginated, and neither sort is URL state.
 *
 * What is *not* shared is what an order means. `compare` stays with the
 * feature, because "by camera" is a question only the Videos page can answer.
 * This module owns direction, the tie-break and the state machine; nothing
 * here knows a column name.
 *
 * Processing Queue deliberately has none of this: its order is the operational
 * statement (active, then failed, then completed), and an operator-selectable
 * sort would discard it.
 */

export type SortDirection = 'asc' | 'desc';

export type SortState<Column extends string> = {
  readonly column: Column;
  readonly direction: SortDirection;
};

/**
 * Order `rows` by the active column.
 *
 * The tie-break is not optional and not a nicety. Two videos recorded in the
 * same second are ordered by whatever the API happened to return otherwise,
 * so the list would reshuffle on a refetch that changed nothing — and a row
 * that moves while the operator is reaching for it is worse than a row in an
 * arbitrary but fixed place. `tieBreak` returns a value that is unique per
 * row, which in practice is its identifier.
 */
export function sortRows<Row, Column extends string>(
  rows: readonly Row[],
  state: SortState<Column>,
  compare: (left: Row, right: Row, column: Column) => number,
  tieBreak: (row: Row) => string,
): Row[] {
  const factor = state.direction === 'asc' ? 1 : -1;
  return [...rows].sort((left, right) => {
    const byColumn = compare(left, right, state.column);
    if (byColumn !== 0) return byColumn * factor;
    // The tie-break is not reversed with the column. It exists to make equal
    // values land somewhere fixed, and a tie-break that flipped with the
    // direction would simply be a second sort key the operator did not ask for.
    return tieBreak(left).localeCompare(tieBreak(right));
  });
}

export type LedgerSort<Column extends string> = {
  readonly state: SortState<Column>;
  /**
   * Activate a column. Re-activating the active column reverses it; a new
   * column starts in the direction that column reads best in — ascending for
   * text, descending for a time, where "most recent first" is the answer the
   * operator wanted (§7 of the UI-3 brief, §16 of the specification).
   */
  readonly activate: (column: Column, firstDirection: SortDirection) => void;
};

export function useLedgerSort<Column extends string>(initial: SortState<Column>): LedgerSort<Column> {
  const [state, setState] = useState<SortState<Column>>(initial);

  const activate = useCallback((column: Column, firstDirection: SortDirection) => {
    setState((current) => (
      current.column === column
        ? { column, direction: current.direction === 'asc' ? 'desc' : 'asc' }
        : { column, direction: firstDirection }
    ));
  }, []);

  return { state, activate };
}
