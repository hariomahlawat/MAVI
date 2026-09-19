import { describe, expect, it } from 'vitest';
import type { Camera } from '../../api/cameras';
import type { VideoAsset } from '../../api/videos';
import { countByStatus, filterVideoRows, joinVideoRows, parseStatusFilter, sortVideoRows } from './videoRows';

const camera: Camera = {
  id: '018F3F5A-2F70-7A2B-8A12-2D02F4C21412',
  code: 'CAM-01',
  name: 'North Gate',
  description: null,
  locationName: null,
  timeZoneId: 'Asia/Kolkata',
  isActive: true,
  createdAtUtc: '2026-09-14T02:30:00Z',
  updatedAtUtc: '2026-09-14T02:30:00Z',
};

function video(id: string, overrides: Partial<VideoAsset> = {}): VideoAsset {
  return {
    id,
    cameraId: camera.id.toLowerCase(),
    originalFileName: `${id}.mp4`,
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

describe('video rows', () => {
  it('joins cameras case-insensitively and keeps orphaned videos listed', () => {
    const rows = joinVideoRows([video('a'), video('b', { cameraId: '00000000-0000-0000-0000-000000000000' })], [camera]);
    expect(rows[0]).toMatchObject({ cameraCode: 'CAM-01', cameraName: 'North Gate', cameraTimeZoneId: 'Asia/Kolkata' });
    expect(rows[1]).toMatchObject({ cameraCode: '—', cameraName: 'Unknown camera' });
  });

  it('sorts newest recording first with import time as the tie-break', () => {
    const rows = joinVideoRows([
      video('old', { recordingStartUtc: '2026-09-13T02:00:00Z' }),
      video('new-early', { importedAtUtc: '2026-09-14T03:00:00Z' }),
      video('new-late', { importedAtUtc: '2026-09-14T04:00:00Z' }),
    ], [camera]);
    expect(sortVideoRows(rows).map((row) => row.id)).toEqual(['new-late', 'new-early', 'old']);
  });

  it('filters by camera, status and free text across file and camera names', () => {
    const rows = joinVideoRows([
      video('gate', { originalFileName: 'gate-morning.mp4' }),
      video('failed', { processingStatus: 'Failed' }),
    ], [camera]);
    expect(filterVideoRows(rows, { status: 'Failed' }).map((row) => row.id)).toEqual(['failed']);
    expect(filterVideoRows(rows, { text: 'MORNING' }).map((row) => row.id)).toEqual(['gate']);
    expect(filterVideoRows(rows, { text: 'north' })).toHaveLength(2);
    expect(filterVideoRows(rows, { cameraId: '00000000-0000-0000-0000-000000000000' })).toHaveLength(0);
  });

  it('counts by known status and ignores unknown values', () => {
    const counts = countByStatus([video('a'), video('b', { processingStatus: 'Queued' }), video('c', { processingStatus: 'Bogus' })]);
    expect(counts).toEqual({ NotQueued: 0, Queued: 1, Processing: 0, Processed: 1, Failed: 0 });
  });

  it('parses the status query parameter defensively', () => {
    expect(parseStatusFilter('Failed')).toBe('Failed');
    expect(parseStatusFilter('anything')).toBe('');
    expect(parseStatusFilter(null)).toBe('');
  });
});
