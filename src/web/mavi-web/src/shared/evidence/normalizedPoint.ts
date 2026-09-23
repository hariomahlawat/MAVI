/**
 * The frozen normalised-coordinate rule, mirrored for the browser.
 *
 * The authority is `NormalizedPoint` in the Domain: a component is valid when it
 * is finite and, once rounded to the persisted six decimals, lies within the
 * closed interval [0, 1]. That is the rule the application decoder applies
 * before a trajectory may produce any analytical fact, so it is the rule the
 * browser has to apply before drawing the same sealed evidence. Anything else
 * lets the two disagree about one artefact.
 *
 * This is the single frontend definition. Evidence code imports it rather than
 * re-deriving a bound, because two range rules eventually become two answers.
 *
 * Rounding is written out rather than replaced by a ±5e-7 tolerance so the
 * correspondence with the Domain is visible to a reader. Ties go to even, as
 * they do in .NET. The tie itself is not load-bearing here — it can only change
 * the verdict for a coordinate whose seventh decimal is exactly 5 — but
 * matching the stated rule is cheaper than explaining why a shortcut is
 * equivalent.
 */

/** Decimal places the scene persists a coordinate to. */
export const SCENE_COORDINATE_DECIMALS = 6;

const SCALE = 10 ** SCENE_COORDINATE_DECIMALS;

/** Rounds a raw component to the persisted precision, ties to even. */
export function roundToScenePrecision(value: number): number {
  if (!Number.isFinite(value)) return value;

  const scaled = value * SCALE;
  const lower = Math.floor(scaled);
  const remainder = scaled - lower;

  let units: number;
  if (remainder > 0.5) units = lower + 1;
  else if (remainder < 0.5) units = lower;
  else units = lower % 2 === 0 ? lower : lower + 1;

  const rounded = units / SCALE;

  // A coordinate a hair below zero rounds to negative zero, which would show a
  // sign nothing drew. It compares equal to zero, so normalising costs nothing.
  return rounded === 0 ? 0 : rounded;
}

/** True when a raw component is finite and inside the unit interval once rounded. */
export function isInSceneRange(value: number): boolean {
  if (!Number.isFinite(value)) return false;
  const rounded = roundToScenePrecision(value);
  return rounded >= 0 && rounded <= 1;
}
