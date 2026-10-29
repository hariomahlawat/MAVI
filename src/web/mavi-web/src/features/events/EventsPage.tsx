import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { MAXIMUM_BUCKETS, bucketCount } from '../../api/analytics';
import { getCamera } from '../../api/cameras';
import { ApiError, isGuid } from '../../api/client';
import {
  EVENTS_DEFAULT_LIMIT,
  disabledReasonText,
  eventReviewPath,
  getEvent,
  getEventCatalogue,
  getEventTimeline,
  parameterSourceText,
  serializeEventTimelineQuery,
  type EventCoverage,
  type EventSummary,
  type EventTimeline,
  type RuleCatalogue,
} from '../../api/events';
import { getSystemConfig } from '../../api/system';
import { listVideos } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import { ButtonLink } from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import Panel from '../../shared/components/Panel';
import { displayTimestamp, formatOffset } from '../../shared/format/format';

/** Preferred bucket sizes; the smallest one that keeps the window within the response bound is used. */
const BUCKETS = [60, 300, 900, 3_600, 21_600, 86_400] as const;

type Window = { fromUtc: string; toUtc: string; bucketSeconds: number };

/**
 * The window that covers every recording of this camera, snapped outward to whole
 * minutes. Demo recordings are short and in the past, so "the last 24 hours" would
 * usually show nothing; the recordings themselves are the natural default.
 */
export function recordingsWindow(recordings: { recordingStartUtc: string; recordingEndUtc: string }[]): Window | null {
  if (recordings.length === 0) return null;
  const start = Math.min(...recordings.map((item) => Date.parse(item.recordingStartUtc)));
  const end = Math.max(...recordings.map((item) => Date.parse(item.recordingEndUtc)));
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  const from = Math.floor(start / 60_000) * 60_000;
  const to = Math.ceil(end / 60_000) * 60_000;
  return { fromUtc: new Date(from).toISOString(), toUtc: new Date(to).toISOString(), bucketSeconds: bucketFor(from, to) };
}

/**
 * A window bound typed by the operator, as epoch milliseconds, or NaN unless it names
 * its offset (`Z` or `±hh:mm`): without one the browser would read it as local time and
 * move the window silently. The API refuses such a value for the same reason.
 */
export function parseUtcBound(value: string): number {
  return /(Z|[+-]\d{2}:\d{2})$/i.test(value.trim()) ? Date.parse(value.trim()) : Number.NaN;
}

function bucketFor(from: number, to: number): number {
  for (const size of BUCKETS) {
    if (bucketCount(new Date(from).toISOString(), new Date(to).toISOString(), size) <= MAXIMUM_BUCKETS) return size;
  }
  return BUCKETS[BUCKETS.length - 1];
}

/** What is missing from an answer, in words; empty when the coverage is complete. */
export function coverageGaps(coverage: EventCoverage): string[] {
  const analytics = coverage.analytics;
  const gaps: string[] = [];
  if (analytics.pendingRuns > 0) gaps.push(`${analytics.pendingRuns} run(s) awaiting scene analytics`);
  if (analytics.failedRuns > 0) gaps.push(`${analytics.failedRuns} run(s) whose scene analytics failed`);
  if (analytics.staleRuns > 0) gaps.push(`${analytics.staleRuns} run(s) analysed against an older scene revision (stale)`);
  if (analytics.notConfiguredRuns > 0) gaps.push(`${analytics.notConfiguredRuns} run(s) on a camera with no scene configuration`);
  if (analytics.disabledRuns > 0) gaps.push(`${analytics.disabledRuns} run(s) with analytics switched off`);
  if (coverage.eventsPendingRuns > 0) gaps.push(`${coverage.eventsPendingRuns} analysed run(s) whose events are not derived yet`);
  return gaps;
}

function ruleTitle(catalogue: RuleCatalogue | undefined, ruleId: string): string {
  return catalogue?.rules.find((rule) => rule.ruleId === ruleId)?.title ?? ruleId;
}

/** The one-line statement of an event, from transported fields only. */
export function eventSentence(event: EventSummary, catalogue: RuleCatalogue | undefined): string {
  const title = ruleTitle(catalogue, event.ruleId);
  const where = event.zoneName ?? event.lineName;
  const direction = event.directionLabel ? ` (${event.directionLabel})` : '';
  const who = event.objectClass ? `${event.objectClass}` : `${event.participantCount} Tracks`;
  return `${title}${where ? ` — ${where}` : ''}${direction}: ${who}`;
}

/**
 * The Events timeline (ADR-025; register C7.2).
 *
 * One camera, one window, one resolved identity, as on the Analytics workbench. Every
 * event drills through to its provenance and to the participant Tracks' evidence:
 * the Review page opens the Track read against the event's own scene revision, with
 * the player at the event's instant.
 */
export default function EventsPage() {
  const { cameraId: rawCameraId = '' } = useParams();
  const cameraId = isGuid(rawCameraId) ? rawCameraId.toLowerCase() : '';

  const camera = useQuery({
    queryKey: queryKeys.camera(cameraId),
    queryFn: ({ signal }) => getCamera(cameraId, signal),
    enabled: cameraId !== '',
  });
  const systemConfig = useQuery({ queryKey: queryKeys.systemConfig, queryFn: ({ signal }) => getSystemConfig(signal), staleTime: 60_000 });
  const catalogue = useQuery({ queryKey: ['event-catalogue'], queryFn: ({ signal }) => getEventCatalogue(signal), staleTime: Infinity });
  const videos = useQuery({ queryKey: queryKeys.videos, queryFn: ({ signal }) => listVideos(signal), enabled: cameraId !== '' });

  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId ?? undefined;
  const recordings = useMemo(
    () => (videos.data ?? []).filter((video) => video.cameraId.toLowerCase() === cameraId),
    [videos.data, cameraId],
  );
  const defaultWindow = useMemo(() => recordingsWindow(recordings), [recordings]);

  const [window, setWindow] = useState<Window | null>(null);
  const [draft, setDraft] = useState<{ fromUtc: string; toUtc: string }>({ fromUtc: '', toUtc: '' });
  const [hiddenRules, setHiddenRules] = useState<ReadonlySet<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (window === null && defaultWindow !== null) {
      setWindow(defaultWindow);
      setDraft({ fromUtc: defaultWindow.fromUtc, toUtc: defaultWindow.toUtc });
    }
  }, [defaultWindow, window]);

  const enabledRules = useMemo(
    () => (catalogue.data?.rules ?? []).filter((rule) => rule.enabled).map((rule) => rule.ruleId),
    [catalogue.data],
  );
  const shownRules = enabledRules.filter((ruleId) => !hiddenRules.has(ruleId));

  const query = window && shownRules.length > 0
    ? { ...window, ruleIds: shownRules, limit: EVENTS_DEFAULT_LIMIT }
    : null;
  const timeline = useQuery({
    queryKey: ['camera-events', cameraId, query ? serializeEventTimelineQuery(query) : ''],
    queryFn: ({ signal }) => getEventTimeline(cameraId, query!, signal),
    enabled: cameraId !== '' && query !== null,
  });

  // The evidence panel sits below the list; bring it to the operator when they ask for it.
  const evidenceRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selectedId !== null) evidenceRef.current?.scrollIntoView?.({ block: 'nearest' });
  }, [selectedId]);

  const detail = useQuery({
    queryKey: ['analytic-event', selectedId ?? ''],
    queryFn: ({ signal }) => getEvent(selectedId!, signal),
    enabled: selectedId !== null,
  });

  if (cameraId === '') {
    return <EmptyState title="This is not a camera address">Choose a camera from Cameras.</EmptyState>;
  }
  if (camera.error instanceof ApiError && camera.error.status === 404) {
    return <EmptyState title="Camera not found">It may have been removed.</EmptyState>;
  }

  const applyDraft = () => {
    const from = parseUtcBound(draft.fromUtc);
    const to = parseUtcBound(draft.toUtc);
    if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) return;
    setWindow({ fromUtc: new Date(from).toISOString(), toUtc: new Date(to).toISOString(), bucketSeconds: bucketFor(from, to) });
    setSelectedId(null);
  };
  const draftInvalid = !(parseUtcBound(draft.fromUtc) < parseUtcBound(draft.toUtc));

  return (
    <div className="events-page">
      <header className="events-page__header">
        <h1>Events{camera.data ? ` — ${camera.data.name}` : ''}</h1>
        <p className="events-page__disclosure">
          Deterministic events derived from scene analytics by rule catalogue{' '}
          <strong>{catalogue.data?.catalogueVersion ?? '…'}</strong>. No model decides an event; each one names its rule,
          scene revision and the facts it came from. PoC, Development evidence, not Production-qualified.
        </p>
        <nav className="events-page__links" aria-label="Camera">
          <Link to={`/cameras/${cameraId}/analytics`}>Analytics</Link>
          <Link to={`/cameras/${cameraId}/scene`}>Scene</Link>
        </nav>
      </header>

      <Panel title="Window and rules">
        <form
          className="events-page__controls"
          onSubmit={(event) => { event.preventDefault(); applyDraft(); }}
        >
          <label>
            From (UTC)
            <input
              aria-label="From (UTC)"
              value={draft.fromUtc}
              onChange={(event) => setDraft((current) => ({ ...current, fromUtc: event.target.value }))}
            />
          </label>
          <label>
            To (UTC)
            <input
              aria-label="To (UTC)"
              value={draft.toUtc}
              onChange={(event) => setDraft((current) => ({ ...current, toUtc: event.target.value }))}
            />
          </label>
          <button type="submit" className="button button--secondary button--md" disabled={draftInvalid}>Show</button>
          {draftInvalid ? (
            <p className="events-page__muted" role="status">
              Enter both instants with an offset, for example 2026-09-21T05:00:00Z, and To after From.
            </p>
          ) : null}
          {defaultWindow ? (
            <button
              type="button"
              className="button button--ghost button--md"
              onClick={() => { setDraft({ fromUtc: defaultWindow.fromUtc, toUtc: defaultWindow.toUtc }); setWindow(defaultWindow); }}
            >
              Fit to recordings
            </button>
          ) : null}
        </form>
        <fieldset className="events-page__rules">
          <legend>Rules</legend>
          {(catalogue.data?.rules ?? []).map((rule) => (
            <label key={rule.ruleId} className={rule.enabled ? undefined : 'events-page__rule--disabled'}>
              <input
                type="checkbox"
                checked={rule.enabled && !hiddenRules.has(rule.ruleId)}
                disabled={!rule.enabled}
                onChange={(event) => setHiddenRules((current) => {
                  const next = new Set(current);
                  if (event.target.checked) next.delete(rule.ruleId); else next.add(rule.ruleId);
                  return next;
                })}
              />
              {rule.title} <span className="events-page__muted">v{rule.ruleVersion}</span>
              {rule.enabled ? null : <span className="events-page__reason">{disabledReasonText(rule.disabledReason)}</span>}
            </label>
          ))}
        </fieldset>
      </Panel>

      {videos.isError || catalogue.isError ? (
        <EmptyState title="Events are unavailable">The camera's recordings or the rule catalogue could not be read. Try again.</EmptyState>
      ) : window === null && (videos.isPending || catalogue.isPending) ? (
        <p className="events-page__muted" role="status">Loading recordings…</p>
      ) : window === null ? (
        <EmptyState title="No recordings for this camera">Import and process a video to see its events.</EmptyState>
      ) : shownRules.length === 0 ? (
        <EmptyState title="No rule selected">Choose at least one rule to see its events.</EmptyState>
      ) : timeline.isError ? (
        <EmptyState title="Events are unavailable">The timeline could not be read. Try again.</EmptyState>
      ) : !timeline.data ? (
        <p className="events-page__muted" role="status">Loading events…</p>
      ) : (
        <TimelineBody
          timeline={timeline.data}
          catalogue={catalogue.data}
          shownRules={shownRules}
          displayTimeZoneId={displayTimeZoneId}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
      )}

      {selectedId !== null ? (
        <div ref={evidenceRef}>
        <Panel title="Event evidence">
          {detail.isError ? (
            <p>The event could not be read.</p>
          ) : !detail.data ? (
            <p className="events-page__muted" role="status">Loading event…</p>
          ) : (
            <section aria-label="Event evidence" className="events-page__detail">
              <p className="events-page__sentence">{eventSentence(detail.data.event, catalogue.data)}</p>
              <dl className="events-page__facts">
                <dt>When</dt>
                <dd>
                  {displayTimestamp(detail.data.event.startUtc, displayTimeZoneId)}
                  {detail.data.event.endOffsetMs > detail.data.event.startOffsetMs
                    ? ` to ${displayTimestamp(detail.data.event.endUtc, displayTimeZoneId)}`
                    : ''}
                  {' '}(media {formatOffset(detail.data.event.startOffsetMs)})
                </dd>
                <dt>Rule</dt>
                <dd>{detail.data.event.ruleId} v{detail.data.event.ruleVersion}, catalogue {detail.data.catalogueVersion}</dd>
                <dt>Scene</dt>
                <dd>Revision {detail.data.sceneRevisionNumber}, analytics {detail.data.analyticsAlgorithmVersion}</dd>
                <dt>Input digest</dt>
                <dd><code title={detail.data.inputSha256}>{detail.data.inputSha256.slice(0, 16)}…</code></dd>
              </dl>
              {detail.data.parameters.length > 0 ? (
                <>
                  <h3>Parameters as applied</h3>
                  <ul>
                    {detail.data.parameters.map((parameter) => (
                      <li key={parameter.name}>
                        {parameter.name}: {parameter.value}{parameter.unit ? ` ${parameter.unit}` : ''}{' '}
                        <span className="events-page__muted">({parameterSourceText(parameter.source)}: {parameter.reference})</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
              {detail.data.details.length > 0 ? (
                <ul className="events-page__muted">
                  {detail.data.details.map((item) => <li key={item.name}>{item.name}: {item.value}</li>)}
                </ul>
              ) : null}
              <h3>Tracks</h3>
              <ul className="events-page__participants">
                {detail.data.participants.map((participant) => (
                  <li key={participant.trackId}>
                    <ParticipantCrop url={participant.thumbnailContentUrl} objectClass={participant.objectClass} />
                    <span>{participant.objectClass} · {participant.role} · {formatOffset(participant.startOffsetMs)}–{formatOffset(participant.endOffsetMs)}</span>
                    <ButtonLink to={eventReviewPath(detail.data, participant)} size="sm">
                      Review at event
                    </ButtonLink>
                  </li>
                ))}
              </ul>
              <p className="events-page__muted">
                Inputs: {detail.data.inputs.map((input) => input.kind).join(', ')}. Review opens the Track against
                revision {detail.data.sceneRevisionNumber} with its crop, source frame and the player at the event.
              </p>
            </section>
          )}
        </Panel>
        </div>
      ) : null}
    </div>
  );
}

/** A participant's representative crop; a failed load says so instead of showing a broken image. */
function ParticipantCrop({ url, objectClass }: { url: string | null; objectClass: string }) {
  const [failed, setFailed] = useState(false);
  if (url === null || failed) return <span className="events-page__muted">Crop unavailable</span>;
  return (
    <img src={url} alt={`${objectClass} Track crop`} width={64} height={64} onError={() => setFailed(true)} />
  );
}

function TimelineBody({
  timeline,
  catalogue,
  shownRules,
  displayTimeZoneId,
  selectedId,
  onSelect,
}: {
  timeline: EventTimeline;
  catalogue: RuleCatalogue | undefined;
  shownRules: string[];
  displayTimeZoneId: string | undefined;
  selectedId: string | null;
  onSelect: (eventId: string) => void;
}) {
  const gaps = coverageGaps(timeline.coverage);
  // Nothing was evaluated: an empty answer here is not an observed absence of events.
  const noneEvaluated = timeline.coverage.derivedRuns === 0;
  const from = Date.parse(timeline.fromUtc);
  const span = Math.max(1, Date.parse(timeline.toUtc) - from);
  const lanes = shownRules;
  const laneHeight = 22;
  const labelWidth = 150;
  const width = 1000;
  const plot = width - labelWidth;

  return (
    <>
      <div className={gaps.length > 0 ? 'events-page__coverage events-page__coverage--incomplete' : 'events-page__coverage'} role="status">
        {timeline.sceneRevisionId === null
          ? 'This camera has no scene configuration, so no events can be derived.'
          : gaps.length > 0
            ? `Incomplete: ${gaps.join('; ')}. Missing runs are not shown as zero events.`
            : noneEvaluated
              ? 'No analysed runs in this window, so there is nothing to derive events from.'
              : `Complete: ${timeline.coverage.derivedRuns} run(s) evaluated against scene revision ${timeline.sceneRevisionNumber}.`}
        {timeline.truncated ? ` Showing the first ${timeline.limit} events; counts cover all of them.` : ''}
      </div>

      <Panel title="Timeline">
        {gaps.length > 0 && timeline.ruleCounts.length > 0 ? (
          <p className="events-page__muted">Counts cover the evaluated runs only.</p>
        ) : null}
        <ul className="events-page__counts" aria-label="Events per rule">
          {timeline.ruleCounts.map((count) => (
            <li key={count.ruleId}>{ruleTitle(catalogue, count.ruleId)}: <strong>{count.count}</strong></li>
          ))}
        </ul>
        <svg
          className="events-page__lanes"
          viewBox={`0 0 ${width} ${Math.max(1, lanes.length) * laneHeight}`}
          role="img"
          aria-label="Events on a timeline, one lane per rule"
        >
          {lanes.map((ruleId, lane) => (
            <g key={ruleId} transform={`translate(0 ${lane * laneHeight})`}>
              <text x={0} y={laneHeight / 2 + 4} className="events-page__lane-label">{ruleTitle(catalogue, ruleId)}</text>
              <line x1={labelWidth} x2={width} y1={laneHeight / 2} y2={laneHeight / 2} className="events-page__lane" />
              {timeline.events.filter((item) => item.ruleId === ruleId).map((item) => {
                const x1 = labelWidth + ((Date.parse(item.startUtc) - from) / span) * plot;
                const x2 = labelWidth + ((Date.parse(item.endUtc) - from) / span) * plot;
                const selected = item.eventId === selectedId;
                // Clamp both ends into the plot, so a span reaching outside the window
                // never draws over the lane labels or past the right edge.
                const left = Math.min(width, Math.max(labelWidth, x1));
                const right = Math.min(width, Math.max(labelWidth, x2));
                return (
                  <rect
                    key={item.eventId}
                    x={Math.min(left, width - 3)}
                    y={4}
                    width={Math.max(3, right - left)}
                    height={laneHeight - 8}
                    className={selected ? 'events-page__mark events-page__mark--selected' : 'events-page__mark'}
                    onClick={() => onSelect(item.eventId)}
                  >
                    <title>{eventSentence(item, catalogue)}</title>
                  </rect>
                );
              })}
            </g>
          ))}
        </svg>
        {timeline.events.length === 0 ? (
          <p>
            {gaps.length > 0
              ? 'No events in the evaluated runs so far.'
              : noneEvaluated ? 'No analysed runs in this window.' : 'No events in this window.'}
          </p>
        ) : (
          <table className="events-page__table">
            <thead>
              <tr><th>Time</th><th>Event</th><th>Media offset</th><th /></tr>
            </thead>
            <tbody>
              {timeline.events.map((item) => (
                <tr key={item.eventId} aria-selected={item.eventId === selectedId}>
                  <td>{displayTimestamp(item.startUtc, displayTimeZoneId)}</td>
                  <td>{eventSentence(item, catalogue)}</td>
                  <td>{formatOffset(item.startOffsetMs)}</td>
                  <td>
                    <button type="button" className="button button--ghost button--sm" onClick={() => onSelect(item.eventId)}>
                      Evidence
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {timeline.crossingCounts.length > 0 ? (
        <Panel title={`Line crossings per ${timeline.bucketSeconds >= 3_600 ? `${timeline.bucketSeconds / 3_600} h` : `${timeline.bucketSeconds / 60} min`}`}>
          {timeline.crossingCounts.map((line) => (
            <table key={line.lineId} className="events-page__table" aria-label={`Crossings of ${line.name}`}>
              <caption>{line.name}</caption>
              <thead>
                <tr><th>From</th><th>{line.aToBLabel}</th><th>{line.bToALabel}</th></tr>
              </thead>
              <tbody>
                {timeline.buckets.map((bucket, index) => (line.aToBCounts[index] + line.bToACounts[index] > 0 ? (
                  <tr key={bucket.startUtc}>
                    <td>{displayTimestamp(bucket.startUtc, displayTimeZoneId)}</td>
                    <td>{line.aToBCounts[index]}</td>
                    <td>{line.bToACounts[index]}</td>
                  </tr>
                ) : null))}
                <tr>
                  <th scope="row">Window</th>
                  <td>{line.aToBCounts.reduce((sum, value) => sum + value, 0)}</td>
                  <td>{line.bToACounts.reduce((sum, value) => sum + value, 0)}</td>
                </tr>
              </tbody>
            </table>
          ))}
        </Panel>
      ) : null}
    </>
  );
}
