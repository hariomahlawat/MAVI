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
import StatusBadge from '../../shared/components/StatusBadge';
import { configuredUtcToWallTimeText } from '../../shared/time/wallTime';
import { ContextBar, InvestigationLayout, Segmented } from '../../shared/workspace';
import { isNavigationTarget, nearEnd, neighbourId, selectedIndex } from './resultNavigation';
import { findSelectControl, isSelectedResultControl } from './resultSelection';
import type { AnalyticsCoverage, TrackAnalyticsIdentity } from '../../api/tracks';
import CommittedFilterChips from './CommittedFilterChips';
import CoverageStrip from '../../shared/evidence/CoverageStrip';
import SearchFilterRail, { ANALYTICS_DRAFT_FIELDS, emptyDraft, type DisplayZoneState, type SearchDraft } from './SearchFilterRail';
import TrackInspector from './TrackInspector';
import TrackResultCard from './TrackResultCard';
import TrackResultList, { reviewPath } from './TrackResultList';
import {
  canonicalSearchKey,
  canonicalSearchParams,
  confidenceFractionToPercentText,
  isAnalyticSearch,
  millisecondsToSecondsText,
  parseCommittedSearch,
  removeCriteria,
  type CommittedTrackSearch,
} from './searchState';
import { commitDraft, type SearchFieldErrors, type SearchFieldKey } from './searchValidation';
import { useSceneGeometry } from './useSceneGeometry';

const PAGE_SIZE = 24;
const SELECTION_PARAM = 'track';
const VIEW_STORAGE_KEY = 'mavi.search.view';

type ResultView = 'list' | 'grid';

type DraftField = keyof SearchDraft;

/**
 * The draft, and the committed state it was derived from.
 *
 * Holding both is what makes "dirty" mean *currently differs from committed*
 * rather than *was typed into at some point*. The flags this replaces were set
 * by an edit event and cleared only by a commit, a reset or a rebase, so a
 * field edited to Vehicle and back to Person stayed dirty: its value matched
 * the committed state while the surface still believed it did not. Removing
 * that criterion's chip then preserved the "edit", and the next Search put
 * back a filter the operator had explicitly removed.
 *
 * Keeping the baseline beside the values also removes the need for a ref of
 * what was dirty last render: every transition has both the old baseline (here)
 * and the new one (computed from the new committed state) in hand at once.
 */
type DraftState = { values: SearchDraft; baseline: SearchDraft };

const DRAFT_FIELDS = Object.keys(emptyDraft) as DraftField[];

/** Which fields currently say something other than the committed state. */
function dirtyFields(state: DraftState): DraftField[] {
  return DRAFT_FIELDS.filter((key) => state.values[key] !== state.baseline[key]);
}

function wallValue(utc: string | undefined, timeZoneId: string | undefined): string {
  if (!utc || !timeZoneId) return '';
  try {
    return configuredUtcToWallTimeText(utc, timeZoneId);
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
    zoneId: filters.zoneId ?? '',
    zoneRelation: filters.zoneRelation ?? 'dwelled',
    minDwellSeconds: millisecondsToSecondsText(filters.minDwellMs),
    lineId: filters.lineId ?? '',
    crossingDirection: filters.crossingDirection ?? '',
    motionDirection: filters.motionDirection ?? '',
    minStationarySeconds: millisecondsToSecondsText(filters.minStationaryMs),
    loitering: filters.loitering ? 'true' : '',
  };
}

/**
 * The zero-results message for an analytic search (plan §S, UI/UX §14, §17).
 *
 * It must not reuse the ordinary "No Tracks matched": an analytic search
 * evaluates only the analysed runs, so "no match" and "nothing was looked at"
 * are different facts, and the three not-evaluated causes get three verbs.
 */
function analyticEmptyState(coverage: AnalyticsCoverage): { title: string; body: string; hatched: boolean } {
  if (coverage.evaluatedRuns === 0) {
    if (coverage.notConfiguredRuns > 0 && coverage.disabledRuns === 0 && coverage.pendingRuns === 0 && coverage.failedRuns === 0 && coverage.staleRuns === 0) {
      return { title: 'No scene configured for this camera.', body: 'Define zones and trip lines in the Scene Editor before searching by analytics.', hatched: true };
    }
    if (coverage.disabledRuns > 0 && coverage.pendingRuns === 0 && coverage.failedRuns === 0 && coverage.staleRuns === 0 && coverage.notConfiguredRuns === 0) {
      return { title: 'Analytics disabled by the active scene revision.', body: 'Runs in this scope were not evaluated. Enable a zone or trip line in the Scene Editor to analyse them.', hatched: true };
    }
    return { title: 'Not analysed yet.', body: 'No run in this scope has been evaluated against the scene revision, so there is nothing to match. The coverage above names each run\'s state.', hatched: true };
  }
  if (coverage.complete) {
    return { title: 'No evaluated Tracks matched this search.', body: 'Every run in scope was analysed. Adjust the analytics filters or the committed scope.', hatched: false };
  }
  return { title: 'No evaluated Tracks matched.', body: 'Some runs in this scope were not evaluated; the coverage above names them. A match may exist in a run that has not been analysed yet.', hatched: false };
}

/**
 * Bring the draft back in line with committed state without discarding work.
 *
 * Removing a chip, following a deep link, stepping Back or the display timezone
 * arriving all change the committed state without the operator having pressed
 * Search, and the rail must not lose what they were in the middle of typing
 * because of it. A field that differed from the *old* baseline keeps its value;
 * every other field takes the new one.
 *
 * A field edited back to its baseline is, by that definition, not differing —
 * so it rebases like any untouched field and cannot resurrect a criterion the
 * operator has since removed.
 */
function rebase(state: DraftState, baseline: SearchDraft): DraftState {
  const values: SearchDraft = { ...baseline };
  // Every draft field is a string; the object class is a narrower string, which
  // is the only reason this needs to say so.
  const writable = values as Record<DraftField, string>;
  for (const key of dirtyFields(state)) writable[key] = state.values[key];
  return { values, baseline };
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
  // §14: pending and failed are different states, and the operator's next move
  // differs — wait, or press Retry. The rail used to be told only the zone, so
  // it described a request still in flight as unavailable.
  const displayZone: DisplayZoneState = displayTimeZoneId
    ? { status: 'ready', timeZoneId: displayTimeZoneId }
    : systemConfig.isError ? { status: 'unavailable' } : { status: 'loading' };
  // A failed *refetch* keeps the data it already had, so `isError` alone does
  // not mean there is no configuration. Saying "unavailable, editing disabled,
  // timestamps in UTC" while the retained zone is still on screen and still
  // converting the time fields is the surface contradicting itself. The two
  // failures are told apart by whether a usable zone survived.
  const configUnavailable = systemConfig.isError && !displayTimeZoneId;
  const configRefreshFailed = systemConfig.isError && Boolean(displayTimeZoneId);

  const [draft, setDraft] = useState<DraftState>({ values: emptyDraft, baseline: emptyDraft });
  // Set when this surface commits a search itself. Only then is the draft known
  // to already say what the committed state says, so only then is it settled
  // outright; every other committed change rebases around outstanding edits.
  const submittedFingerprint = useRef<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<SearchFieldErrors>({});
  const [view, setView] = useState<ResultView>(readView);

  const outstanding = dirtyFields(draft);
  const hasDraftChanges = outstanding.length > 0;

  const committedFilters = committed.isValid ? committed.filters : {};
  const analytic = committed.isValid && isAnalyticSearch(committed.filters);

  useEffect(() => {
    try {
      window.localStorage.setItem(VIEW_STORAGE_KEY, view);
    } catch {
      // Losing the preference is harmless.
    }
  }, [view]);

  /**
   * One transition for every committed-state change.
   *
   * Keyed on the committed fingerprint and the display zone rather than on the
   * URL: selecting a result changes the URL too and must not touch the rail.
   * The zone belongs here because a committed UTC bound cannot be shown as a
   * wall time until the zone is known, so its arrival changes the baseline in
   * exactly the same way a new filter does — which is why it is the same
   * transition rather than a second effect racing the first.
   */
  useEffect(() => {
    const filters = committed.isValid ? committed.filters : {};
    const baseline = draftFromFilters(filters, displayTimeZoneId);
    if (submittedFingerprint.current === fingerprint) {
      // Our own commit: the draft produced this state, so it already says what
      // the URL says and nothing is outstanding.
      submittedFingerprint.current = null;
      setDraft({ values: baseline, baseline });
    } else {
      setDraft((current) => rebase(current, baseline));
    }
    setFieldErrors({});
    // `committed` is derived from `fingerprint`; depending on the object would
    // re-run this on every render that reparses an unchanged URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fingerprint, displayTimeZoneId]);

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

  // Coverage is part of the snapshot: page one computed it and every continuation
  // carries the same block, so the first page is the one to read it from.
  const coverage = analytic ? tracks.data?.pages[0]?.analyticsCoverage : undefined;

  // The camera the analytics group is about: the draft's camera, the draft's
  // video's camera, or — for a committed run scope the rail has no control for —
  // the camera the results themselves name. Nothing here broadens the search;
  // it only decides which scene's geometry the choices are read from.
  const draftVideoCamera = draft.values.videoAssetId
    ? videos.data?.find((video) => video.id.toLowerCase() === draft.values.videoAssetId.toLowerCase())?.cameraId
    : undefined;
  const analyticsCameraId = draft.values.cameraId
    || draftVideoCamera
    || (committedFilters.processingRunId ? items[0]?.cameraId : undefined);
  const analyticsScoped = Boolean(draft.values.cameraId || draft.values.videoAssetId || committedFilters.processingRunId);

  // (B) The geometry the *controls* are composed from. This one follows the
  // current configuration on purpose: the rail offers the zones and lines the
  // backend will accept for the query being composed, which is the explicitly
  // committed revision when there is one and the camera's active scene
  // otherwise. It says nothing about results already on screen.
  const draftGeometry = useSceneGeometry(analyticsCameraId, committedFilters.sceneRevisionId);

  // The identity the results were evaluated against, carried to the inspector,
  // the detail request and the review links so the facts shown there are the
  // facts the search evaluated (plan §S).
  //
  // The backend resolves this identity at the first page's linearisation point
  // and returns it whole in coverage. The committed filters are a *request*: an
  // explicit revision with no engine version is an incomplete pair, and reading
  // it back as identity lets a later engine upgrade re-point the detail endpoint
  // at a different algorithm than the search ran. So the resolved pair wins
  // whenever there is one, and the request is only a fallback for a search the
  // backend never resolved an identity for.
  //
  // Memoised because it is a dependency of the keyboard navigation callback, and
  // a fresh object each render would re-register the document key listener on
  // every render.
  const requestedRevisionId = committedFilters.sceneRevisionId;
  const requestedAlgorithmVersion = committedFilters.analyticsAlgorithmVersion;
  const analyticsIdentity: TrackAnalyticsIdentity | undefined = useMemo(() => (coverage
    ? coverage.sceneRevisionId
      ? { sceneRevisionId: coverage.sceneRevisionId, analyticsAlgorithmVersion: coverage.algorithmVersion }
      : undefined
    : requestedRevisionId
      ? { sceneRevisionId: requestedRevisionId, analyticsAlgorithmVersion: requestedAlgorithmVersion }
      : undefined
  ), [coverage, requestedRevisionId, requestedAlgorithmVersion]);

  // (A) The geometry the *results* are labelled with, read against the revision
  // the backend pinned rather than whatever is active now. Activating a new
  // scene must not silently relabel facts that were evaluated against the old
  // one. The camera comes from the committed scope, not the draft, for the same
  // reason: editing the rail does not change what the results on screen mean.
  const committedVideoCamera = committedFilters.videoAssetId
    ? videos.data?.find((video) => video.id.toLowerCase() === committedFilters.videoAssetId!.toLowerCase())?.cameraId
    : undefined;
  const resultCameraId = coverage
    ? committedFilters.cameraId || committedVideoCamera || items[0]?.cameraId
    : undefined;
  const resultGeometry = useSceneGeometry(resultCameraId, analyticsIdentity?.sceneRevisionId, 'pinned');
  const resultGeometryNames = resultGeometry.status === 'ready' ? resultGeometry.names : undefined;

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

  // Keyboard Enter is the same operation as the list, grid and inspector Review
  // links, so it carries the same resolved identity. A navigation that dropped it
  // would send the operator to Review with no provenance, where the current
  // revision and engine are then legitimately resolved and different facts shown.
  const openSelected = useCallback(() => {
    const selected = position >= 0 ? items[position] : undefined;
    if (selected) navigate(reviewPath(selected, searchContext, analyticsIdentity));
  }, [items, position, navigate, searchContext, analyticsIdentity]);

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
    // Nothing is marked here. Whether a field is outstanding is read off the
    // baseline, so editing a value back to what is committed makes it clean
    // again without anything having to notice that it happened.
    setDraft((current) => {
      const values = { ...current.values, ...patch };
      // A zone or line belongs to one camera's scene. Changing the camera or the
      // video clears the geometry draft rather than carrying another camera's
      // identifiers along (plan §S); generic motion, stationary and loitering
      // intent stays.
      const scopeChanged = ('cameraId' in patch && patch.cameraId !== current.values.cameraId)
        || ('videoAssetId' in patch && patch.videoAssetId !== current.values.videoAssetId);
      if (scopeChanged) {
        for (const key of ANALYTICS_DRAFT_FIELDS) (values as Record<string, string>)[key] = emptyDraft[key];
      }
      return { ...current, values };
    });
    // A field the operator is correcting stops claiming to be wrong as soon as
    // they touch it; it is re-judged when they ask for the search again.
    const keys = Object.keys(patch) as DraftField[];
    setFieldErrors((current) => {
      if (!keys.some((key) => key in current)) return current;
      const next = { ...current };
      for (const key of keys) delete next[key as SearchFieldKey];
      return next;
    });
  };

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // Only a field that currently differs from the committed state is
    // reconverted. An untouched one — and one edited back to its baseline —
    // keeps the committed value byte for byte, so a bookmarked
    // `minimumConfidence=0.00075` is not rewritten to the 0.075% the field
    // displays it as.
    const outstandingNow = new Set(outstanding);
    const result = commitDraft({
      draft: draft.values,
      committed: committed.isValid ? committed.filters : {},
      timeDirty: { from: outstandingNow.has('fromLocal'), to: outstandingNow.has('toLocal') },
      numericDirty: {
        duration: outstandingNow.has('minimumDurationSeconds'),
        confidence: outstandingNow.has('minimumConfidencePercent'),
        dwell: outstandingNow.has('minDwellSeconds'),
        stationary: outstandingNow.has('minStationarySeconds'),
      },
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
      const baseline = draftFromFilters(result.filters, displayTimeZoneId);
      setDraft({ values: baseline, baseline });
    }
  };

  const resetSearch = () => {
    setFieldErrors({});
    setDraft({ values: emptyDraft, baseline: emptyDraft });
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
    // Dependents go with the criterion they depend on (plan §S): a removed zone
    // takes its relation and dwell, a removed camera scope takes the geometry.
    commitFilters(removeCriteria(committed.filters, keys));
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
      {configUnavailable ? (
        <Alert tone="warning" actions={<Button size="sm" onClick={() => void systemConfig.refetch()}>Retry display config</Button>}>
          Display timezone is unavailable. Existing UTC time scope remains active; time editing is disabled and result timestamps are shown explicitly in UTC.
        </Alert>
      ) : null}
      {configRefreshFailed ? (
        <Alert tone="warning" actions={<Button size="sm" onClick={() => void systemConfig.refetch()}>Retry display config</Button>}>
          Display configuration could not be refreshed. The last known configuration remains in use, so times are still shown and entered in the timezone above.
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
    || configUnavailable || configRefreshFailed || cameras.isError || videos.isError;

  return (
    <section className="page page--full page--workspace">
      <ContextBar
        crumbs={[{ label: 'Visual Search' }]}
        status={(
          <>
            {/* §21: draft state appears in the Context Bar. The wording is the
                operator's — the filters exist and are simply not the ones the
                results were fetched with — rather than the "unsaved record" of
                a create/edit form, because nothing here is being saved. */}
            {hasDraftChanges ? <StatusBadge tone="warn">Unapplied filters</StatusBadge> : null}
            <DisplayTimeZone timeZoneId={displayTimeZoneId} />
          </>
        )}
      />

      <InvestigationLayout
        notices={hasNotice ? notices : undefined}
        rail={(
          <SearchFilterRail
            draft={draft.values}
            errors={fieldErrors}
            onDraftChange={onDraftChange}
            onSubmit={submitSearch}
            onReset={resetSearch}
            cameras={cameras.data}
            videos={videos.data}
            videosUnavailable={videos.isError}
            displayZone={displayZone}
            analyticsScoped={analyticsScoped}
            geometry={draftGeometry}
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
            analyticsIdentity={analyticsIdentity}
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
              geometry={resultGeometryNames}
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

          {/* §17: the coverage strip sits immediately beneath the header and chips
              and persists for the snapshot, so an incomplete answer is never
              read as a complete one. */}
          {coverage ? <CoverageStrip coverage={coverage} geometry={resultGeometryNames} /> : null}

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
            coverage ? (
              (() => {
                const state = analyticEmptyState(coverage);
                return (
                  <EmptyState icon="search" title={state.title} hatched={state.hatched}>
                    {state.body}
                  </EmptyState>
                );
              })()
            ) : (
              <EmptyState icon="search" title="No Tracks matched this search.">
                Adjust the committed filters or reset to view the newest available Tracks.
              </EmptyState>
            )
          ) : null}

          {items.length > 0 ? (
            view === 'list' ? (
              <TrackResultList items={items} selectedId={selectedId} displayTimeZoneId={displayTimeZoneId} searchContext={searchContext} analyticsIdentity={analyticsIdentity} onSelect={selectTrack} />
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
                      analyticsIdentity={analyticsIdentity}
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
