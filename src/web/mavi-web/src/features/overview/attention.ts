import { isFinalizationFailure, type ProcessingStatus, type VideoAsset } from '../../api/videos';
import type { AsyncState } from '../../shared/async/asyncState';

/**
 * What needs the operator's attention (§4.1.1, attention-first Overview),
 * decided from the platform's own status vocabularies and nothing else.
 *
 * Each condition below is one the existing contracts state authoritatively:
 *
 * - **Processing failed** — the video inventory's `Failed` status. The failure
 *   code comes from the video's processing status, where it was looked up.
 * - **Analysis failed / Stale** — the latest run's `analyticsReadiness`, read
 *   only for a run that `Completed`: readiness is derived for any run, and a
 *   failed or cancelled run's readiness means nothing (`isAnalyticsPending`).
 *   `NotConfigured` and `Disabled` are the operator's own scene choices, and
 *   `Pending` is on its way; none of them needs attention.
 * - **Not queued** — the inventory's `NotQueued` status: imported media that
 *   is not searchable until it is processed. One aggregate item, not one row
 *   per video.
 *
 * Deliberately not claimed: a *stalled* run. No contract exposes a lease or a
 * heartbeat — the server turns an abandoned run into a terminal failure itself
 * (`vision_job_attempts_exhausted`), which then appears here as a failure — and
 * a threshold on elapsed time would be invented. A run that is still moving is
 * not an attention item.
 */

export type AttentionCondition = 'processing-failed' | 'analytics-failed' | 'analytics-stale' | 'awaiting-processing';

export type AttentionItem = {
  /** Stable identity: the condition and what it is about. */
  readonly key: string;
  readonly condition: AttentionCondition;
  /** What is affected: a video and its camera, or the set of videos. */
  readonly subject: string;
  /** Why it matters, in one short sentence; the state itself is the row's badge. */
  readonly reason: string;
  /** The failure code the platform recorded, where there is one. */
  readonly code: string | null;
  /** The surface that acts on it. */
  readonly to: string;
  readonly actionLabel: string;
};

/** How far the evaluation got: what the clear state may and may not claim. */
export type AttentionEvaluation = {
  readonly items: readonly AttentionItem[];
  /** Processed videos whose analytics this evaluation covers, and the total. */
  readonly analyticsScope: { readonly checked: number; readonly total: number };
  /** Status lookups still answering: nothing may be declared clear yet. */
  readonly pendingLookups: number;
  /** Every video whose status could not be read (what a retry re-requests). */
  readonly unavailableLookups: readonly string[];
  /** Of those, failed videos: listed regardless, only their detail is missing. */
  readonly unavailableDetails: number;
  /** Of those, processed videos: whether they need attention is not known. */
  readonly unknownAnalytics: number;
  /**
   * Videos classified from a cached status whose refresh failed: their items
   * stand on the last known answer, which is no longer known to be current, so
   * nothing may be declared clear while there are any.
   */
  readonly staleLookups: readonly string[];
};

/** Status lookups per kind of video. Bounded, so the page never fans out over a whole inventory. */
export const ATTENTION_LOOKUP_LIMIT = 12;

const ORDER: Record<AttentionCondition, number> = {
  'processing-failed': 0,
  'analytics-failed': 1,
  'analytics-stale': 2,
  'awaiting-processing': 3,
};

/** Newest first, then by id, so the order — and the lookups — never depend on response order. */
function newestFirst(a: VideoAsset, b: VideoAsset): number {
  return b.importedAtUtc.localeCompare(a.importedAtUtc) || a.id.localeCompare(b.id);
}

/**
 * The videos whose processing status the Overview reads: the most recently
 * imported failed videos (for their failure code) and processed videos (for
 * their analytics readiness), at most `limit` of each. A stable list, so each
 * lookup keeps its query identity and shares the per-video cache.
 */
export function attentionLookupIds(videos: readonly VideoAsset[], limit = ATTENTION_LOOKUP_LIMIT): string[] {
  const pick = (status: string) => videos.filter((v) => v.processingStatus === status).sort(newestFirst).slice(0, limit).map((v) => v.id);
  return [...pick('Failed'), ...pick('Processed')];
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * Classify the inventory and the status lookups into attention items.
 *
 * `lookup` returns a video's processing-status state, or `undefined` for a
 * video that was not looked up. A lookup that failed leaves its video's
 * condition unknown — reported, never read as healthy.
 */
export function evaluateAttention({
  videos,
  cameraCodes,
  lookup,
  limit = ATTENTION_LOOKUP_LIMIT,
}: {
  videos: readonly VideoAsset[];
  cameraCodes: ReadonlyMap<string, string> | null;
  lookup: (videoId: string) => AsyncState<ProcessingStatus> | undefined;
  limit?: number;
}): AttentionEvaluation {
  const items: AttentionItem[] = [];
  const subjectOf = (video: VideoAsset) => {
    const code = cameraCodes?.get(video.cameraId);
    return code ? `${video.originalFileName} · ${code}` : video.originalFileName;
  };
  const runPath = (video: VideoAsset) => `/processing/${video.id.toLowerCase()}`;
  let pendingLookups = 0;
  const unavailableLookups: string[] = [];
  let unavailableDetails = 0;
  let unknownAnalytics = 0;
  const staleLookups: string[] = [];
  const read = (video: VideoAsset): ProcessingStatus | null => {
    const state = lookup(video.id);
    if (!state) return null;
    if (state.kind === 'loading') { pendingLookups += 1; return null; }
    if (state.kind === 'unavailable') {
      unavailableLookups.push(video.id);
      if (video.processingStatus === 'Failed') unavailableDetails += 1; else unknownAnalytics += 1;
      return null;
    }
    if (state.degraded) staleLookups.push(video.id);
    return state.data;
  };

  // Failed processing: every failed video is an item, from the inventory; the
  // code is added where the lookup has it.
  for (const video of videos.filter((v) => v.processingStatus === 'Failed').sort(newestFirst)) {
    const run = read(video)?.latestRun ?? null;
    const failedRun = run && run.status === 'Failed' ? run : null;
    items.push({
      key: `processing-failed:${video.id}`,
      condition: 'processing-failed',
      subject: subjectOf(video),
      reason: isFinalizationFailure(failedRun)
        ? 'Failed while publishing; its Tracks are not searchable.'
        : 'Its Tracks are not searchable.',
      code: failedRun?.failureCode ?? null,
      to: runPath(video),
      actionLabel: 'Open run',
    });
  }

  // Analytics of a completed run, for the processed videos in scope.
  const processed = videos.filter((v) => v.processingStatus === 'Processed').sort(newestFirst);
  const inScope = processed.slice(0, limit);
  for (const video of inScope) {
    const run = read(video)?.latestRun ?? null;
    if (!run || run.status !== 'Completed') continue;
    if (run.analyticsReadiness === 'Failed') {
      items.push({
        key: `analytics-failed:${video.id}`,
        condition: 'analytics-failed',
        subject: subjectOf(video),
        reason: 'Its zone and line results are missing.',
        code: null,
        to: runPath(video),
        actionLabel: 'Open run',
      });
    } else if (run.analyticsReadiness === 'Stale') {
      items.push({
        key: `analytics-stale:${video.id}`,
        condition: 'analytics-stale',
        subject: subjectOf(video),
        reason: 'Its zone and line results use an earlier scene geometry.',
        code: null,
        to: runPath(video),
        actionLabel: 'Open run',
      });
    }
  }

  // Media awaiting processing: one item for all of it.
  const notQueued = videos.filter((v) => v.processingStatus === 'NotQueued').length;
  if (notQueued > 0) {
    items.push({
      key: 'awaiting-processing',
      condition: 'awaiting-processing',
      subject: plural(notQueued, 'video', 'videos'),
      reason: 'Not searchable until processed.',
      code: null,
      to: '/videos?status=NotQueued',
      actionLabel: 'Open videos',
    });
  }

  // Severity order is the condition order; within one, the inventory's newest
  // first (already applied). Keys are unique by construction; the guard keeps it so.
  const seen = new Set<string>();
  const ordered = items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => ORDER[a.item.condition] - ORDER[b.item.condition] || a.index - b.index)
    .map(({ item }) => item)
    .filter((item) => (seen.has(item.key) ? false : (seen.add(item.key), true)));

  return {
    items: ordered,
    analyticsScope: { checked: inScope.length, total: processed.length },
    pendingLookups,
    unavailableLookups,
    unavailableDetails,
    unknownAnalytics,
    staleLookups,
  };
}
