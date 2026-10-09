import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { isFinalizationFailure, isFinalizing, listVideos } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import { hasFailure } from '../../shared/async/asyncState';
import StateRegion, { SupportingRequestNotice } from '../../shared/async/StateRegion';
import { ButtonLink } from '../../shared/components/Button';
import DisplayTimeZone from '../../shared/components/DisplayTimeZone';
import Progress from '../../shared/components/Progress';
import StatusBadge from '../../shared/components/StatusBadge';
import { compactTimestamp, displayTimestamp, formatCount } from '../../shared/format/format';
import { FINALIZATION_FAILED_LABEL, isActiveStatus } from '../../shared/status/status';
import TruncatedText from '../../shared/overlay/Truncated';
import { ContextBar, LEDGER_SKELETON, LedgerLayout, LedgerTable, Toolbar } from '../../shared/workspace';
import { useVideoProcessing } from '../videos/useVideoProcessing';
import { joinVideoRows, sortVideoRows, type VideoRow } from '../videos/videoRows';
import { analyticsReadinessText } from './analyticsReadiness';

type Bucket = 'active' | 'failed' | 'completed';

export function bucketFor(status: string): Bucket | null {
  if (isActiveStatus(status)) return 'active';
  if (status === 'Failed') return 'failed';
  if (status === 'Processed') return 'completed';
  return null;
}

/** Active work first, then failures needing attention, then completed. */
export function orderForQueue(rows: readonly VideoRow[]): VideoRow[] {
  const rank: Record<Bucket, number> = { active: 0, failed: 1, completed: 2 };
  return rows
    .filter((row) => bucketFor(row.processingStatus) !== null)
    .sort((left, right) => rank[bucketFor(left.processingStatus)!] - rank[bucketFor(right.processingStatus)!]);
}

/**
 * A run's own state, coarsened to what it means operationally, so that §16's
 * "a secondary run state appears only when it differs from the primary state"
 * can be decided rather than guessed. `Processing` and `Running` are the same
 * answer in two vocabularies and must not produce a second badge.
 */
function coarse(status: string): Bucket | 'other' {
  return bucketFor(status) ?? (status === 'Completed' ? 'completed' : 'other');
}

/**
 * Processing — a Ledger (§4.1), and the one whose order is itself information.
 *
 * Active work first, then failures needing attention, then completed, each
 * bucket keeping the recording order it already had. That sequence is the
 * operational statement this surface exists to make, which is why §32
 * decision 5 gives this Ledger no operator-selectable sorting at all: an
 * operator who re-ordered it would have thrown the statement away.
 *
 * Rows are the *latest* run per video, not a run history. That was standing
 * prose under a page title before UI-3; it is now in the toolbar band, where
 * it belongs to the table it qualifies and does not scroll away from it.
 */
export default function ProcessingQueuePage() {
  const videos = useQuery({ queryKey: queryKeys.videos, queryFn: ({ signal }) => listVideos(signal), refetchInterval: 10_000 });
  const cameras = useQuery({ queryKey: queryKeys.cameras, queryFn: ({ signal }) => listCameras(signal) });
  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    staleTime: 60_000,
  });
  const displayZone = systemConfig.data?.displayTimeZoneId;
  const zoneState = fromQuery(systemConfig);

  const rows = useMemo(
    () => (videos.data ? orderForQueue(sortVideoRows(joinVideoRows(videos.data, cameras.data))) : []),
    [videos.data, cameras.data],
  );
  const ids = useMemo(() => rows.map((row) => row.id), [rows]);
  const processing = useVideoProcessing(ids);

  const counts = useMemo(() => {
    const result = { active: 0, failed: 0, completed: 0 };
    for (const row of rows) {
      const bucket = bucketFor(row.processingStatus);
      if (bucket) result[bucket] += 1;
    }
    return result;
  }, [rows]);

  return (
    <section className="page page--full page--workspace">
      <ContextBar
        surface="processing"
        status={<DisplayTimeZone timeZoneId={displayZone} />}
      />

      <LedgerLayout
        toolbar={(
          <Toolbar
            label="Processing queue"
            hint={(
              <>
                {/* The invariant the page title used to carry: this is a
                    current picture, not a log of every run ever made. */}
                Latest run per video — earlier runs are not listed here.
                {videos.data ? (
                  <>
                    {' · '}
                    <span className="queue-counts">
                      <span>{formatCount(counts.active)} active</span>
                      <span>{formatCount(counts.failed)} failed</span>
                      <span>{formatCount(counts.completed)} completed</span>
                    </span>
                  </>
                ) : null}
              </>
            )}
          />
        )}
        notices={hasFailure(fromQuery(cameras)) || hasFailure(zoneState) ? (
          <>
            <SupportingRequestNotice
              state={fromQuery(cameras)}
              unavailableMessage="Camera metadata is unavailable; runs are listed without their camera."
              degradedMessage="Showing the last known camera names; refreshing camera metadata failed."
              onRetry={() => void cameras.refetch()}
            />
            {/* The display timezone has no region of its own (§37.1): timestamps
                fall back to explicit UTC, and the page says so once. */}
            <SupportingRequestNotice
              state={zoneState}
              unavailableMessage="Display timezone is unavailable. Absolute timestamps are shown explicitly in UTC."
              degradedMessage="Display configuration could not be refreshed. The last known timezone remains in use."
              onRetry={() => void systemConfig.refetch()}
              retryLabel="Retry display config"
            />
          </>
        ) : null}
      >
        <StateRegion
          kind="column"
          state={fromQuery(videos)}
          label="processing state"
          loadingLabel="Loading processing state…"
          skeleton={LEDGER_SKELETON}
          isEmpty={() => rows.length === 0}
          empty={{
            icon: 'activity',
            title: 'Nothing has been queued',
            body: 'Queue processing from the Videos page or import a new recording.',
            action: <ButtonLink to="/videos">Open Videos</ButtonLink>,
          }}
          unavailableMessage={(error) => describeError(error, 'Processing state is unavailable.')}
          degradedMessage="Showing the last known processing state; refreshing failed."
          onRetry={() => videos.refetch()}
        >
          {() => (
            <LedgerTable caption="Latest processing run per video">
              <thead>
                <tr>
                  <th scope="col">Video</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">Queued</th>
                  <th scope="col" className="num">Attempt</th>
                  <th scope="col" className="num" title="Final count, recorded when the run completed">Tracks</th>
                  {/* Slice 4: a separate compact column, as text. The Status
                      column keeps its one badge (§16); analytics readiness is a
                      second fact about the row, not a second opinion about the
                      same one, and is never a second badge. */}
                  <th scope="col" title="Scene analytics readiness for the latest run">Analytics</th>
                  <th scope="col"><span className="visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const run = processing.byVideo.get(row.id)?.latestRun ?? null;
                  const statusState = processing.stateOf(row.id);
                  const active = isActiveStatus(row.processingStatus);
                  // §16: one badge per row. The run's own state is named only
                  // where it genuinely disagrees with the video's, and then as
                  // text, never as a second badge describing the same thing.
                  const divergent = run !== null && coarse(run.status) !== coarse(row.processingStatus);
                  // A Finalizing run is `Running` and a finalization failure is
                  // `Failed`, so both agree with the video's status; their phase
                  // is what differs, and it is named the same way.
                  const finalizing = isFinalizing(run);
                  const runState = finalizing ? 'Finalizing'
                    : isFinalizationFailure(run) ? FINALIZATION_FAILED_LABEL
                      : divergent ? run.status
                        : null;
                  return (
                    <tr key={row.id}>
                      <td>
                        <TruncatedText text={`${row.originalFileName} · ${row.cameraCode} · ${row.cameraName}`} className="cap-lg">
                          {row.originalFileName} <span className="faint">{row.cameraCode}</span>
                        </TruncatedText>
                      </td>
                      <td>
                        <div className="run-cell">
                          <span className="run-cell__line">
                            <StatusBadge status={row.processingStatus} />
                            {/* Inference progress only: finalization has none. */}
                            {active && run && !finalizing ? <Progress value={run.progressPercent} inline /> : null}
                            {/* The code rides the status line rather than a
                                second one: a failed row is still one row. */}
                            {run?.failureCode ? <code><TruncatedText text={run.failureCode} className="cap-md" /></code> : null}
                          </span>
                          {/* Its own truncating element: a flex line's bare text can never show
                              the ellipsis (§36.2) when the capped cell squeezes it. */}
                          {runState ? <span className="run-cell__line"><TruncatedText text={`Run: ${runState}`} /></span> : null}
                          {/* A failed lookup must never keep reading as a
                              lookup still in progress (§14). */}
                          {/* The row's run status is its own request (§37.1,
                              row): the row keeps its identity and this cell
                              carries the request's state. */}
                          {!run || hasFailure(statusState) ? (
                            <span className="run-cell__line">
                              <StateRegion
                                kind="row"
                                state={statusState}
                                label="run status"
                                loadingLabel="Loading run…"
                                unavailableMessage={() => 'Run status unavailable'}
                                degradedMessage="Run status may be out of date"
                                onRetry={() => processing.retry(row.id)}
                                // R2's dense-cell retry (M2): a 26×26 icon named
                                // for its request and video. The full-text
                                // "Retry" kept its width while the status line
                                // ran out of the 260px cap, and was clipped by
                                // it under a wider font; a row's controls must
                                // all be distinguishable by name.
                                retryLabel={`Retry run status for ${row.originalFileName}`}
                                compactRetry
                              >
                                {() => null}
                              </StateRegion>
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td className="num" title={run ? displayTimestamp(run.queuedAtUtc, displayZone) : undefined}>
                        {run ? compactTimestamp(run.queuedAtUtc, displayZone) : '—'}
                      </td>
                      <td className="num">{run ? formatCount(run.attemptCount) : '—'}</td>
                      <td className="num">{run && run.status === 'Completed' ? formatCount(run.tracksCreated) : '—'}</td>
                      <td>
                        {run && run.status === 'Completed' ? (
                          <span className="analytics-state" data-readiness={run.analyticsReadiness}>
                            {analyticsReadinessText(run.analyticsReadiness)}
                          </span>
                        ) : (
                          <span className="faint">—</span>
                        )}
                      </td>
                      <td>
                        {/* §16: one secondary text action per row (§8.1: a row
                            never carries the accent primary), plus at most one
                            icon-only action. A processed run has somewhere
                            to go, so Results is the text and its detail is the
                            icon; a run with nothing to open yet makes its
                            detail the text rather than leaving the row with a
                            lone glyph. This is the grammar Videos uses. */}
                        <div className="table__actions">
                          {row.processingStatus === 'Processed' ? (
                            <>
                              <ButtonLink size="sm" to={`/search?videoAssetId=${row.id.toLowerCase()}`} icon="search">Results</ButtonLink>
                              <ButtonLink
                                size="sm"
                                variant="ghost"
                                to={`/processing/${row.id.toLowerCase()}`}
                                title="Processing detail"
                                iconOnly
                                icon="activity"
                              >
                                Processing detail for {row.originalFileName}
                              </ButtonLink>
                            </>
                          ) : (
                            <ButtonLink size="sm" to={`/processing/${row.id.toLowerCase()}`} icon="activity">Detail</ButtonLink>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </LedgerTable>
          )}
        </StateRegion>
      </LedgerLayout>
    </section>
  );
}
