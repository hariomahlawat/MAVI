import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import type { FormEvent } from 'react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { searchTracks, type TrackObjectClass } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import { configuredUtcToWallTime, configuredWallTimeToUtc } from '../../shared/time/wallTime';
import TrackResultCard from './TrackResultCard';
import {
  canonicalSearchParams,
  compareUtcInstants,
  confidenceFractionToPercentText,
  confidencePercentTextToFraction,
  millisecondsToSecondsText,
  parseCommittedSearch,
  secondsTextToMilliseconds,
  type CommittedTrackSearch,
} from './searchState';

const PAGE_SIZE = 24;

type SearchDraft = {
  cameraId: string;
  objectClass: '' | TrackObjectClass;
  fromLocal: string;
  toLocal: string;
  minimumDurationSeconds: string;
  minimumConfidencePercent: string;
};

type TimeDirtyState = {
  from: boolean;
  to: boolean;
};

type NumericDirtyState = {
  duration: boolean;
  confidence: boolean;
};

const emptyDraft: SearchDraft = {
  cameraId: '',
  objectClass: '',
  fromLocal: '',
  toLocal: '',
  minimumDurationSeconds: '',
  minimumConfidencePercent: '',
};

function wallValue(utc: string | undefined, timeZoneId: string | undefined): string {
  if (!utc || !timeZoneId) return '';
  try {
    return configuredUtcToWallTime(utc, timeZoneId);
  } catch {
    return '';
  }
}

function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

export default function VisualSearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchString = searchParams.toString();
  const committed = useMemo(
    () => parseCommittedSearch(new URLSearchParams(searchString)),
    [searchString],
  );
  const activeFilters = committed.isValid ? committed.filters : {};
  const fingerprint = committed.isValid ? committed.canonicalQuery : 'invalid:' + searchString;
  const trackQueryKey = queryKeys.trackSearch(fingerprint);
  const queryClient = useQueryClient();

  const cameras = useQuery({
    queryKey: queryKeys.cameras,
    queryFn: ({ signal }) => listCameras(signal),
  });

  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    staleTime: 60_000,
  });
  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId;

  const [draft, setDraft] = useState<SearchDraft>(emptyDraft);
  const [timeDirty, setTimeDirty] = useState<TimeDirtyState>({ from: false, to: false });
  const [numericDirty, setNumericDirty] = useState<NumericDirtyState>({ duration: false, confidence: false });
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const filters = committed.isValid ? committed.filters : {};
    setDraft({
      cameraId: filters.cameraId ?? '',
      objectClass: filters.objectClass ?? '',
      fromLocal: wallValue(filters.fromUtc, displayTimeZoneId),
      toLocal: wallValue(filters.toUtc, displayTimeZoneId),
      minimumDurationSeconds: millisecondsToSecondsText(filters.minimumDurationMs),
      minimumConfidencePercent: confidenceFractionToPercentText(filters.minimumConfidence),
    });
    setTimeDirty({ from: false, to: false });
    setNumericDirty({ duration: false, confidence: false });
    setFormError(null);
    // Route identity owns full draft rehydration. Config recovery is handled separately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchString]);

  useEffect(() => {
    if (!displayTimeZoneId || !committed.isValid) return;
    setDraft((current) => ({
      ...current,
      fromLocal: timeDirty.from
        ? current.fromLocal
        : wallValue(committed.filters.fromUtc, displayTimeZoneId),
      toLocal: timeDirty.to
        ? current.toLocal
        : wallValue(committed.filters.toUtc, displayTimeZoneId),
    }));
  }, [displayTimeZoneId, committed, timeDirty.from, timeDirty.to]);

  const tracks = useInfiniteQuery({
    queryKey: trackQueryKey,
    queryFn: ({ pageParam, signal }) => searchTracks({
      ...activeFilters,
      cursor: pageParam ?? undefined,
      limit: PAGE_SIZE,
    }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    enabled: committed.isValid,
    retry: shouldRetryQuery,
  });

  const items = tracks.data?.pages.flatMap((page) => page.items) ?? [];
  const selectedCameraKnown = draft.cameraId
    ? cameras.data?.some((camera) => camera.id.toLowerCase() === draft.cameraId.toLowerCase()) ?? false
    : true;

  const commitFilters = (next: CommittedTrackSearch) => {
    setFormError(null);
    setSearchParams(canonicalSearchParams(next));
  };

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next: CommittedTrackSearch = committed.isValid ? { ...committed.filters } : {};

    if (draft.cameraId) next.cameraId = draft.cameraId.toLowerCase();
    else delete next.cameraId;

    if (draft.objectClass) next.objectClass = draft.objectClass;
    else delete next.objectClass;

    try {
      if (numericDirty.duration) {
        const duration = secondsTextToMilliseconds(draft.minimumDurationSeconds);
        if (duration === undefined) delete next.minimumDurationMs;
        else next.minimumDurationMs = duration;
      }

      if (numericDirty.confidence) {
        const confidence = confidencePercentTextToFraction(draft.minimumConfidencePercent);
        if (confidence === undefined) delete next.minimumConfidence;
        else next.minimumConfidence = confidence;
      }

      if (timeDirty.from) {
        if (!draft.fromLocal) {
          delete next.fromUtc;
        } else {
          if (!displayTimeZoneId) throw new RangeError('Display timezone is unavailable; the From time cannot be edited safely.');
          next.fromUtc = configuredWallTimeToUtc(draft.fromLocal, displayTimeZoneId);
        }
      }

      if (timeDirty.to) {
        if (!draft.toLocal) {
          delete next.toUtc;
        } else {
          if (!displayTimeZoneId) throw new RangeError('Display timezone is unavailable; the To time cannot be edited safely.');
          next.toUtc = configuredWallTimeToUtc(draft.toLocal, displayTimeZoneId);
        }
      }

      if (next.fromUtc && next.toUtc && compareUtcInstants(next.fromUtc, next.toUtc) >= 0) {
        throw new RangeError('From time must be earlier than To time.');
      }

      commitFilters(next);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Search filters are invalid.');
    }
  };

  const resetSearch = () => {
    setFormError(null);
    setDraft(emptyDraft);
    setTimeDirty({ from: false, to: false });
    setNumericDirty({ duration: false, confidence: false });
    setSearchParams(new URLSearchParams());
  };

  const clearTimeScope = () => {
    if (!committed.isValid) return;
    const next = { ...committed.filters };
    delete next.fromUtc;
    delete next.toUtc;
    commitFilters(next);
  };

  const removeAdvancedScope = (key: 'videoAssetId' | 'processingRunId') => {
    if (!committed.isValid) return;
    const next = { ...committed.filters };
    delete next[key];
    commitFilters(next);
  };

  const continuationInvalid = tracks.isFetchNextPageError
    && tracks.error instanceof ApiError
    && tracks.error.code === 'track_search_invalid';

  return (
    <section className="page-stack">
      <PageHeader
        title="Visual Search"
        description="Search authoritative person and vehicle Tracks. Filters are bookmarkable; result pagination uses a stable backend snapshot."
      />

      {!committed.isValid ? <Alert tone="error">{committed.error}</Alert> : null}
      {formError ? <Alert tone="error">{formError}</Alert> : null}
      {systemConfig.isError ? (
        <Alert tone="warning">
          <div className="inline-alert-actions">
            <span>
              Display timezone is unavailable. Existing UTC time scope remains active; time editing is disabled and result timestamps are shown explicitly in UTC.
            </span>
            <button className="button button--secondary" type="button" onClick={() => void systemConfig.refetch()}>
              Retry display config
            </button>
          </div>
        </Alert>
      ) : null}
      {cameras.isError ? (
        <Alert tone="warning">
          Camera metadata is unavailable. Any committed camera identifier remains active and Track search continues without broadening its scope.
        </Alert>
      ) : null}

      <form className="panel search-panel" onSubmit={submitSearch} noValidate>
        <div className="search-filter-grid">
          <label>
            Camera
            <select
              value={draft.cameraId}
              onChange={(event) => setDraft((current) => ({ ...current, cameraId: event.target.value }))}
            >
              <option value="">Any camera</option>
              {draft.cameraId && !selectedCameraKnown ? (
                <option value={draft.cameraId}>Camera ID · {draft.cameraId}</option>
              ) : null}
              {cameras.data?.map((camera) => (
                <option key={camera.id} value={camera.id.toLowerCase()}>
                  {camera.code} · {camera.name}{camera.isActive ? '' : ' · Inactive'}
                </option>
              ))}
            </select>
          </label>

          <label>
            Object class
            <select
              value={draft.objectClass}
              onChange={(event) => setDraft((current) => ({
                ...current,
                objectClass: event.target.value as '' | TrackObjectClass,
              }))}
            >
              <option value="">Any class</option>
              <option value="Person">Person</option>
              <option value="Vehicle">Vehicle</option>
            </select>
          </label>

          <label>
            From
            <input
              type="datetime-local"
              step="1"
              value={draft.fromLocal}
              disabled={!displayTimeZoneId}
              onChange={(event) => {
                setTimeDirty((current) => ({ ...current, from: true }));
                setDraft((current) => ({ ...current, fromLocal: event.target.value }));
              }}
            />
          </label>

          <label>
            To
            <input
              type="datetime-local"
              step="1"
              value={draft.toLocal}
              disabled={!displayTimeZoneId}
              onChange={(event) => {
                setTimeDirty((current) => ({ ...current, to: true }));
                setDraft((current) => ({ ...current, toLocal: event.target.value }));
              }}
            />
          </label>

          <label>
            Minimum duration (seconds)
            <input
              inputMode="decimal"
              value={draft.minimumDurationSeconds}
              onChange={(event) => {
                setNumericDirty((current) => ({ ...current, duration: true }));
                setDraft((current) => ({
                  ...current,
                  minimumDurationSeconds: event.target.value,
                }));
              }}
              placeholder="e.g. 2.5"
            />
          </label>

          <label>
            Minimum confidence (%)
            <input
              inputMode="decimal"
              value={draft.minimumConfidencePercent}
              onChange={(event) => {
                setNumericDirty((current) => ({ ...current, confidence: true }));
                setDraft((current) => ({
                  ...current,
                  minimumConfidencePercent: event.target.value,
                }));
              }}
              placeholder="e.g. 80"
            />
          </label>
        </div>

        <div className="search-panel__meta">
          <span>
            Display timezone: <code>{displayTimeZoneId ?? 'Unavailable'}</code>
          </span>
          <span>Page size: {PAGE_SIZE}</span>
        </div>

        {(activeFilters.fromUtc || activeFilters.toUtc) ? (
          <div className="scope-row" aria-label="Active time scope">
            <span className="scope-chip">
              Time · {activeFilters.fromUtc ?? 'open start'} → {activeFilters.toUtc ?? 'open end'}
              <button type="button" onClick={clearTimeScope} aria-label="Remove time scope">×</button>
            </span>
          </div>
        ) : null}

        {(activeFilters.videoAssetId || activeFilters.processingRunId) ? (
          <div className="scope-row" aria-label="Active advanced scopes">
            {activeFilters.videoAssetId ? (
              <span className="scope-chip">
                Video · {activeFilters.videoAssetId}
                <button type="button" onClick={() => removeAdvancedScope('videoAssetId')} aria-label="Remove video scope">×</button>
              </span>
            ) : null}
            {activeFilters.processingRunId ? (
              <span className="scope-chip">
                Run · {activeFilters.processingRunId}
                <button type="button" onClick={() => removeAdvancedScope('processingRunId')} aria-label="Remove processing run scope">×</button>
              </span>
            ) : null}
          </div>
        ) : null}

        <div className="button-row">
          <button className="button button--primary" type="submit">Search</button>
          <button className="button button--secondary" type="button" onClick={resetSearch}>Reset</button>
        </div>
      </form>

      {committed.isValid && tracks.isPending ? <LoadingState label="Searching visual intelligence…" /> : null}

      {tracks.isError && items.length === 0 ? (
        <Alert tone="error">
          {tracks.error instanceof ApiError
            ? tracks.error.detail + ' (' + tracks.error.code + ')'
            : 'Visual search could not be completed.'}
        </Alert>
      ) : null}

      {!tracks.isPending && !tracks.isError && committed.isValid && items.length === 0 ? (
        <div className="panel empty-state">
          <strong>No Tracks matched this search.</strong>
          <span>Adjust the committed filters or reset to view the newest available Tracks.</span>
        </div>
      ) : null}

      {items.length > 0 ? (
        <>
          <div className="results-header">
            <div>
              <strong>{items.length} Track{items.length === 1 ? '' : 's'} loaded</strong>
              <span>Newest Tracks first · stable cursor snapshot</span>
            </div>
          </div>

          <div className="track-grid">
            {items.map((track) => (
              <TrackResultCard
                key={track.id}
                track={track}
                displayTimeZoneId={displayTimeZoneId}
              />
            ))}
          </div>

          {tracks.isFetchNextPageError ? (
            <Alert tone={continuationInvalid ? 'warning' : 'error'}>
              {continuationInvalid
                ? 'This result snapshot can no longer continue. Refresh results to start a new snapshot with the same committed filters.'
                : 'The next page could not be loaded. Existing results remain available.'}
            </Alert>
          ) : null}

          <div className="load-more-row">
            {continuationInvalid ? (
              <button
                className="button button--secondary"
                type="button"
                onClick={() => void queryClient.resetQueries({ queryKey: trackQueryKey, exact: true })}
              >
                Refresh results
              </button>
            ) : tracks.hasNextPage ? (
              <button
                className="button button--secondary"
                type="button"
                disabled={tracks.isFetchingNextPage}
                onClick={() => void tracks.fetchNextPage()}
              >
                {tracks.isFetchingNextPage
                  ? 'Loading…'
                  : tracks.isFetchNextPageError ? 'Retry load more' : 'Load more'}
              </button>
            ) : (
              <span className="results-end">End of this result snapshot.</span>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}
