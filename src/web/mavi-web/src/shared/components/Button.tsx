import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Link, type LinkProps } from 'react-router-dom';
import Icon, { type IconName } from './Icon';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
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
  return (
    <Link className={classes(variant, size, iconOnly, className)} {...rest}>
      {icon ? <Icon name={icon} size={size === 'sm' ? 'sm' : 'md'} /> : null}
      {iconOnly ? <span className="visually-hidden">{children}</span> : children}
    </Link>
  );
}
