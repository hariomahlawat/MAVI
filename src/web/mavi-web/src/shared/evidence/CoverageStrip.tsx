import type { AnalyticsCoverage } from '../../api/tracks';
import { ButtonLink } from '../components/Button';
import Icon from '../components/Icon';
import { formatCount } from '../format/format';
import { engineLabel, shortId, type GeometryNames } from './analyticsLabels';

/**
 * How much of an analytical scope analytics actually evaluated (UI/UX
 * specification §14 "partially available" and §17).
 *
 * Shared rather than owned by one surface: Investigation reads it against a
 * search scope and Analytics against a time window, and a second readiness
 * vocabulary saying the same thing in different words would be a second thing
 * for an operator to learn and for the two surfaces to disagree about.
 *
 * It persists for the snapshot it describes, because an answer that is silent
 * about the runs it did not evaluate is an answer that lies by omission. Every
 * non-zero bucket is named in operator words; unavailable Tracks are disclosed
 * separately from run readiness, because a unit that completed still could not
 * read them and a complete run-level claim must never be read as complete Track
 * evidence.
 */

function plural(count: number, singular: string, pluralForm = singular + 's'): string {
  return `${formatCount(count)} ${count === 1 ? singular : pluralForm}`;
}

export function coverageSentences(coverage: AnalyticsCoverage): string[] {
  const sentences: string[] = [];
  if (coverage.pendingRuns > 0) sentences.push(`${plural(coverage.pendingRuns, 'run')} not yet analysed`);
  if (coverage.failedRuns > 0) sentences.push(`${plural(coverage.failedRuns, 'run')} failed analysis`);
  if (coverage.staleRuns > 0) sentences.push(`${plural(coverage.staleRuns, 'run')} analysed with an earlier revision or engine`);
  if (coverage.disabledRuns > 0) sentences.push(`${plural(coverage.disabledRuns, 'run')} with analytics disabled by the scene revision`);
  if (coverage.notConfiguredRuns > 0) sentences.push(`${plural(coverage.notConfiguredRuns, 'run')} with no scene configured`);
  return sentences;
}

export function coverageHeadline(coverage: AnalyticsCoverage, scopeNoun = 'search scope'): string {
  const total = coverage.evaluatedRuns + coverage.pendingRuns + coverage.failedRuns
    + coverage.notConfiguredRuns + coverage.disabledRuns + coverage.staleRuns;
  if (total === 0) return `No processing runs in this ${scopeNoun}`;
  if (coverage.complete) return `All ${plural(total, 'run')} analysed`;
  return `${formatCount(coverage.evaluatedRuns)} of ${plural(total, 'run')} analysed`;
}

export default function CoverageStrip({
  coverage,
  geometry,
  scopeNoun,
}: {
  coverage: AnalyticsCoverage;
  geometry?: GeometryNames;
  /** What the scope is, for the case where it holds no runs at all. */
  scopeNoun?: string;
}) {
  const tone = coverage.staleRuns > 0 ? 'stale' : coverage.complete ? 'success' : 'info';
  const revision = coverage.sceneRevisionId === null
    ? 'no scene configured'
    : geometry?.revisionNumber !== null && geometry?.revisionNumber !== undefined
      ? `Revision ${geometry.revisionNumber}`
      : `Revision ${shortId(coverage.sceneRevisionId)}`;
  const sentences = coverageSentences(coverage);

  return (
    <div className={`coverage coverage--${tone}`} role="region" aria-label="Analytics coverage">
      <Icon name={tone === 'success' ? 'check' : 'info'} size="sm" />
      <div className="coverage__body">
        <span className="coverage__headline">
          <strong>{coverageHeadline(coverage, scopeNoun)}</strong>
          <span className="faint"> · {revision} · {engineLabel(coverage.algorithmVersion)}</span>
        </span>
        {sentences.length > 0 ? <span className="coverage__buckets">{sentences.join(' · ')}</span> : null}
        <span className="coverage__tracks">
          {plural(coverage.analysedTracks, 'Track')} analysed
          {coverage.unavailableTracks > 0
            ? <> · <span className="text-warn">{plural(coverage.unavailableTracks, 'Track')} could not be analysed</span></>
            : null}
        </span>
      </div>
      {!coverage.complete ? (
        <ButtonLink size="sm" variant="ghost" to="/processing" icon="activity">Processing</ButtonLink>
      ) : null}
    </div>
  );
}
