import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getCamera } from '../../api/cameras';
import { ApiError } from '../../api/client';
import {
  getCameraScene,
  getCameraSceneRevision,
  saveCameraScene,
  type CameraScene,
  type SaveSceneRequest,
  type SceneRevision,
} from '../../api/scene';
import { getSystemConfig } from '../../api/system';
import { listVideos, type VideoAsset } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import { renderWithApp } from '../../test/renderWithApp';
import SceneEditorPage, { sceneQueryKeys } from './SceneEditorPage';
import { SHELL_QUERIES } from '../../shared/overlay/useMediaQuery';
import { stubMatchMediaLive } from '../../test/matchMedia';

vi.mock('../../api/cameras', () => ({ getCamera: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn() };
});
vi.mock('../../api/scene', async () => {
  const actual = await vi.importActual<typeof import('../../api/scene')>('../../api/scene');
  return { ...actual, getCameraScene: vi.fn(), getCameraSceneRevision: vi.fn(), saveCameraScene: vi.fn() };
});

const cameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21412';
const zoneId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21b01';
const lineId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21c01';
const videoId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21421';

const camera = {
  id: cameraId,
  code: 'CAM-01',
  name: 'North Gate',
  description: null,
  locationName: null,
  timeZoneId: 'Asia/Kolkata',
  isActive: true,
  createdAtUtc: '2026-09-14T02:30:00Z',
  updatedAtUtc: '2026-09-14T02:30:00Z',
};

function video(overrides: Partial<VideoAsset> = {}): VideoAsset {
  return {
    id: videoId,
    cameraId,
    originalFileName: 'gate.mp4',
    recordingStartUtc: '2026-09-14T02:00:00Z',
    recordingEndUtc: '2026-09-14T02:10:00Z',
    recordingTimeZoneId: 'Asia/Kolkata',
    recordingUtcOffsetMinutes: 330,
    durationMs: 600_000,
    width: 1920,
    height: 1080,
    frameRateNumerator: 25,
    frameRateDenominator: 1,
    codecName: 'h264',
    processingStatus: 'Processed',
    importedAtUtc: '2026-09-14T03:00:00Z',
    ...overrides,
  };
}

function revision(overrides: Partial<SceneRevision> = {}): SceneRevision {
  return {
    revisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21501',
    revisionNumber: 2,
    cameraId,
    createdAtUtc: '2026-09-20T06:00:00Z',
    createdBy: 'development-unattributed',
    note: null,
    referenceFrameVideoAssetId: null,
    referenceFrameOffsetMs: null,
    analyticsEnabled: true,
    zones: [{
      zoneId,
      name: 'Gate',
      kind: 'Restricted',
      enabled: true,
      vertices: [{ x: 0.2, y: 0.2 }, { x: 0.6, y: 0.2 }, { x: 0.6, y: 0.6 }, { x: 0.2, y: 0.6 }],
      loiteringThresholdSeconds: 45,
    }],
    tripLines: [{
      lineId,
      name: 'Kerb',
      enabled: true,
      a: { x: 0.1, y: 0.5 },
      b: { x: 0.9, y: 0.5 },
      directed: true,
      aToBLabel: 'inbound',
      bToALabel: 'outbound',
    }],
    ...overrides,
  };
}

function configured(overrides: Partial<CameraScene> = {}): CameraScene {
  const active = revision();
  return {
    cameraId,
    configured: true,
    activeRevision: active,
    history: [
      {
        revisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21500',
        revisionNumber: 1,
        createdAtUtc: '2026-09-19T06:00:00Z',
        createdBy: 'development-unattributed',
        note: 'First layout',
        analyticsEnabled: true,
        zoneCount: 1,
        tripLineCount: 0,
      },
      {
        revisionId: active.revisionId,
        revisionNumber: 2,
        createdAtUtc: active.createdAtUtc,
        createdBy: active.createdBy,
        note: null,
        analyticsEnabled: true,
        zoneCount: 1,
        tripLineCount: 1,
      },
    ],
    ...overrides,
  };
}

function unconfigured(): CameraScene {
  return { cameraId, configured: false, activeRevision: null, history: [] };
}

function render() {
  return renderWithApp(<SceneEditorPage />, {
    route: `/cameras/${cameraId}/scene`,
    routePath: '/cameras/:cameraId/scene',
    // The page uses the router's blocker for unsaved-changes protection, which
    // only exists under a data router, as in the application itself.
    dataRouter: true,
  });
}

/** Whether the leave guard is holding the page: a reload would be refused. */
function unloadBlocked(): boolean {
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

/** The canvas reports its measured content rectangle for tests to click through. */
function frameRect(): { x: number; y: number; width: number; height: number } {
  const canvas = screen.getByTestId('scene-canvas');
  const [x, y, width, height] = (canvas.dataset.frame ?? '0,0,0,0').split(',').map(Number);
  return { x, y, width, height };
}

/** Selects an object by clicking its name button, which is not its delete button. */
async function selectObject(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(objectButton(name));
}

/** A drawing tool in the mode strip, which is not the navigator's "+ Zone" button. */
function toolButton(name: 'Select' | 'Zone' | 'Trip line'): HTMLElement {
  return within(screen.getByRole('group', { name: 'Drawing tools' })).getByRole('button', { name });
}

/** The navigator's own button for an object, which is not its delete button. */
function objectButton(name: string): HTMLElement {
  return screen.getByRole('button', { name: new RegExp(`^${name}(,|$)`) });
}

function queryObjectButton(name: string): HTMLElement | null {
  return screen.queryByRole('button', { name: new RegExp(`^${name}(,|$)`) });
}

/** Clicks the canvas at a normalised position, going through the real projection. */
async function clickFrame(user: ReturnType<typeof userEvent.setup>, nx: number, ny: number) {
  const frame = frameRect();
  const canvas = screen.getByTestId('scene-canvas');
  await user.pointer({
    target: canvas,
    coords: { clientX: frame.x + nx * frame.width, clientY: frame.y + ny * frame.height },
    keys: '[MouseLeft]',
  });
}

beforeEach(() => {
  vi.mocked(getCamera).mockResolvedValue(camera);
  vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
  vi.mocked(listVideos).mockResolvedValue([video()]);
  vi.mocked(getCameraScene).mockResolvedValue(configured());
  vi.mocked(getCameraSceneRevision).mockReset();
  vi.mocked(saveCameraScene).mockReset();

  // jsdom gives every element a zero-sized box; the canvas needs a real one to
  // project through.
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 640 });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, value: 360 });
  Element.prototype.getBoundingClientRect = function boundingRect() {
    return { x: 0, y: 0, top: 0, left: 0, right: 640, bottom: 360, width: 640, height: 360, toJSON: () => ({}) } as DOMRect;
  };
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.hasPointerCapture = vi.fn(() => false);
});

describe('scene editor', () => {
  // Loading and states
  it('shows the active revision with its geometry', async () => {
    render();

    // The page title block is gone (UI-2); the Context Bar's breadcrumb is what
    // names the surface now, and it must name the object being edited rather
    // than only its parent section.
    // The Context Bar is present while the scene loads too (§37.1, page), so
    // the editor itself is what says the scene has arrived.
    await screen.findByRole('button', { name: /^Gate/ });
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByText('Cameras')).toBeInTheDocument();
    // §5: `Cameras › {camera} › Scene`, the camera named by code and name.
    expect(within(crumbs).getByText('CAM-01 · North Gate')).toBeInTheDocument();
    expect(within(crumbs).getByText('Scene')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('button', { name: /^Gate/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Kerb/ })).toBeInTheDocument();
    expect(getCameraScene).toHaveBeenCalledWith(cameraId, expect.anything());
  });

  it('explains that a never-configured camera saves revision 1', async () => {
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();

    expect(await screen.findByText('No scene configured')).toBeInTheDocument();
    expect(screen.getByText('No zones or trip lines yet.')).toBeInTheDocument();
  });

  it('has one drawing entry: the mode strip, with one invitation to the first zone that arms the same tool (R4)', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText('No scene configured');

    // The navigator creates nothing; the empty stage invites once.
    expect(screen.queryByRole('button', { name: /^\+ ?(Zone|Line)$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Draw a trip line' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Draw a zone' })).toHaveLength(1);
    // Trip lines stay one press away, in the mode strip.
    expect(toolButton('Trip line')).toBeEnabled();

    await user.click(screen.getByRole('button', { name: 'Draw a zone' }));
    expect(toolButton('Zone')).toHaveAttribute('aria-pressed', 'true');
    // Accepted: the invitation gets out of the way of the frame being drawn on.
    expect(screen.queryByText('No scene configured')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Draw a zone' })).not.toBeInTheDocument();
  });

  describe('identity in every state (§5, §14)', () => {
    const fallback = `Camera ${cameraId.slice(0, 8)}…`;
    const renderInShell = () => renderWithApp(<SceneEditorPage />, {
      route: `/cameras/${cameraId}/scene`,
      routePath: '/cameras/:cameraId/scene',
      shell: 'scene',
    });

    /** `Cameras › {identity} › Scene` in the bar and the title, the full GUID in neither. */
    async function expectCameraIdentity(identity: string) {
      const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
      expect(within(crumbs).getByRole('link', { name: 'Cameras' })).toHaveAttribute('href', '/cameras');
      expect(await within(crumbs).findByText(identity)).toBeInTheDocument();
      expect(within(crumbs).getByText('Scene')).toHaveAttribute('aria-current', 'page');
      expect(within(crumbs).getAllByRole('listitem')).toHaveLength(3);
      expect(crumbs.textContent).not.toContain(cameraId);
      await waitFor(() => expect(document.title).toBe(`Scene — ${identity} — Cameras — MAVI`));
      expect(document.title).not.toContain(cameraId);
    }

    it('names a camera that is still loading by its shortened identifier', async () => {
      vi.mocked(getCamera).mockImplementation(() => new Promise(() => {}));
      renderInShell();
      expect(await screen.findByText('Loading scene…')).toBeInTheDocument();
      await expectCameraIdentity(fallback);
    });

    it('keeps the camera named while it is unavailable, the state said by the region', async () => {
      vi.mocked(getCamera).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Camera store unavailable.' }));
      renderInShell();
      expect(await screen.findByText('The camera could not be loaded. Camera store unavailable. (api_error)')).toBeInTheDocument();
      await expectCameraIdentity(fallback);
    });

    it('keeps a missing camera on the Scene surface under Cameras, not the global Not found', async () => {
      vi.mocked(getCamera).mockRejectedValue(new ApiError({ status: 404, code: 'camera_not_found', detail: 'x' }));
      vi.mocked(getCameraScene).mockRejectedValue(new ApiError({ status: 404, code: 'camera_not_found', detail: 'x' }));
      renderInShell();
      expect(await screen.findByText('This camera does not exist.')).toBeInTheDocument();
      await expectCameraIdentity(fallback);
      expect(document.title).not.toBe('Not found — MAVI');
      // One page heading: the bar's; the state is the region's.
      expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    });

    it('names the camera it resolved when only its scene is missing', async () => {
      vi.mocked(getCameraScene).mockRejectedValue(new ApiError({ status: 404, code: 'camera_not_found', detail: 'x' }));
      renderInShell();
      expect(await screen.findByText('This camera does not exist.')).toBeInTheDocument();
      await expectCameraIdentity('CAM-01 · North Gate');
    });

    it('keeps the camera named while only the scene is unavailable', async () => {
      vi.mocked(getCameraScene).mockRejectedValue(new ApiError({ status: 500, code: 'api_error', detail: 'Scene store is down.' }));
      renderInShell();
      await expectCameraIdentity('CAM-01 · North Gate');
    });
  });

  it('reports a missing camera rather than an empty scene', async () => {
    vi.mocked(getCamera).mockRejectedValue(new ApiError({ status: 404, code: 'camera_not_found', detail: 'x' }));
    vi.mocked(getCameraScene).mockRejectedValue(new ApiError({ status: 404, code: 'camera_not_found', detail: 'x' }));
    render();

    expect(await screen.findByText('This camera does not exist.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Cameras' })).toHaveAttribute('href', '/cameras');
  });

  it('never presents an unavailable scene API as an empty scene', async () => {
    vi.mocked(getCameraScene).mockRejectedValue(
      new ApiError({ status: 500, code: 'api_error', detail: 'Scene store is down.' }),
    );
    render();

    const alert = await screen.findByRole('alert');
    // The subject first, then the server's detail and code.
    expect(alert).toHaveTextContent('The scene could not be loaded. Scene store is down. (api_error)');
    // One alert, its retry trailing inside it, and the Context Bar still
    // naming the surface (§37.1, page).
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(within(alert).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(within(screen.getByRole('navigation', { name: 'Breadcrumb' })).getByText('Scene')).toBeInTheDocument();
    // No editor, and above all no empty geometry presented as the truth.
    expect(screen.queryByRole('button', { name: 'Save revision' })).not.toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Zones' })).not.toBeInTheDocument();
    expect(screen.queryByText('No zones or trip lines yet.')).not.toBeInTheDocument();
  });

  it('offers a neutral frame when the camera has no videos', async () => {
    vi.mocked(listVideos).mockResolvedValue([]);
    render();

    expect(await screen.findByText(/No imported video for this camera/)).toBeInTheDocument();
    expect(toolButton('Zone')).toBeEnabled();
  });

  it('withholds editing on an inactive camera, saying why once, where the tools would be (R4)', async () => {
    const user = userEvent.setup();
    vi.mocked(getCamera).mockResolvedValue({ ...camera, isActive: false });
    render();

    // The server refuses every change (`scene_camera_inactive`), so the tools
    // are removed rather than offered and refused at Save.
    const reason = await screen.findByText('This camera is inactive, so its scene cannot be changed.');
    expect(screen.getAllByText(/This camera is inactive/)).toHaveLength(1);
    expect(screen.queryByRole('group', { name: 'Drawing tools' })).not.toBeInTheDocument();
    const save = screen.getByRole('button', { name: 'Save revision' });
    expect(save).toBeDisabled();
    expect(save).toHaveAttribute('aria-describedby', reason.id);

    // Still readable and selectable; not editable, not deletable.
    await user.click(await screen.findByRole('button', { name: /^Gate/ }));
    expect(screen.getByLabelText('Name')).toBeDisabled();
    expect(screen.queryByRole('button', { name: /^Delete / })).not.toBeInTheDocument();
    await user.keyboard('{Delete}');
    expect(screen.getByRole('button', { name: /^Gate/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reset' })).toBeDisabled();
  });

  it('keeps an inactive camera stated while a past revision is open on it', async () => {
    const user = userEvent.setup();
    vi.mocked(getCamera).mockResolvedValue({ ...camera, isActive: false });
    vi.mocked(getCameraSceneRevision).mockResolvedValue(revision({ revisionNumber: 1, tripLines: [] }));
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await user.click(screen.getByRole('button', { name: /View revision 1/ }));
    expect(await screen.findByText(/Drawing tools are unavailable while a past revision is open/)).toBeInTheDocument();
    // One reason does not hide the other.
    expect(screen.getByText('This camera is inactive, so its scene cannot be changed.')).toBeInTheDocument();
  });

  describe('Codex P2 corrections on PR #192', () => {
    it('keeps a past revision named and read only when its refresh fails, says so with Retry, and recovers', async () => {
      const user = userEvent.setup();
      vi.mocked(getCameraSceneRevision).mockResolvedValue(revision({ revisionNumber: 1, tripLines: [] }));
      const { queryClient } = render();
      await screen.findByRole('button', { name: /^Gate/ });
      await user.click(screen.getByRole('button', { name: /View revision 1/ }));
      expect(await screen.findByText('Viewing revision 1 — read only')).toBeInTheDocument();

      // The background refetch fails; the revision already read is retained.
      vi.mocked(getCameraSceneRevision).mockRejectedValue(new ApiError({ status: 503, code: 'upstream_unavailable', detail: 'down' }));
      await act(async () => { await queryClient.refetchQueries({ queryKey: sceneQueryKeys.revision(cameraId, 1) }); });

      const warning = await screen.findByText('Revision 1 could not be refreshed. It is shown as last loaded.');
      // Still the same revision, named and read only, its geometry still shown —
      // never the first-load "unavailable" state over evidence that is there.
      expect(screen.getByText('Viewing revision 1 — read only')).toBeInTheDocument();
      expect(objectButton('Gate')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Return to active revision' })).toBeInTheDocument();
      expect(screen.queryByText(/could not be loaded/)).not.toBeInTheDocument();
      expect(screen.queryByText('Revision 1 is unavailable.')).not.toBeInTheDocument();
      expect(screen.queryByRole('group', { name: 'Drawing tools' })).not.toBeInTheDocument();

      vi.mocked(getCameraSceneRevision).mockResolvedValue(revision({ revisionNumber: 1, tripLines: [] }));
      await user.click(within(warning.closest('.alert') as HTMLElement).getByRole('button', { name: 'Retry' }));
      await waitFor(() => expect(screen.queryByText(/could not be refreshed/)).not.toBeInTheDocument());
      expect(screen.getByText('Viewing revision 1 — read only')).toBeInTheDocument();
      expect(objectButton('Gate')).toBeInTheDocument();
    });

    it('keeps a note left behind by a reverted edit visible, guarded and resettable, so it never rides a later save', async () => {
      const user = userEvent.setup();
      const { router } = render();
      await screen.findByRole('button', { name: /^Gate/ });

      await selectObject(user, 'Gate');
      const name = screen.getByLabelText('Name');
      await user.type(name, 'x');
      await user.type(screen.getByLabelText('Revision note (optional)'), 'Moved the gate');
      // The geometry and fields return to their baseline; the note does not.
      await user.clear(name);
      await user.type(name, 'Gate');

      expect(screen.getByLabelText('Revision note (optional)')).toHaveValue('Moved the gate');
      expect(screen.getByRole('button', { name: 'Reset' })).toBeEnabled();
      // A note alone is not a revision.
      expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
      // It is the operator's input, so leaving asks.
      expect(unloadBlocked()).toBe(true);
      act(() => { void router.navigate('/cameras'); });
      const leave = await screen.findByRole('dialog', { name: 'Leave with unsaved changes?' });
      await user.click(within(leave).getByRole('button', { name: 'Stay on this page' }));

      // Reset confirms, then clears the note with the draft.
      await user.click(screen.getByRole('button', { name: 'Reset' }));
      const discard = await screen.findByRole('dialog', { name: 'Discard your unsaved scene changes?' });
      await user.click(within(discard).getByRole('button', { name: 'Discard changes' }));
      await waitFor(() => expect(screen.queryByLabelText('Revision note (optional)')).not.toBeInTheDocument());
      expect(screen.getByRole('button', { name: 'Reset' })).toBeDisabled();
      expect(unloadBlocked()).toBe(false);

      // A later, unrelated edit is saved without the old note.
      await selectObject(user, 'Gate');
      await user.type(screen.getByLabelText('Name'), ' east');
      expect(screen.getByLabelText('Revision note (optional)')).toHaveValue('');
      await user.click(screen.getByRole('button', { name: 'Save revision' }));
      await waitFor(() => expect(saveCameraScene).toHaveBeenCalledTimes(1));
      expect((vi.mocked(saveCameraScene).mock.calls[0][1] as SaveSceneRequest).note).toBeNull();
    });

    it.each(['Zone', 'Trip line'] as const)(
      'abandons an unfinished %s when the camera becomes inactive, releases the guard, and does not re-arm on reactivation',
      async (tool) => {
        const user = userEvent.setup();
        const { queryClient } = render();
        await screen.findByRole('button', { name: /^Gate/ });

        await user.click(toolButton(tool));
        await clickFrame(user, 0.6, 0.6);
        expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
        expect(unloadBlocked()).toBe(true);

        vi.mocked(getCamera).mockResolvedValue({ ...camera, isActive: false });
        await act(async () => { await queryClient.refetchQueries({ queryKey: queryKeys.camera(cameraId) }); });
        expect(await screen.findByText('This camera is inactive, so its scene cannot be changed.')).toBeInTheDocument();
        // No hidden gesture holding the page, nothing to cancel that cannot be seen.
        expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
        expect(unloadBlocked()).toBe(false);

        vi.mocked(getCamera).mockResolvedValue(camera);
        await act(async () => { await queryClient.refetchQueries({ queryKey: queryKeys.camera(cameraId) }); });
        await waitFor(() => expect(toolButton('Select')).toHaveAttribute('aria-pressed', 'true'));
        expect(screen.queryByRole('button', { name: /^(Finish zone|Cancel)$/ })).not.toBeInTheDocument();
        expect(unloadBlocked()).toBe(false);
      },
    );

    it('keeps completed unsaved changes, and their guard, when the camera becomes inactive', async () => {
      const user = userEvent.setup();
      const { queryClient } = render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');
      await user.type(screen.getByLabelText('Name'), ' east');

      vi.mocked(getCamera).mockResolvedValue({ ...camera, isActive: false });
      await act(async () => { await queryClient.refetchQueries({ queryKey: queryKeys.camera(cameraId) }); });
      await screen.findByText('This camera is inactive, so its scene cannot be changed.');

      expect(screen.getByLabelText('Name')).toHaveValue('Gate east');
      expect(unloadBlocked()).toBe(true);
      expect(screen.getByRole('button', { name: 'Reset' })).toBeEnabled();
      expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
    });
  });

  describe('cold-review corrections on PR #192', () => {
    it('names the scene, not the camera, when only a cached camera refresh failed beside a scene that never loaded', async () => {
      vi.mocked(getCamera).mockResolvedValueOnce(camera).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Camera store down.' }));
      vi.mocked(getCameraScene).mockRejectedValue(new ApiError({ status: 500, code: 'api_error', detail: 'Scene store is down.' }));
      const { queryClient } = render();
      await screen.findByText('The scene could not be loaded. Scene store is down. (api_error)');

      // The camera already read now fails its refresh; Retry re-renders the
      // page with the camera in error but still holding its data.
      await act(async () => { await queryClient.refetchQueries({ queryKey: queryKeys.camera(cameraId) }); });
      await userEvent.setup().click(within(screen.getByRole('alert')).getByRole('button', { name: 'Retry' }));
      await waitFor(() => expect(vi.mocked(getCameraScene).mock.calls.length).toBeGreaterThan(1));
      expect(await screen.findByRole('alert')).toHaveTextContent('The scene could not be loaded. Scene store is down. (api_error)');
      expect(screen.queryByText(/The camera could not be loaded/)).not.toBeInTheDocument();
    });

    it('asks before Reload active revision discards a retained note', async () => {
      const user = userEvent.setup();
      vi.mocked(saveCameraScene).mockRejectedValue(new ApiError({ status: 409, code: 'scene_revision_conflict', detail: 'stale' }));
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');
      const name = screen.getByLabelText('Name');
      await user.type(name, 'x');
      await user.type(screen.getByLabelText('Revision note (optional)'), 'Moved the gate');
      await user.click(screen.getByRole('button', { name: 'Save revision' }));
      await screen.findByText(/This scene changed since you started editing/);
      // The edit is reverted; the note is not.
      await user.clear(name);
      await user.type(name, 'Gate');

      await user.click(screen.getByRole('button', { name: 'Reload active revision' }));
      expect(await screen.findByRole('dialog', { name: 'Discard your changes and load the saved revision?' })).toBeInTheDocument();
      expect(screen.getByLabelText('Revision note (optional)')).toHaveValue('Moved the gate');
    });

    it('returns focus to the armed tool when the last object is deleted from a focused vertex', async () => {
      const user = userEvent.setup();
      vi.mocked(getCameraScene).mockResolvedValue(configured({ activeRevision: revision({ tripLines: [] }) }));
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');
      await user.click(screen.getByText(/^Vertices · \d+$/));
      await user.tab();
      await user.keyboard('{Enter}{Delete}');

      expect(queryObjectButton('Gate')).toBeNull();
      await waitFor(() => expect(toolButton('Select')).toHaveFocus());
    });

    it('lets Enter act on a focused vertex while a zone is being drawn, and Escape keep focus on the page', async () => {
      const user = userEvent.setup();
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');
      await user.click(screen.getByText(/^Vertices · \d+$/));
      await user.click(toolButton('Zone'));
      await clickFrame(user, 0.6, 0.6);

      const vertex = screen.getByRole('button', { name: /^Vertex 2: / });
      vertex.focus();
      await user.keyboard('{Enter}');
      // The vertex is selected; the unfinished polygon is still unfinished.
      expect(vertex).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('button', { name: 'Finish zone' })).toBeInTheDocument();

      await user.click(toolButton('Select'));
      screen.getByRole('button', { name: /^Vertex 2: / }).focus();
      await user.keyboard('{Escape}');
      // The selection clears and its inspector controls go; focus does not fall to the page.
      await waitFor(() => expect(objectButton('Gate')).toHaveFocus());
    });

    it('locks editing while a save is in flight, so nothing typed then is lost to the response', async () => {
      const user = userEvent.setup();
      let resolve: (value: SceneRevision) => void = () => {};
      vi.mocked(saveCameraScene).mockReturnValue(new Promise((done) => { resolve = done; }));
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');
      await user.type(screen.getByLabelText('Name'), ' east');
      await user.click(screen.getByRole('button', { name: 'Save revision' }));

      expect(await screen.findByRole('button', { name: 'Saving…' })).toBeDisabled();
      expect(screen.getByLabelText('Name')).toBeDisabled();
      expect(screen.queryByRole('button', { name: /^Delete / })).not.toBeInTheDocument();
      await act(async () => { resolve(revision({ revisionNumber: 3 })); });
      await waitFor(() => expect(screen.getByRole('button', { name: 'Save revision' })).toBeInTheDocument());
    });

    it('does not adopt a newer revision over an unfinished polygon; it says so and keeps the drawing', async () => {
      const user = userEvent.setup();
      const { queryClient } = render();
      await screen.findByRole('button', { name: /^Gate/ });
      await user.click(toolButton('Zone'));
      await clickFrame(user, 0.6, 0.6);

      vi.mocked(getCameraScene).mockResolvedValue(configured({ activeRevision: revision({ revisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c219ff', revisionNumber: 5 }) }));
      await act(async () => { await queryClient.refetchQueries({ queryKey: sceneQueryKeys.scene(cameraId) }); });

      expect(await screen.findByText(/Somebody saved revision 5 while you were editing/)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
      expect(unloadBlocked()).toBe(true);
    });
  });

  it('offers Reset only when there is something to reset', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });
    expect(screen.getByRole('button', { name: 'Reset' })).toBeDisabled();

    await selectObject(user, 'Gate');
    await user.type(screen.getByLabelText('Name'), 'x');
    expect(screen.getByRole('button', { name: 'Reset' })).toBeEnabled();
  });

  // Drawing
  it('draws a polygon and closes it with Enter', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText('No scene configured');

    await user.click(toolButton('Zone'));
    await clickFrame(user, 0.2, 0.2);
    await clickFrame(user, 0.5, 0.2);
    await clickFrame(user, 0.5, 0.5);
    await user.keyboard('{Enter}');

    expect(await screen.findByRole('button', { name: /^Zone 1/ })).toBeInTheDocument();
    expect(objectButton('Zone 1')).toHaveAttribute('aria-pressed', 'true');
  });

  it('cancels an unfinished polygon with Escape', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText('No scene configured');

    await user.click(toolButton('Zone'));
    await clickFrame(user, 0.2, 0.2);
    await clickFrame(user, 0.5, 0.2);
    await user.keyboard('{Escape}');
    await user.keyboard('{Enter}');

    expect(screen.queryByRole('button', { name: /^Zone 1/ })).not.toBeInTheDocument();
  });

  it('draws a trip line from two clicks', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText('No scene configured');

    await user.click(toolButton('Trip line'));
    await clickFrame(user, 0.1, 0.5);
    await clickFrame(user, 0.9, 0.5);

    expect(await screen.findByRole('button', { name: /^Line 1/ })).toBeInTheDocument();
  });

  it('ignores a click on a letterbox bar without snapping it to the edge', async () => {
    const user = userEvent.setup();
    // 21:9 in the 640x360 element leaves real bars above and below, which is
    // the only way this test can be about letterboxing at all.
    vi.mocked(listVideos).mockResolvedValue([video({ width: 2560, height: 1080 })]);
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText('No scene configured');
    await user.selectOptions(screen.getByLabelText('Reference video'), videoId);

    const frame = await waitFor(() => {
      const rect = frameRect();
      if (rect.y <= 0 || rect.height >= 360) throw new Error('the frame is not letterboxed yet');
      return rect;
    });

    await user.click(toolButton('Zone'));
    const canvas = screen.getByTestId('scene-canvas');
    // Three clicks inside the element but above the image: a bar, not the
    // picture. Three is deliberate — it is enough vertices to close a polygon,
    // so if these were accepted (clamped onto y = 0, as unprojectPoint would
    // do) a zone would exist. The absence of one is the whole assertion.
    const bar = Math.floor(frame.y / 2);
    for (const clientX of [160, 320, 480]) {
      await user.pointer({ target: canvas, coords: { clientX, clientY: bar }, keys: '[MouseLeft]' });
    }
    await user.keyboard('{Enter}');

    expect(screen.queryByRole('button', { name: /^Zone 1/ })).not.toBeInTheDocument();

    // The same gesture inside the image does place a vertex, so the refusal
    // above is about where the click landed and not about the tool.
    await clickFrame(user, 0.3, 0.3);
    await clickFrame(user, 0.7, 0.3);
    await clickFrame(user, 0.5, 0.7);
    await user.keyboard('{Enter}');

    expect(screen.getByRole('button', { name: /^Zone 1/ })).toBeInTheDocument();
  });

  it('lets an armed drawing tool through existing geometry', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    // jsdom does no hit testing, so a test that clicks the surface can never
    // see an existing shape intercept the click the way a browser would. The
    // contract is asserted at the shape instead: while a drawing tool is armed
    // a pointerdown on a zone or a line must not be handled, because the click
    // belongs to the surface underneath — a zone has to be drawable over or
    // inside one that is already there.
    const overlay = screen.getByTestId('scene-overlay');
    const polygon = overlay.querySelector('.scene-zone polygon') as SVGPolygonElement;
    const line = overlay.querySelector('.scene-line__segment') as SVGLineElement;

    await user.click(toolButton('Zone'));
    fireEvent.pointerDown(polygon);
    fireEvent.pointerDown(line);

    expect(objectButton('Gate')).toHaveAttribute('aria-pressed', 'false');
    expect(objectButton('Kerb')).toHaveAttribute('aria-pressed', 'false');

    // With Select armed the same gesture selects, so the guard is about the
    // mode and not about the shape being unreachable.
    await user.click(toolButton('Select'));
    fireEvent.pointerDown(polygon);

    expect(objectButton('Gate')).toHaveAttribute('aria-pressed', 'true');
  });

  // Selection and editing
  it('keeps the list and the canvas agreeing about the selection', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');

    expect(objectButton('Gate')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Name')).toHaveValue('Gate');
    expect(screen.getByRole('button', { name: /Vertex 1: x 0.200000, y 0.200000/ })).toBeInTheDocument();
  });

  it('nudges a selected vertex by one thousandth', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.click(screen.getByRole('button', { name: /Vertex 1: x 0.200000/ }));
    await user.keyboard('{ArrowRight}');

    expect(await screen.findByRole('button', { name: /Vertex 1: x 0.201000, y 0.200000/ })).toBeInTheDocument();
  });

  describe('forensic geometry behind a disclosure, still a keyboard path (R4, F18, §37.2)', () => {
    const geometry = () => screen.getByText(/^Vertices · \d+$/).closest('details') as HTMLDetailsElement;

    it('keeps exact coordinates and identity closed by default, below the controls that change the object', async () => {
      const user = userEvent.setup();
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');

      const details = geometry();
      expect(details).not.toHaveAttribute('open');
      expect(within(details).getByText('Identity')).toBeInTheDocument();
      // Operational controls come first; the forensic tier is last.
      const name = screen.getByLabelText('Name');
      expect(name.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      // The coordinates are the object's own values at domain precision.
      expect(within(details).getByRole('button', { name: 'Vertex 1: x 0.200000, y 0.200000' })).toBeInTheDocument();
    });

    it('lets a keyboard operator open it, select a vertex, nudge it and read the exact result, keeping focus', async () => {
      const user = userEvent.setup();
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');

      // Discoverable: the next Tab stop after the last operational field.
      screen.getByLabelText('Loitering').focus();
      await user.tab();
      const summary = screen.getByText(/^Vertices · \d+$/);
      expect(summary).toHaveFocus();
      // A browser toggles a focused <summary> on Enter or Space natively;
      // jsdom does not implement that activation, so it is opened by click here.
      await user.click(summary);
      expect(geometry()).toHaveAttribute('open');

      await user.tab();
      const vertex = screen.getByRole('button', { name: 'Vertex 1: x 0.200000, y 0.200000' });
      expect(vertex).toHaveFocus();
      await user.keyboard('{Enter}');
      expect(vertex).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByText(/vertex 1 selected/)).toBeInTheDocument();

      await user.keyboard('{ArrowRight}');
      const moved = await screen.findByRole('button', { name: 'Vertex 1: x 0.201000, y 0.200000' });
      // The same control, still focused, in a disclosure that stayed open.
      expect(moved).toHaveFocus();
      expect(geometry()).toHaveAttribute('open');
    });

    it('returns focus to the navigator when the object a focused vertex belonged to is deleted', async () => {
      const user = userEvent.setup();
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');
      await user.click(screen.getByText(/^Vertices · \d+$/));
      await user.tab();
      await user.keyboard('{Enter}{Delete}');

      expect(queryObjectButton('Gate')).toBeNull();
      await waitFor(() => expect(objectButton('Kerb')).toHaveFocus());
    });
  });

  it('does not delete the object while its name is being edited', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    const name = screen.getByLabelText('Name');
    await user.clear(name);
    await user.type(name, 'Forecourt');
    await user.keyboard('{Delete}');

    expect(screen.getByRole('button', { name: /^Forecourt/ })).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Forecourt');
  });

  it('deletes the selected object with the Delete key outside a field', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.click(screen.getByRole('heading', { name: 'Scene objects' }));
    await user.keyboard('{Delete}');

    await waitFor(() => expect(screen.queryByRole('button', { name: /^Gate/ })).not.toBeInTheDocument());
  });

  it('toggles an object out of analytics without removing it', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.click(screen.getByRole('checkbox', { name: 'Evaluate this zone' }));

    await waitFor(() => expect(objectButton('Gate')).toHaveAccessibleName(expect.stringContaining('disabled')));
  });

  // Saving
  it('sends the whole scene with the expected revision number', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockResolvedValue(revision({ revisionNumber: 3 }));
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    await user.type(screen.getByPlaceholderText('Note (optional)'), 'Widened');
    await user.click(screen.getByRole('button', { name: 'Save revision' }));

    await waitFor(() => expect(saveCameraScene).toHaveBeenCalled());
    const request = vi.mocked(saveCameraScene).mock.calls[0][1] as SaveSceneRequest;
    expect(request.expectedRevisionNumber).toBe(2);
    expect(request.note).toBe('Widened');
    expect(request.zones).toHaveLength(1);
    expect(request.zones[0].zoneId).toBe(zoneId);
    expect(request.zones[0].name).toBe('Forecourt');
    expect(request.tripLines[0].lineId).toBe(lineId);
    expect(request.referenceFrameVideoAssetId).toBeNull();
    expect(request.referenceFrameOffsetMs).toBeNull();
  });

  it('saves revision 1 from an expected revision number of zero', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    vi.mocked(saveCameraScene).mockResolvedValue(revision({ revisionNumber: 1 }));
    render();
    await screen.findByText('No scene configured');

    await user.click(toolButton('Zone'));
    await clickFrame(user, 0.2, 0.2);
    await clickFrame(user, 0.5, 0.2);
    await clickFrame(user, 0.5, 0.5);
    await user.keyboard('{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save revision' }));

    await waitFor(() => expect(saveCameraScene).toHaveBeenCalled());
    const request = vi.mocked(saveCameraScene).mock.calls[0][1] as SaveSceneRequest;
    expect(request.expectedRevisionNumber).toBe(0);
    expect('zoneId' in request.zones[0]).toBe(false);
  });

  it('adopts the server-issued revision after a save', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    vi.mocked(saveCameraScene).mockResolvedValue(revision({ revisionNumber: 1 }));
    render();
    await screen.findByText('No scene configured');

    await user.click(toolButton('Zone'));
    await clickFrame(user, 0.2, 0.2);
    await clickFrame(user, 0.5, 0.2);
    await clickFrame(user, 0.5, 0.5);
    await user.keyboard('{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save revision' }));

    expect(await screen.findByRole('button', { name: /^Gate/ })).toBeInTheDocument();
    expect(screen.getByText('Revision 1')).toBeInTheDocument();
    expect(screen.getByText('Saved')).toBeInTheDocument();
  });

  /** Turns every object off, which is what "analytics disabled" means here. */
  async function disableEverything(user: ReturnType<typeof userEvent.setup>) {
    await selectObject(user, 'Gate');
    await user.click(screen.getByRole('checkbox', { name: 'Evaluate this zone' }));
    await selectObject(user, 'Kerb');
    await user.click(screen.getByRole('checkbox', { name: 'Evaluate this line' }));
  }

  it('states what a revision that disables analytics will do, and saves nothing yet', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await disableEverything(user);
    await user.click(screen.getByRole('button', { name: 'Save revision' }));

    const save = screen.getByRole('button', { name: 'Save and disable analytics' });
    expect(save).toHaveAccessibleDescription(
      expect.stringContaining('stops future runs of this camera being analysed'),
    );
    expect(save).toHaveAccessibleDescription(expect.stringContaining('Earlier revisions are unchanged'));
    expect(saveCameraScene).not.toHaveBeenCalled();
  });

  it('abandons the disabling save when the operator cancels', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await disableEverything(user);
    await user.click(screen.getByRole('button', { name: 'Save revision' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.getByRole('button', { name: 'Save revision' })).toBeInTheDocument();
    expect(saveCameraScene).not.toHaveBeenCalled();
  });

  it('saves the disabling revision once it has been confirmed', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockResolvedValue(revision({ revisionNumber: 3, zones: [], tripLines: [] }));
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await disableEverything(user);
    await user.click(screen.getByRole('button', { name: 'Save revision' }));
    await user.click(screen.getByRole('button', { name: 'Save and disable analytics' }));

    await waitFor(() => expect(saveCameraScene).toHaveBeenCalled());
  });

  it('asks for no confirmation for an ordinary enabled revision', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockResolvedValue(revision({ revisionNumber: 3 }));
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Save revision' }));

    await waitFor(() => expect(saveCameraScene).toHaveBeenCalled());
  });

  // Failures
  it('shows a validation failure against its own code', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockRejectedValue(
      new ApiError({ status: 400, code: 'scene_zone_self_intersecting', detail: 'nope' }),
    );
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Save revision' }));

    expect(await screen.findByText('A zone boundary may not cross itself.')).toBeInTheDocument();
  });

  it('keeps the draft and offers a reload on a conflict', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockRejectedValue(
      new ApiError({ status: 409, code: 'scene_revision_conflict', detail: 'stale' }),
    );
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Save revision' }));

    const conflictText = await screen.findByText(/This scene changed since you started editing/);
    // One alert, its recovery trailing inside it (§14.1), saying what it does.
    const alert = conflictText.closest('.alert') as HTMLElement;
    expect(within(alert).getByRole('button', { name: 'Reload active revision' })).toBeInTheDocument();
    expect(alert).toHaveTextContent('Reloading discards them');
    // The unsaved draft survives until the operator decides.
    expect(screen.getByLabelText('Name')).toHaveValue('Forecourt');
    expect(saveCameraScene).toHaveBeenCalledTimes(1);
  });

  it('really replaces the draft when the reload is taken, even if nothing changed on the server', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockRejectedValue(
      new ApiError({ status: 409, code: 'scene_revision_conflict', detail: 'stale' }),
    );
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Save revision' }));
    await screen.findByRole('button', { name: 'Reload active revision' });

    // getCameraScene keeps answering with the same scene, so the query's value
    // is structurally unchanged. The reload must still adopt it: telling the
    // operator their work was discarded and then leaving the draft dirty
    // against a revision it can no longer save on to is the worst of both.
    await user.click(screen.getByRole('button', { name: 'Reload active revision' }));
    // The discard is decided in the product's Dialog (§15), never window.confirm.
    const dialog = await screen.findByRole('dialog', { name: 'Discard your changes and load the saved revision?' });
    await user.click(within(dialog).getByRole('button', { name: 'Discard and load revision' }));

    await waitFor(() => expect(queryObjectButton('Forecourt')).toBeNull());
    expect(objectButton('Gate')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
  });

  it('keeps the draft when the reload is cancelled', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockRejectedValue(
      new ApiError({ status: 409, code: 'scene_revision_conflict', detail: 'stale' }),
    );
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Save revision' }));
    const reload = await screen.findByRole('button', { name: 'Reload active revision' });
    const fetches = vi.mocked(getCameraScene).mock.calls.length;

    await user.click(reload);
    const dialog = await screen.findByRole('dialog');
    // Escape cancels the confirmation; it never discards.
    await user.keyboard('{Escape}');
    expect(dialog).not.toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Forecourt');
    expect(vi.mocked(getCameraScene).mock.calls.length).toBe(fetches);
    expect(reload).toHaveFocus();
  });

  it('blocks a save on a duplicate zone name', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    // Two zones, same name: the backend would refuse it, and the browser can
    // see that for itself.
    await user.click(toolButton('Zone'));
    await clickFrame(user, 0.7, 0.7);
    await clickFrame(user, 0.9, 0.7);
    await clickFrame(user, 0.8, 0.9);
    await user.keyboard('{Enter}');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'gate');

    expect(await screen.findByText('Another zone already uses this name.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
    expect(screen.getByText('Fix the highlighted problems before saving.')).toBeInTheDocument();
  });

  it('reports a failed reference video without discarding the scene', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await user.selectOptions(screen.getByLabelText('Reference video'), videoId);
    const video = screen.getByLabelText('Reference frame video') as HTMLVideoElement;
    video.dispatchEvent(new Event('error'));

    // Said on the stage it affects (§37.1, media), not as a page alert.
    expect(await screen.findByText(/Reference video unavailable/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Gate/ })).toBeInTheDocument();
  });

  // Reference frame
  it('records the chosen instant and not a later playhead position', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockResolvedValue(revision({ revisionNumber: 3 }));
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await user.selectOptions(screen.getByLabelText('Reference video'), videoId);
    const media = screen.getByLabelText('Reference frame video') as HTMLVideoElement;
    Object.defineProperty(media, 'currentTime', { configurable: true, writable: true, value: 12.5 });
    await user.click(screen.getByRole('button', { name: 'Use current frame' }));

    expect(await screen.findByText(/Reference · /)).toBeInTheDocument();

    // Scrubbing afterwards must not move what will be saved.
    (media as unknown as { currentTime: number }).currentTime = 90;
    await user.click(screen.getByRole('button', { name: 'Save revision' }));

    await waitFor(() => expect(saveCameraScene).toHaveBeenCalled());
    const request = vi.mocked(saveCameraScene).mock.calls[0][1] as SaveSceneRequest;
    expect(request.referenceFrameVideoAssetId).toBe(videoId);
    expect(request.referenceFrameOffsetMs).toBe(12_500);
  });

  // History
  it('shows a historical revision read only and returns to the active draft', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraSceneRevision).mockResolvedValue(revision({
      revisionNumber: 1,
      zones: [{
        zoneId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21b99',
        name: 'Old gate',
        kind: 'General',
        enabled: true,
        vertices: [{ x: 0.1, y: 0.1 }, { x: 0.3, y: 0.1 }, { x: 0.3, y: 0.3 }],
        loiteringThresholdSeconds: null,
      }],
      tripLines: [],
    }));
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await user.click(screen.getByRole('button', { name: /View revision 1/ }));

    expect(await screen.findByText(/Viewing revision 1 — read only/)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /^Old gate/ })).toBeInTheDocument();
    // In read-only the drawing tools and Save are gone, not merely greyed: a
    // past revision must never look like something that can be edited.
    expect(screen.queryByRole('group', { name: 'Drawing tools' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save revision' })).not.toBeInTheDocument();
    expect(getCameraSceneRevision).toHaveBeenCalledWith(cameraId, 1, expect.anything());

    await user.click(screen.getByRole('button', { name: 'Return to active revision' }));

    expect(await screen.findByRole('button', { name: /^Gate/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Old gate/ })).not.toBeInTheDocument();
    expect(toolButton('Zone')).toBeEnabled();
  });

  it('guards an unfinished polygon as the unsaved work it is', async () => {
    const user = userEvent.setup();
    const add = vi.spyOn(window, 'addEventListener');
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    const armed = () => add.mock.calls.filter(([type]) => type === 'beforeunload').length;
    expect(armed()).toBe(0);

    // A placed vertex does not belong to any object yet, so the draft is not
    // dirty — but losing it to a stray reload is the same loss.
    await user.click(toolButton('Zone'));
    await clickFrame(user, 0.2, 0.2);

    await waitFor(() => expect(armed()).toBeGreaterThan(0));
    add.mockRestore();
  });

  it('never shows the editable scene under a historical revision banner', async () => {
    const user = userEvent.setup();
    let release: ((value: SceneRevision) => void) | null = null;
    vi.mocked(getCameraSceneRevision).mockReturnValue(new Promise((resolve) => { release = resolve; }));
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await user.click(screen.getByRole('button', { name: /View revision 1/ }));

    // The stage already names revision 1 — loading — so the active scene must
    // not be what is underneath it while the revision is still on its way. The
    // loading line is the stage's own banner, so nothing above the workspace
    // appears and then disappears (§36.3).
    // Each region says it is loading (§37.1) — the stage banner, the navigator
    // and the inspector — and none says what an unread revision contains:
    // no "no geometry", no zero counts, no analytics state (§14).
    expect(await screen.findAllByText('Loading revision 1…')).toHaveLength(3);
    expect(screen.queryByText(/This revision has no geometry/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 \(0 enabled\)/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Analytics (on|off)$/i)).not.toBeInTheDocument();
    expect(document.querySelector('.workspace__notices')?.textContent ?? '').not.toMatch(/revision 1/);
    expect(queryObjectButton('Gate')).toBeNull();
    expect(queryObjectButton('Kerb')).toBeNull();

    (release as unknown as (value: SceneRevision) => void)(
      revision({ revisionNumber: 1, tripLines: [] }),
    );

    expect(await screen.findByRole('button', { name: /^Gate/ })).toBeInTheDocument();
    expect(screen.getByText('Viewing revision 1 — read only')).toBeInTheDocument();
  });

  it('abandons an unfinished polygon rather than carrying it into a past revision', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraSceneRevision).mockResolvedValue(revision({ revisionNumber: 1, tripLines: [] }));
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await user.click(toolButton('Zone'));
    await clickFrame(user, 0.2, 0.2);
    await clickFrame(user, 0.4, 0.2);
    await clickFrame(user, 0.4, 0.4);
    await user.click(screen.getByRole('button', { name: /View revision 1/ }));
    await screen.findByText(/Viewing revision 1 — read only/);

    // No mutating action may survive into read-only: a Finish here would
    // commit geometry to a scene the operator is not looking at.
    expect(screen.queryByRole('button', { name: 'Finish zone' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Return to active revision' }));
    await screen.findByRole('group', { name: 'Drawing tools' });

    expect(screen.queryByRole('button', { name: 'Finish zone' })).not.toBeInTheDocument();
    expect(queryObjectButton('Zone 1')).toBeNull();
  });

  it('reports an unavailable video list as an outage, not as a camera with no video', async () => {
    vi.mocked(listVideos).mockRejectedValue(new ApiError({ status: 503, code: 'unavailable', detail: 'down' }));
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    expect(await screen.findByText(/The video list is unavailable/)).toBeInTheDocument();
    // One cause, one alert, its retry trailing (§14.1).
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.getAllByText(/The video list is unavailable/)).toHaveLength(1);
    expect(screen.queryByText(/No imported video for this camera/)).not.toBeInTheDocument();
  });

  it('never lets a historical revision alter what would be saved', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraSceneRevision).mockResolvedValue(revision({
      revisionNumber: 1,
      zones: [{
        zoneId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21b99',
        name: 'Old gate',
        kind: 'General',
        enabled: true,
        vertices: [{ x: 0.1, y: 0.1 }, { x: 0.3, y: 0.1 }, { x: 0.3, y: 0.3 }],
        loiteringThresholdSeconds: null,
      }],
      tripLines: [],
    }));
    vi.mocked(saveCameraScene).mockResolvedValue(revision({ revisionNumber: 3 }));
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await user.click(screen.getByRole('button', { name: /View revision 1/ }));
    await screen.findByRole('button', { name: /^Old gate/ });
    await user.click(screen.getByRole('button', { name: 'Return to active revision' }));
    await screen.findByRole('button', { name: /^Gate/ });

    // Edit the active draft after the excursion, so the save carries whatever
    // the history view might have leaked into it.
    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Save revision' }));

    await waitFor(() => expect(saveCameraScene).toHaveBeenCalled());
    const request = vi.mocked(saveCameraScene).mock.calls[0][1] as SaveSceneRequest;
    // The stale identity from revision 1 can never reach the server.
    expect(request.zones.map((zone) => zone.zoneId)).toEqual([zoneId]);
    expect(request.expectedRevisionNumber).toBe(2);
  });

  it('keeps the active draft when a historical revision fails to load', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraSceneRevision).mockRejectedValue(
      new ApiError({ status: 404, code: 'scene_revision_not_found', detail: 'no' }),
    );
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await user.click(screen.getByRole('button', { name: /View revision 1/ }));

    // Said on the stage it would have filled, with its retry — not above the
    // workspace, and never with the active geometry under the revision's name.
    const message = await screen.findByText('That revision does not exist for this camera.');
    const stageState = message.closest('.scene-stage__state') as HTMLElement;
    expect(stageState).not.toBeNull();
    expect(within(stageState).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByText(/Viewing revision 1/)).not.toBeInTheDocument();
    expect(queryObjectButton('Gate')).toBeNull();
    expect(document.querySelector('.workspace__notices')?.textContent ?? '').not.toMatch(/revision/);
    // The other regions say it is unavailable — never that it is empty.
    expect(screen.getAllByText('Revision 1 is unavailable.')).toHaveLength(2);
    expect(screen.queryByText(/This revision has no geometry/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 \(0 enabled\)/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Analytics (on|off)$/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Return to active revision' }));
    expect(await screen.findByRole('button', { name: /^Gate/ })).toBeInTheDocument();
  });

  // Reset
  it('confirms before discarding meaningful edits, in the product dialog', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Reset' }));

    const dialog = await screen.findByRole('dialog', { name: 'Discard your unsaved scene changes?' });
    expect(dialog).toHaveTextContent('returns to the active revision');
    // Focus starts on the safe choice.
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await user.click(within(dialog).getByRole('button', { name: 'Discard changes' }));

    expect(await screen.findByRole('button', { name: /^Gate/ })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('never traps navigation when the page turns not-found under an open discard dialog', async () => {
    const user = userEvent.setup();
    const { router, queryClient } = render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    await screen.findByRole('dialog', { name: 'Discard your unsaved scene changes?' });

    // A background read finds the camera gone: the page becomes not-found and
    // the discard decision goes with the editor it concerned.
    vi.mocked(getCameraScene).mockRejectedValue(new ApiError({ status: 404, code: 'camera_not_found', detail: 'Gone.' }));
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: sceneQueryKeys.scene(cameraId) });
    });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Discard your unsaved scene changes?' })).not.toBeInTheDocument());

    // Navigating away still asks — the guard is not held busy by a decision no
    // longer on screen — and leaving works.
    act(() => { void router!.navigate('/cameras'); });
    const leave = await screen.findByRole('dialog', { name: 'Leave with unsaved changes?' });
    await user.click(within(leave).getByRole('button', { name: 'Leave and discard changes' }));
    await waitFor(() => expect(router!.state.location.pathname).toBe('/cameras'));
  });

  it('keeps every edit when the reset is cancelled', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    const resetButton = screen.getByRole('button', { name: 'Reset' });
    await user.click(resetButton);

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Forecourt');
    expect(resetButton).toHaveFocus();
  });

  it('lets no editor shortcut act on the draft behind an open discard dialog', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    await screen.findByRole('dialog');

    // Delete would remove the selected object; it must not, behind the decision.
    await user.keyboard('{Delete}');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByLabelText('Name')).toHaveValue('Forecourt');
  });

  it('does not confirm a reset that would discard nothing', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await user.click(screen.getByRole('button', { name: 'Reset' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });


  // The most expensive thing this page can do is lose work nobody asked it to.
  it('never discards unsaved work when the scene changes underneath', async () => {
    const user = userEvent.setup();
    const { queryClient } = render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');

    // Somebody else saves revision 3 and a background refetch brings it back.
    vi.mocked(getCameraScene).mockResolvedValue({
      ...configured(),
      activeRevision: revision({
        revisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21777',
        revisionNumber: 3,
        zones: [],
        tripLines: [],
      }),
    });
    await queryClient.invalidateQueries({ queryKey: ['camera-scene', cameraId] });

    expect(await screen.findByText(/Somebody saved revision 3 while you were editing/)).toBeInTheDocument();
    // The draft is exactly as it was left.
    expect(screen.getByLabelText('Name')).toHaveValue('Forecourt');
    expect(objectButton('Forecourt')).toBeInTheDocument();
  });

  it('adopts the saved revision only when the operator asks', async () => {
    const user = userEvent.setup();
    const { queryClient } = render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Forecourt');

    vi.mocked(getCameraScene).mockResolvedValue({
      ...configured(),
      activeRevision: revision({
        revisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21777',
        revisionNumber: 3,
        zones: [],
        tripLines: [],
      }),
    });
    await queryClient.invalidateQueries({ queryKey: ['camera-scene', cameraId] });
    await screen.findByText(/Somebody saved revision 3 while you were editing/);

    await user.click(screen.getByRole('button', { name: /Discard my changes and load revision 3/ }));

    await waitFor(() => expect(queryObjectButton('Forecourt')).not.toBeInTheDocument());
    expect(screen.getByText('Revision 3')).toBeInTheDocument();
  });

  // Validation the browser can do for itself
  it('refuses to save while the browser can see the request is invalid', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));

    expect(await screen.findByText('This zone needs a name.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
    expect(saveCameraScene).not.toHaveBeenCalled();
  });

  it('marks a duplicate name before the backend has to', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Kerb');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Kerb 2');
    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Kerb 2');

    // Different object kinds, so the names do not collide.
    expect(screen.getByRole('button', { name: 'Save revision' })).toBeEnabled();
  });

  it('says why a refused drawing gesture did nothing', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText('No scene configured');

    await user.click(toolButton('Trip line'));
    await clickFrame(user, 0.5, 0.5);
    await clickFrame(user, 0.501, 0.5);

    expect(await screen.findByText(/two ends of a trip line must be further apart/)).toBeInTheDocument();
    expect(queryObjectButton('Line 1')).not.toBeInTheDocument();
  });

  it('closes a polygon when the first vertex is clicked', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText('No scene configured');

    await user.click(toolButton('Zone'));
    await clickFrame(user, 0.2, 0.2);
    await clickFrame(user, 0.5, 0.2);
    await clickFrame(user, 0.5, 0.5);
    await clickFrame(user, 0.2, 0.2);

    expect(await screen.findByRole('button', { name: /^Zone 1/ })).toBeInTheDocument();
    // Closing must not append a fourth coincident vertex.
    expect(screen.getByRole('button', { name: /^Zone 1/ })).toHaveAccessibleName(expect.stringContaining('3 vertices'));
  });

  // No false capability
  it('claims nothing about analytics that have not run', async () => {
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    expect(screen.queryByText(/Analyse existing runs/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/analysed runs/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/readiness/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/crossing count/i)).not.toBeInTheDocument();
  });
});

describe('scene editor across the Tier C boundary (§25: below 768px it is the unsupported state)', () => {
  const tierC = (query: string) => query === SHELL_QUERIES.narrow || query === SHELL_QUERIES.compact;
  const tierB = (query: string) => query === SHELL_QUERIES.compact;

  it('keeps a dirty draft, its leave guard and its edits across 768px both ways — neither saved nor discarded', async () => {
    const live = stubMatchMediaLive(tierB);
    try {
      const user = userEvent.setup();
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');
      await user.type(screen.getByLabelText('Name'), ' east');
      expect(unloadBlocked()).toBe(true);

      live.set(tierC);
      // The editor is not drawn: no canvas, no Save, no editing control.
      expect(screen.queryByTestId('scene-canvas')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Save revision' })).not.toBeInTheDocument();
      expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
      expect(screen.getByText(/Editing a scene needs a display at least 768px wide/)).toBeInTheDocument();
      // The summary says what the draft holds and that it is unsaved, and the
      // guard still holds it: nothing was sent and nothing was dropped.
      expect(screen.getByText(/This scene has unsaved changes/)).toBeInTheDocument();
      expect(screen.getByText(/Gate east/)).toBeInTheDocument();
      expect(unloadBlocked()).toBe(true);
      expect(saveCameraScene).not.toHaveBeenCalled();

      live.set(tierB);
      await selectObject(user, 'Gate east');
      expect(screen.getByLabelText('Name')).toHaveValue('Gate east');
      expect(screen.getByRole('button', { name: 'Save revision' })).toBeEnabled();
      expect(unloadBlocked()).toBe(true);
    } finally {
      live.restore();
    }
  });

  it('still asks before leaving a dirty draft carried into Tier C — the leave guard Dialog works where the editor is not drawn', async () => {
    const live = stubMatchMediaLive(tierB);
    try {
      const user = userEvent.setup();
      const { router } = render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');
      await user.type(screen.getByLabelText('Name'), ' east');
      live.set(tierC);
      act(() => { void router.navigate('/cameras'); });
      const leave = await screen.findByRole('dialog', { name: 'Leave with unsaved changes?' });
      expect(leave).toHaveAttribute('aria-modal', 'true');
      await user.click(within(leave).getByRole('button', { name: 'Stay on this page' }));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(screen.getByText(/This scene has unsaved changes/)).toBeInTheDocument();
      expect(unloadBlocked()).toBe(true);
    } finally {
      live.restore();
    }
  });

  it('never summarises a past revision that could not be read as an empty one (T2 cold review)', async () => {
    const live = stubMatchMediaLive(tierB);
    try {
      const user = userEvent.setup();
      vi.mocked(getCameraSceneRevision).mockRejectedValue(new ApiError({ status: 503, code: 'upstream_unavailable', detail: 'down' }));
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await user.click(screen.getByRole('button', { name: /View revision 1/ }));
      live.set(tierC);
      expect(await screen.findByText(/Revision 1 could not be loaded|could not be loaded/)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument();
      expect(screen.queryByText('None')).not.toBeInTheDocument();
    } finally {
      live.restore();
    }
  });

  it('says, in the Tier C summary, that a past revision shown as last loaded could not be refreshed (Codex P2 on #200)', async () => {
    const live = stubMatchMediaLive(tierB);
    try {
      const user = userEvent.setup();
      vi.mocked(getCameraSceneRevision).mockResolvedValue(revision({ revisionNumber: 1, tripLines: [] }));
      const { queryClient } = render();
      await screen.findByRole('button', { name: /^Gate/ });
      await user.click(screen.getByRole('button', { name: /View revision 1/ }));
      expect(await screen.findByText('Viewing revision 1 — read only')).toBeInTheDocument();
      vi.mocked(getCameraSceneRevision).mockRejectedValue(new ApiError({ status: 503, code: 'upstream_unavailable', detail: 'down' }));
      await act(async () => { await queryClient.refetchQueries({ queryKey: sceneQueryKeys.revision(cameraId, 1) }); });
      live.set(tierC);
      expect(await screen.findByText('Revision 1 could not be refreshed. It is shown as last loaded.')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
      expect(screen.getByText('Gate')).toBeInTheDocument();
    } finally {
      live.restore();
    }
  });

  it('states a conflict at Tier C without offering to discard the draft the operator cannot see (Codex P2 on #200)', async () => {
    const live = stubMatchMediaLive(tierB);
    try {
      const user = userEvent.setup();
      vi.mocked(saveCameraScene).mockRejectedValue(new ApiError({ status: 409, code: 'scene_revision_conflict', detail: 'stale' }));
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');
      await user.type(screen.getByLabelText('Name'), ' east');
      await user.click(screen.getByRole('button', { name: 'Save revision' }));
      await screen.findByText(/This scene changed since you started editing/);
      live.set(tierC);
      const alert = screen.getByText(/This scene changed since you started editing/).closest('.alert') as HTMLElement;
      expect(within(alert).queryByRole('button')).not.toBeInTheDocument();
      expect(alert).toHaveTextContent('on a display at least 768px wide');
      expect(screen.getByText(/This scene has unsaved changes/)).toBeInTheDocument();
      live.set(tierB);
      expect(screen.getByRole('button', { name: 'Reload active revision' })).toBeInTheDocument();
    } finally {
      live.restore();
    }
  });

  it('shows a clean scene as its read-only summary, with no unsaved-changes notice and no guard', async () => {
    const live = stubMatchMediaLive(tierC);
    try {
      render();
      expect(await screen.findByText(/Editing a scene needs a display at least 768px wide/)).toBeInTheDocument();
      expect(screen.queryByText(/This scene has unsaved changes/)).not.toBeInTheDocument();
      expect(screen.queryByTestId('scene-canvas')).not.toBeInTheDocument();
      expect(unloadBlocked()).toBe(false);
      live.set(tierB);
      expect(await screen.findByTestId('scene-canvas')).toBeInTheDocument();
    } finally {
      live.restore();
    }
  });

  it('lets no editing key act on the draft while the editor is not drawn', async () => {
    const live = stubMatchMediaLive(tierB);
    try {
      const user = userEvent.setup();
      render();
      await screen.findByRole('button', { name: /^Gate/ });
      await selectObject(user, 'Gate');
      live.set(tierC);
      await user.keyboard('{Delete}');
      live.set(tierB);
      expect(screen.getByRole('button', { name: /^Gate/ })).toBeInTheDocument();
      expect(unloadBlocked()).toBe(false);
    } finally {
      live.restore();
    }
  });
});

describe('scene editor accessibility', () => {
  it('names every tool button', async () => {
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    expect(screen.getByRole('button', { name: 'Select' })).toHaveAttribute('aria-pressed', 'true');
    expect(toolButton('Zone')).toHaveAttribute('aria-pressed', 'false');
    expect(toolButton('Trip line')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('group', { name: 'Drawing tools' })).toBeInTheDocument();
  });

  it('exposes the whole scene as a list', async () => {
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    const zones = screen.getByRole('list', { name: 'Zones' });
    expect(within(zones).getAllByRole('listitem')).toHaveLength(1);
    expect(within(zones).getByRole('button', { name: /^Gate/ })).toHaveAttribute('aria-pressed', 'false');
    const lines = screen.getByRole('list', { name: 'Trip lines' });
    expect(within(lines).getAllByRole('listitem')).toHaveLength(1);
  });

  it('exposes every coordinate a keyboard user needs', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    const vertices = screen.getByRole('list', { name: 'Vertices of Gate' });
    expect(within(vertices).getAllByRole('button')).toHaveLength(4);

    await selectObject(user, 'Kerb');
    const endpoints = screen.getByRole('list', { name: 'Endpoints of Kerb' });
    expect(within(endpoints).getByRole('button', { name: /Endpoint A: x 0.100000, y 0.500000/ })).toBeInTheDocument();
    expect(within(endpoints).getByRole('button', { name: /Endpoint B: x 0.900000, y 0.500000/ })).toBeInTheDocument();
  });

  it('labels every property control and connects its validation message', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');
    expect(screen.getByLabelText('Type')).toHaveValue('Restricted');
    expect(screen.getByLabelText('Loitering')).toHaveValue(45);

    const name = screen.getByLabelText('Name');
    await user.clear(name);

    expect(name).toHaveAttribute('aria-invalid', 'true');
    expect(name).toHaveAccessibleDescription(expect.stringContaining('This zone needs a name.'));
  });

  it('gives every delete control a name that says what it deletes', async () => {
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    expect(screen.getByRole('button', { name: 'Delete zone Gate' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete trip line Kerb' })).toBeInTheDocument();
  });

  it('hides the decorative overlay from assistive technology', async () => {
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    expect(screen.getByTestId('scene-overlay')).toHaveAttribute('aria-hidden', 'true');
  });

  // Composition
  it('keeps the whole scene listed while one object is selected', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('button', { name: /^Gate/ });

    await selectObject(user, 'Gate');

    // The selection opens the object's coordinates in the inspector; the
    // navigator stays the size of the scene rather than the size of the
    // selection, so nothing it lists is pushed out of the way.
    expect(objectButton('Gate')).toHaveAttribute('aria-pressed', 'true');
    expect(queryObjectButton('Kerb')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Vertices of Gate' })).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Zones' })).queryByRole('list')).toBeNull();
  });

  it('gets the empty state out of the way once a drawing tool is armed', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText('No scene configured');

    await user.click(toolButton('Zone'));

    expect(screen.queryByText('No scene configured')).not.toBeInTheDocument();

    await user.click(toolButton('Select'));

    expect(screen.getByText('No scene configured')).toBeInTheDocument();
  });

  it('does not call a scene that has never been saved active', async () => {
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText('No revision yet');

    // "Active" describes a revision, and there is not one to describe.
    expect(screen.queryByText('Active')).not.toBeInTheDocument();
  });
});
