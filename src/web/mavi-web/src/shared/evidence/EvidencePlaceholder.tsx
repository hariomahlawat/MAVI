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
 * `dense` is for a frame too small to carry text (a 40px strip thumbnail): the
 * icon stays, the label is kept for assistive technology.
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
  /** Icon only; the label stays in the accessible name. */
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
      {pending || dense ? null : <span className="evidence-placeholder__label">{label}</span>}
    </span>
  );
}
