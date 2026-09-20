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

/**
 * A rendered pixel position converted back into normalised source-frame
 * coordinates: the inverse of {@link projectPoint}.
 *
 * The editor needs this to turn a pointer position into geometry. Measuring
 * against the element instead of the frame would put every drawn point in the
 * wrong place whenever the video is letterboxed, so the conversion uses the
 * same content rectangle the overlay draws against.
 *
 * The result is clamped to the unit interval, so a pointer that leaves the
 * frame mid-drag keeps the vertex on the nearest edge rather than producing a
 * coordinate the scene model would reject. Use {@link isInsideFrame} first when
 * a position outside the frame should be ignored rather than clamped.
 */
export function unprojectPoint(x: number, y: number, frame: PixelRect): { x: number; y: number } {
  if (!Number.isFinite(x) || !Number.isFinite(y) || frame.width <= 0 || frame.height <= 0) {
    return { x: 0, y: 0 };
  }
  return {
    x: clampUnit((x - frame.x) / frame.width),
    y: clampUnit((y - frame.y) / frame.height),
  };
}

/** True when a rendered pixel position falls on the frame rather than a letterbox bar. */
export function isInsideFrame(x: number, y: number, frame: PixelRect): boolean {
  if (!Number.isFinite(x) || !Number.isFinite(y) || frame.width <= 0 || frame.height <= 0) return false;
  return x >= frame.x && x <= frame.x + frame.width && y >= frame.y && y <= frame.y + frame.height;
}

function clampUnit(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}
