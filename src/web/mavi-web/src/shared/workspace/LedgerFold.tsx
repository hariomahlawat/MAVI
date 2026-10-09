import type { ReactNode } from 'react';

/**
 * The primary cell of a Ledger whose lower-priority columns can fold into it
 * (§25 Tier B). `identity` is the cell as it always is; `folded` is the folded
 * columns' values, drawn inline after it — one line, so the row keeps its
 * 36-40px pitch (§16) — only while those columns are folded, and named for
 * assistive technology by `LedgerFoldedValue`, since their headers are gone.
 */
export function LedgerPrimary({ identity, folded }: { identity: ReactNode; folded: ReactNode }) {
  return (
    <div className="ledger-primary">
      {identity}
      <span className="ledger-folded">{folded}</span>
    </div>
  );
}

/** One folded column's value, named by its header for assistive technology. */
export function LedgerFoldedValue({ name, children, title }: { name: string; children: ReactNode; title?: string }) {
  return (
    <span className="ledger-folded__value" title={title}>
      <span className="visually-hidden">{`${name} `}</span>
      {children}
    </span>
  );
}
