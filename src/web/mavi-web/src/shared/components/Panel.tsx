import type { HTMLAttributes, ReactNode } from 'react';

type PanelProps = Omit<HTMLAttributes<HTMLElement>, 'title'> & {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** `flush` removes body padding for tables and lists; `scroll` lets the body scroll. */
  body?: 'padded' | 'flush' | 'scroll';
  fill?: boolean;
  flat?: boolean;
  children?: ReactNode;
  headingId?: string;
};

export default function Panel({
  title,
  description,
  actions,
  body = 'padded',
  fill = false,
  flat = false,
  className = '',
  children,
  headingId,
  ...rest
}: PanelProps) {
  const bodyClass = [
    'panel__body',
    body === 'flush' || body === 'scroll' ? 'panel__body--flush' : '',
    body === 'scroll' ? 'panel__body--scroll' : '',
  ].filter(Boolean).join(' ');

  return (
    <section
      className={['panel', fill ? 'panel--fill' : '', flat ? 'panel--flat' : '', className].filter(Boolean).join(' ')}
      aria-labelledby={headingId}
      {...rest}
    >
      {title || actions ? (
        <header className="panel__head">
          <div className="panel__title">
            {title ? <h2 id={headingId}>{title}</h2> : null}
            {description ? <p>{description}</p> : null}
          </div>
          {actions ? <div className="panel__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}
