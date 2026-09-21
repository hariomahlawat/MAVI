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

/** The columns the Videos Ledger sorts on (§32 decision 5). */
export type VideoColumn = 'file' | 'camera' | 'recorded' | 'duration';

/**
 * Ascending comparison for one Ledger column. Direction and the final
 * tie-break belong to `sortRows`; this answers only "which of these two comes
 * first when this column reads forwards".
 *
 * `recorded` compares the import time as a second key, ascending, so that
 * reversing the column reverses both — which is exactly the order
 * `sortVideoRows` has always produced for the default view, and the reason the
 * page opens on the same rows in the same sequence as before UI-3.
 *
 * `camera` orders by code and then name rather than by the joined label, so a
 * video whose camera could not be resolved (code `—`) sorts together rather
 * than wherever the em dash happens to fall between two names.
 */
export function compareVideoRows(left: VideoRow, right: VideoRow, column: VideoColumn): number {
  switch (column) {
    case 'file':
      return left.originalFileName.localeCompare(right.originalFileName, undefined, { numeric: true });
    case 'camera': {
      const byCode = left.cameraCode.localeCompare(right.cameraCode, undefined, { numeric: true });
      return byCode !== 0 ? byCode : left.cameraName.localeCompare(right.cameraName);
    }
    case 'duration':
      return left.durationMs - right.durationMs;
    case 'recorded':
    default: {
      const byStart = left.recordingStartUtc.localeCompare(right.recordingStartUtc);
      return byStart !== 0 ? byStart : left.importedAtUtc.localeCompare(right.importedAtUtc);
    }
  }
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
