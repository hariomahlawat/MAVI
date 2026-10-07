import Icon from '../components/Icon';

/**
 * Evidence that cannot be shown (specification §27, §37.1 "media").
 *
 * Its semantics are narrow: an image, crop or poster the product would have
 * drawn and cannot — the Track has no persisted thumbnail, the crop was never
 * written, the bytes failed to load. It is not an empty result, not a
 * not-configured scene and not a failed request: those have their own words.
 *
 * It fills whatever media frame holds it, so the geometry the image would have
 * occupied is reserved and nothing around it moves; it sits on the evidence
 * matte like the image would; it carries one icon and one short label, and the
 * label is the one vocabulary for the condition across the product — `No
 * image` — never a sentence, never a status hue, never a broken-image glyph,
 * and never a spinner, because nothing is coming.
 *
 * `dense` is for the smallest real frames — the 36×36 Evidence Set strip
 * thumbnail and the recent-Track thumbnail (62×38 inside its border). It
 * changes only spacing and icon size: the icon and the visible `No image` are
 * both still drawn (§37.1 has no icon-only form), the label wrapping to two
 * short lines where one does not fit. Measured at the smallest type token
 * (11px): `No image` is 48px on one line, `image` 30px. In the strip thumbnail
 * the label takes two lines, and a 14px icon above them clipped the descender
 * of `g`, so the dense icon is drawn at the label's size (11px). The recent
 * thumbnail holds the label on one line.
 *
 * `pending` is not this condition: while an image is still expected the frame
 * is reserved as matte only — no icon, no label, nothing claimed missing.
 */
export default function EvidencePlaceholder({
  label = 'No image',
  reason,
  dense = false,
  pending = false,
  className,
}: {
  /** The one visible word for the condition. */
  label?: string;
  /** Why, for assistive technology only; never painted inside the frame. */
  reason?: string;
  /** The smallest frames: tighter spacing and the small icon; the label is still drawn. */
  dense?: boolean;
  /** The frame is reserved while an image is still expected: matte only, no spinner. */
  pending?: boolean;
  className?: string;
}) {
  const name = reason ? `${label}: ${reason}` : label;
  return (
    <span
      className={['evidence-placeholder', dense ? 'evidence-placeholder--dense' : '', pending ? 'evidence-placeholder--pending' : '', className ?? '']
        .filter(Boolean)
        .join(' ')}
      role="img"
      aria-label={name}
    >
      {pending ? null : <Icon name="box" size={dense ? 'sm' : 'md'} />}
      {pending ? null : <span className="evidence-placeholder__label">{label}</span>}
    </span>
  );
}
