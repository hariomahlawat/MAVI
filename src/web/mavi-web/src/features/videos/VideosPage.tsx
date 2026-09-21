import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { listVideos, queueProcessing } from '../../api/videos';
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
import { formatDuration } from '../../shared/format/duration';
import { compactTimestamp, displayTimestamp, formatCount } from '../../shared/format/format';
import { isActiveStatus, VIDEO_STATUSES } from '../../shared/status/status';
import { SortableColumn, sortRows, useLedgerSort } from '../../shared/table';
import { ContextBar, LedgerLayout, Toolbar } from '../../shared/workspace';
import { useVideoProcessing } from './useVideoProcessing';
import { compareVideoRows, filterVideoRows, joinVideoRows, parseStatusFilter, type VideoColumn, type VideoRow } from './videoRows';

function canQueue(status: string): boolean {
  return status === 'NotQueued' || status === 'Failed';
}

/**
 * Videos — a Ledger (§4.1).
 *
 * One logical line per video (§16). Resolution and codec used to take the
 * second line of the first cell; they are detail metadata, they are on the
 * Processing detail Record, and the density rule is worth more here than
 * carrying them — this is a list an operator scans to decide what to do next,
 * not a place to read a video's specification.
 *
 * The committed filters are unchanged and stay in the URL exactly as they were
 * (`q`, `cameraId`, `status`); they have simply moved from the panel header
 * into the toolbar band §16 says filters live in. Sorting adds no URL state:
 * a sort is a view preference, not a shareable scope (§32 decision 5).
 */
export default function VideosPage() {
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();

  const videos = useQuery({ queryKey: queryKeys.videos, queryFn: ({ signal }) => listVideos(signal) });
  const cameras = useQuery({ queryKey: queryKeys.cameras, queryFn: ({ signal }) => listCameras(signal) });
  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    staleTime: 60_000,
  });
  const displayZone = systemConfig.data?.displayTimeZoneId;

  const filters = {
    cameraId: params.get('cameraId') ?? '',
    status: parseStatusFilter(params.get('status')),
    text: params.get('q') ?? '',
  };

  // Newest recording first, which is the order this page has always opened in.
  const sort = useLedgerSort<VideoColumn>({ column: 'recorded', direction: 'desc' });

  const rows = useMemo(() => {
    if (!videos.data) return [] as VideoRow[];
    const joined = joinVideoRows(videos.data, cameras.data);
    return sortRows(filterVideoRows(joined, filters), sort.state, compareVideoRows, (row) => row.id);
  }, [videos.data, cameras.data, filters.cameraId, filters.status, filters.text, sort.state]);

  // Only videos that are moving need live run detail; the rest read the
  // authoritative status the list already carries.
  const activeIds = useMemo(
    () => rows.filter((row) => isActiveStatus(row.processingStatus)).map((row) => row.id),
    [rows],
  );
  const processing = useVideoProcessing(activeIds);

  const queue = useMutation({
    mutationFn: (videoId: string) => queueProcessing(videoId),
    onSettled: async (_result, _error, videoId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.videos }),
        queryClient.invalidateQueries({ queryKey: queryKeys.videoProcessing(videoId) }),
      ]);
    },
  });

  function setFilter(key: 'cameraId' | 'status' | 'q', value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const total = videos.data?.length ?? 0;
  const filtered = Boolean(filters.cameraId || filters.status || filters.text);

  const toolbar = (
    <Toolbar
      label="Video filters"
      hint={videos.data
        ? `${formatCount(rows.length)} of ${formatCount(total)} video${total === 1 ? '' : 's'}${filtered ? ' match the filters' : ''}`
        : undefined}
    >
      <label className="visually-hidden" htmlFor="videos-text">Filter by file or camera</label>
      <input
        id="videos-text"
        className="search-input"
        type="search"
        placeholder="Filter by file or camera"
        value={filters.text}
        onChange={(event) => setFilter('q', event.target.value)}
      />
      <label className="visually-hidden" htmlFor="videos-camera">Camera</label>
      <select id="videos-camera" value={filters.cameraId} onChange={(event) => setFilter('cameraId', event.target.value)}>
        <option value="">All cameras</option>
        {cameras.data?.map((camera) => (
          <option key={camera.id} value={camera.id.toLowerCase()}>{camera.code} · {camera.name}</option>
        ))}
      </select>
      <label className="visually-hidden" htmlFor="videos-status">Status</label>
      <select id="videos-status" value={filters.status} onChange={(event) => setFilter('status', event.target.value)}>
        <option value="">All statuses</option>
        {VIDEO_STATUSES.map((status) => (
          <option key={status} value={status}>{status === 'NotQueued' ? 'Not queued' : status}</option>
        ))}
      </select>
    </Toolbar>
  );

  const notices = (
    <>
      {cameras.isError ? <Alert tone="warning">Camera metadata is unavailable; videos are listed by camera identifier.</Alert> : null}
      {queue.isError && !(queue.error instanceof ApiError && queue.error.code === 'processing_already_active') ? (
        <Alert tone="error">
          {queue.error instanceof ApiError ? `${queue.error.detail} (${queue.error.code})` : 'Processing could not be queued.'}
        </Alert>
      ) : null}
    </>
  );

  return (
    <section className="page page--full page--workspace">
      <ContextBar
        crumbs={[{ label: 'Videos' }]}
        status={<DisplayTimeZone timeZoneId={displayZone} />}
        actions={<ButtonLink to="/import" variant="primary" icon="upload">Import video</ButtonLink>}
      />

      <LedgerLayout toolbar={toolbar} notices={cameras.isError || queue.isError ? notices : null}>
        <AsyncBoundary
          state={fromQuery(videos)}
          loading={<LoadingState label="Loading videos…" rows={4} />}
          isEmpty={(all) => all.length === 0}
          empty={(
            <EmptyState icon="video" title="No videos imported yet" actions={<ButtonLink to="/import" variant="primary">Import the first video</ButtonLink>}>
              Import an MP4 recording against a registered camera to begin.
            </EmptyState>
          )}
          unavailable={(error) => (
            <div className="panel__body">
              <Alert tone="error" actions={<Button size="sm" onClick={() => videos.refetch()}>Retry</Button>}>
                {error instanceof ApiError ? `${error.detail} (${error.code})` : 'Video inventory is unavailable.'}
              </Alert>
            </div>
          )}
          degradedLabel="Showing the last known media inventory; refreshing failed."
          onRetry={() => videos.refetch()}
        >
          {() => rows.length === 0 ? (
            <EmptyState
              icon="filter"
              title="No videos match these filters"
              compact
              actions={<Button size="sm" onClick={() => setParams(new URLSearchParams(), { replace: true })}>Clear filters</Button>}
            />
          ) : (
            <table className="table table--ledger">
              <caption className="visually-hidden">Imported videos</caption>
              <thead>
                <tr>
                  <SortableColumn sort={sort} column="file">File</SortableColumn>
                  <SortableColumn sort={sort} column="camera">Camera</SortableColumn>
                  <SortableColumn sort={sort} column="recorded" firstDirection="desc" numeric>Recorded</SortableColumn>
                  <SortableColumn sort={sort} column="duration" firstDirection="desc" numeric>Duration</SortableColumn>
                  <th scope="col">Status</th>
                  <th scope="col"><span className="visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const run = processing.byVideo.get(row.id)?.latestRun;
                  const active = isActiveStatus(row.processingStatus);
                  const statusError = active ? processing.errors.get(row.id) : undefined;
                  return (
                    <tr key={row.id}>
                      <td><span className="truncate cap-lg" title={row.originalFileName}>{row.originalFileName}</span></td>
                      <td>
                        <span className="truncate cap-md" title={`${row.cameraCode} · ${row.cameraName}`}>
                          <strong>{row.cameraCode}</strong> <span className="faint">{row.cameraName}</span>
                        </span>
                      </td>
                      {/* Compact in the column, full on the cell (§24). */}
                      <td className="num" title={displayTimestamp(row.recordingStartUtc, displayZone)}>
                        {compactTimestamp(row.recordingStartUtc, displayZone)}
                      </td>
                      <td className="num">{formatDuration(row.durationMs)}</td>
                      <td>
                        {/* One badge (§16). Live progress belongs in the same
                            cell as the state it is the detail of, never as a
                            second badge describing the same thing. */}
                        <div className="run-cell">
                          <span className="run-cell__line">
                            <StatusBadge status={row.processingStatus} />
                            {active && run ? <Progress value={run.progressPercent} inline /> : null}
                          </span>
                          {statusError ? (
                            <span className="run-cell__line">
                              <span className="text-err">Live status unavailable</span>
                              <Button size="sm" variant="ghost" icon="refresh" onClick={() => processing.retry(row.id)}>Retry</Button>
                            </span>
                          ) : null}
                          {row.processingStatus === 'Failed' && run?.failureCode ? (
                            <span className="run-cell__line"><code>{run.failureCode}</code></span>
                          ) : null}
                        </div>
                      </td>
                      <td>
                        {/* One primary text action, plus at most one icon-only
                            secondary (§16). While a video is processing there
                            is nothing to open and nothing to queue, so its
                            detail becomes the primary action rather than
                            leaving the row with a lone icon. */}
                        <div className="table__actions">
                          {row.processingStatus === 'Processed' ? (
                            <ButtonLink size="sm" variant="primary" to={`/search?videoAssetId=${row.id.toLowerCase()}`} icon="search">
                              Results
                            </ButtonLink>
                          ) : null}
                          {canQueue(row.processingStatus) ? (
                            <Button
                              size="sm"
                              variant="primary"
                              icon="play"
                              disabled={queue.isPending && queue.variables === row.id}
                              onClick={() => queue.mutate(row.id)}
                            >
                              {row.processingStatus === 'Failed' ? 'Retry' : 'Process'}
                            </Button>
                          ) : null}
                          {active ? (
                            <ButtonLink size="sm" to={`/processing/${row.id.toLowerCase()}`} icon="activity">Detail</ButtonLink>
                          ) : (
                            <ButtonLink size="sm" variant="ghost" to={`/processing/${row.id.toLowerCase()}`} title="Processing detail" iconOnly icon="activity">
                              Processing detail for {row.originalFileName}
                            </ButtonLink>
                          )}
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
