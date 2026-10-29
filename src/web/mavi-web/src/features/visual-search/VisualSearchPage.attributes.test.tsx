import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import {
  getAttributeVocabulary,
  searchTracks,
  type AttributeVocabulary,
  type TrackDetail,
  type TrackSearchItem,
  type TrackSearchResponse,
} from '../../api/tracks';
import { listVideos } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import TrackAttributesPanel from '../video-review/TrackAttributesPanel';
import VisualSearchPage from './VisualSearchPage';

vi.mock('../../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return { ...actual, searchTracks: vi.fn(), getTrack: vi.fn(), getAttributeVocabulary: vi.fn() };
});
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn() };
});

const searchDrawn = () => screen.findByLabelText('Object class', undefined, { timeout: 3000 });

const vocabulary: AttributeVocabulary = {
  configured: true,
  notConfiguredReason: null,
  identityFingerprint: 'd'.repeat(64),
  disclosure: 'zero-shot, Development',
  developmentOnly: true,
  attributes: [
    { attributeType: 'person-carried-bag', objectClass: 'person', values: ['present'] },
    { attributeType: 'person-upper-colour', objectClass: 'person', values: ['blue', 'red'] },
    { attributeType: 'vehicle-colour', objectClass: 'vehicle', values: ['red', 'white'] },
  ],
};

const row: TrackSearchItem = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21451',
  processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
  videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
  cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
  cameraCode: 'CAM-01',
  cameraName: 'North Gate',
  objectClass: 'Person',
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
  videoContentUrl: '/api/videos/x/content',
  attributes: [{ attributeType: 'person-upper-colour', value: 'red', confidence: 0.71, supportingObservationId: 'o' }],
};

const page: TrackSearchResponse = {
  items: [row],
  nextCursor: null,
  attributeCoverage: {
    identityFingerprint: 'd'.repeat(64),
    disclosure: 'zero-shot, Development',
    predicates: ['person-upper-colour:red'],
    tracksInScope: 5,
    analysed: 3,
    unavailable: 1,
    notAnalysed: 1,
    unknown: [{ attributeType: 'person-upper-colour', tracks: 2 }],
  },
};

function Location() {
  const location = useLocation();
  return <output aria-label="Current search location">{location.search}</output>;
}

describe('PoC S5 attribute search on Search', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.mocked(listCameras).mockResolvedValue([]);
    vi.mocked(listVideos).mockResolvedValue([]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(getAttributeVocabulary).mockResolvedValue(vocabulary);
    vi.mocked(searchTracks).mockResolvedValue(page);
  });

  it('offers the bound vocabulary with its disclosure and commits a choice with its class', async () => {
    const user = userEvent.setup();
    renderWithApp(<><Location /><VisualSearchPage /></>, { route: '/search' });
    await searchDrawn();

    expect(await screen.findByText('Attribute values: zero-shot, Development')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Upper clothing colour'), 'red');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenLastCalledWith(
      expect.objectContaining({ attribute: ['person-upper-colour:red'], objectClass: 'Person' }),
      expect.any(AbortSignal),
    ));
    expect(screen.getByLabelText('Current search location')).toHaveTextContent('attribute=person-upper-colour%3Ared');
    const chips = screen.getByRole('group', { name: 'Committed filters' });
    expect(chips).toHaveTextContent('Upper clothing colour: red');
  });

  it('states coverage with the disclosure and explains each row in plain text', async () => {
    renderWithApp(<VisualSearchPage />, { route: '/search?objectClass=Person&attribute=person-upper-colour:red' });
    await searchDrawn();

    const coverage = await screen.findByRole('region', { name: 'Attribute coverage' });
    expect(coverage).toHaveTextContent('Attributes (zero-shot, Development): 3 of 5 Tracks in scope analysed');
    expect(coverage).toHaveTextContent('1 unavailable');
    expect(coverage).toHaveTextContent('1 not analysed');
    expect(coverage).toHaveTextContent('upper clothing colour unknown on 2');
    const rows = within(screen.getByRole('list', { name: 'Track results' })).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('Matched upper clothing colour red (score 0.71)');
  });

  it('never reads an empty attribute result as "no such Track" while coverage is partial', async () => {
    vi.mocked(searchTracks).mockResolvedValue({ ...page, items: [] });
    renderWithApp(<VisualSearchPage />, { route: '/search?objectClass=Person&attribute=person-upper-colour:red' });
    await searchDrawn();

    expect(await screen.findByText('No analysed Track has these attribute values.')).toBeInTheDocument();
    expect(screen.getByText(/a match may exist among them/)).toBeInTheDocument();
  });

  it('says so when the installation has no attribute release', async () => {
    vi.mocked(getAttributeVocabulary).mockResolvedValue({ ...vocabulary, configured: false, disclosure: null, attributes: [] });
    renderWithApp(<VisualSearchPage />, { route: '/search' });
    await searchDrawn();

    expect(await screen.findByText('Attribute search is not configured in this installation.')).toBeInTheDocument();
  });
});

function detail(attributes: TrackDetail['attributes']): TrackDetail {
  return {
    id: row.id,
    observations: [{ observationId: 'o', evidenceRole: 'Representative' }],
    attributes,
  } as unknown as TrackDetail;
}

describe('PoC S5 Track attributes panel', () => {
  it('states Observed, Unknown and the disclosure without colour alone', () => {
    render(<TrackAttributesPanel detail={detail({
      readiness: 'Ready',
      disclosure: 'zero-shot, Development',
      developmentOnly: true,
      trackOutcome: 'Analysed',
      attributes: [
        { attributeType: 'person-carried-bag', outcome: 'Unknown' },
        { attributeType: 'person-upper-colour', outcome: 'Observed', value: 'red', confidence: 0.712, supportingObservationId: 'o' },
      ],
      provenance: {
        analysisId: 'a', identityFingerprint: 'd'.repeat(64), attributeSchemaId: 'poc-zero-shot-attributes', attributeSchemaVersion: '1.0.0',
        pipelineId: 'attributes-siglip2-zero-shot', pipelineVersion: '1.0.0', aggregationPolicyId: 'mean-score-argmax',
        aggregationPolicyVersion: '1.0.0', capabilities: '[]', completedAtUtc: null,
      },
    })} />);

    const panel = screen.getByRole('region', { name: 'Attributes' });
    expect(panel).toHaveTextContent('zero-shot, Development: candidate values, not verified facts.');
    expect(panel).toHaveTextContent('Carried bagAnalysed · value unknown');
    expect(panel).toHaveTextContent('Upper clothing colourred · score 0.71 · Representative crop');
    expect(panel).toHaveTextContent('attributes-siglip2-zero-shot 1.0.0');
  });

  it('states a run that is not ready and an unavailable Track in words', () => {
    const { rerender } = render(<TrackAttributesPanel detail={detail({
      readiness: 'Pending', developmentOnly: true, attributes: [],
    })} />);
    expect(screen.getByText('Attribute analysis has not finished for this run.')).toBeInTheDocument();

    rerender(<TrackAttributesPanel detail={detail({
      readiness: 'Ready', developmentOnly: true, trackOutcome: 'Unavailable', unavailableReason: 'evidence_decode_failed', attributes: [],
    })} />);
    expect(screen.getByText('Attributes unavailable for this Track (evidence decode failed).')).toBeInTheDocument();
    expect(screen.getByText('Development: candidate values, not verified facts.')).toBeInTheDocument();
  });
});
