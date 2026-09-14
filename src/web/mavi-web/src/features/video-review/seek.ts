export function calculateReviewSeekSeconds(
  startOffsetMs: number,
  mediaDurationSeconds?: number,
): number {
  if (!Number.isFinite(startOffsetMs) || startOffsetMs < 0) return 0;

  let target = Math.max(0, startOffsetMs / 1000 - 1);
  if (mediaDurationSeconds !== undefined && Number.isFinite(mediaDurationSeconds) && mediaDurationSeconds >= 0) {
    const epsilon = mediaDurationSeconds > 0 ? 0.001 : 0;
    target = Math.min(target, Math.max(0, mediaDurationSeconds - epsilon));
  }
  return target;
}

export function seekVideoToTrack(video: HTMLVideoElement, startOffsetMs: number): void {
  const duration = Number.isFinite(video.duration) ? video.duration : undefined;
  video.currentTime = calculateReviewSeekSeconds(startOffsetMs, duration);
}
