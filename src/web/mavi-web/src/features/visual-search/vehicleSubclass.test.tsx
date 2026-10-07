import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import {
  objectClassLabel,
  searchTracks,
  serializeTrackSearchFilters,
  type TrackSearchItem,
} from '../../api/tracks';
import { listVideos } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import { canonicalSearchKey, parseCommittedSearch, removeCriteria } from './searchState';
import TrackResultCard from './TrackResultCard';
import VisualSearchPage from './VisualSearchPage';

/**
 * Stage 3 X2 in the web client: the committed `objectSubclass` grammar, its
 * canonical query (which is also the cache and search fingerprint), the Vehicle
 * type filter, and `Vehicle · Car` as subordinate metadata on a result. The
 * client shows only what the server exposed; it never infers a subclass.
 */

vi.mock('../../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return { ...actual, searchTracks: vi.fn(), getTrack: vi.fn() };
});
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn() };
});

const camera = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
  code: 'CAM-01',
  name: 'North Gate',
  description: null,
  locationName: null,
  timeZoneId: 'Asia/Kolkata',
  isActive: true,
  createdAtUtc: '2026-09-14T02:30:00Z',
  updatedAtUtc: '2026-09-14T02:30:00Z',
};

function item(id: string, overrides: Partial<TrackSearchItem> = {}): TrackSearchItem {
  return {
    id,
    processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
    videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
    cameraId: camera.id,
    cameraCode: camera.code,
    cameraName: camera.name,
    objectClass: 'Vehicle',
    startTimestampUtc: '2026-09-14T02:30:00Z',
    endTimestampUtc: '2026-09-14T02:30:08Z',
    startOffsetMs: 10_000,
    endOffsetMs: 18_000,
    durationMs: 8_000,
    detectionCount: 32,
    meanConfidence: 0.91,
    maxConfidence: 0.97,
    reviewStatus: 'Unreviewed',
    thumbnailArtifactId: null,
    thumbnailContentUrl: null,
    videoContentUrl: '/api/videos/018f3f5a-2f70-7a2b-8a12-2d02f4c21421/content',
    ...overrides,
  };
}

describe('committed objectSubclass state', () => {
  it('accepts car and states its implied Vehicle class canonically', () => {
    const implied = parseCommittedSearch(new URLSearchParams('objectSubclass=car'));
    const explicit = parseCommittedSearch(new URLSearchParams('objectSubclass=car&objectClass=vehicle'));

    expect(implied).toEqual({
      isValid: true,
      filters: { objectClass: 'Vehicle', objectSubclass: 'car' },
      canonicalQuery: 'objectClass=Vehicle&objectSubclass=car',
    });
    // One semantic search, one canonical query: the URL, the cache key and the
    // fingerprint the server computes all agree.
    expect(explicit.canonicalQuery).toBe(implied.canonicalQuery);
  });

  it.each([
    ['objectSubclass=truck'],
    ['objectSubclass=bus'],
    ['objectSubclass=motorcycle'],
    ['objectSubclass=Car'],
    ['objectSubclass=van'],
    ['objectSubclass='],
    ['objectSubclass=car&objectSubclass=car'],
    ['objectClass=Person&objectSubclass=car'],
  ])('refuses %s rather than coercing it', (query) => {
    const parsed = parseCommittedSearch(new URLSearchParams(query));
    expect(parsed.isValid).toBe(false);
  });

  it('leaves a search without a subclass exactly as it was', () => {
    const parsed = parseCommittedSearch(new URLSearchParams('objectClass=Vehicle&cameraId=' + camera.id));
    expect(parsed).toEqual({
      isValid: true,
      filters: { cameraId: camera.id, objectClass: 'Vehicle' },
      canonicalQuery: 'cameraId=' + camera.id + '&objectClass=Vehicle',
    });
  });

  it('sends the predicate to the server in canonical order', () => {
    expect(serializeTrackSearchFilters({ objectSubclass: 'car', objectClass: 'Vehicle', limit: 24 }))
      .toBe('objectClass=Vehicle&objectSubclass=car&limit=24');
  });

  it('drops the vehicle type with its class, and keeps Vehicle when only the type is removed', () => {
    const filters = { objectClass: 'Vehicle' as const, objectSubclass: 'car' as const };
    expect(removeCriteria(filters, ['objectSubclass'])).toEqual({ objectClass: 'Vehicle' });
    expect(removeCriteria(filters, ['objectClass', 'objectSubclass'])).toEqual({});
    // Removing the class alone cannot leave a type without its class.
    expect(canonicalSearchKey(removeCriteria(filters, ['objectClass']))).toBe('objectClass=Vehicle&objectSubclass=car');
  });
});

describe('Vehicle · Car on a result', () => {
  it('shows the exposed subclass under its broad class', () => {
    render(
      <MemoryRouter>
        <TrackResultCard track={item('018f3f5a-2f70-7a2b-8a12-2d02f4c21451', { objectSubclass: 'car' })} displayTimeZoneId="Asia/Kolkata" />
      </MemoryRouter>,
    );
    expect(screen.getByText('Vehicle · Car')).toBeInTheDocument();
  });

  it('shows a Vehicle without an exposed subclass as a Vehicle only', () => {
    render(
      <MemoryRouter>
        <TrackResultCard track={item('018f3f5a-2f70-7a2b-8a12-2d02f4c21452')} displayTimeZoneId="Asia/Kolkata" />
      </MemoryRouter>,
    );
    expect(screen.getByText('Vehicle')).toBeInTheDocument();
    expect(screen.queryByText(/Car/)).not.toBeInTheDocument();
  });

  it('never renders a value the client does not know as operator-facing', () => {
    const unexpected = { objectClass: 'Vehicle' as const, objectSubclass: 'truck' as never };
    expect(objectClassLabel(unexpected)).toBe('Vehicle');
    expect(objectClassLabel({ objectClass: 'Person' })).toBe('Person');
  });
});

function LocationProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <button type="button" onClick={() => navigate(-1)}>Back</button>
      <output aria-label="Current search location">{location.pathname + location.search}</output>
      <VisualSearchPage />
    </>
  );
}

describe('the Vehicle type filter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(listVideos).mockResolvedValue([]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(searchTracks).mockResolvedValue({
      items: [item('018f3f5a-2f70-7a2b-8a12-2d02f4c21451', { objectSubclass: 'car' })],
      nextCursor: null,
    });
  });

  it('offers Car only, and commits the canonical car search', async () => {
    const user = userEvent.setup();
    renderWithApp(<LocationProbe />, { route: '/search' });
    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(1));

    const type = screen.getByLabelText('Vehicle type');
    expect(within(type).getAllByRole('option').map((option) => option.textContent)).toEqual(['Any vehicle type', 'Car']);

    await user.selectOptions(type, 'car');
    expect(screen.getByLabelText('Object class')).toHaveValue('Vehicle');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0]).toEqual(expect.objectContaining({
      objectClass: 'Vehicle',
      objectSubclass: 'car',
    }));
    await waitFor(() => expect(screen.getByLabelText('Current search location'))
      .toHaveTextContent('/search?objectClass=Vehicle&objectSubclass=car'));
    expect(await screen.findAllByText(/Vehicle · Car/)).not.toHaveLength(0);

    // Back returns to the unfiltered search and its draft.
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await waitFor(() => expect(screen.getByLabelText('Vehicle type')).toHaveValue(''));
    expect(screen.getByLabelText('Current search location')).toHaveTextContent(/^\/search$/);
  });

  it('is not available under Person, and choosing Person clears it', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, { route: '/search?objectSubclass=car' });
    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(1));
    expect(vi.mocked(searchTracks).mock.calls[0][0]).toEqual(expect.objectContaining({
      objectClass: 'Vehicle',
      objectSubclass: 'car',
    }));
    expect(screen.getByLabelText('Vehicle type')).toHaveValue('car');

    await user.selectOptions(screen.getByLabelText('Object class'), 'Person');
    expect(screen.getByLabelText('Vehicle type')).toHaveValue('');
    expect(screen.getByLabelText('Vehicle type')).toBeDisabled();
  });

  it('clears the type when the class is set back to Any class', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, { route: '/search?objectSubclass=car' });
    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(1));

    await user.selectOptions(screen.getByLabelText('Object class'), '');
    expect(screen.getByLabelText('Vehicle type')).toHaveValue('');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    const second = vi.mocked(searchTracks).mock.calls[1][0];
    expect(second.objectClass).toBeUndefined();
    expect(second.objectSubclass).toBeUndefined();
  });

  it('refuses an unsupported vehicle type in the URL without issuing a Track request', async () => {
    renderWithApp(<VisualSearchPage />, { route: '/search?objectSubclass=truck' });

    expect(await screen.findByText(/Vehicle type must be car/i)).toBeInTheDocument();
    expect(searchTracks).not.toHaveBeenCalled();
  });

  it('shows the type as a chip that removes only the type', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, { route: '/search?objectClass=Vehicle&objectSubclass=car' });
    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(1));

    const chips = () => screen.getByRole('group', { name: 'Committed filters' });
    expect(within(chips()).getByTitle(/^Vehicle type:/)).toHaveTextContent('Car');

    await user.click(screen.getByRole('button', { name: 'Remove vehicle type filter' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    const second = vi.mocked(searchTracks).mock.calls[1][0];
    expect(second.objectClass).toBe('Vehicle');
    expect(second.objectSubclass).toBeUndefined();
  });
});
