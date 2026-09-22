import type { ReactNode } from 'react';
import type { PixelRect } from './projection';

/**
 * One piece of spatial evidence, named for an operator who cannot see the stage.
 *
 * This is not a second, parallel representation of the overlay: it is the
 * accessible description carried by the *same* layer object the operator
 * toggles, and the player binds it to that layer's own visible control. The raw
 * SVG stays hidden from assistive technology because narrating geometry helps
 * nobody; what is narrated is the evidence, from the data the layer draws from.
 *
 * A description states what the object is and where it is. It deliberately does
 * **not** state whether it is on screen: whether something is drawn depends on
 * the operator's layer preference as well as on the evidence, and only the
 * player knows both. A layer reports applicability — whether it has anything to
 * assert at this playhead — and the player composes the one sentence that says
 * what is actually drawn. Two independent sentences would eventually disagree.
 */
export type EvidenceDescription = {
  id: string;
  /** What the object is. */
  label: string;
  /** Where it is and what kind of position it is, in operator wording. */
  detail: string;
  /** Whether this object asserts anything at the current playhead. */
  appliesNow: boolean;
  /**
   * Why it does not, as a clause that completes "Not drawn here: …" — for
   * example `the playhead is away from the frame it describes`.
   */
  inapplicableReason?: string;
};

type EvidenceLayerBase = {
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

/**
 * A layer that draws spatial content, which section 23 requires to carry an
 * accessible equivalent. `describe` is **required**, not optional: a layer that
 * could draw geometry without supplying its semantics would be a conformance
 * hole the type system was quietly holding open.
 *
 * Coordinates given here are **normalised source-frame** values, not projected
 * pixels: a pixel position describes the viewport the operator happens to have,
 * while the normalised position is the evidence itself and is the same on every
 * screen. A layer drawing an unbounded number of objects summarises rather than
 * listing every one, because an accessibility tree with ten thousand entries in
 * it is not accessible.
 */
export type SpatialEvidenceLayer = EvidenceLayerBase & {
  kind: 'spatial';
  describe: (currentOffsetMs: number) => readonly EvidenceDescription[];
};

/**
 * A layer that draws nothing spatial — a matte, a tint, a frame treatment.
 * It has no objects and no coordinates, so there is nothing to name beyond the
 * control's own label, and supplying descriptions is refused rather than ignored.
 */
export type NonSpatialEvidenceLayer = EvidenceLayerBase & {
  kind: 'non-spatial';
  describe?: never;
};

/**
 * One evidence overlay layer.
 *
 * A small discriminated union rather than a plugin framework. The player owns
 * whether a layer is visible and draws the visible ones into one stage aligned
 * to the video's content rectangle; the layer itself says what it is called,
 * whether there is anything to draw, how to draw it, and — when it draws
 * spatial content — what that content is.
 *
 * This is what stops the generic player growing a boolean per evidence kind.
 * Slice 5 adds scene geometry by supplying another layer, not by editing the
 * media controller, and cannot do so without its accessible equivalent.
 */
export type EvidenceLayer = SpatialEvidenceLayer | NonSpatialEvidenceLayer;

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

/**
 * What the operator's layer preference says about a layer.
 *
 * This is the generic half of layer state and belongs to the player: it knows
 * about availability and about the toggle, and about nothing else. Whether the
 * evidence applies at this playhead is the layer's own business, and the two
 * are kept apart so that no code path can announce both "enabled" and "not
 * applicable" as if they answered the same question.
 */
export type LayerPreferenceState = 'enabled' | 'hidden' | 'unavailable';

export function layerPreferenceState(
  layer: EvidenceLayer,
  preferences: Record<string, boolean>,
): LayerPreferenceState {
  if (!layer.available) return 'unavailable';
  return (preferences[layer.id] ?? layer.defaultVisible ?? true) ? 'enabled' : 'hidden';
}

/** Whether a layer draws right now: available, and not switched off. */
export function isLayerVisible(layer: EvidenceLayer, preferences: Record<string, boolean>): boolean {
  return layerPreferenceState(layer, preferences) === 'enabled';
}

/**
 * The preference half of the announcement: what the operator has done with this
 * layer. It never claims anything about the frame — "enabled" is a statement
 * about a toggle, not about whether a box is on screen at this instant.
 */
export function layerPreferenceSentence(state: LayerPreferenceState): string {
  switch (state) {
    case 'enabled': return 'Layer enabled.';
    case 'hidden': return 'Layer hidden by operator.';
    default: return 'Layer unavailable.';
  }
}

/**
 * The drawing half, composed from both facts at once.
 *
 * Something is drawn only when the operator has the layer on *and* the evidence
 * applies here. Computing the sentence from the pair is what makes "Layer
 * enabled." beside "Not drawn here: …" a coherent pair of statements rather
 * than a contradiction, and makes the contradiction unrepresentable.
 */
export function evidenceDrawSentence(state: LayerPreferenceState, item: EvidenceDescription): string {
  const because = item.inapplicableReason ?? 'it does not apply at the current position';
  if (state !== 'enabled') {
    return item.appliesNow
      ? 'Not drawn: the layer is switched off. It applies at the current position.'
      : `Not drawn: the layer is switched off, and ${because}.`;
  }
  return item.appliesNow ? 'Drawn at the current position.' : `Not drawn here: ${because}.`;
}
