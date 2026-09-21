import { useQuery } from '@tanstack/react-query';
import { getCameraScene, getCameraSceneRevision } from '../../api/scene';
import { isGuid } from '../../api/client';
import { queryKeys } from '../../app/queryClient';
import { geometryNames, type GeometryNames } from './analyticsLabels';

/**
 * What the Analytics rail group and the analytic chips know about the scene
 * they name geometry from.
 *
 * Four states, not two. `none` is the ordinary case — no camera to ask about.
 * `loading` and `unavailable` are kept apart because the operator's next move
 * differs (§14), and neither drops or broadens a committed id: an unresolved
 * zone stays in force and is shown by its identifier. `ready` carries the
 * geometry of the revision the search evaluates against — the explicitly
 * committed one when there is one, else the camera's active revision — so the
 * choices offered are the choices the backend will accept.
 */
export type SceneGeometryState =
  | { status: 'none' }
  | { status: 'loading' }
  | { status: 'unavailable' }
  | { status: 'unconfigured' }
  | { status: 'ready'; names: GeometryNames; analyticsEnabled: boolean };

export function useSceneGeometry(cameraId: string | undefined, sceneRevisionId: string | undefined): SceneGeometryState {
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

  const active = scene.data.activeRevision;
  if (!active) return { status: 'unconfigured' };
  return {
    status: 'ready',
    names: geometryNames(active.zones, active.tripLines, active.revisionNumber),
    analyticsEnabled: active.analyticsEnabled,
  };
}
