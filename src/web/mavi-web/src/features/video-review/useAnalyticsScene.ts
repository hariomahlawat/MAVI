import { useQuery } from '@tanstack/react-query';
import { isGuid } from '../../api/client';
import { getCameraSceneRevision, type SceneRevision } from '../../api/scene';
import type { TrackDetailAnalytics } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import { geometryNames, type GeometryNames } from '../visual-search/analyticsLabels';

/**
 * The scene revision a Track's analytical facts were measured against.
 *
 * Not "the camera's scene". A Track analysed under revision 4 has dwell times,
 * crossings and visits that only mean anything against revision 4's geometry;
 * drawing them over whatever revision is active now would put a persisted fact
 * on top of a polygon that did not exist when the fact was produced. Revisions
 * are immutable, so pinning is exact rather than approximate — and the wrong
 * revision is worse than none, because an operator cannot see that the outline
 * under the evidence is from a different scene.
 *
 * Six states, because the reasons geometry is absent are different facts and
 * the operator's next move differs between them.
 */
export type AnalyticsSceneState =
  /** Nothing to pin: no camera, or no analytical identity and no facts. */
  | { status: 'none' }
  /**
   * Facts are claimed without a complete revision identity. Fail closed: the
   * facts may still be listed, but nothing revision-dependent is drawn and no
   * revision is guessed.
   */
  | { status: 'incomplete-identity' }
  | { status: 'loading'; revisionNumber: number }
  | { status: 'unavailable'; revisionNumber: number; reason: AnalyticsSceneFailure }
  | { status: 'ready'; revision: SceneRevision; names: GeometryNames };

export type AnalyticsSceneFailure =
  /** The revision endpoint failed or the revision no longer exists. */
  | 'request-failed'
  /** A revision came back, but it is not the one the facts name. */
  | 'identity-mismatch';

/**
 * Whether this analytics block carries facts that are bound to geometry.
 *
 * `Analysed` is the ordinary case. `Stale` is included only when the response
 * actually supplied facts for the selected identity: a stale block with no
 * facts has nothing to draw, and asking for its revision would fetch geometry
 * to decorate an empty answer.
 */
function bindsGeometry(analytics: TrackDetailAnalytics): boolean {
  if (analytics.status === 'Analysed') return true;
  if (analytics.status !== 'Stale') return false;
  return analytics.zoneSummaries.length > 0
    || analytics.zoneVisits.length > 0
    || analytics.lineCrossings.length > 0
    || analytics.motion !== null;
}

export function useAnalyticsScene(
  cameraId: string | undefined,
  analytics: TrackDetailAnalytics | undefined,
): AnalyticsSceneState {
  const camera = cameraId && isGuid(cameraId) ? cameraId.toLowerCase() : '';
  const binds = analytics !== undefined && bindsGeometry(analytics);
  const expectedId = analytics?.sceneRevisionId?.toLowerCase() ?? '';
  const revisionNumber = analytics?.sceneRevisionNumber ?? 0;
  // A complete identity is both halves: the number addresses the endpoint, the
  // id is what the answer is checked against. One without the other cannot be
  // verified, so it is not a usable identity.
  const complete = binds && expectedId !== '' && Number.isInteger(revisionNumber) && revisionNumber > 0;

  // The existing immutable-revision key. A revision never changes, so two
  // Tracks analysed under the same revision share one cache entry, and two
  // analytical identities can never overwrite one another because the number
  // is part of the key.
  const revision = useQuery({
    queryKey: queryKeys.cameraSceneRevision(camera, revisionNumber),
    queryFn: ({ signal }) => getCameraSceneRevision(camera, revisionNumber, signal),
    enabled: camera !== '' && complete,
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });

  if (camera === '' || !binds) return { status: 'none' };
  if (!complete) return { status: 'incomplete-identity' };
  if (revision.isPending) return { status: 'loading', revisionNumber };
  if (revision.isError || !revision.data) {
    return { status: 'unavailable', revisionNumber, reason: 'request-failed' };
  }

  // Verified, not assumed. The number addressed the request and the server is
  // trusted to honour it, but a renumbered, replaced or mis-routed revision
  // would otherwise be drawn as though it were the analysed one. Checking the
  // camera too costs nothing and closes the same hole one level up.
  const served = revision.data;
  if (served.revisionId.toLowerCase() !== expectedId
    || served.cameraId.toLowerCase() !== camera) {
    return { status: 'unavailable', revisionNumber, reason: 'identity-mismatch' };
  }

  return {
    status: 'ready',
    revision: served,
    names: geometryNames(served.zones, served.tripLines, served.revisionNumber),
  };
}

/** The pinned revision when one is loaded, else undefined. Never a substitute. */
export function pinnedRevision(scene: AnalyticsSceneState): SceneRevision | undefined {
  return scene.status === 'ready' ? scene.revision : undefined;
}

/** The pinned names when loaded. Callers fall back to stable ids, never to another revision. */
export function pinnedNames(scene: AnalyticsSceneState): GeometryNames | undefined {
  return scene.status === 'ready' ? scene.names : undefined;
}
