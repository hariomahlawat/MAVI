import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { isFinalizationFailure, isFinalizing, listVideos, queueProcessing } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import { hasFailure } from '../../shared/async/asyncState';
import StateRegion, { SupportingRequestNotice } from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import DisplayTimeZone from '../../shared/components/DisplayTimeZone';
import { FilteredEmptyState } from '../../shared/components/EmptyState';
import Progress from '../../shared/components/Progress';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { compactTimestamp, displayTimestamp, formatCount } from '../../shared/format/format';
import { FINALIZATION_FAILED_LABEL, isActiveStatus, VIDEO_STATUSES } from '../../shared/status/status';
import { SortableColumn, sortRows, useLedgerSort } from '../../shared/table';
import TruncatedText from '../../shared/overlay/Truncated';
import { ContextBar, LEDGER_SKELETON, LedgerLayout, LedgerTable, Toolbar } from '../../shared/workspace';
import { useVideoProcessing } from './useVideoProcessing';
import { compareVideoRows, filterVideoRows, joinVideoRows, parseStatusFilter, type VideoColumn, type VideoRow } from './videoRows';

function canQueue(status: string): boolean {
  return status === 'NotQueued' || status === 'Failed';
}

/**
 * Rows whose cell reads the latest run: live progress while active, and the
 * failure kind and code once failed. A failed row is fetched, not polled —
 * `processingPollInterval` is false for a terminal run.
 */
function needsRunStatus(status: string): boolean {
  return isActiveStatus(status) || status === 'Failed';
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

  // Only rows whose cell reads the latest run look it up; the rest read the
  // authoritative status the list already carries.
  const runStatusIds = useMemo(
    () => rows.filter((row) => needsRunStatus(row.processingStatus)).map((row) => row.id),
    [rows],
  );
  const processing = useVideoProcessing(runStatusIds);

  // One mutation serves every row, so which rows are being queued, and which
  // one failed, is tracked per video: the mutation's own `variables` name only
  // the latest call, and a row queued first must stay disabled until its own
  // request — and the refresh after it — has settled.
  const [queueing, setQueueing] = useState<ReadonlySet<string>>(() => new Set());
  const [queueFailure, setQueueFailure] = useState<{ readonly videoId: string; readonly error: unknown } | null>(null);
  const queue = useMutation({
    mutationFn: (videoId: string) => queueProcessing(videoId),
    onMutate: (videoId) => {
      setQueueing((current) => new Set(current).add(videoId));
      setQueueFailure((current) => (current?.videoId === videoId ? null : current));
    },
    onError: (error, videoId) => {
      // `processing_already_active` is reconciled rather than reported: the
      // video is already doing what the operator asked for.
      if (!(error instanceof ApiError && error.code === 'processing_already_active')) setQueueFailure({ videoId, error });
    },
    onSettled: async (_result, _error, videoId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.videos }),
        queryClient.invalidateQueries({ queryKey: queryKeys.videoProcessing(videoId) }),
      ]);
      setQueueing((current) => {
        const next = new Set(current);
        next.delete(videoId);
        return next;
      });
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

  // A reconciled `processing_already_active` never becomes a failure, so it
  // cannot open an empty notices region either.
  const queueFailed = queueFailure !== null;
  const failedName = queueFailure ? videos.data?.find((video) => video.id === queueFailure.videoId)?.originalFileName : undefined;
  const camerasState = fromQuery(cameras);
  // The display timezone has no region of its own (§37.1): timestamps fall back
  // to explicit UTC, and the page says so once, with its own Retry.
  const zoneState = fromQuery(systemConfig);
  const hasNotices = hasFailure(camerasState) || hasFailure(zoneState) || queueFailed;
  const notices = (
    <>
      <SupportingRequestNotice
        state={zoneState}
        unavailableMessage="Display timezone is unavailable. Absolute timestamps are shown explicitly in UTC."
        degradedMessage="Display configuration could not be refreshed. The last known timezone remains in use."
        onRetry={() => void systemConfig.refetch()}
        retryLabel="Retry display config"
      />
      <SupportingRequestNotice
        state={camerasState}
        unavailableMessage="Camera metadata is unavailable; videos are listed by camera identifier."
        degradedMessage="Showing the last known camera names; refreshing camera metadata failed."
        onRetry={() => void cameras.refetch()}
      />
      {queueFailure ? (
        <Alert tone="error">
          {describeError(queueFailure.error, failedName ? `Processing could not be queued for ${failedName}.` : 'Processing could not be queued.')}
        </Alert>
      ) : null}
    </>
  );

  return (
    <section className="page page--full page--workspace">
      <ContextBar
        surface="videos"
        status={<DisplayTimeZone timeZoneId={displayZone} />}
        actions={<ButtonLink to="/import" variant="primary" icon="upload">Import video</ButtonLink>}
      />

      <LedgerLayout toolbar={toolbar} notices={hasNotices ? notices : null}>
        <StateRegion
          kind="column"
          state={fromQuery(videos)}
          label="videos"
          skeleton={LEDGER_SKELETON}
          isEmpty={(all) => all.length === 0}
          empty={{
            icon: 'video',
            title: 'No videos imported yet',
            body: 'Import an MP4 recording against a registered camera to begin.',
            // Secondary: the Context Bar's `Import video` is this surface's one
            // primary (§8.1).
            action: <ButtonLink to="/import">Import the first video</ButtonLink>,
          }}
          unavailableMessage={(error) => describeError(error, 'Video inventory is unavailable.')}
          degradedMessage="Showing the last known media inventory; refreshing failed."
          onRetry={() => videos.refetch()}
        >
          {() => rows.length === 0 ? (
            // Filtered-empty is not empty: the inventory is real (§37.1).
            <div className="state-region state-region--column state-region--inline">
              <FilteredEmptyState subject="videos" onClear={() => setParams(new URLSearchParams(), { replace: true })} />
            </div>
          ) : (
            <LedgerTable caption="Imported videos">
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
                  const liveState = processing.stateOf(row.id);
                  return (
                    <tr key={row.id}>
                      <td><TruncatedText text={row.originalFileName} className="cap-lg" /></td>
                      <td>
                        <TruncatedText text={`${row.cameraCode} · ${row.cameraName}`} className="cap-md">
                          <strong>{row.cameraCode}</strong> <span className="faint">{row.cameraName}</span>
                        </TruncatedText>
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
                            {/* Inference progress only: finalization has none. */}
                            {active && run && !isFinalizing(run) ? <Progress value={run.progressPercent} inline /> : null}
                            {/* The code rides the status line rather than a
                                second one: a failed row is still one row. */}
                            {row.processingStatus === 'Failed' && run?.failureCode ? (
                              <code><TruncatedText text={run.failureCode} className="cap-sm" /></code>
                            ) : null}
                          </span>
                          {/* The run's phase, where it says more than the badge (§16). */}
                          {active && isFinalizing(run) ? <span className="run-cell__line"><TruncatedText text="Run: Finalizing" /></span> : null}
                          {row.processingStatus === 'Failed' && isFinalizationFailure(run) ? (
                            <span className="run-cell__line"><TruncatedText text={`Run: ${FINALIZATION_FAILED_LABEL}`} /></span>
                          ) : null}
                          {/* The row's run lookup is its own request (§37.1,
                              row): the row keeps its identity and the cell
                              says why the looked-up part is missing — the live
                              progress of an active run, or a failed run's code
                              and kind, which is otherwise silently absent. */}
                          {(active || row.processingStatus === 'Failed') && hasFailure(liveState) ? (
                            <span className="run-cell__line">
                              <StateRegion
                                kind="row"
                                state={liveState}
                                label={active ? 'live status' : 'failure detail'}
                                unavailableMessage={() => (active ? 'Live status unavailable' : 'Failure detail unavailable')}
                                degradedMessage={active ? 'Live status may be out of date' : 'Failure detail may be out of date'}
                                onRetry={() => processing.retry(row.id)}
                                // A failed row's own action is already "Retry"
                                // (processing): the lookup's control is named
                                // for what it does, and in this dense cell it is
                                // an icon so the message, not it, gives way.
                                retryLabel={active ? `Retry live status for ${row.originalFileName}` : `Reload failure detail for ${row.originalFileName}`}
                                compactRetry
                              >
                                {() => null}
                              </StateRegion>
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td>
                        {/* One secondary text action, plus at most one
                            icon-only action (§16). A row never carries the
                            accent-filled primary (§8.1): the surface's one
                            primary is the Context Bar's `Import video`. While a
                            video is processing there is nothing to open and
                            nothing to queue, so its detail becomes the text
                            action rather than leaving the row with a lone icon. */}
                        <div className="table__actions">
                          {row.processingStatus === 'Processed' ? (
                            <ButtonLink size="sm" to={`/search?videoAssetId=${row.id.toLowerCase()}`} icon="search">
                              Results
                            </ButtonLink>
                          ) : null}
                          {canQueue(row.processingStatus) ? (
                            <Button
                              size="sm"
                              icon="play"
                              disabled={queueing.has(row.id)}
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
            </LedgerTable>
          )}
        </StateRegion>
      </LedgerLayout>
    </section>
  );
}
