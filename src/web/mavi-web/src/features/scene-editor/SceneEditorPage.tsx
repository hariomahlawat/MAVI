import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getCamera } from '../../api/cameras';
import { isGuid } from '../../api/client';
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
import { combineStates } from '../../shared/async/asyncState';
import { fromQuery } from '../../shared/async/fromQuery';
import StateRegion, { SupportingRequestNotice } from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import { ContextBar, WorkbenchLayout } from '../../shared/workspace';
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
import Dialog from '../../shared/overlay/Dialog';
import { keyboardHeldElsewhere } from '../../shared/overlay/focus';
import { SHELL_QUERIES, useMediaQuery } from '../../shared/overlay/useMediaQuery';
import Panel from '../../shared/components/Panel';
import { useUnsavedChangesGuard } from './useUnsavedChangesGuard';

/** The frame the stage falls back to when no reference video is loaded. */
const NEUTRAL_FRAME = { width: 16, height: 9 };

const UNSAVED_MESSAGE = 'Your unsaved scene changes are discarded if you leave this page now.';

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
  // An unfinished polygon or line is the operator's work too: adopting a
  // revision over it would drop it with no prompt.
  dirtyRef.current = state.dirty || state.draft.note.trim().length > 0 || state.drawing.kind !== 'none';

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

  const readOnly = viewingRevisionNumber !== null;
  // §25 Tier C: the editor is not rendered below 768px (the Workbench's
  // unsupported state); the draft is this page's and is kept as it is.
  const narrow = useMediaQuery(SHELL_QUERIES.narrow);
  const narrowRef = useRef(narrow);
  narrowRef.current = narrow;
  // The server refuses every scene change on an inactive camera
  // (`scene_camera_inactive`), so its editing tools are withheld rather than
  // offered and then refused at Save: a scene that cannot be changed is shown
  // the way a past revision is — readable, selectable, not editable.
  const cameraActive = camera.data?.isActive ?? false;
  // Nor while a save is in flight: its response rebuilds the draft from the
  // server, so an edit made during the round trip would vanish unannounced.
  const editable = !readOnly && cameraActive && !saveMutation.isPending;
  // Losing editability — a camera refetched as inactive — abandons an
  // unfinished polygon or line and disarms the tool: the gesture belongs to an
  // editor that is no longer offered, so it must neither keep the leave guard
  // busy with work the operator can no longer see or cancel, nor come back
  // armed if the camera is reactivated. Completed draft changes and the note
  // are untouched (`setTool` never touches the draft).
  useEffect(() => {
    if (!editable) dispatch({ type: 'setTool', tool: 'select' });
  }, [editable]);

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
  // What the panels say in place of a revision they cannot show yet — or at
  // all: its geometry is unknown, never absent (§14: unavailable is not empty).
  // A failure with no revision read is the stage's unavailable state; a failed
  // refresh of a revision already shown keeps it — named, read only — and says
  // it may be out of date, with its retry (§37.1 degraded).
  const revisionUnavailable = historicalMissing && historicalRevision.isError;
  const revisionRefreshFailed = readOnly && !historicalMissing && historicalRevision.isError;
  const historicalPending = historicalMissing
    ? historicalRevision.isError
      ? `Revision ${viewingRevisionNumber} is unavailable.`
      : `Loading revision ${viewingRevisionNumber}…`
    : null;
  const blankDraft = useMemo(() => emptyDraft(), []);
  const shownDraft = readOnly ? (historicalDraft ?? blankDraft) : state.draft;
  const shownSelection: Selection = state.selection;

  // A control that belonged to a deleted object — its delete button, one of its
  // vertices in the inspector — leaves the page with it, and focus would fall
  // to the document body. Once the deletion has rendered, focus is returned to
  // the navigator, where the rest of the scene is still listed, so a keyboard
  // operator keeps their place.
  const recoverFocusRef = useRef(false);
  useEffect(() => {
    if (!recoverFocusRef.current) return;
    recoverFocusRef.current = false;
    const active = document.activeElement;
    if (active && active !== document.body && active.isConnected) return;
    // The navigator lists the rest of the scene; with nothing left in it, the
    // armed tool in the mode strip is where drawing the next object starts.
    (document.querySelector<HTMLElement>('[aria-label="Scene objects"] .scene-navigator__name')
      ?? document.querySelector<HTMLElement>('[aria-label="Drawing tools"] [aria-pressed="true"]'))?.focus();
  }, [state.draft, state.selection]);

  const issues = useMemo(() => (readOnly ? [] : validateDraft(state.draft)), [readOnly, state.draft]);
  const issuesForKey = useMemo(() => issuesByKey(issues), [issues]);
  const invalidKeys = useMemo(() => new Set(issuesForKey.keys()), [issuesForKey]);
  const sceneIssues = issues.filter((issue) => issue.key === null);

  // An unfinished polygon is unsaved work the draft has not been told about
  // yet, and losing a dozen placed vertices to a stray navigation is the same
  // loss as losing a saved-shaped one.
  // The one consequential decision open on this surface, if any (§15).
  const [pendingDiscard, setPendingDiscard] = useState<'reset' | 'reload' | null>(null);
  // A discard decision exists only while the editor it concerns is on screen.
  // If a background read turns the page into not-found (or back into its
  // loading/unavailable frame) while one is open, the decision is dropped:
  // otherwise it would hold the leave guard busy with no dialog left to
  // answer, silently refusing every navigation.
  const editorShown = Boolean(cameraId)
    && !isCameraMissing(camera.error) && !isCameraMissing(scene.error)
    && camera.data !== undefined && scene.data !== undefined;
  // The revision note is the operator's typing even when the geometry is back
  // at its baseline, so it is guarded, offered for Reset and kept visible.
  const noteRetained = state.draft.note.trim().length > 0;
  // A discard is decided over the draft on screen: below 768px the editor is
  // not drawn, so a Reset or Reload confirmation open when the window
  // narrows is dropped too — the draft is kept, and the leave guard still
  // asks (Codex P2 on #200).
  const discardAvailable = editorShown && !narrow;
  const leaveGuard = useUnsavedChangesGuard(
    state.dirty || noteRetained || state.drawing.kind !== 'none',
    UNSAVED_MESSAGE,
    pendingDiscard !== null && discardAvailable,
  );
  useEffect(() => {
    if (!discardAvailable && pendingDiscard !== null) setPendingDiscard(null);
  }, [discardAvailable, pendingDiscard]);


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
    if (!editable) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTextEntry(event.target as HTMLElement | null)) return;
      // Behind the navigation overlay or a Dialog the scene is covered: its
      // Delete, Enter and nudges are not the operator's keys there (§20).
      if (keyboardHeldElsewhere('.workspace__inspector')) return;
      // Nor where the editor is not drawn at all (Tier C): a key must never
      // change a draft the operator cannot see.
      if (narrowRef.current) return;

      if (event.key === 'Escape') {
        if (state.drawing.kind !== 'none') dispatch({ type: 'cancelDrawing' });
        else if (state.selection.kind !== 'none') {
          dispatch({ type: 'select', selection: { kind: 'none' } });
          // The inspector's controls for that object leave with it.
          recoverFocusRef.current = true;
        }
        return;
      }
      // Enter on the inspector's geometry controls — its disclosure, a vertex
      // — is that control's activation, not "finish the polygon". Everywhere
      // else (the armed tool keeps focus after it is pressed) Enter finishes.
      if (event.key === 'Enter' && state.drawing.kind === 'zone' && !isGeometryControl(event.target as HTMLElement | null)) {
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
        recoverFocusRef.current = true;
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
  }, [editable, state.drawing.kind, state.selection]);

  const analyticsEnabled = draftAnalyticsEnabled(state.draft);
  // Stated beside Save only when Save is the place to say it: an inactive
  // camera says why in place of the tools it withholds, and "nothing has
  // changed" is what a disabled Save says by itself.
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

  // A discard that would lose edits is decided in the product's own Dialog
  // (§15): it states what is lost and names the action. A discard that loses
  // nothing simply happens.

  const performReset = useCallback(() => {
    dispatch({ type: 'reset' });
    setPreviewVideoId(activeRevision?.referenceFrameVideoAssetId ?? null);
    setConflict(false);
    setSaved(false);
  }, [activeRevision]);

  const reset = useCallback(() => {
    if (state.dirty || noteRetained) {
      setPendingDiscard('reset');
      return;
    }
    performReset();
  }, [state.dirty, noteRetained, performReset]);

  const performReload = useCallback(async () => {
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
  }, [queryClient, cameraId, adopt]);

  const reloadActive = useCallback(() => {
    if (state.dirty || noteRetained) {
      setPendingDiscard('reload');
      return;
    }
    void performReload();
  }, [state.dirty, noteRetained, performReload]);

  const discardDialog = (
    <Dialog
      open={pendingDiscard !== null && discardAvailable}
      title={pendingDiscard === 'reload' ? 'Discard your changes and load the saved revision?' : 'Discard your unsaved scene changes?'}
      confirmLabel={pendingDiscard === 'reload' ? 'Discard and load revision' : 'Discard changes'}
      destructive
      onCancel={() => setPendingDiscard(null)}
      onConfirm={() => {
        const action = pendingDiscard;
        setPendingDiscard(null);
        if (action === 'reset') performReset();
        else if (action === 'reload') void performReload();
      }}
    >
      {pendingDiscard === 'reload'
        ? 'Your unsaved edits are discarded and the editor loads the revision that was saved while you were editing. This cannot be undone.'
        : 'Your unsaved edits are discarded and the editor returns to the active revision. This cannot be undone.'}
    </Dialog>
  );

  // The leave guard is rendered in every branch: the router keeps blocking
  // while the draft is dirty, so a branch without it would hold a navigation
  // with nothing on screen to release it.
  // The camera this route names, in every branch below (§5): its code and name
  // once read, otherwise its identifier shortened. A state — loading, missing,
  // unavailable — is said by the region, never in place of the camera.
  const cameraCrumb = cameraIdentity(cameraId, camera.data);

  if (!cameraId) return <>{leaveGuard}<NotFound camera={cameraCrumb} /></>;

  if (isCameraMissing(camera.error) || isCameraMissing(scene.error)) return <>{leaveGuard}<NotFound camera={cameraCrumb} /></>;

  // The camera and its scene are one page region (§37.1, page): the editor
  // cannot be drawn until both have answered, a failure of either is one alert
  // whose retry re-requests what failed, and the Context Bar keeps the
  // surface's identity throughout. An unavailable scene API must never be
  // presented as an empty scene.
  if (camera.data === undefined || scene.data === undefined) {
    return (
      <section className="page page--full page--workspace">
        {leaveGuard}
        <ContextBar surface="scene" object={cameraCrumb ? { label: cameraCrumb } : undefined} />
        <StateRegion
          kind="page"
          state={combineStates(fromQuery(camera), fromQuery(scene))}
          label="the scene"
          loadingLabel="Loading scene…"
          unavailableMessage={(error) => sceneErrorMessage(
            error,
            // The request with no data is the one that failed to load; a camera
            // already read whose refresh failed is not the subject.
            camera.data === undefined && camera.isError ? 'The camera could not be loaded.' : 'The scene could not be loaded.',
          )}
          onRetry={() => {
            if (camera.isError) void camera.refetch();
            if (scene.isError) void scene.refetch();
          }}
        >
          {() => null}
        </StateRegion>
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
      {/* An inactive camera is said once, in place of the tools it withholds
          (the mode strip), not again here. */}
      {conflict ? (
        <Alert
          tone="error"
          // At Tier C the draft is not drawn: a discard of edits the operator
          // cannot review is not offered there (Codex P2 on #200).
          actions={narrow ? undefined : <Button size="sm" icon="refresh" onClick={reloadActive}>Reload active revision</Button>}
        >
          This scene changed since you started editing. Your edits are still here and have not been sent.
          {narrow
            ? ' Review them, or reload what is now saved, on a display at least 768px wide.'
            : ' Reloading discards them and loads what is now saved.'}
        </Alert>
      ) : null}
      {supersededRevision !== null && !conflict ? (
        <Alert
          tone="warning"
          actions={narrow ? undefined : (
            <Button size="sm" icon="refresh" onClick={adoptActiveRevision}>
              Discard my changes and load revision {supersededRevision}
            </Button>
          )}
        >
          Somebody saved revision {supersededRevision} while you were editing. Your unsaved changes are untouched, but
          saving them now will be refused as a conflict.
          {narrow ? ' Review them, or load the new revision, on a display at least 768px wide.' : ''}
        </Alert>
      ) : null}
      {saveMutation.isError && !conflict ? (
        <Alert tone="error">{sceneErrorMessage(saveMutation.error, 'The scene could not be saved.')}</Alert>
      ) : null}
      {/* The reference video and a historical revision are the stage's own
          content, so their failures are said on the stage (§37.1: in the
          region they affect), not stacked above the workspace — and a revision
          loading there moves nothing (§36.3). */}
      {/* The camera and scene already on screen keep the editor working when a
          refresh fails; it says so rather than going quiet (§14.1, degraded). */}
      <SupportingRequestNotice
        state={combineStates(fromQuery(camera), fromQuery(scene))}
        unavailableMessage={null}
        degradedMessage="The saved scene could not be refreshed. The editor shows what was last loaded; your unsaved changes are untouched."
        onRetry={() => {
          void camera.refetch();
          void scene.refetch();
        }}
      />
      {sceneIssues.length > 0 ? (
        <Alert tone="warning">{sceneIssues.map((issue) => issue.message).join(' ')}</Alert>
      ) : null}
      {/* Both of these explain the Save button, which lives in the Context Bar
          above. A 44px band cannot hold a sentence, so they are stated here and
          referenced from the control by `aria-describedby`: the association is
          the part that matters, and it does not depend on adjacency. */}
      {blockedReason && !narrow ? (
        <p className="scene-notice" id="scene-save-blocked">{blockedReason}</p>
      ) : null}
      {confirmingDisable && !narrow ? (
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
      {leaveGuard}
      {discardDialog}
      <SceneContextBar
        cameraCode={camera.data.code}
        cameraName={camera.data.name}
        revisionNumber={readOnly ? (viewingRevisionNumber as number) : state.draft.baseRevisionNumber}
        saveState={saveState}
        analyticsEnabled={readOnly ? (historicalRevision.data?.analyticsEnabled ?? null) : analyticsEnabled}
        note={state.draft.note}
        canSave={canSave}
        blockedReason={blockedReason}
        inactive={!cameraActive}
        noteRetained={noteRetained}
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
        unsupported={{
          statement: 'Editing a scene needs a display at least 768px wide. This is a read-only summary of it.',
          summary: (
            <Panel title={readOnly ? `Revision ${viewingRevisionNumber as number}` : 'Scene'}>
              {revisionRefreshFailed ? (
                // As the stage says it above Tier C: retained, and not current.
                <Alert
                  tone="warning"
                  actions={<Button size="sm" onClick={() => void historicalRevision.refetch()}>Retry</Button>}
                >
                  {`Revision ${viewingRevisionNumber} could not be refreshed. It is shown as last loaded.`}
                </Alert>
              ) : null}
              {readOnly && !historicalDraft ? (
                // The stage says this above Tier C; here it is the summary's
                // whole content, never an empty revision (§37.1).
                <StateRegion
                  kind="panel"
                  state={fromQuery(historicalRevision)}
                  label={`revision ${viewingRevisionNumber as number}`}
                  loadingLabel={`Loading revision ${viewingRevisionNumber as number}…`}
                  unavailableMessage={(error) => sceneErrorMessage(error, `Revision ${viewingRevisionNumber as number} could not be loaded.`)}
                  onRetry={() => void historicalRevision.refetch()}
                >
                  {() => null}
                </StateRegion>
              ) : (
              <dl className="kv">
                <dt>Camera</dt>
                <dd>{`${camera.data.code} · ${camera.data.name}`}{cameraActive ? '' : ' (inactive)'}</dd>
                <dt>Revision</dt>
                <dd>
                  {readOnly
                    ? `Revision ${viewingRevisionNumber as number}, a past revision`
                    : state.draft.baseRevisionNumber > 0 ? `Revision ${state.draft.baseRevisionNumber}, active` : 'No revision saved yet'}
                </dd>
                {(readOnly ? historicalRevision.data?.analyticsEnabled ?? null : analyticsEnabled) === null ? null : (
                  <>
                    <dt>Analytics</dt>
                    <dd>{(readOnly ? historicalRevision.data?.analyticsEnabled : analyticsEnabled) ? 'On' : 'Off'}</dd>
                  </>
                )}
                <dt>Zones</dt>
                <dd>{shownDraft.zones.length ? shownDraft.zones.map((zone) => zone.name).join(', ') : 'None'}</dd>
                <dt>Trip lines</dt>
                <dd>{shownDraft.tripLines.length ? shownDraft.tripLines.map((line) => line.name).join(', ') : 'None'}</dd>
              </dl>
              )}
              {!readOnly && (state.dirty || noteRetained) ? (
                // Said plainly, not as an alarm: nothing has been lost or sent.
                <p className="scene-notice" role="status">
                  This scene has unsaved changes. They are kept while this page stays open; review and save them on a
                  display at least 768px wide.
                </p>
              ) : null}
            </Panel>
          ),
        }}
        modes={(
          <SceneToolbar
            tool={state.tool}
            drawing={editable ? state.drawing : { kind: 'none' }}
            withheld={{ revision: readOnly, inactive: !cameraActive }}
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
              tool={editable ? state.tool : 'select'}
              selection={shownSelection}
              drawing={editable ? state.drawing : { kind: 'none' }}
              readOnly={!editable}
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
                  <div className={`scene-stage__banner${readOnly && !revisionUnavailable ? '' : ' is-idle'}`} role="status">
                    {/* The revision's own request: loading said in place, in the
                        shared loading grammar (§37.1, row), then its name — which
                        a failed refresh of a revision already shown keeps. */}
                    {readOnly && !revisionUnavailable ? (
                      historicalMissing
                        ? <span className="state-row state-row--loading">{`Loading revision ${viewingRevisionNumber}…`}</span>
                        : `Viewing revision ${viewingRevisionNumber} — read only`
                    ) : null}
                  </div>
                  {revisionRefreshFailed ? (
                    <div className="scene-stage__refresh">
                      <Alert
                        tone="warning"
                        actions={<Button size="sm" onClick={() => void historicalRevision.refetch()}>Retry</Button>}
                      >
                        {`Revision ${viewingRevisionNumber} could not be refreshed. It is shown as last loaded.`}
                      </Alert>
                    </div>
                  ) : null}
                  {/* A past revision that will not load leaves nothing to show:
                      the stage says so, with its retry, instead of drawing the
                      active geometry (or nothing) under the revision's name. */}
                  {revisionUnavailable ? (
                    <div className="scene-stage__state">
                      <Alert
                        tone="error"
                        actions={<Button size="sm" onClick={() => void historicalRevision.refetch()}>Retry</Button>}
                      >
                        {sceneErrorMessage(historicalRevision.error, `Revision ${viewingRevisionNumber} could not be loaded.`)}
                      </Alert>
                    </div>
                  ) : null}
                  {mediaFailed && !revisionUnavailable ? (
                    <p className="scene-stage__media-note" role="status">
                      Reference video unavailable · geometry is shown on a blank frame and is unchanged
                    </p>
                  ) : null}
                  {/* The empty state invites the first object; once a tool is armed the
                      operator has accepted the invitation, so it gets out of the way of
                      the surface they are drawing on. */}
                  {/* The mode strip is the drawing control (§4.3). An empty scene
                      adds one invitation to it — the first zone, through the
                      same tool — and steps aside once a tool is armed. */}
                  {editable && !configured && state.tool === 'select'
                    && shownDraft.zones.length === 0 && shownDraft.tripLines.length === 0 ? (
                    <div className={`scene-stage__intro${canvasVideoId && !mediaFailed ? '' : ' is-empty'}`}>
                      <strong>No scene configured</strong>
                      <span>
                        {cameraVideos.length > 0
                          ? 'Choose a reference video below and scrub to a clear frame. Zones and trip lines are drawn with the tools above.'
                          : 'No imported video is available for this camera, so geometry is drawn on the normalised frame with the tools above.'}
                      </span>
                      <Button variant="primary" size="sm" onClick={() => dispatch({ type: 'setTool', tool: 'zone' })}>
                        Draw a zone
                      </Button>
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

            {/* The video list is the reference bar's own region (§37.1): it loads,
                is unavailable with its retry in the alert, or is the bar. Not the
                same thing as a camera with no imported video — saying so would be
                reporting an outage as a fact about the camera. */}
            <StateRegion
              kind="panel"
              state={fromQuery(videos)}
              label="video list"
              unavailableMessage={() => 'The video list is unavailable, so no reference frame can be chosen right now. Geometry is still saved in normalised coordinates.'}
              degradedMessage="Showing the last known video list; refreshing failed."
              onRetry={() => videos.refetch()}
            >
              {() => (
                <ReferenceFrameBar
                  videos={cameraVideos}
                  videoRef={videoRef}
                  previewVideoId={readOnly ? canvasVideoId : previewVideoId}
                  savedVideoId={readOnly
                    ? historicalRevision.data?.referenceFrameVideoAssetId ?? null
                    : state.draft.referenceFrameVideoAssetId}
                  savedOffsetMs={readOnly
                    ? historicalRevision.data?.referenceFrameOffsetMs ?? null
                    : state.draft.referenceFrameOffsetMs}
                  readOnly={!editable}
                  onPreviewVideo={setPreviewVideoId}
                  onUseCurrentFrame={(offsetMs) => {
                    if (!previewVideoId) return;
                    dispatch({ type: 'setReferenceFrame', videoAssetId: previewVideoId, offsetMs });
                  }}
                  onClear={() => dispatch({ type: 'clearReferenceFrame' })}
                />
              )}
            </StateRegion>
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
              readOnly={!editable}
              historical={readOnly}
              pending={historicalPending}
              pendingLoading={historicalMissing && !historicalRevision.isError}
              invalidKeys={invalidKeys}
              onSelect={(selection) => dispatch({ type: 'select', selection })}
              onDelete={(key) => {
                dispatch({ type: 'deleteObject', key });
                recoverFocusRef.current = true;
              }}
            />
            <ScenePropertiesPanel
              draft={shownDraft}
              selection={shownSelection}
              pending={historicalPending}
              readOnly={!editable}
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

/**
 * The camera's identity for the crumb: `CODE · Name` once read, otherwise the
 * route's identifier shortened (§14); none when the route names no valid camera.
 */
function cameraIdentity(cameraId: string, camera: { code: string; name: string } | undefined): string | undefined {
  if (camera) return `${camera.code} · ${camera.name}`;
  return isGuid(cameraId) ? `Camera ${cameraId.toLowerCase().slice(0, 8)}…` : undefined;
}

/**
 * A missing camera. Still the Scene surface under Cameras (§5) — not the global
 * Not found — so it keeps its Context Bar and the camera the route names; the
 * bar carries the page's h1, and the state is said once, in the shell's own
 * not-found grammar.
 */
function NotFound({ camera }: { camera?: string }) {
  return (
    <section className="page page--full">
      <ContextBar surface="scene" object={camera ? { label: camera } : undefined} />
      <EmptyState title="This camera does not exist." actions={<ButtonLink to="/cameras">Go to Cameras</ButtonLink>}>
        The address may be mistyped. Choose the camera from the list instead.
      </EmptyState>
    </section>
  );
}

/** The inspector's forensic-tier controls, whose own activation Enter is. */
function isGeometryControl(target: HTMLElement | null): boolean {
  return Boolean(target?.closest('.scene-inspector__geometry'));
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
