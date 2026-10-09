import { createContext, useContext, type ButtonHTMLAttributes, ReactNode, Ref } from 'react';
import { Link, type LinkProps } from 'react-router-dom';
import Icon, { type IconName } from './Icon';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';

/**
 * Where actions are compacted (§25 Tier C Context Bar: the primary action keeps
 * its icon and label; the band has room for nothing else drawn at full width).
 * A non-primary action with an icon is drawn icon-only there, its label kept as
 * its accessible name; the primary, and an action with no icon, are unchanged.
 */
export const CompactActionsContext = createContext(false);

function useIconOnly(variant: Variant, icon: IconName | undefined, iconOnly: boolean): boolean {
  const compact = useContext(CompactActionsContext);
  return iconOnly || (compact && variant !== 'primary' && Boolean(icon));
}
type Size = 'sm' | 'md';

function classes(variant: Variant, size: Size, iconOnly: boolean, extra?: string): string {
  return [
    'btn',
    variant !== 'secondary' ? `btn--${variant}` : '',
    size === 'sm' ? 'btn--sm' : '',
    iconOnly ? 'btn--icon' : '',
    extra ?? '',
  ].filter(Boolean).join(' ');
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /**
   * React 19 passes `ref` as an ordinary prop, so a caller that has to put
   * focus back on a control — a Ledger returning focus to the action that
   * opened its create region — can do so without a forwarding wrapper.
   */
  ref?: Ref<HTMLButtonElement>;
  variant?: Variant;
  size?: Size;
  icon?: IconName;
  /** Icon-only buttons must carry an accessible name; `title` doubles as the tooltip. */
  iconOnly?: boolean;
  children?: ReactNode;
};

export default function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  iconOnly = false,
  className,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  iconOnly = useIconOnly(variant, icon, iconOnly);
  return (
    <button type={type} className={classes(variant, size, iconOnly, className)} {...rest}>
      {icon ? <Icon name={icon} size={size === 'sm' ? 'sm' : 'md'} /> : null}
      {iconOnly ? <span className="visually-hidden">{children}</span> : children}
    </button>
  );
}

type ButtonLinkProps = LinkProps & {
  variant?: Variant;
  size?: Size;
  icon?: IconName;
  iconOnly?: boolean;
};

export function ButtonLink({
  variant = 'secondary',
  size = 'md',
  icon,
  iconOnly = false,
  className,
  children,
  ...rest
}: ButtonLinkProps) {
  iconOnly = useIconOnly(variant, icon, iconOnly);
  return (
    <Link className={classes(variant, size, iconOnly, className)} {...rest}>
      {icon ? <Icon name={icon} size={size === 'sm' ? 'sm' : 'md'} /> : null}
      {iconOnly ? <span className="visually-hidden">{children}</span> : children}
    </Link>
  );
}
