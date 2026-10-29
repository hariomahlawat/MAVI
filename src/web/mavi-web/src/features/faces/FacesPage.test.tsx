import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras, type Camera } from '../../api/cameras';
import {
  FACE_CANDIDATES_LABEL,
  addGalleryTemplate,
  deleteGalleryEntry,
  deleteGalleryTemplate,
  getFaceQuery,
  listGallery,
  setCameraFaceAnalysis,
  updateGalleryEntry,
  uploadFaceQuery,
  type GalleryResponse,
} from '../../api/faces';
import { renderWithApp } from '../../test/renderWithApp';
import FacesPage from './FacesPage';

vi.mock('../../api/faces', async () => {
  const actual = await vi.importActual<typeof import('../../api/faces')>('../../api/faces');
  return {
    ...actual,
    uploadFaceQuery: vi.fn(), getFaceQuery: vi.fn(), listGallery: vi.fn(), updateGalleryEntry: vi.fn(),
    addGalleryTemplate: vi.fn(), deleteGalleryTemplate: vi.fn(), deleteGalleryEntry: vi.fn(), setCameraFaceAnalysis: vi.fn(),
    searchFace: vi.fn(), compareWithGallery: vi.fn(), enrolInGallery: vi.fn(),
  };
});
vi.mock('../../api/cameras', async () => {
  const actual = await vi.importActual<typeof import('../../api/cameras')>('../../api/cameras');
  return { ...actual, listCameras: vi.fn() };
});

const camera: Camera = {
  id: 'cam-12', code: 'POC-S2-12', name: 'MEVA stairwell', description: null, locationName: null, timeZoneId: 'UTC',
  isActive: true, createdAtUtc: '2026-10-29T00:00:00Z', updatedAtUtc: '2026-10-29T00:00:00Z',
};

function gallery(): GalleryResponse {
  return {
    label: FACE_CANDIDATES_LABEL,
    entries: [{
      enrolledPersonId: 'e1', label: 'Visitor A', note: 'Demo actor', createdAtUtc: '2026-10-29T00:00:00Z', updatedAtUtc: '2026-10-29T00:00:00Z',
      templates: [
        { templateId: 't1', sourceKind: 'query', sourceFaceId: null, sourceObservationId: null, evidenceCropUrl: null, box: null, thumbnailDataUrl: 'data:image/jpeg;base64,AA==', createdAtUtc: '2026-10-29T00:00:00Z' },
        { templateId: 't2', sourceKind: 'evidence', sourceFaceId: 'f1', sourceObservationId: 'o1', evidenceCropUrl: '/api/artifacts/a/content', box: { x: 1, y: 1, width: 40, height: 40 }, thumbnailDataUrl: null, createdAtUtc: '2026-10-29T00:00:00Z' },
      ],
    }],
  };
}

describe('PoC S6 Faces page', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(listGallery).mockResolvedValue(gallery());
    vi.mocked(listCameras).mockResolvedValue([camera]);
  });

  it('carries the candidate label and lists the gallery with both template kinds', async () => {
    renderWithApp(<FacesPage />);
    expect(await screen.findByText(FACE_CANDIDATES_LABEL)).toBeInTheDocument();
    const entries = await screen.findByRole('list', { name: 'Gallery entries' });
    expect(entries).toHaveTextContent('Visitor A');
    expect(entries).toHaveTextContent('2 templates');
    expect(within(entries).getByRole('img', { name: 'Template from an uploaded image' })).toBeInTheDocument();
    expect(within(entries).getByRole('img', { name: 'Template from evidence' })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/identified|match found/i);
  });

  it('uploads a query image as JSON, polls until analysed and offers the usable face', async () => {
    const user = userEvent.setup();
    vi.mocked(uploadFaceQuery).mockResolvedValue({ queryId: 'q1', status: 'pending', purgeAfterUtc: '2026-10-29T11:00:00Z' });
    vi.mocked(getFaceQuery)
      .mockResolvedValueOnce({ label: FACE_CANDIDATES_LABEL, queryId: 'q1', status: 'pending', failureCode: null, purgeAfterUtc: 'x', faces: [] })
      .mockResolvedValue({
        label: FACE_CANDIDATES_LABEL, queryId: 'q1', status: 'completed', failureCode: null, purgeAfterUtc: 'x',
        faces: [{ faceIndex: 0, box: { x: 1, y: 1, width: 80, height: 90 }, score: 0.97, usable: true, thumbnailDataUrl: 'data:image/jpeg;base64,AA==' }],
      });
    renderWithApp(<FacesPage />);

    const file = new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], 'face.jpg', { type: 'image/jpeg' });
    await user.upload(screen.getByLabelText('Query image'), file);
    await user.click(screen.getByRole('button', { name: 'Analyse image' }));

    await waitFor(() => expect(uploadFaceQuery).toHaveBeenCalledWith('/9j/4A==', 'image/jpeg'));
    const faces = await screen.findByRole('list', { name: 'Faces in the query image' }, { timeout: 4000 });
    expect(faces).toHaveTextContent('Usable · 0.970');
    expect(screen.getByRole('button', { name: 'Find this face' })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Add this face to a gallery entry'), 'e1');
    vi.mocked(addGalleryTemplate).mockResolvedValue({ enrolledPersonId: 'e1', templateId: 't3' });
    await user.click(screen.getByRole('button', { name: 'Add template' }));
    await waitFor(() => expect(addGalleryTemplate).toHaveBeenCalledWith('e1', { queryId: 'q1', faceIndex: 0 }));
  });

  it('says a query image without a face is Unknown', async () => {
    const user = userEvent.setup();
    vi.mocked(uploadFaceQuery).mockResolvedValue({ queryId: 'q2', status: 'pending', purgeAfterUtc: 'x' });
    vi.mocked(getFaceQuery).mockResolvedValue({ label: FACE_CANDIDATES_LABEL, queryId: 'q2', status: 'completed', failureCode: null, purgeAfterUtc: 'x', faces: [] });
    renderWithApp(<FacesPage />);
    await user.upload(screen.getByLabelText('Query image'), new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'x.png', { type: 'image/png' }));
    await user.click(screen.getByRole('button', { name: 'Analyse image' }));
    expect(await screen.findByText('Unknown — no face detected in the query image.')).toBeInTheDocument();
  });

  it('renames an entry and deletes a template and an entry only after the dialog', async () => {
    const user = userEvent.setup();
    vi.mocked(updateGalleryEntry).mockResolvedValue(gallery().entries[0]);
    vi.mocked(deleteGalleryTemplate).mockResolvedValue(undefined);
    vi.mocked(deleteGalleryEntry).mockResolvedValue(undefined);
    renderWithApp(<FacesPage />);
    const entries = await screen.findByRole('list', { name: 'Gallery entries' });

    await user.click(within(entries).getByRole('button', { name: 'Edit' }));
    const label = within(entries).getByLabelText('Gallery label');
    await user.clear(label);
    await user.type(label, 'Visitor B');
    await user.click(within(entries).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(updateGalleryEntry).toHaveBeenCalledWith('e1', { label: 'Visitor B', note: 'Demo actor' }));

    await user.click(within(entries).getAllByRole('button', { name: 'Remove template' })[0]);
    expect(deleteGalleryTemplate).not.toHaveBeenCalled();
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Remove template' }));
    await waitFor(() => expect(deleteGalleryTemplate).toHaveBeenCalledWith('e1', 't1'));

    await user.click(await within(await screen.findByRole('list', { name: 'Gallery entries' })).findByRole('button', { name: 'Delete entry' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('permanently deleted');
    await user.click(within(dialog).getByRole('button', { name: 'Delete entry' }));
    await waitFor(() => expect(deleteGalleryEntry).toHaveBeenCalledWith('e1'));
  });

  it('shows the flag the camera list reports and offers only the opposite switch', async () => {
    vi.mocked(listCameras).mockResolvedValue([{ ...camera, faceAnalysisEnabled: true }]);
    renderWithApp(<FacesPage />);
    const cameras = await screen.findByRole('list', { name: 'Cameras' });
    expect(await within(cameras).findByText('On')).toBeInTheDocument();
    expect(within(cameras).queryByRole('button', { name: 'Switch on' })).toBeNull();
    expect(within(cameras).getByRole('button', { name: 'Switch off' })).toBeInTheDocument();
  });

  it('switches face analysis on and off per camera, each through the dialog', async () => {
    const user = userEvent.setup();
    vi.mocked(setCameraFaceAnalysis)
      .mockResolvedValueOnce({ cameraId: 'cam-12', faceAnalysisEnabled: true, faceAnalysesDeleted: 0 })
      .mockResolvedValueOnce({ cameraId: 'cam-12', faceAnalysisEnabled: false, faceAnalysesDeleted: 3 });
    renderWithApp(<FacesPage />);

    expect(await screen.findByText(/off by default/)).toBeInTheDocument();
    const cameras = await screen.findByRole('list', { name: 'Cameras' });
    await user.click(within(cameras).getByRole('button', { name: 'Switch on' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Switch on' }));
    await waitFor(() => expect(setCameraFaceAnalysis).toHaveBeenCalledWith('cam-12', true));
    expect(await screen.findByText('Face analysis switched on for POC-S2-12.')).toBeInTheDocument();

    await user.click(within(cameras).getByRole('button', { name: 'Switch off' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent("This camera's face data is deleted now.");
    await user.click(within(dialog).getByRole('button', { name: 'Switch off and delete face data' }));
    await waitFor(() => expect(setCameraFaceAnalysis).toHaveBeenLastCalledWith('cam-12', false));
    expect(await screen.findByText('Face analysis switched off for POC-S2-12; 3 face analyses deleted.')).toBeInTheDocument();
  });
});
