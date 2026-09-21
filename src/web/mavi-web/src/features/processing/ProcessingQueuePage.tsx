import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { listVideos } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import AsyncBoundary from '../../shared/async/AsyncBoundary';
import { fromQuery } from '../../shared/async/fromQuery';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import DisplayTimeZone from '../../shared/components/DisplayTimeZone';
import EmptyState from '../../shared/components/EmptyState';
import LoadingState from '../../shared/components/LoadingState';
import Progress from '../../shared/components/Progress';
import StatusBadge from '../../shared/components/StatusBadge';
import { compactTimestamp, displayTimestamp, formatCount } from '../../shared/format/format';
import { isActiveStatus } from '../../shared/status/status';
import { ContextBar, LedgerLayout, Toolbar } from '../../shared/workspace';
import { useVideoProcessing } from '../videos/useVideoProcessing';
import { joinVideoRows, sortVideoRows, type VideoRow } from '../videos/videoRows';

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
        crumbs={[{ label: 'Processing' }]}
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
        notices={cameras.isError ? (
          <Alert tone="warning">Camera metadata is unavailable; runs are listed without their camera.</Alert>
        ) : null}
      >
        <AsyncBoundary
          state={fromQuery(videos)}
          loading={<LoadingState label="Loading processing state…" rows={4} />}
          isEmpty={() => rows.length === 0}
          empty={(
            <EmptyState icon="activity" title="Nothing has been queued" actions={<ButtonLink to="/videos">Open Videos</ButtonLink>}>
              Queue processing from the Videos page or import a new recording.
            </EmptyState>
          )}
          unavailable={(error) => (
            <div className="panel__body">
              <Alert tone="error" actions={<Button size="sm" onClick={() => videos.refetch()}>Retry</Button>}>
                {error instanceof ApiError ? `${error.detail} (${error.code})` : 'Processing state is unavailable.'}
              </Alert>
            </div>
          )}
          degradedLabel="Showing the last known processing state; refreshing failed."
          onRetry={() => videos.refetch()}
        >
          {() => (
            <table className="table table--ledger">
              <caption className="visually-hidden">Latest processing run per video</caption>
              <thead>
                <tr>
                  <th scope="col">Video</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">Queued</th>
                  <th scope="col" className="num">Attempt</th>
                  <th scope="col" className="num" title="Final count, recorded when the run completed">Tracks</th>
                  <th scope="col"><span className="visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const run = processing.byVideo.get(row.id)?.latestRun ?? null;
                  const statusError = processing.errors.get(row.id);
                  const active = isActiveStatus(row.processingStatus);
                  // §16: one badge per row. The run's own state is named only
                  // where it genuinely disagrees with the video's, and then as
                  // text, never as a second badge describing the same thing.
                  const divergent = run !== null && coarse(run.status) !== coarse(row.processingStatus);
                  return (
                    <tr key={row.id}>
                      <td>
                        <span className="truncate cap-lg" title={`${row.originalFileName} · ${row.cameraCode} · ${row.cameraName}`}>
                          {row.originalFileName} <span className="faint">{row.cameraCode}</span>
                        </span>
                      </td>
                      <td>
                        <div className="run-cell">
                          <span className="run-cell__line">
                            <StatusBadge status={row.processingStatus} />
                            {active && run ? <Progress value={run.progressPercent} inline /> : null}
                            {/* The code rides the status line rather than a
                                second one: a failed row is still one row. */}
                            {run?.failureCode ? <code className="truncate cap-md" title={run.failureCode}>{run.failureCode}</code> : null}
                          </span>
                          {divergent ? <span className="run-cell__line">Run: {run.status}</span> : null}
                          {/* A failed lookup must never keep reading as a
                              lookup still in progress (§14). */}
                          {!run && statusError ? (
                            <span className="run-cell__line">
                              <span className="text-err">Run status unavailable</span>
                              <Button size="sm" variant="ghost" icon="refresh" onClick={() => processing.retry(row.id)}>Retry</Button>
                            </span>
                          ) : null}
                          {!run && !statusError ? <span className="faint">Loading run…</span> : null}
                        </div>
                      </td>
                      <td className="num" title={run ? displayTimestamp(run.queuedAtUtc, displayZone) : undefined}>
                        {run ? compactTimestamp(run.queuedAtUtc, displayZone) : '—'}
                      </td>
                      <td className="num">{run ? formatCount(run.attemptCount) : '—'}</td>
                      <td className="num">{run && run.status === 'Completed' ? formatCount(run.tracksCreated) : '—'}</td>
                      <td>
                        <div className="table__actions">
                          {row.processingStatus === 'Processed' ? (
                            <ButtonLink size="sm" to={`/search?videoAssetId=${row.id.toLowerCase()}`} icon="search">Results</ButtonLink>
                          ) : null}
                          <ButtonLink size="sm" variant="ghost" to={`/processing/${row.id.toLowerCase()}`}>Detail</ButtonLink>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </AsyncBoundary>
      </LedgerLayout>
    </section>
  );
}
