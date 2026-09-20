import type { Camera } from '../../api/cameras';
import type { VideoAsset } from '../../api/videos';
import { isVideoStatus, type VideoStatus } from '../../shared/status/status';

export type VideoRow = VideoAsset & {
  cameraCode: string;
  cameraName: string;
  cameraTimeZoneId: string;
};

export type VideoListFilters = {
  cameraId?: string;
  status?: VideoStatus | '';
  text?: string;
};

/** Join videos to their cameras; a video whose camera is unknown still lists. */
export function joinVideoRows(videos: readonly VideoAsset[], cameras: readonly Camera[] | undefined): VideoRow[] {
  const byId = new Map((cameras ?? []).map((camera) => [camera.id.toLowerCase(), camera]));
  return videos.map((video) => {
    const camera = byId.get(video.cameraId.toLowerCase());
    return {
      ...video,
      cameraCode: camera?.code ?? '—',
      cameraName: camera?.name ?? 'Unknown camera',
      cameraTimeZoneId: camera?.timeZoneId ?? video.recordingTimeZoneId,
    };
  });
}

/** Newest recording first, then by import time so identical starts stay stable. */
export function sortVideoRows(rows: readonly VideoRow[]): VideoRow[] {
  return [...rows].sort((left, right) => {
    const byStart = right.recordingStartUtc.localeCompare(left.recordingStartUtc);
    if (byStart !== 0) return byStart;
    return right.importedAtUtc.localeCompare(left.importedAtUtc);
  });
}

export function filterVideoRows(rows: readonly VideoRow[], filters: VideoListFilters): VideoRow[] {
  const text = (filters.text ?? '').trim().toLowerCase();
  const cameraId = filters.cameraId?.toLowerCase();
  return rows.filter((row) => {
    if (cameraId && row.cameraId.toLowerCase() !== cameraId) return false;
    if (filters.status && row.processingStatus !== filters.status) return false;
    if (text) {
      const haystack = `${row.originalFileName} ${row.cameraCode} ${row.cameraName}`.toLowerCase();
      if (!haystack.includes(text)) return false;
    }
    return true;
  });
}

export function countByStatus(rows: readonly VideoAsset[]): Record<VideoStatus, number> {
  const counts: Record<VideoStatus, number> = { NotQueued: 0, Queued: 0, Processing: 0, Processed: 0, Failed: 0 };
  for (const row of rows) {
    if (isVideoStatus(row.processingStatus)) counts[row.processingStatus] += 1;
  }
  return counts;
}

/** Parse the `status` query value defensively; anything unknown means "all". */
export function parseStatusFilter(value: string | null): VideoStatus | '' {
  return value && isVideoStatus(value) ? value : '';
}
