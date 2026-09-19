import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { listVideos } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import Panel from '../../shared/components/Panel';
import Progress from '../../shared/components/Progress';
import StatusBadge from '../../shared/components/StatusBadge';
import { displayTimestamp } from '../../shared/format/format';
import { isActiveStatus } from '../../shared/status/status';
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
    <section className="page">
      <PageHeader
        title="Processing"
        description="The latest processing run for every video that has one: queued and running first, then failed, then completed. Earlier runs of a video are not listed here."
      />

      {videos.isError ? (
        <Alert tone="error">
          {videos.error instanceof ApiError ? `${videos.error.detail} (${videos.error.code})` : 'Processing state is unavailable.'}
        </Alert>
      ) : null}

      <div className="stats">
        <div className="stat"><span className="stat__label">Active</span><span className="stat__value">{counts.active}</span><span className="stat__meta">queued or running</span></div>
        <div className="stat"><span className="stat__label">Failed</span><span className="stat__value">{counts.failed}</span><span className="stat__meta">need attention</span></div>
        <div className="stat"><span className="stat__label">Completed</span><span className="stat__value">{counts.completed}</span><span className="stat__meta">results available</span></div>
      </div>

      <Panel body="flush" title="Latest run per video" description={videos.data ? `${rows.length} video${rows.length === 1 ? '' : 's'} with a processing run` : 'Loading…'}>
        {videos.isPending ? <div className="panel__body"><LoadingState label="Loading processing state…" /></div> : null}

        {videos.data && rows.length === 0 ? (
          <EmptyState icon="activity" title="Nothing has been queued" actions={<ButtonLink to="/videos">Open Videos</ButtonLink>}>
            Queue processing from the Videos page or import a new recording.
          </EmptyState>
        ) : null}

        {rows.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Video</th>
                  <th scope="col">Status</th>
                  <th scope="col">Run</th>
                  <th scope="col">Worker</th>
                  <th scope="col">Queued</th>
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
                  return (
                    <tr key={row.id}>
                      <td>
                        <div className="video-title">
                          <strong className="truncate" title={row.originalFileName}>{row.originalFileName}</strong>
                          <span>{row.cameraCode} · {row.cameraName}</span>
                        </div>
                      </td>
                      <td><StatusBadge status={row.processingStatus} /></td>
                      <td>
                        <div className="run-cell">
                          {run ? (
                            <>
                              <span className="run-cell__line"><StatusBadge status={run.status} plain /> <span>{run.pipelineVersion}</span></span>
                              {active ? <Progress value={run.progressPercent} inline /> : null}
                              {run.failureCode ? <span className="run-cell__line"><code>{run.failureCode}</code></span> : null}
                            </>
                          ) : statusError ? (
                            <span className="run-cell__line">
                              <span className="text-err">Run status unavailable</span>
                              <Button size="sm" variant="ghost" icon="refresh" onClick={() => processing.retry(row.id)}>Retry</Button>
                            </span>
                          ) : <span className="faint">Loading run…</span>}
                        </div>
                      </td>
                      <td>{run?.workerId ? <code>{run.workerId}</code> : <span className="faint">—</span>}</td>
                      <td className="num" title={run?.queuedAtUtc ?? undefined}>{run ? displayTimestamp(run.queuedAtUtc, displayZone) : '—'}</td>
                      <td className="num">{run?.attemptCount ?? '—'}</td>
                      <td className="num">{run && run.status === 'Completed' ? run.tracksCreated : '—'}</td>
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
          </div>
        ) : null}
      </Panel>
    </section>
  );
}
