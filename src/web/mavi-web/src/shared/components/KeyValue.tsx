import { Fragment, type ReactNode } from 'react';

export type KeyValueItem = {
  label: string;
  value: ReactNode;
  /** Render the value in monospace (identifiers, hashes, zone ids). */
  mono?: boolean;
};

/** A compact definition list. `grid` lays items out in responsive columns. */
export default function KeyValue({ items, grid = false }: { items: KeyValueItem[]; grid?: boolean }) {
  return (
    <dl className={grid ? 'kv kv--grid' : 'kv'}>
      {items.map((item) => {
        const value = item.mono ? <code>{item.value}</code> : item.value;
        return grid ? (
          <div key={item.label}>
            <dt>{item.label}</dt>
            <dd>{value}</dd>
          </div>
        ) : (
          <Fragment key={item.label}>
            <dt>{item.label}</dt>
            <dd>{value}</dd>
          </Fragment>
        );
      })}
    </dl>
  );
}
