import type { ReactNode } from 'react';

/**
 * The inspector shell.
 *
 * §27.1 promotion: the Workbench and Investigation inspectors are the same
 * structural object — a titled column on the right that owns its own scroll and
 * never goes blank — with the same accessibility contract (a labelled
 * complementary region) and the same responsive fate (it becomes an overlay
 * before it becomes a squeezed column). What they show is entirely theirs; this
 * owns the boundary, the padding and the scroll.
 *
 * `summary` is not decoration. §4.3 requires the Workbench inspector to show a
 * workspace summary when nothing is selected, because an inspector that is
 * blank half the time reads as broken.
 */
export default function Inspector({
  label,
  title,
  actions,
  children,
  summary,
  isEmpty = false,
}: {
  /** Names the region; it is a complementary landmark. */
  label: string;
  /** Visible heading for the panel. */
  title?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  /** Shown instead of `children` when nothing is selected. Never blank. */
  summary?: ReactNode;
  isEmpty?: boolean;
}) {
  return (
    <aside className="inspector" aria-label={label}>
      {title || actions ? (
        <header className="inspector__head">
          {title ? <h2>{title}</h2> : null}
          {actions ? <div className="inspector__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className="inspector__body">{isEmpty ? summary : children}</div>
    </aside>
  );
}
