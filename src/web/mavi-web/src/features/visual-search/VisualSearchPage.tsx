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
import { formatCount } from '../../shared/format/format';
import Icon from '../../shared/components/Icon';
import LoadingState from '../../shared/components/LoadingState';
import DisplayTimeZone from '../../shared/components/DisplayTimeZone';
import { configuredUtcToWallTime } from '../../shared/time/wallTime';
import { ContextBar, InvestigationLayout, Segmented } from '../../shared/workspace';
import { isNavigationTarget, nearEnd, neighbourId, selectedIndex } from './resultNavigation';
import { findSelectControl, isSelectedResultControl } from './resultSelection';
import CommittedFilterChips from './CommittedFilterChips';
import SearchFilterRail, { emptyDraft, type SearchDraft } from './SearchFilterRail';
import TrackInspector from './TrackInspector';
import TrackResultCard from './TrackResultCard';
import TrackResultList, { reviewPath } from './TrackResultList';
import {
  canonicalSearchKey,
  canonicalSearchParams,
  confidenceFractionToPercentText,
  millisecondsToSecondsText,
  parseCommittedSearch,
  type CommittedTrackSearch,
} from './searchState';
import { commitDraft, type SearchFieldErrors, type SearchFieldKey } from './searchValidation';

const PAGE_SIZE = 24;
const SELECTION_PARAM = 'track';
const VIEW_STORAGE_KEY = 'mavi.search.view';

type ResultView = 'list' | 'grid';

/**
 * Which draft fields the operator has changed since the committed state last
 * arrived. It decides two things that used to be decided separately: whether a
 * numeric or time value is recomputed on submit (an untouched one keeps the
 * committed value to whatever precision it was bookmarked with), and — new in
 * UI-4 — which fields survive a committed-state change the operator did not
 * make by pressing Search.
 */
type DirtyState = Partial<Record<keyof SearchDraft, true>>;

function wallValue(utc: string | undefined, timeZoneId: string | undefined): string {
  if (!utc || !timeZoneId) return '';
  try {
    return configuredUtcToWallTime(utc, timeZoneId);
  } catch {
    return '';
  }
}

/** The draft a committed search would produce if nothing had been typed. */
function draftFromFilters(filters: CommittedTrackSearch, timeZoneId: string | undefined): SearchDraft {
  return {
    cameraId: filters.cameraId ?? '',
    videoAssetId: filters.videoAssetId ?? '',
    objectClass: filters.objectClass ?? '',
    fromLocal: wallValue(filters.fromUtc, timeZoneId),
    toLocal: wallValue(filters.toUtc, timeZoneId),
    minimumDurationSeconds: millisecondsToSecondsText(filters.minimumDurationMs),
    minimumConfidencePercent: confidenceFractionToPercentText(filters.minimumConfidence),
  };
}

/**
 * Bring the draft back in line with committed state without discarding work.
 *
 * Removing a chip, following a deep link or stepping Back changes the committed
 * search without the operator having pressed Search, and the rail must not lose
 * what they were in the middle of typing because of it. Every untouched field
 * takes the committed value; every field they have changed keeps theirs.
 */
function rebaseUntouched(current: SearchDraft, rebased: SearchDraft, dirty: DirtyState): SearchDraft {
  const next = { ...rebased };
  for (const key of Object.keys(rebased) as Array<keyof SearchDraft>) {
    if (dirty[key]) (next as Record<string, string>)[key] = current[key];
  }
  return next;
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
 * Search — an Investigation (§4.4): committed filters (URL) in the rail, the
 * result snapshot in the middle and, when a `track` is selected, the inspector
 * beside it. Selection is URL state too, so a deep link reopens the same view.
 *
 * UI-4 replaces the presentation architecture and keeps the state machinery.
 * The surface used to own a page header, its own three-column CSS grid and its
 * own inspector shell, all of which were this feature's private restatement of
 * things §4.4 freezes; they are now the shared archetype's, which is what stops
 * the two drifting apart. Everything about *what* a search is — the committed
 * URL parameters, the draft that stays local until Search, the cursor snapshot
 * and its retry semantics — is deliberately untouched.
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
  const [dirty, setDirtyState] = useState<DirtyState>({});
  // The rebase effect below runs on a committed-state change and must know what
  // is dirty *now*, not what was dirty when it last ran — depending on the
  // state would re-run it on every keystroke and undo the keystroke. The ref is
  // written in the same call that sets the state so the two cannot disagree.
  const dirtyRef = useRef<DirtyState>({});
  const setDirty = useCallback((update: (current: DirtyState) => DirtyState) => {
    dirtyRef.current = update(dirtyRef.current);
    setDirtyState(dirtyRef.current);
  }, []);
  // Set when this surface commits a search itself. Only then is the draft known
  // to already say what the committed state says, so only then are the dirty
  // marks cleared; every other committed change rebases around them.
  const submittedFingerprint = useRef<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<SearchFieldErrors>({});
  const [view, setView] = useState<ResultView>(readView);

  useEffect(() => {
    try {
      window.localStorage.setItem(VIEW_STORAGE_KEY, view);
    } catch {
      // Losing the preference is harmless.
    }
  }, [view]);

  // Committed filters own draft rehydration. Selecting a result changes the URL
  // too, but must not discard what the operator has typed in the rail — which
  // is why this is keyed on the committed fingerprint and not on the URL.
  useEffect(() => {
    const filters = committed.isValid ? committed.filters : {};
    const rebased = draftFromFilters(filters, displayTimeZoneId);
    if (submittedFingerprint.current === fingerprint) {
      // Our own commit: the draft produced this state, so it already says what
      // the URL says and nothing is outstanding.
      submittedFingerprint.current = null;
      setDraft(rebased);
      setDirty(() => ({}));
    } else {
      setDraft((current) => rebaseUntouched(current, rebased, dirtyRef.current));
    }
    setFieldErrors({});
    // Config recovery is handled separately below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fingerprint]);

  // The display zone arrives asynchronously, and until it does a committed UTC
  // bound cannot be shown as a wall time at all. When it lands, the two time
  // fields are filled in — unless the operator has meanwhile typed into them.
  useEffect(() => {
    if (!displayTimeZoneId || !committed.isValid) return;
    setDraft((current) => ({
      ...current,
      fromLocal: dirtyRef.current.fromLocal ? current.fromLocal : wallValue(committed.filters.fromUtc, displayTimeZoneId),
      toLocal: dirtyRef.current.toLocal ? current.toLocal : wallValue(committed.filters.toUtc, displayTimeZoneId),
    }));
  }, [displayTimeZoneId, committed]);

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
  // Where focus goes when the inspector closes on a result that is no longer
  // in the list — the region it belonged to, rather than the document.
  const resultsRef = useRef<HTMLElement | null>(null);

  const selectTrack = useCallback((id: string | null) => {
    if (id === null) pendingAdvance.current = null;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (id) next.set(SELECTION_PARAM, id);
      else next.delete(SELECTION_PARAM);
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  /**
   * Close the inspector and put focus back where the operator left it.
   *
   * Closing removes the subtree that held focus, and focus then falls to the
   * document — from where the next Tab starts at the top of the page and the
   * shortcuts, which ignore text-entry contexts but not a lost focus, have
   * nothing to act on. It returns to the selection control of the result that
   * was open, or, when that result is no longer rendered, to the results region
   * itself rather than to nothing.
   */
  const closeInspector = useCallback(() => {
    const control = findSelectControl(selectedId);
    selectTrack(null);
    const fallback = resultsRef.current;
    const target = control ?? fallback;
    if (target) {
      // After the commit that removes the inspector, so the browser does not
      // move focus back out when the element it was in disappears.
      queueMicrotask(() => target.focus());
    }
  }, [selectedId, selectTrack]);

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
        case 'Enter': {
          // Enter opens the full review of the selected Track. It must not
          // steal Enter from other controls (links, filter buttons), but the
          // focused selection control of the already-selected result is exactly
          // the place an operator presses Enter after choosing one — in either
          // view, which is what `isSelectedResultControl` now decides in place
          // of a class name belonging to the List.
          if (!selectedId) break;
          const target = event.target instanceof HTMLElement ? event.target : null;
          const control = target?.closest('a, button');
          if (control && !isSelectedResultControl(control, selectedId)) break;
          event.preventDefault();
          openSelected();
          break;
        }
        case 'Escape':
          if (selectedId) closeInspector();
          break;
        default:
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [items.length, selectedId, goNext, goPrevious, openSelected, selectTrack]);

  // A new committed search is a new snapshot, so the old selection no longer
  // applies and neither does the cursor chain that produced it. `track` is left
  // out of the canonical parameters, which is what drops it.
  const commitFilters = useCallback((next: CommittedTrackSearch) => {
    setFieldErrors({});
    pendingAdvance.current = null;
    setSearchParams(canonicalSearchParams(next));
  }, [setSearchParams]);

  const onDraftChange = (patch: Partial<SearchDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    const keys = Object.keys(patch) as Array<keyof SearchDraft>;
    setDirty((current) => {
      const next = { ...current };
      for (const key of keys) next[key] = true;
      return next;
    });
    // A field the operator is correcting stops claiming to be wrong as soon as
    // they touch it; it is re-judged when they ask for the search again.
    setFieldErrors((current) => {
      if (!keys.some((key) => key in current)) return current;
      const next = { ...current };
      for (const key of keys) delete next[key as SearchFieldKey];
      return next;
    });
  };

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const result = commitDraft({
      draft,
      committed: committed.isValid ? committed.filters : {},
      timeDirty: { from: Boolean(dirty.fromLocal), to: Boolean(dirty.toLocal) },
      numericDirty: { duration: Boolean(dirty.minimumDurationSeconds), confidence: Boolean(dirty.minimumConfidencePercent) },
      displayTimeZoneId,
    });
    if (!result.ok) {
      setFieldErrors(result.errors);
      return;
    }
    const settled = canonicalSearchKey(result.filters);
    submittedFingerprint.current = settled;
    commitFilters(result.filters);

    // A search can commit the state the surface is already in — an edit that
    // canonicalises to the committed value, or a re-submission after nothing
    // changed. The URL is then identical, so nothing keyed on it runs and the
    // rehydrate above never happens: the field stays marked as an outstanding
    // edit that has in fact been committed. It would then survive the removal
    // of its own chip and reinstate the criterion on the next search.
    //
    // The commit did happen, so the draft is settled here instead.
    if (settled === fingerprint) {
      submittedFingerprint.current = null;
      setDraft(draftFromFilters(result.filters, displayTimeZoneId));
      setDirty(() => ({}));
    }
  };

  const resetSearch = () => {
    setFieldErrors({});
    setDraft(emptyDraft);
    setDirty(() => ({}));
    pendingAdvance.current = null;
    submittedFingerprint.current = '';
    setSearchParams(new URLSearchParams());
  };

  /**
   * Remove one committed criterion.
   *
   * Everything else about the search is kept: the remaining criteria commit
   * unchanged, the canonical URL is rewritten, the selection is dropped because
   * it belongs to a snapshot that no longer exists, and the next request starts
   * a fresh cursor chain at page one rather than continuing the old one. What it
   * must *not* do is rehydrate the rail over the operator's head — removing a
   * chip is not a reason to lose a confidence they were half-way through
   * typing — which is why it does not set `submittedFingerprint`.
   */
  const removeCriterion = useCallback((keys: ReadonlyArray<keyof CommittedTrackSearch>) => {
    if (!committed.isValid) return;
    const next = { ...committed.filters };
    for (const key of keys) delete next[key];
    commitFilters(next);
  }, [committed, commitFilters]);

  const continuationInvalid = tracks.isFetchNextPageError
    && tracks.error instanceof ApiError
    && tracks.error.code === 'track_search_invalid';

  const inspecting = selectedId !== null;

  // Page-scope conditions belong to the workspace, not to the results column:
  // a camera-metadata outage is a fact about the whole surface, and putting it
  // above the scroll owner is what stops it scrolling away with the rows.
  const notices = (
    <>
      {!committed.isValid ? <Alert tone="error">{committed.error}</Alert> : null}
      {systemConfig.isError ? (
        <Alert tone="warning" actions={<Button size="sm" onClick={() => void systemConfig.refetch()}>Retry display config</Button>}>
          Display timezone is unavailable. Existing UTC time scope remains active; time editing is disabled and result timestamps are shown explicitly in UTC.
        </Alert>
      ) : null}
      {cameras.isError ? (
        <Alert tone="warning" actions={<Button size="sm" onClick={() => void cameras.refetch()}>Retry cameras</Button>}>
          Camera metadata is unavailable. Any committed camera identifier remains active and Track search continues without broadening its scope.
        </Alert>
      ) : null}
      {videos.isError ? (
        <Alert tone="warning" actions={<Button size="sm" onClick={() => void videos.refetch()}>Retry videos</Button>}>
          Video metadata is unavailable. Any committed video scope remains active and is shown by identifier.
        </Alert>
      ) : null}
    </>
  );
  const hasNotice = !committed.isValid
    || systemConfig.isError || cameras.isError || videos.isError;

  return (
    <section className="page page--full page--workspace">
      <ContextBar
        crumbs={[{ label: 'Visual Search' }]}
        status={<DisplayTimeZone timeZoneId={displayTimeZoneId} />}
      />

      <InvestigationLayout
        notices={hasNotice ? notices : undefined}
        rail={(
          <SearchFilterRail
            draft={draft}
            errors={fieldErrors}
            onDraftChange={onDraftChange}
            onSubmit={submitSearch}
            onReset={resetSearch}
            cameras={cameras.data}
            videos={videos.data}
            videosUnavailable={videos.isError}
            displayTimeZoneId={displayTimeZoneId}
          />
        )}
        inspector={inspecting && selectedId ? (
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
            onClose={closeInspector}
          />
        ) : undefined}
      >
        <section className="results" aria-label="Search results" tabIndex={-1} ref={resultsRef}>
          {committed.isValid ? (
            <CommittedFilterChips
              filters={committed.filters}
              cameras={cameras.data}
              videos={videos.data}
              displayTimeZoneId={displayTimeZoneId}
              onRemove={removeCriterion}
            />
          ) : null}

          <div className="results__head">
            <div className="video-title">
              {/* §13: what the operator has, newest first — not a description
                  of the pagination mechanism they did not ask about. */}
              <strong>
                {items.length > 0
                  ? `${formatCount(items.length)} Track${items.length === 1 ? '' : 's'}`
                  : 'Results'}
              </strong>
              <span>
                {items.length > 0
                  ? hasMore ? 'Newest first · more to load' : 'Newest first · all loaded'
                  : 'Newest first'}
              </span>
            </div>
            {items.length > 0 ? (
              <span className="hints" aria-hidden="true">
                <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>Enter</kbd> open · <kbd>Esc</kbd> close
              </span>
            ) : null}
            {/* §14 of the brief: the List/Grid choice is a property of the
                results column, so it lives on the column rather than in
                permanent page chrome above the whole workspace. */}
            <Segmented
              label="Result view"
              size="sm"
              value={view}
              onChange={setView}
              options={[
                { value: 'list', label: <Icon name="list" size="sm" />, accessibleName: 'List view' },
                { value: 'grid', label: <Icon name="grid" size="sm" />, accessibleName: 'Grid view' },
              ]}
            />
          </div>

          {committed.isValid && tracks.isPending ? <LoadingState label="Searching visual intelligence…" /> : null}

          {tracks.isError && items.length === 0 ? (
            <div className="results__notice">
              <Alert
                tone="error"
                actions={<Button size="sm" icon="refresh" onClick={() => void tracks.refetch()}>Retry</Button>}
              >
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
      </InvestigationLayout>
    </section>
  );
}
