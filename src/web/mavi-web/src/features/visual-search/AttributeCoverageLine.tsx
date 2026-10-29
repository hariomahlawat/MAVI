import type { AttributeCoverage } from '../../api/tracks';
import { formatCount } from '../../shared/format/format';
import { attributeDisclosure, attributeTypeLabel } from './attributeSearch';

/**
 * The attribute coverage of a search (UI/UX §17; Stage-2 plan §16; PoC S5): how
 * many Tracks of the scope were analysed, unavailable or not analysed, and how
 * many analysed Tracks hold an Unknown for each predicate — Tracks that may have
 * the value but where the model abstained. An empty attribute result is
 * therefore never read as "no such Track". The disclosure leads the line.
 */
export default function AttributeCoverageLine({ coverage, developmentOnly = true }: { coverage: AttributeCoverage; developmentOnly?: boolean }) {
  const disclosure = attributeDisclosure(coverage.disclosure, developmentOnly);
  if (coverage.identityFingerprint === null) {
    return (
      <div className="coverage coverage--info" role="region" aria-label="Attribute coverage"><div className="coverage__body"><span className="coverage__headline">
        Attributes: attribute search is not configured in this installation; {formatCount(coverage.tracksInScope)} Tracks in scope were not analysed.
      </span></div></div>
    );
  }
  const unknown = coverage.unknown
    .filter((item) => item.tracks > 0)
    .map((item) => `${attributeTypeLabel(item.attributeType).toLowerCase()} unknown on ${formatCount(item.tracks)}`);
  return (
    <div className="coverage coverage--info" role="region" aria-label="Attribute coverage">
      <div className="coverage__body">
        <span className="coverage__headline">
          Attributes{disclosure ? ` (${disclosure})` : ''}: {formatCount(coverage.analysed)} of {formatCount(coverage.tracksInScope)} Tracks in scope analysed
          {coverage.unavailable > 0 ? ` · ${formatCount(coverage.unavailable)} unavailable` : ''}
          {coverage.notAnalysed > 0 ? ` · ${formatCount(coverage.notAnalysed)} not analysed` : ''}
          {unknown.length > 0 ? ` · ${unknown.join(' · ')}` : ''}
        </span>
      </div>
    </div>
  );
}

/** The empty-result words of an attribute search, by what its coverage says. */
export function attributeEmptyState(coverage: AttributeCoverage): { title: string; body: string; hatched: boolean } {
  if (coverage.identityFingerprint === null) {
    return {
      title: 'Attribute search is not configured in this installation.',
      body: 'Configure the attributes role before using attribute filters.',
      hatched: true,
    };
  }
  const incomplete = coverage.analysed !== coverage.tracksInScope || coverage.unknown.some((item) => item.tracks > 0);
  return {
    title: 'No analysed Track has these attribute values.',
    body: incomplete
      ? 'Some Tracks are not analysed, unavailable or have an unknown value; a match may exist among them. See the attribute coverage above.'
      : 'Every Track in this scope was analysed and none has these values. Adjust the attribute or other filters.',
    hatched: incomplete,
  };
}
