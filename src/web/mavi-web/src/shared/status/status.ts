// One place decides what a status string means visually and in words. Screens
// never map 'Processed' to green on their own.

export type Tone = 'ok' | 'warn' | 'err' | 'info' | 'active' | 'neutral';

/** Video processing statuses the API emits (VideoProcessingStatus). */
export const VIDEO_STATUSES = ['NotQueued', 'Queued', 'Processing', 'Processed', 'Failed'] as const;
export type VideoStatus = typeof VIDEO_STATUSES[number];

/** Processing run statuses the API emits (ProcessingRunStatus). */
export const RUN_STATUSES = ['Queued', 'Running', 'Completed', 'Failed', 'Cancelled'] as const;

export function toneForStatus(status: string | null | undefined): Tone {
  switch (status) {
    case 'Processed':
    case 'Completed':
    case 'Confirmed':
      return 'ok';
    case 'Failed':
    case 'Rejected':
      return 'err';
    case 'Queued':
      return 'info';
    case 'Processing':
    case 'Running':
      return 'active';
    case 'Cancelled':
      return 'warn';
    default:
      return 'neutral';
  }
}

export function labelForStatus(status: string | null | undefined): string {
  switch (status) {
    case 'NotQueued': return 'Not queued';
    case 'Unreviewed': return 'Unreviewed';
    case undefined:
    case null:
    case '': return 'Unknown';
    default: return status;
  }
}

export function isActiveStatus(status: string | null | undefined): boolean {
  return status === 'Queued' || status === 'Processing' || status === 'Running';
}

export function isVideoStatus(value: string): value is VideoStatus {
  return (VIDEO_STATUSES as readonly string[]).includes(value);
}
