import type { AnalyticsCoverage, PlateCoverage } from '../../api/tracks';
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
  plateCoverage,
  geometry,
  scopeNoun,
}: {
  coverage?: AnalyticsCoverage;
  plateCoverage?: PlateCoverage;
  geometry?: GeometryNames;
  /** What the scope is, for the case where it holds no runs at all. */
  scopeNoun?: string;
}) {
  if (!coverage && !plateCoverage) return null;
  const plateComplete = plateCoverage
    ? plateCoverage.ready === plateCoverage.vehicleTracksInScope : true;
  const tone = (coverage?.staleRuns ?? 0) > 0 || (plateCoverage?.stale ?? 0) > 0
    ? 'stale' : (coverage?.complete ?? true) && plateComplete ? 'success' : 'info';
  const revision = !coverage || coverage.sceneRevisionId === null
    ? 'no scene configured'
    : geometry?.revisionNumber !== null && geometry?.revisionNumber !== undefined
      ? `Revision ${geometry.revisionNumber}`
      : `Revision ${shortId(coverage.sceneRevisionId)}`;
  const sentences = coverage ? coverageSentences(coverage) : [];
  const plateSentences = plateCoverage
    ? [
        plateCoverage.pending > 0 ? `${formatCount(plateCoverage.pending)} pending` : null,
        plateCoverage.failed > 0 ? `${formatCount(plateCoverage.failed)} failed` : null,
        plateCoverage.stale > 0 ? `${formatCount(plateCoverage.stale)} from an earlier configuration` : null,
      ].filter((item): item is string => item !== null)
    : [];
  // Processing is offered only for runs it can act on — pending, failed or
  // analysed against an earlier revision. A run with no scene, or with
  // analytics disabled by the scene, is repaired in the scene, not there.
  const processingCanHelp = coverage ? coverage.pendingRuns + coverage.failedRuns + coverage.staleRuns > 0 : false;

  return (
    <div className={`coverage coverage--${tone}`} role="region" aria-label="Analytics coverage">
      <Icon name={tone === 'success' ? 'check' : 'info'} size="sm" />
      <div className="coverage__body">
        {coverage ? <span className="coverage__headline">
          <strong>{coverageHeadline(coverage, scopeNoun)}</strong>
          {/* The identity is a line of its own, its revision and engine each
              unbroken: when the scene's names are withdrawn, "Revision 4"
              becomes the revision's short id, and that must not change how
              many lines the headline takes (S6/X3). */}
          <span className="faint coverage__identity">
            <span className="coverage__revision">{revision}</span>
            {/* A word break for assistive technology where the stacked
                identity draws no separator; a flex container lays it out as
                nothing. */}
            {' '}
            <span className="coverage__engine">{engineLabel(coverage.algorithmVersion)}</span>
          </span>
        </span> : null}
        {sentences.length > 0 ? <span className="coverage__buckets">{sentences.join(' · ')}</span> : null}
        {coverage ? <span className="coverage__tracks">
          {plural(coverage.analysedTracks, 'Track')} analysed
          {coverage.unavailableTracks > 0
            ? <> · <span className="text-warn">{plural(coverage.unavailableTracks, 'Track')} could not be analysed</span></>
            : null}
        </span> : null}
        {plateCoverage ? (
          <span className="coverage__tracks">
            {plateCoverage.notConfigured === plateCoverage.vehicleTracksInScope
              ? 'Plate reading is not configured in this installation'
              : `Plate readings available for ${formatCount(plateCoverage.ready)} of ${formatCount(plateCoverage.vehicleTracksInScope)} vehicle tracks in scope`}
            {plateSentences.length ? ` · ${plateSentences.join(' · ')}` : null}
          </span>
        ) : null}
      </div>
      {coverage && !coverage.complete && processingCanHelp ? (
        <ButtonLink size="sm" variant="ghost" to="/processing" icon="activity">Processing</ButtonLink>
      ) : null}
    </div>
  );
}
