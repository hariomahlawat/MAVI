import { useQuery } from '@tanstack/react-query';
import { getCameraScene, getCameraSceneRevision } from '../../api/scene';
import { isGuid } from '../../api/client';
import { queryKeys } from '../../app/queryClient';
import { geometryNames, type GeometryNames } from '../../shared/evidence/analyticsLabels';

/**
 * What a surface knows about the scene it names geometry from.
 *
 * Four states, not two. `none` is the ordinary case — no camera to ask about.
 * `loading` and `unavailable` are kept apart because the operator's next move
 * differs (§14), and neither drops or broadens a committed id: an unresolved
 * zone stays in force and is shown by its identifier.
 */
export type SceneGeometryState =
  | { status: 'none' }
  | { status: 'loading' }
  | { status: 'unavailable' }
  | { status: 'unconfigured' }
  | { status: 'ready'; names: GeometryNames; analyticsEnabled: boolean };

/**
 * Which revision a caller means, because the two are different questions.
 *
 * `current` is what the next search would evaluate against: the explicitly
 * committed revision when there is one, else whatever the camera has active
 * now. The filter rail asks this, so the zones and lines it offers are the ones
 * the backend will accept for the query being composed.
 *
 * `pinned` is the revision a result set was actually evaluated against, as the
 * backend resolved and returned it. It never falls back to "active": a result
 * set pinned to no revision was evaluated against no geometry, and labelling
 * its facts with a revision activated afterwards would state something untrue.
 */
export type SceneGeometryMode = 'current' | 'pinned';

export function useSceneGeometry(
  cameraId: string | undefined,
  sceneRevisionId: string | undefined,
  mode: SceneGeometryMode = 'current',
): SceneGeometryState {
  const camera = cameraId && isGuid(cameraId) ? cameraId.toLowerCase() : '';
  const scene = useQuery({
    queryKey: queryKeys.cameraScene(camera),
    queryFn: ({ signal }) => getCameraScene(camera, signal),
    enabled: camera !== '',
    staleTime: 30_000,
  });

  // A committed historical revision is named by id; the scene's history maps it
  // to the number the revision endpoint is addressed by.
  const wanted = sceneRevisionId?.toLowerCase();
  const historical = wanted && scene.data
    ? scene.data.history.find((entry) => entry.revisionId.toLowerCase() === wanted)
    : undefined;
  // A pinned revision is never served by the active one unless they are the same
  // revision; revisions are immutable, so that identity is enough.
  const wantsHistorical = Boolean(wanted) && scene.data?.activeRevision?.revisionId.toLowerCase() !== wanted;
  const revision = useQuery({
    queryKey: queryKeys.cameraSceneRevision(camera, historical?.revisionNumber ?? 0),
    queryFn: ({ signal }) => getCameraSceneRevision(camera, historical!.revisionNumber, signal),
    enabled: camera !== '' && wantsHistorical && historical !== undefined,
    staleTime: 60_000,
  });

  if (camera === '') return { status: 'none' };
  if (scene.isPending) return { status: 'loading' };
  if (scene.isError || !scene.data) return { status: 'unavailable' };

  if (wantsHistorical) {
    if (!historical) return { status: 'unavailable' };
    if (revision.isPending) return { status: 'loading' };
    if (revision.isError || !revision.data) return { status: 'unavailable' };
    return {
      status: 'ready',
      names: geometryNames(revision.data.zones, revision.data.tripLines, revision.data.revisionNumber),
      analyticsEnabled: revision.data.analyticsEnabled,
    };
  }

  // Reaching here means either no revision was asked for, or the one asked for is
  // the revision that is active — and revisions are immutable, so serving it from
  // the active scene is the same geometry. Only the first case differs by mode: a
  // pinned caller with nothing to name must say so rather than adopt whatever is
  // active now.
  if (mode === 'pinned' && !wanted) return { status: 'unconfigured' };

  const active = scene.data.activeRevision;
  if (!active) return { status: 'unconfigured' };
  return {
    status: 'ready',
    names: geometryNames(active.zones, active.tripLines, active.revisionNumber),
    analyticsEnabled: active.analyticsEnabled,
  };
}
