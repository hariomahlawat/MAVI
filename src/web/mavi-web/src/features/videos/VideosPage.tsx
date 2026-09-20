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
import EmptyState from '../../shared/components/EmptyState';
import Icon from '../../shared/components/Icon';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import Panel from '../../shared/components/Panel';
import Progress from '../../shared/components/Progress';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp } from '../../shared/format/format';
import { isActiveStatus, VIDEO_STATUSES } from '../../shared/status/status';
import { useVideoProcessing } from './useVideoProcessing';
import { filterVideoRows, joinVideoRows, parseStatusFilter, sortVideoRows, type VideoRow } from './videoRows';

function canQueue(status: string): boolean {
  return status === 'NotQueued' || status === 'Failed';
}

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

  const rows = useMemo(() => {
    if (!videos.data) return [] as VideoRow[];
    return filterVideoRows(sortVideoRows(joinVideoRows(videos.data, cameras.data)), filters);
  }, [videos.data, cameras.data, filters.cameraId, filters.status, filters.text]);

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
  const filtered = filters.cameraId || filters.status || filters.text;

  return (
    <section className="page">
      <PageHeader
        title="Videos"
        description="Every imported source video, its processing state, and the way into its results."
        actions={<ButtonLink to="/import" variant="primary" icon="upload">Import video</ButtonLink>}
      />

      {cameras.isError ? <Alert tone="warning">Camera metadata is unavailable; videos are listed by camera identifier.</Alert> : null}
      {queue.isError && !(queue.error instanceof ApiError && queue.error.code === 'processing_already_active') ? (
        <Alert tone="error">
          {queue.error instanceof ApiError ? `${queue.error.detail} (${queue.error.code})` : 'Processing could not be queued.'}
        </Alert>
      ) : null}

      <Panel
        body="flush"
        title="Media inventory"
        description={
          videos.data
            ? `${rows.length} of ${total} video${total === 1 ? '' : 's'}${filtered ? ' match the filters' : ''}`
            : undefined
        }
        actions={(
          <div className="toolbar">
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
          </div>
        )}
      >
        <AsyncBoundary
          state={fromQuery(videos)}
          loading={<div className="panel__body"><LoadingState label="Loading videos…" rows={4} /></div>}
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
            <EmptyState icon="filter" title="No videos match these filters" compact actions={<Button size="sm" onClick={() => setParams(new URLSearchParams(), { replace: true })}>Clear filters</Button>} />
          ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Video</th>
                  <th scope="col">Camera</th>
                  <th scope="col">Recorded</th>
                  <th scope="col" className="num">Duration</th>
                  <th scope="col">Status</th>
                  <th scope="col"><span className="visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const status = processing.byVideo.get(row.id);
                  const run = status?.latestRun;
                  const active = isActiveStatus(row.processingStatus);
                  const statusError = active ? processing.errors.get(row.id) : undefined;
                  return (
                    <tr key={row.id}>
                      <td>
                        <div className="video-title">
                          <strong className="truncate" title={row.originalFileName}>{row.originalFileName}</strong>
                          <span>{row.width}×{row.height}{row.codecName ? ` · ${row.codecName}` : ''}</span>
                        </div>
                      </td>
                      <td>
                        <div className="video-title">
                          <strong>{row.cameraCode}</strong>
                          <span className="truncate">{row.cameraName}</span>
                        </div>
                      </td>
                      <td className="num" title={row.recordingStartUtc}>{displayTimestamp(row.recordingStartUtc, displayZone)}</td>
                      <td className="num">{formatDuration(row.durationMs)}</td>
                      <td>
                        <div className="run-cell">
                          <StatusBadge status={row.processingStatus} />
                          {active && run ? (
                            <Progress value={run.progressPercent} inline label={undefined} />
                          ) : null}
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
                        <div className="table__actions">
                          {row.processingStatus === 'Processed' ? (
                            <ButtonLink size="sm" variant="primary" to={`/search?videoAssetId=${row.id.toLowerCase()}`} icon="search">
                              Results
                            </ButtonLink>
                          ) : null}
                          {canQueue(row.processingStatus) ? (
                            <Button
                              size="sm"
                              icon="play"
                              disabled={queue.isPending && queue.variables === row.id}
                              onClick={() => queue.mutate(row.id)}
                            >
                              {row.processingStatus === 'Failed' ? 'Retry' : 'Process'}
                            </Button>
                          ) : null}
                          <ButtonLink size="sm" variant="ghost" to={`/processing/${row.id.toLowerCase()}`} title="Processing detail" iconOnly icon="activity">
                            Processing detail for {row.originalFileName}
                          </ButtonLink>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          )}
        </AsyncBoundary>
      </Panel>

      {activeIds.length > 0 ? (
        <p className="small faint row"><Icon name="clock" size="sm" /> {activeIds.length} video{activeIds.length === 1 ? ' is' : 's are'} processing; status refreshes every 2 seconds.</p>
      ) : null}
    </section>
  );
}
