import type { EvidenceLayer } from '../../shared/evidence/layers';
import type { ReactNode } from 'react';
import { projectPoint, type PixelRect } from '../../shared/evidence/projection';
import { aToBNormal, arrowHead, bToANormal } from '../scene-editor/lineDirection';
import type { TrackAnalyticsEvidenceModel } from './analyticsEvidence';

/**
 * The spatial analytical overlays: the zones and trip lines of the pinned
 * revision, and the points where this Track crossed a line.
 *
 * Everything drawn here comes from the pinned revision or from a persisted
 * fact. No geometry is inferred and no fact is recomputed: a zone is drawn
 * because the revision contains it, and a crossing glyph sits where the engine
 * said the crossing was, not where a browser-side intersection would put it.
 *
 * **Matched geometry is not distinguished by colour.** A zone this Track
 * visited keeps the same frozen `--geo-zone` role as one it did not, and is
 * marked by a thicker stroke and a halo instead, so the distinction survives
 * colour-vision differences and low-contrast footage. Disabled geometry keeps
 * the dashed neutral grammar the Scene Editor already uses, and can never be
 * drawn as matched — the engine did not evaluate it, so no fact can have come
 * from it.
 */

/**
 * Draw once per content rectangle, not once per playhead tick.
 *
 * The player calls `render(frame, currentOffsetMs)` on every animation frame
 * while the media plays, but none of the analytical geometry moves with the
 * media: a zone is where it was. A valid scene may hold 64 zones of 64
 * vertices, so projecting all of them sixty times a second would spend a
 * quarter of a million operations a second producing the identical picture.
 * The frame rectangle changes only when the element is resized, so it is the
 * whole cache key — and returning the *same* element keeps React from
 * reconciling the subtree as well.
 */
function perFrameRect(draw: (frame: PixelRect) => ReactNode): (frame: PixelRect) => ReactNode {
  let key = '';
  let drawn: ReactNode = null;
  return (frame) => {
    const next = `${frame.x}:${frame.y}:${frame.width}:${frame.height}`;
    if (next !== key) {
      key = next;
      drawn = draw(frame);
    }
    return drawn;
  };
}

function zoneLayer(model: TrackAnalyticsEvidenceModel): EvidenceLayer {
  const descriptions = model.zones.map((zone) => zone.description);
  return {
    kind: 'spatial',
    id: 'analytics-zones',
    label: 'Zones',
    available: model.zones.length > 0,
    unavailableReason: 'The pinned scene revision has no zones, or could not be loaded.',
    render: perFrameRect((frame) => (
      <>
        {model.zones.map((entry) => {
          const points = entry.zone.vertices
            .map((vertex) => projectPoint(vertex.x, vertex.y, frame))
            .map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
            .join(' ');
          return (
            <polygon
              key={entry.zone.zoneId}
              className="evidence-zone"
              data-matched={String(entry.interacted)}
              data-enabled={String(entry.zone.enabled)}
              data-testid="evidence-zone"
              points={points}
            />
          );
        })}
      </>
    )),
    // Returned, not rebuilt: the descriptions were computed once when the
    // evidence model was built, because scene geometry does not move with the
    // playhead and walking every polygon on every frame would produce the same
    // strings at a cost proportional to the whole scene.
    describe: () => descriptions,
  };
}

function lineLayer(model: TrackAnalyticsEvidenceModel): EvidenceLayer {
  const descriptions = model.lines.map((line) => line.description);
  return {
    kind: 'spatial',
    id: 'analytics-lines',
    label: 'Trip lines',
    available: model.lines.length > 0,
    unavailableReason: 'The pinned scene revision has no trip lines, or could not be loaded.',
    render: perFrameRect((frame) => (
      <>
        {model.lines.map((entry) => {
          const a = projectPoint(entry.line.a.x, entry.line.a.y, frame);
          const b = projectPoint(entry.line.b.x, entry.line.b.y, frame);
          return (
            <g
              key={entry.line.lineId}
              className="evidence-line"
              data-matched={String(entry.interacted)}
              data-enabled={String(entry.line.enabled)}
              data-testid="evidence-line"
            >
              <line className="evidence-line__segment" x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
              {/*
                A and B are letters, not colours: which end is which has to
                survive a monochrome print and a colour-vision difference. The
                direction indicator is perpendicular to the line, because that
                is the way a Track has to travel to count as a crossing — an
                arrow along A to B would show where the endpoints are instead.
              */}
              <text className="evidence-line__endpoint" x={a.x} y={a.y}>A</text>
              <text className="evidence-line__endpoint" x={b.x} y={b.y}>B</text>
              {entry.line.directed ? directionCue(entry, a, b) : null}
            </g>
          );
        })}
      </>
    )),
    describe: () => descriptions,
  };
}

/**
 * The two travel directions that count as a crossing, drawn across the line.
 *
 * **Computed in projected pixel space.** Projection scales x and y by different
 * amounts whenever the content rectangle is not square — which is most of the
 * time, since evidence video rarely matches the panel it is shown in — so a
 * normal taken in normalised coordinates and then used as a pixel offset sits
 * visibly off the perpendicular for any line that is not axis-aligned. The
 * Scene Editor already draws it this way and says so; this is the same
 * arithmetic on the same helpers, not a second one.
 *
 * Projection is a positive axis-aligned scaling, so the *side* a normal points
 * to is unchanged by it: this is still the side the engine calls A to B.
 *
 * **Direction survives without colour.** Two plain opposing rays collapse into
 * one undirected line as soon as their hues cannot be told apart, so each ray
 * carries an arrowhead and the operator's own word for that direction. The
 * letters at the ends say which end is A; these say which way is which.
 */
function directionCue(
  entry: TrackAnalyticsEvidenceModel['lines'][number],
  a: { x: number; y: number },
  b: { x: number; y: number },
) {
  const toB = aToBNormal(a, b);
  const toA = bToANormal(a, b);
  if (!toB || !toA) return null;
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const reach = 14;
  const ray = (
    direction: { x: number; y: number },
    kind: 'atob' | 'btoa',
    label: string,
  ) => {
    const tip = { x: mid.x + direction.x * reach, y: mid.y + direction.y * reach };
    return (
      <g className={`evidence-line__dir evidence-line__dir--${kind}`} data-testid={`evidence-line-${kind}`}>
        <line x1={mid.x} y1={mid.y} x2={tip.x} y2={tip.y} />
        <polygon points={arrowHead(tip.x, tip.y, direction.x, direction.y)} />
        <text x={mid.x + direction.x * (reach + 12)} y={mid.y + direction.y * (reach + 12)}>{label}</text>
      </g>
    );
  };
  return (
    <>
      {ray(toB, 'atob', entry.line.aToBLabel || 'A → B')}
      {ray(toA, 'btoa', entry.line.bToALabel || 'B → A')}
    </>
  );
}

function crossingLayer(model: TrackAnalyticsEvidenceModel): EvidenceLayer {
  const descriptions = model.crossings.map((crossing) => crossing.description);
  return {
    kind: 'spatial',
    // "Crossings", not "Events": a persisted line crossing is a geometric fact
    // this slice can draw, and calling it an event would borrow vocabulary from
    // the behaviour records a later stage defines.
    id: 'analytics-crossings',
    label: 'Crossings',
    available: model.crossings.length > 0,
    unavailableReason: 'This Track has no persisted line crossing.',
    render: perFrameRect((frame) => (
      <>
        {model.crossings.map((crossing) => {
          const p = projectPoint(crossing.x, crossing.y, frame);
          const size = 6;
          return (
            <g
              key={crossing.id}
              className="evidence-crossing"
              data-direction={crossing.direction}
              data-testid="evidence-crossing"
            >
              {/*
                A diamond, not a disc: the shape is what distinguishes a
                crossing from the trajectory's sample discs and from the
                direction arrows when hue does not.
              */}
              <polygon
                className="evidence-crossing__glyph"
                points={`${p.x},${p.y - size} ${p.x + size},${p.y} ${p.x},${p.y + size} ${p.x - size},${p.y}`}
              />
            </g>
          );
        })}
      </>
    )),
    describe: () => descriptions,
  };
}

/**
 * Every analytical spatial layer, in drawing order.
 *
 * Zones first so their fills sit under the lines, lines under the crossing
 * glyphs, and all of them under the Track's own bounding box and trajectory —
 * the raw evidence stays on top, because the analytical context exists to be
 * read against it rather than over it.
 */
export function analyticsLayers(model: TrackAnalyticsEvidenceModel): EvidenceLayer[] {
  return [zoneLayer(model), lineLayer(model), crossingLayer(model)];
}
