import type { TrackBoundingBox } from '../../api/tracks';

export type PixelRect = { x: number; y: number; width: number; height: number };

/**
 * Where the video frame actually sits inside a <video> element that uses
 * `object-fit: contain` (the browser default). The element box is letterboxed
 * when its aspect differs from the intrinsic frame, and a bounding box drawn
 * against the element rather than the frame would be visibly wrong.
 */
export function contentRect(
  elementWidth: number,
  elementHeight: number,
  intrinsicWidth: number,
  intrinsicHeight: number,
): PixelRect {
  if (elementWidth <= 0 || elementHeight <= 0 || intrinsicWidth <= 0 || intrinsicHeight <= 0) {
    return { x: 0, y: 0, width: Math.max(0, elementWidth), height: Math.max(0, elementHeight) };
  }
  const scale = Math.min(elementWidth / intrinsicWidth, elementHeight / intrinsicHeight);
  const width = intrinsicWidth * scale;
  const height = intrinsicHeight * scale;
  return {
    x: (elementWidth - width) / 2,
    y: (elementHeight - height) / 2,
    width,
    height,
  };
}

/** A normalised (0..1) box projected into the frame's pixel rectangle. */
export function projectBox(box: TrackBoundingBox, frame: PixelRect): PixelRect {
  return {
    x: frame.x + box.x * frame.width,
    y: frame.y + box.y * frame.height,
    width: box.width * frame.width,
    height: box.height * frame.height,
  };
}

export function projectPoint(x: number, y: number, frame: PixelRect): { x: number; y: number } {
  return { x: frame.x + x * frame.width, y: frame.y + y * frame.height };
}

/**
 * The representative box is evidence for one frame. It is shown while the
 * playhead is within a short window of that frame; further away it would claim
 * a position the detector never asserted.
 */
export const BOX_VISIBILITY_WINDOW_MS = 400;

export function isBoxVisibleAt(currentOffsetMs: number, representativeOffsetMs: number): boolean {
  return Math.abs(currentOffsetMs - representativeOffsetMs) <= BOX_VISIBILITY_WINDOW_MS;
}
