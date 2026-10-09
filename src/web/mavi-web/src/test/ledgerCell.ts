/**
 * A Ledger cell's text as the workstation shows it: without the folded
 * columns' values, which ride the primary cell only where those columns are
 * folded (§25 Tier B) and are `display: none` everywhere else — a stylesheet
 * jsdom does not apply.
 */
export function cellText(cell: Element): string {
  const copy = cell.cloneNode(true) as Element;
  copy.querySelectorAll('.ledger-folded').forEach((folded) => folded.remove());
  return copy.textContent ?? '';
}
