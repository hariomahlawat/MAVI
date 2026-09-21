import Icon from './Icon';

/**
 * The surface-level timezone disclosure (§24).
 *
 * Per ADR-004 the browser's zone is never authoritative, so a surface that
 * shows absolute times has to say which zone it is showing them in. §24 says
 * that is stated **once per surface**, in the Context Bar — not repeated as a
 * key/value row on every panel beneath it, which is what the product did
 * before UI-3.
 *
 * §27.1 promotion: four surfaces disclose exactly the same fact in exactly the
 * same place, with no interaction and one accessibility contract — a static
 * readout whose visible text is the zone and whose accessible name says what
 * the zone is for.
 */
export default function DisplayTimeZone({ timeZoneId }: { timeZoneId: string | null | undefined }) {
  // Before the configuration arrives there is no zone to disclose, and a
  // placeholder in a 44px band would be chrome claiming to be information.
  if (!timeZoneId) return null;
  return (
    <span className="zone-note">
      <Icon name="clock" size="sm" />
      <span className="visually-hidden">Times shown in</span>
      <code>{timeZoneId}</code>
    </span>
  );
}
