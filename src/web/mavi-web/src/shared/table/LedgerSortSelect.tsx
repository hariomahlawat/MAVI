import type { LedgerSort, SortDirection } from './ledgerSort';

export type SortOption<Column extends string> = {
  column: Column;
  /** The column's header text. */
  label: string;
  /** What each direction reads as, in this column's terms ("newest first"). */
  ascending: string;
  descending: string;
};

/**
 * The Ledger's order where its sort keys have no header to activate (§25 Tier
 * B): a column folded into the primary cell takes its header with it, and a
 * sort the operator can no longer reach is a control lost to the width. One
 * select carries every sort key and direction; it is drawn only while a sort
 * key is folded (workspace.css, the Ledger's own container query), so at the
 * widths where every header is present it adds nothing.
 */
export default function LedgerSortSelect<Column extends string>({
  sort,
  options,
}: {
  sort: LedgerSort<Column>;
  options: readonly SortOption<Column>[];
}) {
  const value = `${sort.state.column}:${sort.state.direction}`;
  return (
    <label className="ledger-sort">
      <span className="ledger-sort__label">Sort</span>
      <select
        value={value}
        onChange={(event) => {
          const [column, direction] = event.target.value.split(':') as [Column, SortDirection];
          sort.set({ column, direction });
        }}
      >
        {options.flatMap((option) => [
          <option key={`${option.column}:asc`} value={`${option.column}:asc`}>{`${option.label}, ${option.ascending}`}</option>,
          <option key={`${option.column}:desc`} value={`${option.column}:desc`}>{`${option.label}, ${option.descending}`}</option>,
        ])}
      </select>
    </label>
  );
}
