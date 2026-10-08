import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import type { VideoAsset } from '../../api/videos';
import type { AsyncState } from '../../shared/async/asyncState';
import Button from '../../shared/components/Button';
import Icon from '../../shared/components/Icon';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatCount } from '../../shared/format/format';
import { ANALYTICS_READINESS_TEXT } from '../processing/analyticsReadiness';
import type { AttentionEvaluation, AttentionItem } from './attention';

/** Rows shown before the disclosure (§37.1 large data, panel: default 5). */
export const ATTENTION_VISIBLE = 5;

/** The row's one state treatment, from the shared vocabularies — never a second badge. */
function StateBadge({ item }: { item: AttentionItem }) {
  switch (item.condition) {
    case 'processing-failed': return <StatusBadge status="Failed" />;
    case 'analytics-failed': return <StatusBadge tone="err">{ANALYTICS_READINESS_TEXT.Failed}</StatusBadge>;
    case 'analytics-stale': return <StatusBadge status="Stale" />;
    case 'awaiting-processing': return <StatusBadge status="NotQueued" />;
  }
}

/**
 * The Overview's first region (§4.1.1): what needs the operator's attention,
 * each row linking to the surface that acts on it.
 *
 * It claims only what its evaluation supports. Nothing to report is one line
 * and reserves no space (§36.3, nothing states) — and is said only when every
 * check in scope answered: until then the page passes no evaluation and the
 * region is its loading line, and a check that failed is named rather than
 * read as healthy (§14.1). The video
 * inventory's own failure is the page's one notice (§14.1, one cause, one
 * alert); this region says only that it cannot be evaluated without it.
 */
export default function AttentionRegion({
  videos,
  evaluation,
  onRetryLookups,
}: {
  videos: AsyncState<readonly VideoAsset[]>;
  evaluation: AttentionEvaluation | null;
  onRetryLookups: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const headingId = useId();

  if (videos.kind === 'unavailable') {
    return (
      <p className="attention-line">
        <Icon name="alert" size="sm" />
        <span>What needs attention cannot be determined while the video inventory is unavailable.</span>
      </p>
    );
  }
  if (videos.kind === 'loading' || !evaluation) {
    return (
      <p className="attention-line" aria-live="polite">
        <span className="state-row state-row--loading">Checking what needs attention…</span>
      </p>
    );
  }

  const { items, analyticsScope, pendingLookups, unavailableLookups, unavailableDetails, unknownAnalytics } = evaluation;
  const scopeNote = analyticsScope.checked < analyticsScope.total
    ? `Analytics checked for the ${formatCount(analyticsScope.checked)} most recently imported processed videos of ${formatCount(analyticsScope.total)}.`
    : null;
  // A failed video is listed whatever its lookup did — only its detail is
  // missing; a processed video whose lookup failed is the one whose need for
  // attention is not known.
  const videosText = (count: number) => (count === 1 ? '1 video' : `${formatCount(count)} videos`);
  const unavailableNote = unavailableLookups.length > 0 ? (
    <span className="attention-note">
      {unknownAnalytics > 0
        ? `The analytics of ${videosText(unknownAnalytics)} could not be read, so it is not known whether ${unknownAnalytics === 1 ? 'it needs' : 'they need'} attention.`
        : null}
      {unknownAnalytics > 0 && unavailableDetails > 0 ? ' ' : null}
      {unavailableDetails > 0 ? `The failure detail of ${videosText(unavailableDetails)} could not be read.` : null}
      <Button size="sm" variant="ghost" icon="refresh" onClick={onRetryLookups}>Retry</Button>
    </span>
  ) : null;

  if (items.length === 0) {
    // Clear only when every check in scope answered.
    if (pendingLookups > 0) {
      return (
        <p className="attention-line" aria-live="polite">
          <span className="state-row state-row--loading">Checking what needs attention…</span>
        </p>
      );
    }
    if (unavailableNote) {
      return (
        <p className="attention-line">
          <Icon name="alert" size="sm" />
          <span>Nothing found in the checks that answered.</span>
          {unavailableNote}
        </p>
      );
    }
    return (
      <p className="attention-line attention-line--clear">
        <Icon name="check" size="sm" />
        <span>No items need attention.</span>
        {scopeNote ? <span className="attention-note">{scopeNote}</span> : null}
      </p>
    );
  }

  const shown = expanded ? items : items.slice(0, ATTENTION_VISIBLE);
  const hidden = items.length - ATTENTION_VISIBLE;
  return (
    <Panel
      body="flush"
      title="Needs attention"
      headingId={headingId}
      actions={<span className="faint small num">{formatCount(items.length)}</span>}
      className="attention"
    >
      <ul className="attention-list" id={listId}>
        {shown.map((item) => (
          <li key={item.key}>
            <Link className="attention-row" to={item.to}>
              <span className="attention-row__state"><StateBadge item={item} /></span>
              <span className="attention-row__text">
                <span className="attention-row__subject" title={item.subject}>{item.subject}</span>
                <span className="attention-row__reason">
                  {item.reason}
                  {item.code ? <code className="attention-row__code">{item.code}</code> : null}
                </span>
              </span>
              <span className="attention-row__action">
                {item.actionLabel}
                <Icon name="chevronRight" size="sm" />
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {hidden > 0 || unavailableNote || scopeNote ? (
        <div className="attention-foot">
          {hidden > 0 ? (
            <Button size="sm" variant="ghost" aria-expanded={expanded} aria-controls={listId} onClick={() => setExpanded((value) => !value)}>
              {expanded ? 'Show fewer' : `Show ${formatCount(hidden)} more`}
            </Button>
          ) : null}
          {unavailableNote}
          {scopeNote ? <span className="attention-note">{scopeNote}</span> : null}
        </div>
      ) : null}
    </Panel>
  );
}
