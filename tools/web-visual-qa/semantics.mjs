/**
 * Assertions on what the browser gives assistive technology, which the DOM
 * alone cannot show — CSS can change a role. They read Chromium's
 * accessibility tree through CDP (`browser.axRole`), so they run beside the
 * in-page assertions rather than inside them.
 */

/**
 * §25 Tier C Ledger (T2): the single-column list is the same table, composed
 * as a list by CSS — and stays a table to assistive technology, so each value
 * keeps its column's name. Returns findings for `tier.c-composition`, or
 * `null` where there is no Ledger table to judge.
 */
export async function tierCLedgerSemantics(browser) {
  // Behind an open modal the Ledger is inert by design (§20), and inert
  // content is withheld from assistive technology: nothing to judge there.
  // Whether there is a Ledger is the document's to say, never the
  // accessibility tree's: a table the tree has lost entirely is the very
  // failure this exists for (Codex P2 on #200).
  const dom = await browser.evaluate(`(() => { const t = document.querySelector('table.table--ledger'); return { table: Boolean(t), inert: Boolean(t && t.closest('[inert]')) }; })()`);
  if (!dom.table || dom.inert) return null;
  const roles = {
    table: await browser.axRole('table.table--ledger'),
    row: await browser.axRole('table.table--ledger tbody tr'),
    cell: await browser.axRole('table.table--ledger tbody td'),
    header: await browser.axRole('table.table--ledger thead th'),
  };
  const findings = [];
  const expect = { table: 'table', row: 'row', cell: 'cell', header: 'columnheader' };
  for (const [part, role] of Object.entries(expect)) {
    if (roles[part] !== role) {
      findings.push('the Tier C Ledger list exposes its ' + part + ' as "' + roles[part] + '", not "' + role
        + '": composed as a list, it has stopped being a table to assistive technology, and its values have lost their column names');
    }
  }
  return { roles, findings };
}
