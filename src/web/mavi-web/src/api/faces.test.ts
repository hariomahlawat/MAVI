import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  addGalleryTemplate,
  compareWithGallery,
  deleteGalleryEntry,
  deleteGalleryTemplate,
  enrolInGallery,
  formatFaceScore,
  getTrackFaces,
  readQueryImage,
  searchFace,
  setCameraFaceAnalysis,
  thresholdContext,
  unknownFaceSentence,
  updateGalleryEntry,
  uploadFaceQuery,
} from './faces';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe('PoC S6 faces API client', () => {
  it('sends every face mutation as JSON to its route', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({})));
    vi.stubGlobal('fetch', fetchMock);

    await uploadFaceQuery('AAAA', 'image/png');
    await searchFace({ faceId: 'f1' }, 10);
    await searchFace({ queryId: 'q1', faceIndex: 0 }, 20, 'snap');
    await compareWithGallery({ faceId: 'f1' });
    await enrolInGallery('Visitor A', null, { faceId: 'f1' });
    await updateGalleryEntry('e1', { label: 'Visitor B' });
    await addGalleryTemplate('e1', { queryId: 'q1', faceIndex: 1 });
    await deleteGalleryTemplate('e1', 't1');
    await deleteGalleryEntry('e1');
    await setCameraFaceAnalysis('c1', true);

    const calls = fetchMock.mock.calls.map(([path, init]) => [path, init.method, JSON.parse(init.body), init.headers['Content-Type']]);
    expect(calls).toEqual([
      ['/api/faces/queries', 'POST', { imageBase64: 'AAAA', mimeType: 'image/png' }, 'application/json'],
      ['/api/faces/search', 'POST', { source: { faceId: 'f1' }, k: 10 }, 'application/json'],
      ['/api/faces/search', 'POST', { source: { queryId: 'q1', faceIndex: 0 }, k: 20, snapshot: 'snap' }, 'application/json'],
      ['/api/faces/gallery/compare', 'POST', { source: { faceId: 'f1' } }, 'application/json'],
      ['/api/faces/gallery', 'POST', { label: 'Visitor A', note: null, source: { faceId: 'f1' } }, 'application/json'],
      ['/api/faces/gallery/e1', 'PATCH', { label: 'Visitor B' }, 'application/json'],
      ['/api/faces/gallery/e1/templates', 'POST', { source: { queryId: 'q1', faceIndex: 1 } }, 'application/json'],
      ['/api/faces/gallery/e1/templates/t1/delete', 'POST', {}, 'application/json'],
      ['/api/faces/gallery/e1/delete', 'POST', {}, 'application/json'],
      ['/api/cameras/c1/face-analysis', 'PUT', { enabled: true }, 'application/json'],
    ]);
  });

  it('reads a Track’s faces with a GET', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ state: 'unknown' }));
    vi.stubGlobal('fetch', fetchMock);
    await getTrackFaces('t-1');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/tracks/t-1/faces');
  });

  it('states the threshold context and Unknown reasons, never a verdict', () => {
    expect(thresholdContext({ cosine: 0.2121, provenance: 's6-embedder-spike-v1: LFW 6,000 pairs', calibratedOnCctv: false }))
      .toBe('reference threshold 0.2121 (LFW, not calibrated on CCTV)');
    expect(unknownFaceSentence('face_too_small')).toBe('Unknown — no usable face (every detected face is smaller than 32 px)');
    expect(unknownFaceSentence('no_face_detected')).toMatch(/^Unknown — no usable face/);
    expect(unknownFaceSentence('something_new')).toBe('Unknown — no usable face (something_new)');
    for (const reason of ['no_evidence', 'evidence_unavailable', 'no_face_detected', 'face_too_small', null]) {
      expect(unknownFaceSentence(reason)).not.toMatch(/match/i);
    }
    expect(formatFaceScore(0.71234)).toBe('0.712');
  });

  it('reads a query image as base64 and refuses other types and sizes', async () => {
    const png = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'q.png', { type: 'image/png' });
    await expect(readQueryImage(png)).resolves.toEqual({ imageBase64: 'iVBORw==', mimeType: 'image/png' });
    await expect(readQueryImage(new File(['x'], 'q.gif', { type: 'image/gif' }))).rejects.toThrow('JPEG or PNG');
    const big = new File([new Uint8Array(2 * 1024 * 1024 + 1)], 'big.jpg', { type: 'image/jpeg' });
    await expect(readQueryImage(big)).rejects.toThrow('2 MB');
  });
});
