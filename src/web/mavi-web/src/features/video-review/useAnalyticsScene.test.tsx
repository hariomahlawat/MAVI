import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createMaviQueryClient } from '../../app/queryClient';
import {
  ANALYSED_REVISION_ID,
  CAMERA_ID,
  OTHER_REVISION_ID,
  analysedAnalytics,
  notConfiguredAnalytics,
  sceneRevision,
} from '../../test/analyticsFixtures';
import type { TrackDetailAnalytics } from '../../api/tracks';
import { useAnalyticsScene, type AnalyticsSceneState } from './useAnalyticsScene';

/** Renders the hook and prints its state, so assertions read like the contract. */
function Probe({ cameraId, analytics }: { cameraId?: string; analytics?: TrackDetailAnalytics }) {
  const state = useAnalyticsScene(cameraId, analytics);
  return <output data-testid="state">{describeState(state)}</output>;
}

function describeState(state: AnalyticsSceneState): string {
  switch (state.status) {
    case 'ready':
      return `ready:${state.revision.revisionNumber}:${state.revision.revisionId}:zones=${state.revision.zones.length}`;
    case 'unavailable':
      return `unavailable:${state.reason}`;
    case 'loading':
      return `loading:${state.revisionNumber}`;
    default:
      return state.status;
  }
}

function renderProbe(props: { cameraId?: string; analytics?: TrackDetailAnalytics }) {
  const queryClient = createMaviQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false, refetchOnWindowFocus: false } });
  return render(
    <QueryClientProvider client={queryClient}>
      <Probe {...props} />
    </QueryClientProvider>,
  );
}

const state = () => screen.getByTestId('state').textContent;

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** One JSON response, as the API client reads it. */
function respond(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  }));
}

describe('pinned analytics scene revision', () => {
  it('fetches the exact revision the facts name, by its own number', async () => {
    fetchMock.mockImplementation(() => respond(sceneRevision()));
    renderProbe({ cameraId: CAMERA_ID, analytics: analysedAnalytics() });

    await waitFor(() => expect(state()).toMatch(/^ready:/));
    expect(state()).toBe(`ready:4:${ANALYSED_REVISION_ID}:zones=1`);

    // Addressed by the analytical revision number, not by asking what is active
    // now. One request, to the immutable revision endpoint.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain(`/api/cameras/${CAMERA_ID}/scene/revisions/4`);
    expect(url).not.toContain('/scene?');
    expect(url.endsWith('/scene')).toBe(false);
  });

  it('fails closed when the served revision is not the one the facts name', async () => {
    // The number addressed the request and a revision came back, but it is a
    // different revision. Drawing it would put persisted facts over geometry
    // that never produced them, and nothing on screen would say so.
    fetchMock.mockImplementation(() => respond(sceneRevision({ revisionId: OTHER_REVISION_ID })));
    renderProbe({ cameraId: CAMERA_ID, analytics: analysedAnalytics() });

    await waitFor(() => expect(state()).toBe('unavailable:identity-mismatch'));
  });

  it('fails closed when the revision belongs to another camera', async () => {
    fetchMock.mockImplementation(() => respond(
      sceneRevision({ cameraId: '22222222-2222-7222-8222-222222222222' }),
    ));
    renderProbe({ cameraId: CAMERA_ID, analytics: analysedAnalytics() });

    await waitFor(() => expect(state()).toBe('unavailable:identity-mismatch'));
  });

  it('never substitutes the active revision when the pinned one cannot be loaded', async () => {
    fetchMock.mockImplementation(() => respond({ detail: 'gone', code: 'not_found' }, 404));
    renderProbe({ cameraId: CAMERA_ID, analytics: analysedAnalytics() });

    await waitFor(() => expect(state()).toBe('unavailable:request-failed'));
    // The camera-scene endpoint, which is what serves the *active* revision, is
    // never consulted. There is no path from "pinned revision missing" to
    // "draw whatever is current".
    for (const call of fetchMock.mock.calls) {
      expect(String(call[0])).not.toMatch(/\/scene$/);
    }
  });

  it('refuses to guess when facts are claimed without a complete identity', async () => {
    // Analysed, but the identity is half-present. Both halves are needed: the
    // number to address the revision, the id to verify the answer.
    renderProbe({ cameraId: CAMERA_ID, analytics: analysedAnalytics({ sceneRevisionNumber: null }) });
    expect(state()).toBe('incomplete-identity');
    expect(fetchMock).not.toHaveBeenCalled();

    renderProbe({ cameraId: CAMERA_ID, analytics: analysedAnalytics({ sceneRevisionId: null }) });
    expect(screen.getAllByTestId('state')[1].textContent).toBe('incomplete-identity');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('asks for nothing when no analytical facts bind to geometry', () => {
    renderProbe({ cameraId: CAMERA_ID, analytics: notConfiguredAnalytics() });
    expect(state()).toBe('none');

    // A Track whose analysis could not run has an identity but no facts; there
    // is no geometry question to ask on its behalf.
    renderProbe({
      cameraId: CAMERA_ID,
      analytics: analysedAnalytics({ status: 'Unavailable', unavailableReason: 'trajectory_too_short' }),
    });
    expect(screen.getAllByTestId('state')[1].textContent).toBe('none');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('pins a stale identity only when that identity actually supplied facts', async () => {
    renderProbe({ cameraId: CAMERA_ID, analytics: analysedAnalytics({ status: 'Stale' }) });
    expect(state()).toBe('none');
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockImplementation(() => respond(sceneRevision()));
    renderProbe({
      cameraId: CAMERA_ID,
      analytics: analysedAnalytics({
        status: 'Stale',
        motion: {
          heading: 'E', pathLengthNormalised: 0.4, meanDisplacementRate: 0.01,
          longestStationaryMs: 0, totalStationaryMs: 0, stationaryIntervals: [], stationaryZoneIds: [],
        },
      }),
    });
    await waitFor(() => expect(screen.getAllByTestId('state')[1].textContent).toMatch(/^ready:/));
  });

  it('asks nothing without a camera', () => {
    renderProbe({ cameraId: undefined, analytics: analysedAnalytics() });
    expect(state()).toBe('none');
    renderProbe({ cameraId: 'not-a-guid', analytics: analysedAnalytics() });
    expect(screen.getAllByTestId('state')[1].textContent).toBe('none');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
