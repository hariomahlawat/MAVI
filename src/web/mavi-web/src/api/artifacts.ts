import { ApiError } from './client';

const MAX_TRAJECTORY_BYTES = 8 * 1024 * 1024;

/**
 * Fetch a small evidence artefact as bytes. Evidence is served by the
 * range-capable artifact endpoint; this reads it whole, which is right for
 * trajectories (a few KiB) and wrong for video, which the player streams.
 */
export async function fetchArtifactBytes(contentUrl: string, signal?: AbortSignal): Promise<Uint8Array> {
  const response = await fetch(contentUrl, { signal });
  if (!response.ok) {
    throw new ApiError({
      status: response.status,
      code: response.status === 404 ? 'artifact_not_found' : 'artifact_unavailable',
      detail: response.status === 404 ? 'Artifact was not found.' : 'Artifact content is unavailable.',
    });
  }
  const declared = Number(response.headers.get('content-length') ?? '0');
  if (declared > MAX_TRAJECTORY_BYTES) {
    throw new ApiError({ status: 413, code: 'artifact_too_large', detail: 'Artifact is larger than the client will read.' });
  }
  const buffer = await response.arrayBuffer();
  if (buffer.byteLength > MAX_TRAJECTORY_BYTES) {
    throw new ApiError({ status: 413, code: 'artifact_too_large', detail: 'Artifact is larger than the client will read.' });
  }
  return new Uint8Array(buffer);
}
