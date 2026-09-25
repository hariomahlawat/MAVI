// One place decides what a status string means visually and in words. Screens
// never map 'Processed' to green on their own.

/**
 * The operational-state vocabulary (section 8.2). One place decides what a
 * state means, so two screens cannot disagree about it.
 *
 * `stale` and `unavailable` are not hues on their own: stale carries a dashed
 * edge and unavailable a diagonal hatch, because section 23 forbids colour as
 * the only carrier of a status. `disabled` is deliberately absent — it is an
 * opacity, not a tone, and giving it a colour would make it look like a state
 * the system is in rather than a control the operator cannot use.
 */
export type Tone = 'ok' | 'warn' | 'err' | 'info' | 'active' | 'neutral' | 'stale' | 'unavailable';

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
    // A run phase, not a run status: inference is over and the platform is
    // still finalizing, which is still moving.
    case 'Finalizing':
      return 'active';
    case 'Cancelled':
      return 'warn';
    case 'Stale':
      return 'stale';
    case 'Unavailable':
      return 'unavailable';
    default:
      return 'neutral';
  }
}

export function labelForStatus(status: string | null | undefined): string {
  switch (status) {
    case 'NotQueued': return 'Not queued';
    case 'Stale': return 'Stale';
    case 'Unavailable': return 'Unavailable';
    case 'Unreviewed': return 'Unreviewed';
    case undefined:
    case null:
    case '': return 'Unknown';
    default: return status;
  }
}

/** The operator's name for a run that failed while being finalized. */
export const FINALIZATION_FAILED_LABEL = 'Finalization failed';

export function isActiveStatus(status: string | null | undefined): boolean {
  return status === 'Queued' || status === 'Processing' || status === 'Running';
}

export function isVideoStatus(value: string): value is VideoStatus {
  return (VIDEO_STATUSES as readonly string[]).includes(value);
}
