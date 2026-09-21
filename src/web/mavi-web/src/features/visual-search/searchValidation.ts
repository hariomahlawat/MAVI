import {
  compareUtcInstants,
  confidencePercentTextToFraction,
  removeCriteria,
  secondsTextToMilliseconds,
  withCameraScope,
  type CommittedTrackSearch,
} from './searchState';
import { configuredWallTimeToUtc } from '../../shared/time/wallTime';
import type { SearchDraft } from './SearchFilterRail';

/**
 * Turning a draft into a committed search, field by field.
 *
 * This used to live inside the page's submit handler as one `try` around the
 * whole conversion, which meant the first refused field aborted the rest and
 * the operator was told, once, at page level, that something was wrong. §10
 * asks for the opposite: the message belongs to the field that earned it, and
 * an operator who mistyped both a duration and a confidence should be told
 * both times rather than made to discover the second after fixing the first.
 *
 * So each field is converted in its own `try` and the errors accumulate. What
 * is deliberately unchanged is *which* edits are converted at all: an
 * untouched field keeps the committed value exactly, to whatever precision it
 * was bookmarked with, because recomputing it through the operator's display
 * precision would silently rewrite a value nobody edited.
 *
 * It is not a form engine (§10). It knows these four fields by name, it holds
 * no state, and it validates nothing it is not asked to commit.
 */

export type SearchFieldKey =
  | 'fromLocal' | 'toLocal' | 'minimumDurationSeconds' | 'minimumConfidencePercent'
  | 'minDwellSeconds' | 'minStationarySeconds';

export type SearchFieldErrors = Partial<Record<SearchFieldKey, string>>;

export type TimeDirtyState = { from: boolean; to: boolean };
export type NumericDirtyState = { duration: boolean; confidence: boolean; dwell: boolean; stationary: boolean };

export type DraftCommit =
  | { ok: true; filters: CommittedTrackSearch }
  | { ok: false; errors: SearchFieldErrors };

function message(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function commitDraft({
  draft,
  committed,
  timeDirty,
  numericDirty,
  displayTimeZoneId,
}: {
  draft: SearchDraft;
  /** The committed filters to rebase onto; untouched criteria survive verbatim. */
  committed: CommittedTrackSearch;
  timeDirty: TimeDirtyState;
  numericDirty: NumericDirtyState;
  displayTimeZoneId: string | undefined;
}): DraftCommit {
  // The camera scope goes first, because a changed camera drops the scene-local
  // criteria (plan §S) before the analytics fields below restate what survives.
  const next: CommittedTrackSearch = withCameraScope(committed, {
    cameraId: draft.cameraId || undefined,
    videoAssetId: draft.videoAssetId || undefined,
    processingRunId: committed.processingRunId,
  });
  const errors: SearchFieldErrors = {};

  if (draft.objectClass) next.objectClass = draft.objectClass;
  else delete next.objectClass;

  if (numericDirty.duration) {
    try {
      const duration = secondsTextToMilliseconds(draft.minimumDurationSeconds);
      if (duration === undefined) delete next.minimumDurationMs;
      else next.minimumDurationMs = duration;
    } catch (error) {
      errors.minimumDurationSeconds = message(error, 'Minimum duration is not a valid number of seconds.');
    }
  }

  if (numericDirty.confidence) {
    try {
      const confidence = confidencePercentTextToFraction(draft.minimumConfidencePercent);
      if (confidence === undefined) delete next.minimumConfidence;
      else next.minimumConfidence = confidence;
    } catch (error) {
      errors.minimumConfidencePercent = message(error, 'Minimum confidence is not a valid percentage.');
    }
  }

  // The analytics group. Every field is stated by the draft, so the committed
  // value is replaced rather than rebased: a select has no "untouched" precision
  // to preserve. The two durations keep the seconds-to-milliseconds discipline
  // the existing duration field uses, dirty-gated for the same reason.
  if (draft.zoneId) {
    next.zoneId = draft.zoneId.toLowerCase();
    if (draft.zoneRelation !== 'dwelled') next.zoneRelation = draft.zoneRelation;
    else delete next.zoneRelation;
  } else {
    delete next.zoneId;
    delete next.zoneRelation;
    delete next.minDwellMs;
  }

  if (numericDirty.dwell && draft.zoneId) {
    try {
      const dwell = secondsTextToMilliseconds(draft.minDwellSeconds);
      if (dwell === undefined) delete next.minDwellMs;
      else next.minDwellMs = dwell;
    } catch (error) {
      errors.minDwellSeconds = message(error, 'Minimum dwell is not a valid number of seconds.');
    }
  }

  if (draft.lineId) {
    next.lineId = draft.lineId.toLowerCase();
    if (draft.crossingDirection) next.crossingDirection = draft.crossingDirection;
    else delete next.crossingDirection;
  } else {
    delete next.lineId;
    delete next.crossingDirection;
  }

  if (draft.motionDirection) next.motionDirection = draft.motionDirection;
  else delete next.motionDirection;

  if (numericDirty.stationary) {
    try {
      const stationary = secondsTextToMilliseconds(draft.minStationarySeconds);
      if (stationary === undefined) delete next.minStationaryMs;
      else next.minStationaryMs = stationary;
    } catch (error) {
      errors.minStationarySeconds = message(error, 'Minimum stationary time is not a valid number of seconds.');
    }
  }

  if (draft.loitering === 'true') next.loitering = true;
  else delete next.loitering;

  // ADR-004: the browser's zone is never authoritative, so a wall time can only
  // be converted once the configured display zone is known. Without it the edit
  // is refused rather than guessed at.
  for (const bound of ['from', 'to'] as const) {
    const key = bound === 'from' ? 'fromLocal' : 'toLocal';
    const target = bound === 'from' ? 'fromUtc' : 'toUtc';
    if (!timeDirty[bound]) continue;
    const value = draft[key];
    if (!value) {
      delete next[target];
      continue;
    }
    if (!displayTimeZoneId) {
      errors[key] = 'Display timezone is unavailable; this time cannot be edited safely.';
      continue;
    }
    try {
      next[target] = configuredWallTimeToUtc(value, displayTimeZoneId);
    } catch (error) {
      errors[key] = message(error, 'This time could not be interpreted in the display timezone.');
    }
  }

  // Ordering is a fact about the pair, and the operator fixes it by moving the
  // end of the range far more often than the start, so it is reported on To.
  if (!errors.fromLocal && !errors.toLocal
      && next.fromUtc && next.toUtc
      && compareUtcInstants(next.fromUtc, next.toUtc) >= 0) {
    errors.toLocal = 'To time must be later than the From time.';
  }

  if (Object.keys(errors).length > 0) return { ok: false, errors };
  // Settle the dependency graph once more: an analytic criterion cannot stand
  // without a camera-resolving scope, whatever the draft said about it.
  return { ok: true, filters: removeCriteria(next, []) };
}
