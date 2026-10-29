import { apiJson, apiRequest } from './client';

/**
 * Face intelligence (PoC S6; ADR-022). Every route requires the operator
 * (ADR-010) and every change is JSON. Every result is a *candidate*: a cosine
 * score beside the reference threshold and the model identity. Nothing here is
 * identity, and nothing the operator does here stores a match.
 */

/** The label every face surface carries; the API sends the same text as `label`. */
export const FACE_CANDIDATES_LABEL = 'Face candidates — not identification — Development';

/** The gallery comparison's answer when no enrolled person scores at or above the threshold. */
export const NO_GALLERY_CANDIDATE = 'No gallery candidate above the threshold';

/** The query image limit the platform enforces (`queryImageMaximumBytes` of the pipeline profile). */
export const FACE_QUERY_MAXIMUM_BYTES = 2 * 1024 * 1024;

export const FACE_SEARCH_K_DEFAULT = 20;

export type FaceBox = { x: number; y: number; width: number; height: number };

export type FaceIdentity = { fingerprint: string; modelId: string; modelVersion: string };

export type ReferenceThreshold = { cosine: number; provenance: string; calibratedOnCctv: boolean };

export type TrackFacesState =
  | 'observed'
  | 'unknown'
  | 'pending'
  | 'failed'
  | 'notAnalysed'
  | 'notEnabled'
  | 'notPerson'
  | 'notConfigured';

export type UnknownFaceReason = 'no_evidence' | 'evidence_unavailable' | 'no_face_detected' | 'face_too_small';

export type TrackFace = {
  faceId: string;
  observationId: string;
  evidenceCropUrl: string | null;
  box: FaceBox;
  landmarks: number[][];
  score: number;
  usable: boolean;
};

export type TrackFacesResponse = {
  label: string;
  state: TrackFacesState;
  reason: UnknownFaceReason | (string & {}) | null;
  identity: FaceIdentity | null;
  referenceThreshold: ReferenceThreshold | null;
  faces: TrackFace[];
};

export type FaceQueryFace = {
  faceIndex: number;
  box: FaceBox;
  score: number;
  usable: boolean;
  thumbnailDataUrl: string | null;
};

export type FaceQueryResponse = {
  label: string;
  queryId: string;
  status: 'pending' | 'completed' | 'failed';
  failureCode: string | null;
  purgeAfterUtc: string;
  faces: FaceQueryFace[];
};

export type FaceQueryUploadResponse = { queryId: string; status: 'pending'; purgeAfterUtc: string };

/** The face a search, comparison or enrolment starts from: a stored face, or one face of a query image. */
export type FaceSource = { faceId: string } | { queryId: string; faceIndex: number };

export type FaceSearchCandidate = {
  rank: number;
  trackId: string;
  processingRunId: string;
  cameraId: string;
  cameraName: string;
  startTimestampUtc: string;
  score: number;
  aboveThreshold: boolean;
  faceId: string;
  observationId: string;
  evidenceCropUrl: string | null;
  box: FaceBox;
};

export type FaceSearchResponse = {
  label: string;
  identity: FaceIdentity;
  referenceThreshold: ReferenceThreshold;
  snapshot: string;
  snapshotUtc: string;
  candidates: FaceSearchCandidate[];
};

export type GalleryCandidate = { enrolledPersonId: string; label: string; score: number; aboveThreshold: boolean };

export type GalleryCompareResponse = {
  label: string;
  identity: FaceIdentity;
  referenceThreshold: ReferenceThreshold;
  candidates: GalleryCandidate[];
  message: string | null;
};

export type GalleryTemplate = {
  templateId: string;
  sourceKind: 'evidence' | 'query';
  sourceFaceId: string | null;
  sourceObservationId: string | null;
  evidenceCropUrl: string | null;
  box: FaceBox | null;
  thumbnailDataUrl: string | null;
  createdAtUtc: string;
};

export type GalleryEntry = {
  enrolledPersonId: string;
  label: string;
  note: string | null;
  createdAtUtc: string;
  updatedAtUtc: string;
  templates: GalleryTemplate[];
};

export type GalleryResponse = { label: string; entries: GalleryEntry[] };

export type CameraFaceAnalysisResponse = { cameraId: string; faceAnalysisEnabled: boolean; faceAnalysesDeleted: number };

const enc = encodeURIComponent;

export function getTrackFaces(trackId: string, signal?: AbortSignal): Promise<TrackFacesResponse> {
  return apiRequest<TrackFacesResponse>('/api/tracks/' + enc(trackId) + '/faces', { signal });
}

export function uploadFaceQuery(imageBase64: string, mimeType: 'image/jpeg' | 'image/png'): Promise<FaceQueryUploadResponse> {
  return apiJson<FaceQueryUploadResponse>('/api/faces/queries', 'POST', { imageBase64, mimeType });
}

export function getFaceQuery(queryId: string, signal?: AbortSignal): Promise<FaceQueryResponse> {
  return apiRequest<FaceQueryResponse>('/api/faces/queries/' + enc(queryId), { signal });
}

export function searchFace(source: FaceSource, k: number = FACE_SEARCH_K_DEFAULT, snapshot?: string): Promise<FaceSearchResponse> {
  return apiJson<FaceSearchResponse>('/api/faces/search', 'POST', { source, k, ...(snapshot ? { snapshot } : {}) });
}

export function compareWithGallery(source: FaceSource): Promise<GalleryCompareResponse> {
  return apiJson<GalleryCompareResponse>('/api/faces/gallery/compare', 'POST', { source });
}

export function listGallery(signal?: AbortSignal): Promise<GalleryResponse> {
  return apiRequest<GalleryResponse>('/api/faces/gallery', { signal });
}

export function enrolInGallery(label: string, note: string | null, source: FaceSource): Promise<{ enrolledPersonId: string }> {
  return apiJson('/api/faces/gallery', 'POST', { label, note, source });
}

export function updateGalleryEntry(id: string, changes: { label?: string; note?: string | null }): Promise<GalleryEntry> {
  return apiJson<GalleryEntry>('/api/faces/gallery/' + enc(id), 'PATCH', changes);
}

export function addGalleryTemplate(id: string, source: FaceSource): Promise<{ enrolledPersonId: string; templateId: string }> {
  return apiJson('/api/faces/gallery/' + enc(id) + '/templates', 'POST', { source });
}

export function deleteGalleryTemplate(id: string, templateId: string): Promise<void> {
  return apiJson<void>('/api/faces/gallery/' + enc(id) + '/templates/' + enc(templateId) + '/delete', 'POST', {});
}

export function deleteGalleryEntry(id: string): Promise<void> {
  return apiJson<void>('/api/faces/gallery/' + enc(id) + '/delete', 'POST', {});
}

export function setCameraFaceAnalysis(cameraId: string, enabled: boolean): Promise<CameraFaceAnalysisResponse> {
  return apiJson<CameraFaceAnalysisResponse>('/api/cameras/' + enc(cameraId) + '/face-analysis', 'PUT', { enabled });
}

/** A score as three decimals, never a percentage: it is a cosine, not a probability. */
export function formatFaceScore(score: number): string {
  return Number.isFinite(score) ? score.toFixed(3) : '—';
}

/** "reference threshold 0.2121 (LFW, not calibrated on CCTV)": the context every score is shown with. */
export function thresholdContext(threshold: ReferenceThreshold | null): string {
  if (!threshold) return 'No reference threshold is configured.';
  const origin = /\bLFW\b/.test(threshold.provenance) ? 'LFW' : threshold.provenance;
  return `reference threshold ${threshold.cosine.toFixed(4)} (${origin}${threshold.calibratedOnCctv ? '' : ', not calibrated on CCTV'})`;
}

/** One sentence per Unknown reason (ADR-022 §1): "not analysable", never "no match". */
export function unknownFaceSentence(reason: string | null): string {
  switch (reason) {
    case 'no_face_detected':
      return 'Unknown — no usable face (no face detected in the evidence crops)';
    case 'face_too_small':
      return 'Unknown — no usable face (every detected face is smaller than 32 px)';
    case 'no_evidence':
      return 'Unknown — no usable face (the Track has no accepted evidence crops)';
    case 'evidence_unavailable':
      return 'Unknown — no usable face (the evidence crops could not be read)';
    default:
      return reason ? `Unknown — no usable face (${reason})` : 'Unknown — no usable face';
  }
}

/** Reads a chosen file as base64 (without the `data:` prefix), refusing anything but a JPEG or PNG of at most 2 MB. */
export async function readQueryImage(file: File): Promise<{ imageBase64: string; mimeType: 'image/jpeg' | 'image/png' }> {
  if (file.type !== 'image/jpeg' && file.type !== 'image/png') throw new Error('Choose a JPEG or PNG image.');
  if (file.size < 1 || file.size > FACE_QUERY_MAXIMUM_BYTES) throw new Error('The image must be at most 2 MB.');
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return { imageBase64: btoa(binary), mimeType: file.type };
}
