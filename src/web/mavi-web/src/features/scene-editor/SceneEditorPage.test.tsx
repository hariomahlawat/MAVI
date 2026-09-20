import { screen, waitFor, within } from '@testing-library/react';
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
import { renderWithApp } from '../../test/renderWithApp';
import SceneEditorPage from './SceneEditorPage';

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

/** The canvas reports its measured content rectangle for tests to click through. */
function frameRect(): { x: number; y: number; width: number; height: number } {
  const canvas = screen.getByTestId('scene-canvas');
  const [x, y, width, height] = (canvas.dataset.frame ?? '0,0,0,0').split(',').map(Number);
  return { x, y, width, height };
}

/** Selects an object by clicking its name button, which is not its delete button. */
async function selectObject(user: ReturnType<typeof userEvent.setup>, name: string) {
  const option = screen.getByRole('option', { name: new RegExp(`^${name}`) });
  await user.click(within(option).getByRole('button', { name: new RegExp(`^${name}`) }));
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

    expect(await screen.findByRole('heading', { name: /Scene · North Gate/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Gate/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Kerb/ })).toBeInTheDocument();
    expect(getCameraScene).toHaveBeenCalledWith(cameraId, expect.anything());
  });

  it('explains that a never-configured camera saves revision 1', async () => {
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();

    expect(await screen.findByText(/No scene configured yet/)).toBeInTheDocument();
    expect(screen.getByText(/No geometry yet/)).toBeInTheDocument();
  });

  it('reports a missing camera rather than an empty scene', async () => {
    vi.mocked(getCamera).mockRejectedValue(new ApiError({ status: 404, code: 'camera_not_found', detail: 'x' }));
    vi.mocked(getCameraScene).mockRejectedValue(new ApiError({ status: 404, code: 'camera_not_found', detail: 'x' }));
    render();

    expect(await screen.findByRole('heading', { name: 'Camera not found' })).toBeInTheDocument();
  });

  it('never presents an unavailable scene API as an empty scene', async () => {
    vi.mocked(getCameraScene).mockRejectedValue(
      new ApiError({ status: 500, code: 'api_error', detail: 'Scene store is down.' }),
    );
    render();

    expect(await screen.findByRole('alert')).toHaveTextContent('Scene store is down.');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    // No editor, and above all no empty geometry presented as the truth.
    expect(screen.queryByRole('button', { name: 'Save and activate' })).not.toBeInTheDocument();
    expect(screen.queryByRole('listbox', { name: 'Zones' })).not.toBeInTheDocument();
    expect(screen.queryByText(/No geometry yet/)).not.toBeInTheDocument();
  });

  it('offers a neutral frame when the camera has no videos', async () => {
    vi.mocked(listVideos).mockResolvedValue([]);
    render();

    expect(await screen.findByText(/No videos imported for this camera/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Draw zone' })).toBeEnabled();
  });

  it('refuses changes on an inactive camera', async () => {
    vi.mocked(getCamera).mockResolvedValue({ ...camera, isActive: false });
    render();

    expect(await screen.findByText(/This camera is inactive/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save and activate' })).toBeDisabled();
  });

  // Drawing
  it('draws a polygon and closes it with Enter', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText(/No scene configured yet/);

    await user.click(screen.getByRole('button', { name: 'Draw zone' }));
    await clickFrame(user, 0.2, 0.2);
    await clickFrame(user, 0.5, 0.2);
    await clickFrame(user, 0.5, 0.5);
    await user.keyboard('{Enter}');

    expect(await screen.findByRole('option', { name: /Zone 1/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Zone 1/ })).toHaveAttribute('aria-selected', 'true');
  });

  it('cancels an unfinished polygon with Escape', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText(/No scene configured yet/);

    await user.click(screen.getByRole('button', { name: 'Draw zone' }));
    await clickFrame(user, 0.2, 0.2);
    await clickFrame(user, 0.5, 0.2);
    await user.keyboard('{Escape}');
    await user.keyboard('{Enter}');

    expect(screen.queryByRole('option', { name: /Zone 1/ })).not.toBeInTheDocument();
  });

  it('draws a trip line from two clicks', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText(/No scene configured yet/);

    await user.click(screen.getByRole('button', { name: 'Draw trip line' }));
    await clickFrame(user, 0.1, 0.5);
    await clickFrame(user, 0.9, 0.5);

    expect(await screen.findByRole('option', { name: /Line 1/ })).toBeInTheDocument();
  });

  it('ignores a click on a letterbox bar', async () => {
    const user = userEvent.setup();
    vi.mocked(getCameraScene).mockResolvedValue(unconfigured());
    render();
    await screen.findByText(/No scene configured yet/);

    // A 16:9 source in a 640x360 element fills it, so widen the source to
    // create bars above and below.
    await user.click(screen.getByRole('button', { name: 'Draw zone' }));
    const canvas = screen.getByTestId('scene-canvas');
    await user.pointer({ target: canvas, coords: { clientX: 320, clientY: -40 }, keys: '[MouseLeft]' });
    await user.keyboard('{Enter}');

    expect(screen.queryByRole('option', { name: /Zone 1/ })).not.toBeInTheDocument();
  });

  // Selection and editing
  it('keeps the list and the canvas agreeing about the selection', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await selectObject(user, 'Gate');

    expect(screen.getByRole('option', { name: /Gate/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByLabelText('Zone name')).toHaveValue('Gate');
    expect(screen.getByRole('button', { name: /Vertex 1: x 0.200000, y 0.200000/ })).toBeInTheDocument();
  });

  it('nudges a selected vertex by one thousandth', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await selectObject(user, 'Gate');
    await user.click(screen.getByRole('button', { name: /Vertex 1: x 0.200000/ }));
    await user.keyboard('{ArrowRight}');

    expect(await screen.findByRole('button', { name: /Vertex 1: x 0.201000, y 0.200000/ })).toBeInTheDocument();
  });

  it('does not delete the object while its name is being edited', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await selectObject(user, 'Gate');
    const name = screen.getByLabelText('Zone name');
    await user.clear(name);
    await user.type(name, 'Forecourt');
    await user.keyboard('{Delete}');

    expect(screen.getByRole('option', { name: /Forecourt/ })).toBeInTheDocument();
    expect(screen.getByLabelText('Zone name')).toHaveValue('Forecourt');
  });

  it('deletes the selected object with the Delete key outside a field', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await selectObject(user, 'Gate');
    await user.click(screen.getByRole('heading', { name: 'Scene objects' }));
    await user.keyboard('{Delete}');

    await waitFor(() => expect(screen.queryByRole('option', { name: /Gate/ })).not.toBeInTheDocument());
  });

  it('toggles an object out of analytics without removing it', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await selectObject(user, 'Gate');
    await user.click(screen.getByRole('checkbox', { name: 'Enabled for analytics' }));

    expect(await screen.findByRole('option', { name: /Gate.*disabled/s })).toBeInTheDocument();
  });

  // Saving
  it('sends the whole scene with the expected revision number', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockResolvedValue(revision({ revisionNumber: 3 }));
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Zone name'));
    await user.type(screen.getByLabelText('Zone name'), 'Forecourt');
    await user.type(screen.getByLabelText(/Revision note/), 'Widened');
    await user.click(screen.getByRole('button', { name: 'Save and activate' }));

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
    await screen.findByText(/No scene configured yet/);

    await user.click(screen.getByRole('button', { name: 'Draw zone' }));
    await clickFrame(user, 0.2, 0.2);
    await clickFrame(user, 0.5, 0.2);
    await clickFrame(user, 0.5, 0.5);
    await user.keyboard('{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save and activate' }));

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
    await screen.findByText(/No scene configured yet/);

    await user.click(screen.getByRole('button', { name: 'Draw zone' }));
    await clickFrame(user, 0.2, 0.2);
    await clickFrame(user, 0.5, 0.2);
    await clickFrame(user, 0.5, 0.5);
    await user.keyboard('{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save and activate' }));

    expect(await screen.findByText('Saved revision 1.')).toBeInTheDocument();
    expect(await screen.findByRole('option', { name: /Gate/ })).toBeInTheDocument();
  });

  it('confirms before saving a revision that disables analytics', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await selectObject(user, 'Gate');
    await user.click(screen.getByRole('checkbox', { name: 'Enabled for analytics' }));
    await selectObject(user, 'Kerb');
    await user.click(screen.getByRole('checkbox', { name: 'Enabled for analytics' }));
    await user.click(screen.getByRole('button', { name: 'Save and activate' }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Disable analytics for this camera?'));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Earlier revisions'));
    expect(saveCameraScene).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it('does not confirm for an ordinary enabled revision', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(saveCameraScene).mockResolvedValue(revision({ revisionNumber: 3 }));
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await user.click(screen.getByRole('button', { name: 'Save and activate' }));

    await waitFor(() => expect(saveCameraScene).toHaveBeenCalled());
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  // Failures
  it('shows a validation failure against its own code', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockRejectedValue(
      new ApiError({ status: 400, code: 'scene_zone_self_intersecting', detail: 'nope' }),
    );
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await user.click(screen.getByRole('button', { name: 'Save and activate' }));

    expect(await screen.findByText('A zone boundary may not cross itself.')).toBeInTheDocument();
  });

  it('keeps the draft and offers a reload on a conflict', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockRejectedValue(
      new ApiError({ status: 409, code: 'scene_revision_conflict', detail: 'stale' }),
    );
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Zone name'));
    await user.type(screen.getByLabelText('Zone name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Save and activate' }));

    expect(await screen.findByText(/This scene changed since you started editing/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload active revision' })).toBeInTheDocument();
    // The unsaved draft survives until the operator decides.
    expect(screen.getByLabelText('Zone name')).toHaveValue('Forecourt');
    expect(saveCameraScene).toHaveBeenCalledTimes(1);
  });

  it('reports a failed reference video without discarding the scene', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await user.selectOptions(screen.getByLabelText('Reference video'), videoId);
    const video = screen.getByLabelText('Reference frame video') as HTMLVideoElement;
    video.dispatchEvent(new Event('error'));

    expect(await screen.findByText(/reference video could not be loaded/i)).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Gate/ })).toBeInTheDocument();
  });

  // Reference frame
  it('records the chosen instant and not a later playhead position', async () => {
    const user = userEvent.setup();
    vi.mocked(saveCameraScene).mockResolvedValue(revision({ revisionNumber: 3 }));
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await user.selectOptions(screen.getByLabelText('Reference video'), videoId);
    const media = screen.getByLabelText('Reference frame video') as HTMLVideoElement;
    Object.defineProperty(media, 'currentTime', { configurable: true, writable: true, value: 12.5 });
    await user.click(screen.getByRole('button', { name: 'Use current frame' }));

    expect(await screen.findByText(/gate\.mp4 at/)).toBeInTheDocument();

    // Scrubbing afterwards must not move what will be saved.
    (media as unknown as { currentTime: number }).currentTime = 90;
    await user.click(screen.getByRole('button', { name: 'Save and activate' }));

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
    await screen.findByRole('option', { name: /Gate/ });

    await user.click(screen.getByRole('button', { name: 'View revision 1' }));

    expect(await screen.findByText(/Viewing revision 1 — read only/)).toBeInTheDocument();
    expect(await screen.findByRole('option', { name: /Old gate/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Draw zone' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save and activate' })).toBeDisabled();
    expect(getCameraSceneRevision).toHaveBeenCalledWith(cameraId, 1, expect.anything());

    await user.click(screen.getByRole('button', { name: 'Return to active revision' }));

    expect(await screen.findByRole('option', { name: /Gate/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Old gate/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Draw zone' })).toBeEnabled();
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
    await screen.findByRole('option', { name: /Gate/ });

    await user.click(screen.getByRole('button', { name: 'View revision 1' }));
    await screen.findByRole('option', { name: /Old gate/ });
    await user.click(screen.getByRole('button', { name: 'Return to active revision' }));
    await screen.findByRole('option', { name: /Gate/ });
    await user.click(screen.getByRole('button', { name: 'Save and activate' }));

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
    await screen.findByRole('option', { name: /Gate/ });

    await user.click(screen.getByRole('button', { name: 'View revision 1' }));

    expect(await screen.findByText('That revision does not exist for this camera.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Return to active revision' }));
    expect(await screen.findByRole('option', { name: /Gate/ })).toBeInTheDocument();
  });

  // Reset
  it('confirms before discarding meaningful edits', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await selectObject(user, 'Gate');
    await user.clear(screen.getByLabelText('Zone name'));
    await user.type(screen.getByLabelText('Zone name'), 'Forecourt');
    await user.click(screen.getByRole('button', { name: 'Reset' }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Discard unsaved scene changes'));
    expect(await screen.findByRole('option', { name: /Gate/ })).toBeInTheDocument();
    confirm.mockRestore();
  });

  it('does not confirm a reset that would discard nothing', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render();
    await screen.findByRole('option', { name: /Gate/ });

    await user.click(screen.getByRole('button', { name: 'Reset' }));

    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  // No false capability
  it('claims nothing about analytics that have not run', async () => {
    render();
    await screen.findByRole('option', { name: /Gate/ });

    expect(screen.queryByText(/Analyse existing runs/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/analysed runs/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/readiness/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/crossing count/i)).not.toBeInTheDocument();
  });
});

describe('scene editor accessibility', () => {
  it('names every tool button', async () => {
    render();
    await screen.findByRole('option', { name: /Gate/ });

    expect(screen.getByRole('button', { name: 'Select' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Draw zone' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Draw trip line' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('group', { name: 'Drawing tools' })).toBeInTheDocument();
  });

  it('exposes the whole scene as a list', async () => {
    render();
    await screen.findByRole('option', { name: /Gate/ });

    const zones = screen.getByRole('listbox', { name: 'Zones' });
    expect(within(zones).getAllByRole('option')).toHaveLength(1);
    const lines = screen.getByRole('listbox', { name: 'Trip lines' });
    expect(within(lines).getAllByRole('option')).toHaveLength(1);
  });

  it('exposes every coordinate a keyboard user needs', async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole('option', { name: /Gate/ });

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
    await screen.findByRole('option', { name: /Gate/ });

    await selectObject(user, 'Gate');
    expect(screen.getByLabelText('Kind')).toHaveValue('Restricted');
    expect(screen.getByLabelText(/Loitering threshold/)).toHaveValue(45);

    const name = screen.getByLabelText('Zone name');
    await user.clear(name);

    expect(name).toHaveAttribute('aria-invalid', 'true');
    expect(name).toHaveAccessibleDescription('A zone needs a name.');
  });

  it('gives every delete control a name that says what it deletes', async () => {
    render();
    await screen.findByRole('option', { name: /Gate/ });

    expect(screen.getByRole('button', { name: 'Delete zone Gate' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete trip line Kerb' })).toBeInTheDocument();
  });

  it('hides the decorative overlay from assistive technology', async () => {
    render();
    await screen.findByRole('option', { name: /Gate/ });

    expect(screen.getByTestId('scene-overlay')).toHaveAttribute('aria-hidden', 'true');
  });
});
