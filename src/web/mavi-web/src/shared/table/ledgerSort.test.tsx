import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import SortableColumn from './SortableColumn';
import { sortRows, useLedgerSort, type SortState } from './ledgerSort';

type Row = { id: string; name: string; recorded: string };

const compare = (left: Row, right: Row, column: 'name' | 'recorded'): number =>
  column === 'name' ? left.name.localeCompare(right.name) : left.recorded.localeCompare(right.recorded);

const ids = (rows: readonly Row[]) => rows.map((row) => row.id);

describe('sortRows', () => {
  const rows: Row[] = [
    { id: 'c', name: 'Bravo', recorded: '2026-09-14T02:00:00Z' },
    { id: 'a', name: 'Alpha', recorded: '2026-09-14T02:00:00Z' },
    { id: 'b', name: 'Charlie', recorded: '2026-09-13T02:00:00Z' },
  ];

  it('orders ascending and descending by the active column', () => {
    expect(ids(sortRows(rows, { column: 'name', direction: 'asc' }, compare, (r) => r.id)))
      .toEqual(['a', 'c', 'b']);
    expect(ids(sortRows(rows, { column: 'name', direction: 'desc' }, compare, (r) => r.id)))
      .toEqual(['b', 'c', 'a']);
  });

  it('breaks ties deterministically rather than leaving them to the response order', () => {
    // 'c' and 'a' share a recording start. Whichever order the API returns
    // them in, the rendered order must be the same one, or the list reshuffles
    // under the operator on a refetch that changed nothing.
    const state: SortState<'recorded'> = { column: 'recorded', direction: 'desc' };
    const forward = ids(sortRows(rows, state, compare, (r) => r.id));
    const reversed = ids(sortRows([...rows].reverse(), state, compare, (r) => r.id));
    expect(forward).toEqual(reversed);
    expect(forward).toEqual(['a', 'c', 'b']);
  });

  it('does not reverse the tie-break with the column', () => {
    // Descending by a column two rows share still lists them a, c — the
    // tie-break exists to make equal values land somewhere fixed, not to act
    // as a second sort key the operator never asked for.
    const equal: Row[] = [
      { id: 'b', name: 'Same', recorded: '2026-09-14T02:00:00Z' },
      { id: 'a', name: 'Same', recorded: '2026-09-14T02:00:00Z' },
    ];
    expect(ids(sortRows(equal, { column: 'name', direction: 'desc' }, compare, (r) => r.id))).toEqual(['a', 'b']);
    expect(ids(sortRows(equal, { column: 'name', direction: 'asc' }, compare, (r) => r.id))).toEqual(['a', 'b']);
  });

  it('leaves the source array untouched', () => {
    const source = [...rows];
    sortRows(source, { column: 'name', direction: 'asc' }, compare, (r) => r.id);
    expect(ids(source)).toEqual(['c', 'a', 'b']);
  });
});

function Harness() {
  const sort = useLedgerSort<'name' | 'recorded'>({ column: 'recorded', direction: 'desc' });
  return (
    <table>
      <caption>Harness</caption>
      <thead>
        <tr>
          <SortableColumn sort={sort} column="name" firstDirection="asc">Name</SortableColumn>
          <SortableColumn sort={sort} column="recorded" firstDirection="desc" numeric>Recorded</SortableColumn>
        </tr>
      </thead>
      <tbody><tr><td>x</td><td>y</td></tr></tbody>
    </table>
  );
}

describe('SortableColumn', () => {
  const header = (name: string) => screen.getByRole('columnheader', { name: new RegExp(name) });

  it('marks only the active column and toggles its direction', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    expect(header('Recorded')).toHaveAttribute('aria-sort', 'descending');
    expect(header('Name')).toHaveAttribute('aria-sort', 'none');

    await user.click(screen.getByRole('button', { name: 'Name' }));
    expect(header('Name')).toHaveAttribute('aria-sort', 'ascending');
    expect(header('Recorded')).toHaveAttribute('aria-sort', 'none');

    await user.click(screen.getByRole('button', { name: 'Name' }));
    expect(header('Name')).toHaveAttribute('aria-sort', 'descending');
  });

  it('starts each column in the direction that column reads best', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole('button', { name: 'Name' }));
    expect(header('Name')).toHaveAttribute('aria-sort', 'ascending');

    // Recorded is a time column: first activation is newest first, not oldest.
    await user.click(screen.getByRole('button', { name: 'Recorded' }));
    expect(header('Recorded')).toHaveAttribute('aria-sort', 'descending');
  });

  it('sorts from the keyboard through a real button, not a clickable header cell', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const button = screen.getByRole('button', { name: 'Name' });
    button.focus();
    await user.keyboard('{Enter}');
    expect(header('Name')).toHaveAttribute('aria-sort', 'ascending');

    await user.keyboard(' ');
    expect(header('Name')).toHaveAttribute('aria-sort', 'descending');

    // The cell itself must carry no handler of its own: a <th> has no
    // activation role, so one there would be pointer-only.
    expect(header('Name').getAttribute('onclick')).toBeNull();
  });

  it('carries the direction outside colour, and does not fold it into the button name', () => {
    render(<Harness />);
    const active = screen.getByRole('button', { name: 'Recorded' });
    expect(active).toHaveAccessibleName('Recorded');
    // The glyph is the non-colour cue (§23); it is hidden from the name so the
    // control does not rename itself as the operator sorts.
    expect(active.querySelector('.col-sort__mark')).toHaveTextContent('▼');
    expect(active.querySelector('.col-sort__mark')).toHaveAttribute('aria-hidden', 'true');
  });
});
