import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getCamera } from '../../api/cameras';
import {
  getCameraScene,
  getCameraSceneRevision,
  saveCameraScene,
  videoContentUrl,
  type SceneRevision,
} from '../../api/scene';
import { getSystemConfig } from '../../api/system';
import { listVideos, type VideoAsset } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { editorReducer, initialEditorState, NUDGE_STEP, type Selection } from './editorState';
import ReferenceFramePicker from './ReferenceFramePicker';
import RevisionHistory from './RevisionHistory';
import SceneCanvas from './SceneCanvas';
import { draftAnalyticsEnabled, draftFromRevision, saveRequestFromDraft, type SceneDraft } from './sceneDraft';
import { isCameraMissing, isRevisionConflict, sceneErrorMessage } from './sceneErrors';
import SceneObjectList from './SceneObjectList';
import ScenePropertiesPanel from './ScenePropertiesPanel';
import { useUnsavedChangesGuard } from './useUnsavedChangesGuard';

/** The frame the canvas falls back to when no reference video is loaded. */
const NEUTRAL_FRAME = { width: 16, height: 9 };

const UNSAVED_MESSAGE = 'You have unsaved scene changes. Leave without saving?';

export const sceneQueryKeys = {
  scene: (cameraId: string) => ['camera-scene', cameraId] as const,
  revision: (cameraId: string, revisionNumber: number) =>
    ['camera-scene-revision', cameraId, revisionNumber] as const,
};

/**
 * Configures the geometry a camera's future analytics will be evaluated
 * against.
 *
 * This page describes work that has not happened. It never reports analytics
 * readiness, matches or counts, because no analysis has run: the lifecycle that
 * would produce them arrives in a later slice.
 */
export default function SceneEditorPage() {
  const { cameraId = '' } = useParams<{ cameraId: string }>();
  const queryClient = useQueryClient();

  const camera = useQuery({
    queryKey: queryKeys.camera(cameraId),
    queryFn: ({ signal }) => getCamera(cameraId, signal),
    enabled: Boolean(cameraId),
  });
  const scene = useQuery({
    queryKey: sceneQueryKeys.scene(cameraId),
    queryFn: ({ signal }) => getCameraScene(cameraId, signal),
    enabled: Boolean(cameraId),
  });
  const videos = useQuery({
    queryKey: queryKeys.videos,
    queryFn: ({ signal }) => listVideos(signal),
  });
  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    staleTime: 60_000,
  });

  const [state, dispatch] = useReducer(editorReducer, null, () => initialEditorState(null));
  const [previewVideoId, setPreviewVideoId] = useState<string | null>(null);
  const [mediaFailed, setMediaFailed] = useState(false);
  const [viewingRevisionNumber, setViewingRevisionNumber] = useState<number | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const loadedRevisionRef = useRef<string | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);

  const activeRevision = scene.data?.activeRevision ?? null;

  // The draft follows the active revision, but only when the server actually
  // hands over a different one: re-rendering must never discard local edits.
  useEffect(() => {
    const signature = activeRevision ? activeRevision.revisionId : 'none';
    if (loadedRevisionRef.current === signature) return;
    loadedRevisionRef.current = signature;
    dispatch({ type: 'loadActive', revision: activeRevision });
    setPreviewVideoId(activeRevision?.referenceFrameVideoAssetId ?? null);
    setViewingRevisionNumber(null);
  }, [activeRevision]);

  const cameraVideos = useMemo(
    // GET /api/videos has no camera filter, so the camera's own videos are
    // selected from the list the client already holds rather than by adding an
    // endpoint for it.
    () => (videos.data ?? []).filter((video) => video.cameraId === cameraId),
    [videos.data, cameraId],
  );

  const historicalRevision = useQuery({
    queryKey: sceneQueryKeys.revision(cameraId, viewingRevisionNumber ?? 0),
    queryFn: ({ signal }) => getCameraSceneRevision(cameraId, viewingRevisionNumber as number, signal),
    enabled: Boolean(cameraId) && viewingRevisionNumber !== null,
  });

  const readOnly = viewingRevisionNumber !== null;
  const historicalDraft: SceneDraft | null = useMemo(
    () => (historicalRevision.data ? draftFromRevision(historicalRevision.data) : null),
    [historicalRevision.data],
  );
  const shownDraft = readOnly && historicalDraft ? historicalDraft : state.draft;
  const shownSelection: Selection = readOnly ? { kind: 'none' } : state.selection;

  useUnsavedChangesGuard(state.dirty, UNSAVED_MESSAGE);

  const saveMutation = useMutation({
    mutationFn: (draft: SceneDraft) => saveCameraScene(cameraId, saveRequestFromDraft(draft)),
    onSuccess: async (revision: SceneRevision) => {
      setConflict(false);
      setSaveMessage(`Saved revision ${revision.revisionNumber}.`);
      // The server-issued identities arrive with the response; the draft is
      // rebuilt from it rather than guessing what the server chose.
      loadedRevisionRef.current = revision.revisionId;
      dispatch({ type: 'savedRevision', revision });
      setPreviewVideoId(revision.referenceFrameVideoAssetId ?? null);
      await queryClient.invalidateQueries({ queryKey: sceneQueryKeys.scene(cameraId) });
    },
    onError: (error: unknown) => {
      setSaveMessage(null);
      setConflict(isRevisionConflict(error));
    },
  });

  const previewVideo: VideoAsset | undefined = previewVideoId
    ? cameraVideos.find((video) => video.id === previewVideoId)
    : undefined;

  const referenceOffsetForCanvas = readOnly
    ? historicalRevision.data?.referenceFrameOffsetMs ?? null
    : state.draft.referenceFrameOffsetMs;
  const canvasVideoId = readOnly
    ? historicalRevision.data?.referenceFrameVideoAssetId ?? null
    : previewVideoId;
  const canvasVideo = canvasVideoId ? cameraVideos.find((video) => video.id === canvasVideoId) : undefined;

  const useCurrentFrame = useCallback(() => {
    if (!previewVideoId) return;
    const video = canvasRef.current?.querySelector('video');
    const offsetMs = video && Number.isFinite(video.currentTime) ? Math.round(video.currentTime * 1000) : 0;
    dispatch({ type: 'setReferenceFrame', videoAssetId: previewVideoId, offsetMs });
  }, [previewVideoId]);

  const handleFrameClick = useCallback((point: { x: number; y: number }) => {
    if (state.tool === 'zone') {
      dispatch({ type: 'addDrawingVertex', point });
      return;
    }
    if (state.tool === 'line') {
      if (state.drawing.kind === 'line') dispatch({ type: 'finishLine', point });
      else dispatch({ type: 'startLine', point });
    }
  }, [state.tool, state.drawing.kind]);

  // Editor shortcuts must never fire while the operator is typing: Delete has
  // to delete a character in a name field, not the zone being named.
  useEffect(() => {
    if (readOnly) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (isTextEntry(target)) return;

      if (event.key === 'Escape') {
        if (state.drawing.kind !== 'none') dispatch({ type: 'cancelDrawing' });
        else if (state.selection.kind !== 'none') dispatch({ type: 'select', selection: { kind: 'none' } });
        return;
      }
      if (event.key === 'Enter' && state.drawing.kind === 'zone') {
        event.preventDefault();
        dispatch({ type: 'closeZone' });
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        if (state.selection.kind === 'none') return;
        event.preventDefault();
        dispatch({ type: 'deleteSelected' });
        return;
      }
      const nudge = nudgeFor(event.key);
      if (!nudge) return;
      const movable = (state.selection.kind === 'zone' && state.selection.vertexIndex !== null)
        || (state.selection.kind === 'line' && state.selection.endpoint !== null);
      if (!movable) return;
      event.preventDefault();
      dispatch({ type: 'nudgeVertex', dx: nudge.dx, dy: nudge.dy });
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [readOnly, state.drawing.kind, state.selection]);

  const analyticsEnabled = draftAnalyticsEnabled(state.draft);
  const saveDisabled = saveMutation.isPending || readOnly || !camera.data?.isActive;

  const submit = useCallback(() => {
    if (saveDisabled) return;
    if (!analyticsEnabled) {
      const confirmed = window.confirm(
        'Disable analytics for this camera?\n\n'
          + 'This saves a new revision in which no geometry is enabled, so no future run of this camera will be '
          + 'analysed. Earlier revisions and anything already derived from them are kept exactly as they are.',
      );
      if (!confirmed) return;
    }
    saveMutation.mutate(state.draft);
  }, [saveDisabled, analyticsEnabled, saveMutation, state.draft]);

  const reset = useCallback(() => {
    if (state.dirty && !window.confirm('Discard unsaved scene changes and return to the active revision?')) return;
    dispatch({ type: 'reset' });
    setPreviewVideoId(activeRevision?.referenceFrameVideoAssetId ?? null);
    setConflict(false);
    setSaveMessage(null);
  }, [state.dirty, activeRevision]);

  const reloadActive = useCallback(async () => {
    loadedRevisionRef.current = null;
    setConflict(false);
    await queryClient.invalidateQueries({ queryKey: sceneQueryKeys.scene(cameraId) });
  }, [queryClient, cameraId]);

  if (!cameraId) {
    return <NotFound />;
  }

  if (camera.isPending || scene.isPending) {
    return (
      <section className="page">
        <LoadingState label="Loading scene…" />
      </section>
    );
  }

  if (isCameraMissing(camera.error) || isCameraMissing(scene.error)) {
    return <NotFound />;
  }

  if (camera.isError) {
    return (
      <section className="page">
        <Alert tone="error">{sceneErrorMessage(camera.error, 'Camera is unavailable.')}</Alert>
        <div className="row"><Button icon="refresh" onClick={() => camera.refetch()}>Retry</Button></div>
      </section>
    );
  }

  if (scene.isError) {
    // An unavailable scene API must never be presented as an empty scene.
    return (
      <section className="page">
        <PageHeader title="Scene" description={camera.data?.name} />
        <Alert tone="error">{sceneErrorMessage(scene.error, 'Scene configuration is unavailable.')}</Alert>
        <div className="row"><Button icon="refresh" onClick={() => scene.refetch()}>Retry</Button></div>
      </section>
    );
  }

  const configured = scene.data?.configured ?? false;

  return (
    <section className="page scene-page">
      <PageHeader
        title={`Scene · ${camera.data?.name ?? 'Camera'}`}
        description="Zones and trip lines this camera's future analytics will be evaluated against."
        actions={<ButtonLink to="/cameras" icon="chevronLeft">Cameras</ButtonLink>}
      />

      {camera.data && !camera.data.isActive ? (
        <Alert tone="warning">This camera is inactive, so its scene cannot be changed.</Alert>
      ) : null}

      {!configured ? (
        <Alert tone="info">
          No scene configured yet. Saving creates revision 1 and activates it.
        </Alert>
      ) : null}

      {conflict ? (
        <Alert tone="error">
          This scene changed since you started editing. Your edits are still here and have not been sent.
          Reload the active revision to start from what is now saved.
          <div className="row">
            <Button size="sm" icon="refresh" onClick={reloadActive}>Reload active revision</Button>
          </div>
        </Alert>
      ) : null}

      {saveMutation.isError && !conflict ? (
        <Alert tone="error">{sceneErrorMessage(saveMutation.error, 'The scene could not be saved.')}</Alert>
      ) : null}

      {saveMessage ? <Alert tone="success">{saveMessage}</Alert> : null}

      {readOnly ? (
        <Alert tone="info">
          Viewing revision {viewingRevisionNumber} — read only. Changes always start from the active revision.
        </Alert>
      ) : null}

      <div className="scene-workspace">
        <div className="scene-workspace__main">
          <Panel
            headingId="scene-canvas-title"
            title="Reference frame"
            description={
              readOnly
                ? `Revision ${viewingRevisionNumber}`
                : `Revision ${state.draft.baseRevisionNumber || 'none'}${state.dirty ? ' · unsaved changes' : ''}`
            }
            actions={
              <div className="scene-toolbar" role="group" aria-label="Drawing tools">
                <Button
                  size="sm"
                  icon="box"
                  variant={state.tool === 'select' ? 'primary' : 'secondary'}
                  aria-pressed={state.tool === 'select'}
                  disabled={readOnly}
                  onClick={() => dispatch({ type: 'setTool', tool: 'select' })}
                >
                  Select
                </Button>
                <Button
                  size="sm"
                  icon="layers"
                  variant={state.tool === 'zone' ? 'primary' : 'secondary'}
                  aria-pressed={state.tool === 'zone'}
                  disabled={readOnly}
                  onClick={() => dispatch({ type: 'setTool', tool: 'zone' })}
                >
                  Draw zone
                </Button>
                <Button
                  size="sm"
                  icon="path"
                  variant={state.tool === 'line' ? 'primary' : 'secondary'}
                  aria-pressed={state.tool === 'line'}
                  disabled={readOnly}
                  onClick={() => dispatch({ type: 'setTool', tool: 'line' })}
                >
                  Draw trip line
                </Button>
                {state.drawing.kind === 'zone' ? (
                  <Button size="sm" icon="check" onClick={() => dispatch({ type: 'closeZone' })}>
                    Close zone
                  </Button>
                ) : null}
                {state.drawing.kind !== 'none' ? (
                  <Button size="sm" variant="ghost" onClick={() => dispatch({ type: 'cancelDrawing' })}>
                    Cancel drawing
                  </Button>
                ) : null}
              </div>
            }
          >
            <div ref={canvasRef}>
              <SceneCanvas
                draft={shownDraft}
                tool={readOnly ? 'select' : state.tool}
                selection={shownSelection}
                drawing={readOnly ? { kind: 'none' } : state.drawing}
                readOnly={readOnly}
                videoSrc={canvasVideoId ? videoContentUrl(canvasVideoId) : null}
                frameWidth={canvasVideo?.width ?? NEUTRAL_FRAME.width}
                frameHeight={canvasVideo?.height ?? NEUTRAL_FRAME.height}
                seekToMs={referenceOffsetForCanvas}
                onMediaFailed={setMediaFailed}
                onFrameClick={handleFrameClick}
                onSelect={(selection) => dispatch({ type: 'select', selection })}
                onMoveVertex={(key, vertexIndex, point) => dispatch({ type: 'moveVertex', key, vertexIndex, point })}
                onMoveEndpoint={(key, endpoint, point) => dispatch({ type: 'moveEndpoint', key, endpoint, point })}
              />
            </div>
            {state.tool === 'zone' && !readOnly ? (
              <p className="field-help">
                Click inside the frame to add vertices. Press Enter to close the zone once it has three, or Escape to
                cancel.
              </p>
            ) : null}
            {state.tool === 'line' && !readOnly ? (
              <p className="field-help">Click once for endpoint A and once for endpoint B. Escape cancels.</p>
            ) : null}
            {!canvasVideoId ? (
              <p className="field-help">
                No reference frame selected. Geometry drawn on the neutral frame is still saved in normalised
                coordinates, but it is harder to place accurately without a still from this camera.
              </p>
            ) : null}
          </Panel>

          <Panel headingId="scene-objects-title" title="Scene objects" body="padded">
            <SceneObjectList
              draft={shownDraft}
              selection={shownSelection}
              readOnly={readOnly}
              onSelect={(selection) => dispatch({ type: 'select', selection })}
              onDelete={(key) => dispatch({ type: 'deleteObject', key })}
            />
          </Panel>
        </div>

        <div className="scene-workspace__side">
          <Panel headingId="scene-properties-title" title="Properties">
            <ScenePropertiesPanel
              draft={shownDraft}
              selection={shownSelection}
              readOnly={readOnly}
              onUpdateZone={(key, changes) => dispatch({ type: 'updateZone', key, changes })}
              onUpdateLine={(key, changes) => dispatch({ type: 'updateLine', key, changes })}
            />
          </Panel>

          <Panel headingId="scene-reference-title" title="Reference frame">
            <ReferenceFramePicker
              videos={cameraVideos}
              previewVideoId={previewVideoId}
              savedVideoId={state.draft.referenceFrameVideoAssetId}
              savedOffsetMs={state.draft.referenceFrameOffsetMs}
              readOnly={readOnly}
              mediaFailed={mediaFailed}
              onPreviewVideo={setPreviewVideoId}
              onUseCurrentFrame={useCurrentFrame}
              onClear={() => dispatch({ type: 'clearReferenceFrame' })}
            />
          </Panel>

          <Panel headingId="scene-save-title" title="Save revision">
            <div className="form-stack">
              <label htmlFor="scene-note">
                Revision note (optional)
                <textarea
                  id="scene-note"
                  rows={2}
                  maxLength={500}
                  value={state.draft.note}
                  disabled={readOnly}
                  onChange={(event) => dispatch({ type: 'setNote', note: event.target.value })}
                />
              </label>
              <div className="row">
                <StatusBadge tone={analyticsEnabled ? 'info' : 'neutral'}>
                  {analyticsEnabled ? 'Analytics enabled' : 'Analytics disabled'}
                </StatusBadge>
              </div>
              <div className="row">
                <Button variant="primary" disabled={saveDisabled} onClick={submit}>
                  {saveMutation.isPending ? 'Saving…' : 'Save and activate'}
                </Button>
                <Button variant="ghost" disabled={readOnly || saveMutation.isPending} onClick={reset}>
                  Reset
                </Button>
              </div>
            </div>
          </Panel>

          <Panel headingId="scene-history-title" title="Revision history" body="padded">
            {historicalRevision.isError ? (
              <Alert tone="error">
                {sceneErrorMessage(historicalRevision.error, 'That revision could not be loaded.')}
              </Alert>
            ) : null}
            <RevisionHistory
              history={scene.data?.history ?? []}
              displayTimeZoneId={systemConfig.data?.displayTimeZoneId}
              activeRevisionNumber={activeRevision?.revisionNumber ?? null}
              viewingRevisionNumber={viewingRevisionNumber}
              onView={setViewingRevisionNumber}
              onReturnToActive={() => setViewingRevisionNumber(null)}
            />
          </Panel>
        </div>
      </div>
    </section>
  );
}

function NotFound() {
  return (
    <section className="page">
      <h1>Camera not found</h1>
      <EmptyState
        title="The requested camera does not exist."
        actions={<ButtonLink to="/cameras">Go to Cameras</ButtonLink>}
      />
    </section>
  );
}

function isTextEntry(target: HTMLElement | null): boolean {
  if (!target) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

function nudgeFor(key: string): { dx: number; dy: number } | null {
  switch (key) {
    case 'ArrowLeft': return { dx: -NUDGE_STEP, dy: 0 };
    case 'ArrowRight': return { dx: NUDGE_STEP, dy: 0 };
    case 'ArrowUp': return { dx: 0, dy: -NUDGE_STEP };
    case 'ArrowDown': return { dx: 0, dy: NUDGE_STEP };
    default: return null;
  }
}
