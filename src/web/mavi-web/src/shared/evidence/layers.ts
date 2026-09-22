import type { ReactNode } from 'react';
import type { PixelRect } from './projection';

/**
 * One piece of spatial evidence, described for someone who cannot see the stage.
 *
 * The overlay is drawn as SVG and is hidden from assistive technology, because
 * narrating raw geometry helps nobody. The specification still requires spatial
 * content to have an accessible twin naming each object, its state and its
 * coordinates, so a layer that draws something describes it here — from the
 * same evidence it draws from, never a second invented dataset.
 */
export type EvidenceDescription = {
  id: string;
  /** What the object is. */
  label: string;
  /** Its state and its coordinates, in operator wording. */
  detail: string;
};

/**
 * One evidence overlay layer.
 *
 * A small typed record rather than a plugin framework. The player owns whether
 * a layer is visible and draws the visible ones into one stage aligned to the
 * video's content rectangle; the layer itself only says what it is called,
 * whether there is anything to draw, and how to draw it.
 *
 * This is what stops the generic player growing a boolean per evidence kind.
 * Slice 5 adds scene geometry by supplying another layer, not by editing the
 * media controller.
 */
export type EvidenceLayer = {
  id: string;
  /** The visible control label, which is also the control's accessible name. */
  label: string;
  /**
   * Whether there is evidence to draw. A layer with nothing to show is offered
   * as a disabled control with its reason stated beside it, rather than
   * silently missing — "unavailable" and "empty" are different facts.
   */
  available: boolean;
  /** Why the layer is unavailable, in operator wording. Shown next to the control. */
  unavailableReason?: string;
  /** Whether the layer starts visible when the operator has expressed no preference. */
  defaultVisible?: boolean;
  /** Draw into the stage. `frame` is the true video content rectangle. */
  render: (frame: PixelRect, currentOffsetMs: number) => ReactNode;
  /**
   * The accessible twin of what this layer draws.
   *
   * Coordinates given here are **normalised source-frame** values, not
   * projected pixels: a pixel position describes the viewport the operator
   * happens to have, while the normalised position is the evidence itself and
   * is the same on every screen.
   *
   * A layer that draws an unbounded number of objects summarises rather than
   * listing every one, because an accessibility tree with ten thousand entries
   * in it is not accessible.
   */
  describe?: (currentOffsetMs: number) => readonly EvidenceDescription[];
};

const STORAGE_PREFIX = 'mavi.evidence.layers.';

/**
 * Layer visibility the operator chose, per player scope.
 *
 * Kept locally because it is a per-operator working preference, not evidence.
 * Storage can be unavailable or blocked, so every read and write tolerates
 * throwing and the player renders correctly with nothing stored.
 */
export function readLayerPreferences(scope: string): Record<string, boolean> {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + scope);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const result: Record<string, boolean> = {};
    for (const [key, value] of Object.entries(parsed)) {
      if (typeof value === 'boolean') result[key] = value;
    }
    return result;
  } catch {
    return {};
  }
}

export function writeLayerPreferences(scope: string, preferences: Record<string, boolean>): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + scope, JSON.stringify(preferences));
  } catch {
    // Losing a display preference is harmless.
  }
}

/** Whether a layer draws right now: available, and not switched off. */
export function isLayerVisible(layer: EvidenceLayer, preferences: Record<string, boolean>): boolean {
  if (!layer.available) return false;
  return preferences[layer.id] ?? layer.defaultVisible ?? true;
}
