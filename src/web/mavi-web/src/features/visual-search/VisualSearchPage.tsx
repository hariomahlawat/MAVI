import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import type { FormEvent } from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { listCameras } from '../../api/cameras';
import { ApiError, isGuid } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { searchTracks } from '../../api/tracks';
import { listVideos } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import { configuredUtcToWallTime, configuredWallTimeToUtc } from '../../shared/time/wallTime';
import { isNavigationTarget, nearEnd, neighbourId, selectedIndex } from './resultNavigation';
import SearchFilterRail, { emptyDraft, type SearchDraft } from './SearchFilterRail';
import TrackInspector from './TrackInspector';
import TrackResultCard from './TrackResultCard';
import TrackResultList, { reviewPath } from './TrackResultList';
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
const SELECTION_PARAM = 'track';
const VIEW_STORAGE_KEY = 'mavi.search.view';

type ResultView = 'list' | 'grid';
type TimeDirtyState = { from: boolean; to: boolean };
type NumericDirtyState = { duration: boolean; confidence: boolean };

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

function readView(): ResultView {
  try {
    return window.localStorage.getItem(VIEW_STORAGE_KEY) === 'grid' ? 'grid' : 'list';
  } catch {
    return 'list';
  }
}

/**
 * Search workspace: committed filters (URL) on the left, the result snapshot in
 * the middle and, when a `track` is selected, the in-place inspector on the
 * right. Selection is URL state too, so a deep link reopens the same view.
 */
export default function VisualSearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const searchString = searchParams.toString();
  const committed = useMemo(
    () => parseCommittedSearch(new URLSearchParams(searchString)),
    [searchString],
  );
  const activeFilters = committed.isValid ? committed.filters : {};
  const fingerprint = committed.isValid ? committed.canonicalQuery : 'invalid:' + searchString;
  const trackQueryKey = queryKeys.trackSearch(fingerprint);
  const queryClient = useQueryClient();

  const rawSelection = searchParams.get(SELECTION_PARAM);
  const selectedId = rawSelection && isGuid(rawSelection) ? rawSelection.toLowerCase() : null;

  const cameras = useQuery({
    queryKey: queryKeys.cameras,
    queryFn: ({ signal }) => listCameras(signal),
  });
  const videos = useQuery({
    queryKey: queryKeys.videos,
    queryFn: ({ signal }) => listVideos(signal),
    staleTime: 30_000,
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
  const [view, setView] = useState<ResultView>(readView);

  useEffect(() => {
    try {
      window.localStorage.setItem(VIEW_STORAGE_KEY, view);
    } catch {
      // Losing the preference is harmless.
    }
  }, [view]);

  // Committed filters own draft rehydration. Selecting a result changes the
  // URL too, but must not discard what the operator has typed in the rail.
  useEffect(() => {
    const filters = committed.isValid ? committed.filters : {};
    setDraft({
      cameraId: filters.cameraId ?? '',
      videoAssetId: filters.videoAssetId ?? '',
      objectClass: filters.objectClass ?? '',
      fromLocal: wallValue(filters.fromUtc, displayTimeZoneId),
      toLocal: wallValue(filters.toUtc, displayTimeZoneId),
      minimumDurationSeconds: millisecondsToSecondsText(filters.minimumDurationMs),
      minimumConfidencePercent: confidenceFractionToPercentText(filters.minimumConfidence),
    });
    setTimeDirty({ from: false, to: false });
    setNumericDirty({ duration: false, confidence: false });
    setFormError(null);
    // Config recovery is handled separately below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fingerprint]);

  useEffect(() => {
    if (!displayTimeZoneId || !committed.isValid) return;
    setDraft((current) => ({
      ...current,
      fromLocal: timeDirty.from ? current.fromLocal : wallValue(committed.filters.fromUtc, displayTimeZoneId),
      toLocal: timeDirty.to ? current.toLocal : wallValue(committed.filters.toUtc, displayTimeZoneId),
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

  const items = useMemo(() => tracks.data?.pages.flatMap((page) => page.items) ?? [], [tracks.data]);
  const position = selectedIndex(items, selectedId);
  const hasMore = Boolean(tracks.hasNextPage);

  // A next-page advance the operator asked for; see the effect below.
  const pendingAdvance = useRef<{ fingerprint: string; fromId: string } | null>(null);

  const selectTrack = useCallback((id: string | null) => {
    if (id === null) pendingAdvance.current = null;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (id) next.set(SELECTION_PARAM, id);
      else next.delete(SELECTION_PARAM);
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const { fetchNextPage, isFetchingNextPage, isFetchNextPageError } = tracks;
  // Continuation is automatic only while it succeeds. After a failure the
  // operator decides: "Retry load more" for a transient error, "Refresh
  // results" for an expired snapshot. The query itself retries a 5xx once.
  const canContinue = hasMore && !isFetchingNextPage && !isFetchNextPageError;

  // Keep one page ahead of the operator while they step through results.
  useEffect(() => {
    if (canContinue && nearEnd(items, selectedId)) void fetchNextPage();
  }, [items, selectedId, canContinue, fetchNextPage]);

  // Stepping past the last loaded row asks for the next page and remembers
  // where the operator was. The advance happens only when that page lands for
  // the same committed search with the same Track still selected; a changed
  // filter, a changed selection, a closed inspector or an unmount discards it.
  useEffect(() => {
    const pending = pendingAdvance.current;
    if (!pending) return;
    if (pending.fingerprint !== fingerprint || pending.fromId !== selectedId || isFetchNextPageError) {
      pendingAdvance.current = null;
      return;
    }
    const next = neighbourId(items, selectedId, 1);
    if (next) {
      pendingAdvance.current = null;
      selectTrack(next);
    }
  }, [items, fingerprint, selectedId, isFetchNextPageError, selectTrack]);

  const goPrevious = useCallback(() => {
    pendingAdvance.current = null;
    const previous = neighbourId(items, selectedId, -1);
    if (previous) selectTrack(previous);
  }, [items, selectedId, selectTrack]);

  const goNext = useCallback(() => {
    const next = neighbourId(items, selectedId, 1);
    if (next) {
      pendingAdvance.current = null;
      selectTrack(next);
      return;
    }
    if (!selectedId || !hasMore || isFetchNextPageError) return;
    pendingAdvance.current = { fingerprint, fromId: selectedId };
    if (!isFetchingNextPage) void fetchNextPage();
  }, [items, selectedId, hasMore, isFetchingNextPage, isFetchNextPageError, fingerprint, fetchNextPage, selectTrack]);

  // The committed search (without selection) travels with every review link so
  // the Review page can hand back to exactly this search.
  const searchContext = committed.isValid ? committed.canonicalQuery : '';

  const openSelected = useCallback(() => {
    const selected = position >= 0 ? items[position] : undefined;
    if (selected) navigate(reviewPath(selected, searchContext));
  }, [items, position, navigate, searchContext]);

  useEffect(() => {
    if (items.length === 0) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (!isNavigationTarget(event.target)) return;
      switch (event.key) {
        case 'j':
        case 'ArrowDown':
          event.preventDefault();
          goNext();
          break;
        case 'k':
        case 'ArrowUp':
          event.preventDefault();
          goPrevious();
          break;
        case 'Enter':
          if (selectedId && !(event.target instanceof HTMLElement && event.target.closest('a, button'))) {
            event.preventDefault();
            openSelected();
          }
          break;
        case 'Escape':
          if (selectedId) selectTrack(null);
          break;
        default:
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [items.length, selectedId, goNext, goPrevious, openSelected, selectTrack]);

  const commitFilters = (next: CommittedTrackSearch) => {
    setFormError(null);
    // A new committed search is a new snapshot; the old selection no longer applies.
    setSearchParams(canonicalSearchParams(next));
  };

  const onDraftChange = (patch: Partial<SearchDraft>, touched?: { time?: 'from' | 'to'; numeric?: 'duration' | 'confidence' }) => {
    setDraft((current) => ({ ...current, ...patch }));
    if (touched?.time) setTimeDirty((current) => ({ ...current, [touched.time as 'from' | 'to']: true }));
    if (touched?.numeric) setNumericDirty((current) => ({ ...current, [touched.numeric as 'duration' | 'confidence']: true }));
  };

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next: CommittedTrackSearch = committed.isValid ? { ...committed.filters } : {};

    if (draft.cameraId) next.cameraId = draft.cameraId.toLowerCase();
    else delete next.cameraId;

    if (draft.videoAssetId) next.videoAssetId = draft.videoAssetId.toLowerCase();
    else delete next.videoAssetId;

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

  const inspecting = selectedId !== null;

  return (
    <section className="page page--full page--workspace">
      <PageHeader
        title="Visual Search"
        description="Search authoritative person and vehicle Tracks. Filters are bookmarkable; result pagination uses a stable backend snapshot."
        actions={(
          <div className="toolbar__group" role="group" aria-label="Result view">
            <Button size="sm" iconOnly icon="list" aria-pressed={view === 'list'} onClick={() => setView('list')} title="List view">List view</Button>
            <Button size="sm" iconOnly icon="grid" aria-pressed={view === 'grid'} onClick={() => setView('grid')} title="Grid view">Grid view</Button>
          </div>
        )}
      />

      {!committed.isValid ? <Alert tone="error">{committed.error}</Alert> : null}
      {formError ? <Alert tone="error">{formError}</Alert> : null}
      {systemConfig.isError ? (
        <Alert tone="warning">
          <div className="inline-alert-actions">
            <span>
              Display timezone is unavailable. Existing UTC time scope remains active; time editing is disabled and result timestamps are shown explicitly in UTC.
            </span>
            <Button size="sm" onClick={() => void systemConfig.refetch()}>Retry display config</Button>
          </div>
        </Alert>
      ) : null}
      {cameras.isError ? (
        <Alert tone="warning">
          Camera metadata is unavailable. Any committed camera identifier remains active and Track search continues without broadening its scope.
        </Alert>
      ) : null}

      <div className={inspecting ? 'search-workspace search-workspace--inspecting' : 'search-workspace'}>
        <SearchFilterRail
          draft={draft}
          onDraftChange={onDraftChange}
          onSubmit={submitSearch}
          onReset={resetSearch}
          cameras={cameras.data}
          videos={videos.data}
          videosUnavailable={videos.isError}
          displayTimeZoneId={displayTimeZoneId}
          activeFilters={activeFilters}
          onClearTimeScope={clearTimeScope}
          onRemoveScope={removeAdvancedScope}
        />

        <section className="panel results" aria-label="Search results">
          <div className="results__head">
            <div className="video-title">
              <strong>
                {items.length > 0
                  ? `${items.length} Track${items.length === 1 ? '' : 's'} loaded${hasMore ? ' · more available' : ''}`
                  : 'Results'}
              </strong>
              <span>Newest Tracks first · stable cursor snapshot · page size {PAGE_SIZE}</span>
            </div>
            {items.length > 0 ? (
              <span className="hints" aria-hidden="true">
                <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>Enter</kbd> open · <kbd>Esc</kbd> close
              </span>
            ) : null}
          </div>

          {committed.isValid && tracks.isPending ? <LoadingState label="Searching visual intelligence…" /> : null}

          {tracks.isError && items.length === 0 ? (
            <div className="panel__body">
              <Alert tone="error">
                {tracks.error instanceof ApiError
                  ? tracks.error.detail + ' (' + tracks.error.code + ')'
                  : 'Visual search could not be completed.'}
              </Alert>
            </div>
          ) : null}

          {!tracks.isPending && !tracks.isError && committed.isValid && items.length === 0 ? (
            <EmptyState icon="search" title="No Tracks matched this search.">
              Adjust the committed filters or reset to view the newest available Tracks.
            </EmptyState>
          ) : null}

          {items.length > 0 ? (
            view === 'list' ? (
              <TrackResultList items={items} selectedId={selectedId} displayTimeZoneId={displayTimeZoneId} searchContext={searchContext} onSelect={selectTrack} />
            ) : (
              <div className="results__list">
                <div className="track-grid">
                  {items.map((track) => (
                    <TrackResultCard
                      key={track.id}
                      track={track}
                      displayTimeZoneId={displayTimeZoneId}
                      selected={selectedId !== null && track.id.toLowerCase() === selectedId}
                      searchContext={searchContext}
                      onSelect={selectTrack}
                    />
                  ))}
                </div>
              </div>
            )
          ) : null}

          {items.length > 0 ? (
            <div className="results__foot">
              {tracks.isFetchNextPageError ? (
                <Alert tone={continuationInvalid ? 'warning' : 'error'}>
                  {continuationInvalid
                    ? 'This result snapshot can no longer continue. Refresh results to start a new snapshot with the same committed filters.'
                    : 'The next page could not be loaded. Existing results remain available.'}
                </Alert>
              ) : null}
              {continuationInvalid ? (
                <Button icon="refresh" onClick={() => void queryClient.resetQueries({ queryKey: trackQueryKey, exact: true })}>
                  Refresh results
                </Button>
              ) : tracks.hasNextPage ? (
                <Button disabled={tracks.isFetchingNextPage} onClick={() => void tracks.fetchNextPage()}>
                  {tracks.isFetchingNextPage
                    ? 'Loading…'
                    : tracks.isFetchNextPageError ? 'Retry load more' : 'Load more'}
                </Button>
              ) : (
                <span className="results-end">End of this result snapshot.</span>
              )}
            </div>
          ) : null}
        </section>

        {inspecting && selectedId ? (
          <TrackInspector
            key={selectedId}
            trackId={selectedId}
            position={position}
            total={items.length}
            hasMore={hasMore}
            displayTimeZoneId={displayTimeZoneId}
            searchContext={searchContext}
            summary={position >= 0 ? items[position] : undefined}
            onPrevious={goPrevious}
            onNext={goNext}
            onClose={() => selectTrack(null)}
          />
        ) : null}
      </div>
    </section>
  );
}
