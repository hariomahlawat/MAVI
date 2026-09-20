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
import { WorkbenchLayout } from '../../shared/workspace';
import { editorReducer, initialEditorState, NUDGE_STEP, type Selection } from './editorState';
import ReferenceFrameBar from './ReferenceFrameBar';
import RevisionHistory from './RevisionHistory';
import SceneCanvas from './SceneCanvas';
import SceneContextBar from './SceneContextBar';
import {
  draftAnalyticsEnabled,
  draftFromRevision,
  emptyDraft,
  saveRequestFromDraft,
  type SceneDraft,
} from './sceneDraft';
import { isCameraMissing, isRevisionConflict, sceneErrorMessage } from './sceneErrors';
import SceneObjectList from './SceneObjectList';
import ScenePropertiesPanel from './ScenePropertiesPanel';
import SceneToolbar from './SceneToolbar';
import { issuesByKey, validateDraft } from './sceneValidation';
import { useUnsavedChangesGuard } from './useUnsavedChangesGuard';

/** The frame the stage falls back to when no reference video is loaded. */
const NEUTRAL_FRAME = { width: 16, height: 9 };

const UNSAVED_MESSAGE = 'You have unsaved scene changes. Leave without saving?';

export const sceneQueryKeys = {
  scene: (cameraId: string) => ['camera-scene', cameraId] as const,
  revision: (cameraId: string, revisionNumber: number) =>
    ['camera-scene-revision', cameraId, revisionNumber] as const,
};

/**
 * The scene configuration workstation.
 *
 * The frame is the work, so it takes the room; everything else is a compact
 * band around it. The page describes work that has not happened: it never
 * reports analytics readiness, matches or counts, because no analysis has run.
 * The lifecycle that would produce them arrives in a later slice.
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
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const [saved, setSaved] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [supersededRevision, setSupersededRevision] = useState<number | null>(null);
  const loadedRevisionRef = useRef<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  // Read inside an effect that must not re-run when it changes. A note never
  // dirties the draft — it describes the save, not the scene — but it is still
  // the operator's typing, so adopting a revision over it would lose work.
  const dirtyRef = useRef(state.dirty);
  dirtyRef.current = state.dirty || state.draft.note.trim().length > 0;

  const activeRevision = scene.data?.activeRevision ?? null;

  // The draft follows the active revision, but never at the cost of the
  // operator's work. A refetch can bring back a revision somebody else saved
  // while this scene was being edited; adopting it would erase unsaved
  // geometry with no prompt and no way back, so instead the page says what
  // happened and leaves the decision, and the draft, alone. A save from here
  // is refused by the server as a conflict, which is exactly right.
  useEffect(() => {
    const signature = activeRevision ? activeRevision.revisionId : 'none';
    if (loadedRevisionRef.current === signature) return;
    if (dirtyRef.current) {
      setSupersededRevision(activeRevision?.revisionNumber ?? null);
      return;
    }
    loadedRevisionRef.current = signature;
    setSupersededRevision(null);
    dispatch({ type: 'loadActive', revision: activeRevision });
    setPreviewVideoId(activeRevision?.referenceFrameVideoAssetId ?? null);
    setViewingRevisionNumber(null);
  }, [activeRevision]);

  /** Adopts a saved revision, discarding the local draft on purpose. */
  const adopt = useCallback((revision: SceneRevision | null) => {
    loadedRevisionRef.current = revision ? revision.revisionId : 'none';
    dirtyRef.current = false;
    setSupersededRevision(null);
    setConflict(false);
    dispatch({ type: 'loadActive', revision });
    setPreviewVideoId(revision?.referenceFrameVideoAssetId ?? null);
    setViewingRevisionNumber(null);
  }, []);

  const adoptActiveRevision = useCallback(() => adopt(activeRevision), [adopt, activeRevision]);

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

  // The two drafts mint their own local keys, so a selection made in one names
  // nothing in the other. Crossing between them without clearing it leaves the
  // inspector reporting "nothing selected" while an object still looks picked.
  // An unfinished polygon is abandoned for the same reason: it belongs to the
  // editable draft, and carrying it into a read-only revision would leave a
  // finish action that commits invisible geometry to a scene the operator is
  // not looking at.
  useEffect(() => {
    dispatch({ type: 'select', selection: { kind: 'none' } });
    dispatch({ type: 'cancelDrawing' });
  }, [readOnly, viewingRevisionNumber]);
  const historicalDraft: SceneDraft | null = useMemo(
    () => (historicalRevision.data ? draftFromRevision(historicalRevision.data) : null),
    [historicalRevision.data],
  );
  // While the revision is still loading — or if it never arrives — there is no
  // historical geometry to show. Falling back to the editable draft would put
  // the active scene under a banner naming a past revision, which is the one
  // confusion this mode exists to prevent.
  const historicalMissing = readOnly && historicalDraft === null;
  const blankDraft = useMemo(() => emptyDraft(), []);
  const shownDraft = readOnly ? (historicalDraft ?? blankDraft) : state.draft;
  const shownSelection: Selection = state.selection;

  const issues = useMemo(() => (readOnly ? [] : validateDraft(state.draft)), [readOnly, state.draft]);
  const issuesForKey = useMemo(() => issuesByKey(issues), [issues]);
  const invalidKeys = useMemo(() => new Set(issuesForKey.keys()), [issuesForKey]);
  const sceneIssues = issues.filter((issue) => issue.key === null);

  // An unfinished polygon is unsaved work the draft has not been told about
  // yet, and losing a dozen placed vertices to a stray navigation is the same
  // loss as losing a saved-shaped one.
  useUnsavedChangesGuard(state.dirty || state.drawing.kind !== 'none', UNSAVED_MESSAGE);

  const saveMutation = useMutation({
    mutationFn: (draft: SceneDraft) => saveCameraScene(cameraId, saveRequestFromDraft(draft)),
    onSuccess: async (revision: SceneRevision) => {
      setConflict(false);
      setSaved(true);
      // The server-issued identities arrive with the response; the draft is
      // rebuilt from it rather than guessing what the server chose.
      loadedRevisionRef.current = revision.revisionId;
      dispatch({ type: 'savedRevision', revision });
      setPreviewVideoId(revision.referenceFrameVideoAssetId ?? null);
      await queryClient.invalidateQueries({ queryKey: sceneQueryKeys.scene(cameraId) });
    },
    onError: (error: unknown) => {
      setSaved(false);
      setConflict(isRevisionConflict(error));
    },
  });

  const referenceOffsetForCanvas = readOnly
    ? historicalRevision.data?.referenceFrameOffsetMs ?? null
    : state.draft.referenceFrameOffsetMs;
  const canvasVideoId = readOnly
    ? historicalRevision.data?.referenceFrameVideoAssetId ?? null
    : previewVideoId;
  const canvasVideo: VideoAsset | undefined = canvasVideoId
    ? cameraVideos.find((video) => video.id === canvasVideoId)
    : undefined;

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
      if (isTextEntry(event.target as HTMLElement | null)) return;

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
      // Delete only. Backspace is a navigation gesture in some configurations
      // and reaches here from any control that is not a text field, which is
      // far too wide a blast radius for destroying an object.
      if (event.key === 'Delete') {
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
  const cameraActive = camera.data?.isActive ?? false;
  // Stated beside Save only when Save is the place to say it: an inactive
  // camera already has its own notice above, and "nothing has changed" is what
  // a disabled Save says by itself.
  const blockedReason = cameraActive && issues.length > 0
    ? 'Fix the highlighted problems before saving.'
    : null;
  const canSave = !readOnly && !saveMutation.isPending && cameraActive
    && issues.length === 0 && state.dirty;

  // Saving a revision with nothing enabled turns this camera's analytics off.
  // That is a deliberate operation, not an accident, so it is confirmed in the
  // page rather than in an OS dialog: browser confirms cannot say what is at
  // stake in the product's own language, and a browser that offers to suppress
  // further dialogs would quietly remove the safeguard for the session.
  const [confirmingDisable, setConfirmingDisable] = useState(false);

  useEffect(() => {
    if (analyticsEnabled || !canSave) setConfirmingDisable(false);
  }, [analyticsEnabled, canSave]);

  const submit = useCallback(() => {
    if (!canSave) return;
    if (!analyticsEnabled && !confirmingDisable) {
      setConfirmingDisable(true);
      return;
    }
    setConfirmingDisable(false);
    saveMutation.mutate(state.draft);
  }, [canSave, analyticsEnabled, confirmingDisable, saveMutation, state.draft]);

  const reset = useCallback(() => {
    if (state.dirty && !window.confirm('Discard unsaved scene changes and return to the active revision?')) return;
    dispatch({ type: 'reset' });
    setPreviewVideoId(activeRevision?.referenceFrameVideoAssetId ?? null);
    setConflict(false);
    setSaved(false);
  }, [state.dirty, activeRevision]);

  const reloadActive = useCallback(async () => {
    if (state.dirty
      && !window.confirm('Discard your unsaved scene changes and load the revision that is now saved?')) {
      return;
    }
    // Adopt what the refetch returns rather than waiting for the query's own
    // value to change identity. React Query shares structure between fetches,
    // so a refetch that returns an unchanged scene hands back the same object,
    // the load effect never re-runs, and the draft would be left dirty against
    // a revision it can no longer save on to — with the operator having been
    // told their work was discarded.
    const refreshed = await queryClient.fetchQuery({
      queryKey: sceneQueryKeys.scene(cameraId),
      queryFn: ({ signal }) => getCameraScene(cameraId, signal),
      staleTime: 0,
    });
    adopt(refreshed.activeRevision ?? null);
  }, [queryClient, cameraId, state.dirty, adopt]);

  if (!cameraId) return <NotFound />;

  if (camera.isPending || scene.isPending) {
    return (
      <section className="page page--full page--workspace">
        <LoadingState label="Loading scene…" />
      </section>
    );
  }

  if (isCameraMissing(camera.error) || isCameraMissing(scene.error)) return <NotFound />;

  if (camera.isError) {
    return (
      <section className="page page--full">
        <Alert tone="error">{sceneErrorMessage(camera.error, 'Camera is unavailable.')}</Alert>
        <div className="row"><Button icon="refresh" onClick={() => camera.refetch()}>Retry</Button></div>
      </section>
    );
  }

  if (scene.isError) {
    // An unavailable scene API must never be presented as an empty scene.
    return (
      <section className="page page--full">
        <Alert tone="error">{sceneErrorMessage(scene.error, 'Scene configuration is unavailable.')}</Alert>
        <div className="row"><Button icon="refresh" onClick={() => scene.refetch()}>Retry</Button></div>
      </section>
    );
  }

  const configured = scene.data?.configured ?? false;
  const saveState = readOnly
    ? 'readonly' as const
    : saveMutation.isPending
      ? 'saving' as const
      : state.dirty
        ? 'dirty' as const
        : saved
          ? 'saved' as const
          : 'clean' as const;

  const notices = (
    <>
      {!cameraActive ? (
        <Alert tone="warning">This camera is inactive, so its scene cannot be changed.</Alert>
      ) : null}
      {conflict ? (
        <Alert tone="error">
          This scene changed since you started editing. Your edits are still here and have not been sent.
          Reload the active revision to start again from what is now saved.
          <div className="row">
            <Button size="sm" icon="refresh" onClick={reloadActive}>Reload active revision</Button>
          </div>
        </Alert>
      ) : null}
      {supersededRevision !== null && !conflict ? (
        <Alert tone="warning">
          Somebody saved revision {supersededRevision} while you were editing. Your unsaved changes are untouched, but
          saving them now will be refused as a conflict.
          <div className="row">
            <Button size="sm" icon="refresh" onClick={adoptActiveRevision}>
              Discard my changes and load revision {supersededRevision}
            </Button>
          </div>
        </Alert>
      ) : null}
      {saveMutation.isError && !conflict ? (
        <Alert tone="error">{sceneErrorMessage(saveMutation.error, 'The scene could not be saved.')}</Alert>
      ) : null}
      {mediaFailed ? (
        <Alert tone="warning">
          The reference video could not be loaded. The scene and its reference metadata are unchanged.
        </Alert>
      ) : null}
      {historicalRevision.isError ? (
        <Alert tone="error">
          <div className="row">
            <span>{sceneErrorMessage(historicalRevision.error, 'That revision could not be loaded.')}</span>
            <Button size="sm" onClick={() => historicalRevision.refetch()}>Try again</Button>
          </div>
        </Alert>
      ) : historicalMissing ? (
        <Alert tone="info">Loading revision {viewingRevisionNumber}…</Alert>
      ) : null}
      {videos.isError ? (
        // Not the same thing as a camera with no imported video: saying so
        // would be reporting an outage as a fact about the camera.
        <Alert tone="warning">
          <div className="row">
            <span>The video list is unavailable, so no reference frame can be chosen right now.</span>
            <Button size="sm" onClick={() => videos.refetch()}>Try again</Button>
          </div>
        </Alert>
      ) : null}
      {sceneIssues.length > 0 ? (
        <Alert tone="warning">{sceneIssues.map((issue) => issue.message).join(' ')}</Alert>
      ) : null}
      {/* Both of these explain the Save button, which lives in the Context Bar
          above. A 44px band cannot hold a sentence, so they are stated here and
          referenced from the control by `aria-describedby`: the association is
          the part that matters, and it does not depend on adjacency. */}
      {blockedReason ? (
        <p className="scene-notice" id="scene-save-blocked">{blockedReason}</p>
      ) : null}
      {confirmingDisable ? (
        // Stated once, plainly, in the place the operator is already looking.
        // Nothing about this is an emergency, so nothing about it is red; it is
        // simply a consequence worth reading before it happens.
        <p className="scene-notice scene-notice--confirm" id="scene-disable-confirm" role="status">
          Nothing here is enabled, so saving stops future runs of this camera being analysed. Earlier
          revisions are unchanged.
        </p>
      ) : null}
    </>
  );

  return (
    <section className="page page--full page--workspace">
      <SceneContextBar
        cameraCode={camera.data?.code ?? 'Camera'}
        cameraName={camera.data?.name ?? ''}
        revisionNumber={readOnly ? (viewingRevisionNumber as number) : state.draft.baseRevisionNumber}
        saveState={saveState}
        analyticsEnabled={readOnly ? (historicalRevision.data?.analyticsEnabled ?? false) : analyticsEnabled}
        note={state.draft.note}
        canSave={canSave}
        blockedReason={blockedReason}
        confirmingDisable={confirmingDisable}
        onNoteChange={(note) => dispatch({ type: 'setNote', note })}
        onReset={reset}
        onSave={submit}
        onCancelDisable={() => setConfirmingDisable(false)}
        onReturnToActive={() => setViewingRevisionNumber(null)}
      />

      <WorkbenchLayout
        inspectorLabel="Scene inspector"
        notices={notices}
        modes={(
          <SceneToolbar
            tool={state.tool}
            drawing={readOnly ? { kind: 'none' } : state.drawing}
            readOnly={readOnly}
            historyOpen={historyExpanded}
            drawingError={state.drawingError}
            onToolChange={(tool) => dispatch({ type: 'setTool', tool })}
            onCloseZone={() => dispatch({ type: 'closeZone' })}
            onCancelDrawing={() => dispatch({ type: 'cancelDrawing' })}
            onToggleHistory={() => setHistoryExpanded((value) => !value)}
          />
        )}
        stage={(
          <>
            <SceneCanvas
              draft={shownDraft}
              tool={readOnly ? 'select' : state.tool}
              selection={shownSelection}
              drawing={readOnly ? { kind: 'none' } : state.drawing}
              readOnly={readOnly}
              videoSrc={canvasVideoId ? videoContentUrl(canvasVideoId) : null}
              videoRef={videoRef}
              frameWidth={canvasVideo?.width ?? NEUTRAL_FRAME.width}
              frameHeight={canvasVideo?.height ?? NEUTRAL_FRAME.height}
              seekToMs={referenceOffsetForCanvas}
              invalidKeys={invalidKeys}
              overlay={
                <>
                  {/* The live region stays mounted and is written into, because
                      one that appears already populated is routinely not
                      announced — and entering read-only is exactly the mode
                      change a screen-reader user must not miss. */}
                  <div className={`scene-stage__banner${readOnly ? '' : ' is-idle'}`} role="status">
                    {readOnly ? `Viewing revision ${viewingRevisionNumber} — read only` : ''}
                  </div>
                  {/* The empty state invites the first object; once a tool is armed the
                      operator has accepted the invitation, so it gets out of the way of
                      the surface they are drawing on. */}
                  {!readOnly && !configured && state.tool === 'select'
                    && shownDraft.zones.length === 0 && shownDraft.tripLines.length === 0 ? (
                    <div className={`scene-stage__intro${canvasVideoId ? '' : ' is-empty'}`}>
                      <strong>No scene configured</strong>
                      <span>
                        {cameraVideos.length > 0
                          ? 'Choose a reference video below, scrub to a clear frame, then draw zones and trip lines.'
                          : 'No imported video is available for this camera. You can still configure geometry on the '
                            + 'normalised frame.'}
                      </span>
                      <div className="row">
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={() => dispatch({ type: 'setTool', tool: 'zone' })}
                        >
                          Draw a zone
                        </Button>
                        <Button size="sm" onClick={() => dispatch({ type: 'setTool', tool: 'line' })}>
                          Draw a trip line
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </>
              }
              onMediaFailed={setMediaFailed}
              onFrameClick={handleFrameClick}
              onCloseZone={() => dispatch({ type: 'closeZone' })}
              onSelect={(selection) => dispatch({ type: 'select', selection })}
              onMoveVertex={(key, vertexIndex, point) => dispatch({ type: 'moveVertex', key, vertexIndex, point })}
              onMoveEndpoint={(key, endpoint, point) => dispatch({ type: 'moveEndpoint', key, endpoint, point })}
            />

            <ReferenceFrameBar
              videos={cameraVideos}
              videoRef={videoRef}
              previewVideoId={readOnly ? canvasVideoId : previewVideoId}
              videosUnavailable={videos.isError}
              savedVideoId={readOnly
                ? historicalRevision.data?.referenceFrameVideoAssetId ?? null
                : state.draft.referenceFrameVideoAssetId}
              savedOffsetMs={readOnly
                ? historicalRevision.data?.referenceFrameOffsetMs ?? null
                : state.draft.referenceFrameOffsetMs}
              readOnly={readOnly}
              onPreviewVideo={setPreviewVideoId}
              onUseCurrentFrame={(offsetMs) => {
                if (!previewVideoId) return;
                dispatch({ type: 'setReferenceFrame', videoAssetId: previewVideoId, offsetMs });
              }}
              onClear={() => dispatch({ type: 'clearReferenceFrame' })}
            />
          </>
        )}
        inspector={(
          // Two panels in one inspector column: the navigator is the scene
          // listed, and the properties panel is the selected object. Keeping
          // them apart is what stops selecting something pushing the rest of
          // the scene out of view. The column's stacking belongs to the
          // archetype, not to this page.
          <>
            <SceneObjectList
              draft={shownDraft}
              selection={shownSelection}
              readOnly={readOnly}
              invalidKeys={invalidKeys}
              onSelect={(selection) => dispatch({ type: 'select', selection })}
              onDelete={(key) => dispatch({ type: 'deleteObject', key })}
              onAddZone={() => dispatch({ type: 'setTool', tool: 'zone' })}
              onAddLine={() => dispatch({ type: 'setTool', tool: 'line' })}
            />
            <ScenePropertiesPanel
              draft={shownDraft}
              selection={shownSelection}
              readOnly={readOnly}
              issues={issuesForKey}
              onUpdateZone={(key, changes) => dispatch({ type: 'updateZone', key, changes })}
              onUpdateLine={(key, changes) => dispatch({ type: 'updateLine', key, changes })}
              onSelect={(selection) => dispatch({ type: 'select', selection })}
            />
          </>
        )}
        footer={(
          <RevisionHistory
            history={scene.data?.history ?? []}
            displayTimeZoneId={systemConfig.data?.displayTimeZoneId}
            activeRevisionNumber={activeRevision?.revisionNumber ?? null}
            viewingRevisionNumber={viewingRevisionNumber}
            expanded={historyExpanded}
            onView={setViewingRevisionNumber}
            onReturnToActive={() => setViewingRevisionNumber(null)}
          />
        )}
      />
    </section>
  );
}

function NotFound() {
  return (
    <section className="page page--full">
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
