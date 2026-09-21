import type { ReactNode } from 'react';
import type { PixelRect } from './projection';

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
