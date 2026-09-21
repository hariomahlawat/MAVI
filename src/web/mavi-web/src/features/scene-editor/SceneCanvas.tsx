import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type RefObject,
} from 'react';
import type { ScenePoint } from '../../api/scene';
import { SCENE_LIMITS } from '../../api/scene';
import { contentRect, isInsideFrame, projectPoint, unprojectPoint, type PixelRect } from '../../shared/evidence/projection';
import { aToBNormal, alongLine, bToANormal, midpoint } from './lineDirection';
import type { Drawing, EditorTool, Selection } from './editorState';
import type { DraftTripLine, DraftZone, SceneDraft } from './sceneDraft';

type Props = {
  draft: SceneDraft;
  tool: EditorTool;
  selection: Selection;
  drawing: Drawing;
  /** Read-only while a historical revision is on screen. */
  readOnly?: boolean;
  videoSrc: string | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  /** Intrinsic frame size, used until the media reports its own. */
  frameWidth: number;
  frameHeight: number;
  seekToMs: number | null;
  /** Keys of objects the browser already knows are invalid. */
  invalidKeys: ReadonlySet<string>;
  overlay: ReactNode;
  onMediaFailed?: (failed: boolean) => void;
  onFrameClick?: (point: ScenePoint) => void;
  onCloseZone?: () => void;
  onSelect?: (selection: Selection) => void;
  onMoveVertex?: (key: string, vertexIndex: number, point: ScenePoint) => void;
  onMoveEndpoint?: (key: string, endpoint: 'a' | 'b', point: ScenePoint) => void;
};

type Drag =
  | { kind: 'vertex'; key: string; vertexIndex: number }
  | { kind: 'endpoint'; key: string; endpoint: 'a' | 'b' };

/** How near the first vertex a click has to be, in rendered pixels, to close a polygon. */
const CLOSE_RADIUS_PX = 12;

/**
 * The spatial working surface: the reference frame with the scene drawn over it.
 *
 * The video fills this element exactly and is letterboxed inside it by
 * `object-fit: contain`, so the element box and the media box are the same
 * rectangle and `contentRect` describes where the image really sits. Geometry
 * is projected through that rectangle, the same one the evidence player uses,
 * so a zone drawn here is evaluated where it was drawn.
 *
 * Media transport lives below the frame rather than on it. The canvas is for
 * space, and scrubbing a video should never be a click that edits geometry.
 */
export default function SceneCanvas({
  draft,
  tool,
  selection,
  drawing,
  readOnly = false,
  videoSrc,
  videoRef,
  frameWidth,
  frameHeight,
  seekToMs,
  invalidKeys,
  overlay,
  onMediaFailed,
  onFrameClick,
  onCloseZone,
  onSelect,
  onMoveVertex,
  onMoveEndpoint,
}: Props) {
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const [box, setBox] = useState<PixelRect>({ x: 0, y: 0, width: 0, height: 0 });
  const [frame, setFrame] = useState<PixelRect>({ x: 0, y: 0, width: 0, height: 0 });
  const [pointer, setPointer] = useState<ScenePoint | null>(null);
  const [nearFirstVertex, setNearFirstVertex] = useState(false);

  // Overlay geometry follows the rendered surface, which the video fills exactly.
  const measure = useCallback(() => {
    const surface = surfaceRef.current;
    if (!surface) return;
    const width = surface.clientWidth;
    const height = surface.clientHeight;
    const video = videoRef.current;
    const intrinsicWidth = video?.videoWidth || frameWidth;
    const intrinsicHeight = video?.videoHeight || frameHeight;
    setBox({ x: 0, y: 0, width, height });
    setFrame(contentRect(width, height, intrinsicWidth, intrinsicHeight));
  }, [frameWidth, frameHeight, videoRef]);

  useLayoutEffect(() => {
    measure();
    const surface = surfaceRef.current;
    if (!surface) return;
    const video = videoRef.current;
    // The intrinsic size only arrives with the metadata, so re-measure then.
    video?.addEventListener('loadedmetadata', measure);
    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(measure);
      observer.observe(surface);
    } else {
      window.addEventListener('resize', measure);
    }
    return () => {
      video?.removeEventListener('loadedmetadata', measure);
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [measure, videoSrc, videoRef]);

  useEffect(() => {
    onMediaFailed?.(false);
  }, [videoSrc, onMediaFailed]);

  useEffect(() => {
    if (drawing.kind === 'none') {
      setPointer(null);
      setNearFirstVertex(false);
    }
  }, [drawing.kind]);

  // Seek to the revision's own reference instant when one is persisted.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || seekToMs === null) return;
    let active = true;
    const apply = () => {
      if (!active) return;
      const duration = Number.isFinite(video.duration) ? video.duration : Number.POSITIVE_INFINITY;
      const seconds = Math.max(0, seekToMs / 1000);
      video.currentTime = Number.isFinite(duration) ? Math.min(seconds, Math.max(0, duration - 0.001)) : seconds;
    };
    if (video.readyState >= 1) apply();
    else video.addEventListener('loadedmetadata', apply, { once: true });
    return () => {
      active = false;
      video.removeEventListener('loadedmetadata', apply);
    };
  }, [seekToMs, videoSrc, videoRef]);

  const pixelFromEvent = useCallback((event: ReactPointerEvent<Element>) => {
    const surface = surfaceRef.current;
    if (!surface) return null;
    const rect = surface.getBoundingClientRect();
    // The rectangle is the border box; the overlay and the video are laid out
    // in the content box, which the surface's border insets by clientLeft and
    // clientTop. Measuring in one space and drawing in the other would place
    // every vertex a border-width away from the pixel that was clicked.
    return {
      x: event.clientX - rect.left - surface.clientLeft,
      y: event.clientY - rect.top - surface.clientTop,
    };
  }, []);

  const firstVertexPixel = useCallback(() => {
    if (drawing.kind !== 'zone' || drawing.vertices.length < SCENE_LIMITS.minimumZoneVertices) return null;
    return projectPoint(drawing.vertices[0].x, drawing.vertices[0].y, frame);
  }, [drawing, frame]);

  const handleSurfacePointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (readOnly || tool === 'select') return;
    const pixel = pixelFromEvent(event);
    if (!pixel) return;
    // A click on a letterbox bar is not a click on the image.
    if (!isInsideFrame(pixel.x, pixel.y, frame)) return;
    event.preventDefault();

    // Clicking the first vertex closes the polygon, which is the gesture the
    // preview has been advertising.
    const first = firstVertexPixel();
    if (first && Math.hypot(pixel.x - first.x, pixel.y - first.y) <= CLOSE_RADIUS_PX) {
      onCloseZone?.();
      return;
    }

    onFrameClick?.(unprojectPoint(pixel.x, pixel.y, frame));
  }, [readOnly, tool, pixelFromEvent, frame, firstVertexPixel, onCloseZone, onFrameClick]);

  const handleSurfacePointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    const pixel = pixelFromEvent(event);
    if (!pixel) return;

    if (drag) {
      // A drag that began on the image stays on it: the point is clamped rather
      // than abandoned when the pointer wanders into the letterbox or off the
      // window entirely.
      const point = unprojectPoint(pixel.x, pixel.y, frame);
      if (drag.kind === 'vertex') onMoveVertex?.(drag.key, drag.vertexIndex, point);
      else onMoveEndpoint?.(drag.key, drag.endpoint, point);
      return;
    }

    if (drawing.kind === 'none') return;
    const inside = isInsideFrame(pixel.x, pixel.y, frame);
    setPointer(inside ? unprojectPoint(pixel.x, pixel.y, frame) : null);
    const first = firstVertexPixel();
    setNearFirstVertex(Boolean(inside && first && Math.hypot(pixel.x - first.x, pixel.y - first.y) <= CLOSE_RADIUS_PX));
  }, [pixelFromEvent, frame, drawing.kind, firstVertexPixel, onMoveVertex, onMoveEndpoint]);

  const endDrag = useCallback((event: ReactPointerEvent<Element>) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    const target = event.currentTarget;
    if (target instanceof Element && target.hasPointerCapture?.(event.pointerId)) {
      target.releasePointerCapture(event.pointerId);
    }
  }, []);

  const startDrag = useCallback((event: ReactPointerEvent<SVGElement>, drag: Drag) => {
    if (readOnly || tool !== 'select') return;
    event.stopPropagation();
    event.preventDefault();
    dragRef.current = drag;
    // Capture on the surface, which is where the move and up handlers live, so
    // the drag survives the pointer leaving the handle or the window and the
    // matching up event is guaranteed. No listener outlives the gesture.
    surfaceRef.current?.setPointerCapture?.(event.pointerId);
    if (drag.kind === 'vertex') onSelect?.({ kind: 'zone', key: drag.key, vertexIndex: drag.vertexIndex });
    else onSelect?.({ kind: 'line', key: drag.key, endpoint: drag.endpoint });
  }, [readOnly, tool, onSelect]);

  const project = useCallback((point: ScenePoint) => projectPoint(point.x, point.y, frame), [frame]);
  const hasSurface = box.width > 0 && box.height > 0;

  return (
    <div
      className={[
        'scene-stage__surface',
        readOnly ? 'is-readonly' : '',
        drawing.kind !== 'none' ? 'is-drawing' : '',
        `tool-${tool}`,
      ].filter(Boolean).join(' ')}
      ref={surfaceRef}
      onPointerDown={handleSurfacePointerDown}
      onPointerMove={handleSurfacePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      data-testid="scene-canvas"
      data-frame={`${frame.x},${frame.y},${frame.width},${frame.height}`}
    >
      {videoSrc ? (
        <video
          key={videoSrc}
          ref={videoRef}
          className="scene-stage__video"
          src={videoSrc}
          preload="metadata"
          playsInline
          aria-label="Reference frame video"
          onError={() => onMediaFailed?.(true)}
        >
          Your browser does not support HTML video playback.
        </video>
      ) : (
        <div className="scene-stage__placeholder" aria-hidden="true" />
      )}

      {hasSurface ? (
        <svg
          className="scene-stage__overlay"
          viewBox={`0 0 ${box.width} ${box.height}`}
          width={box.width}
          height={box.height}
          aria-hidden="true"
          data-testid="scene-overlay"
        >
          {draft.zones.map((zone) => (
            <ZoneShape
              key={zone.key}
              zone={zone}
              project={project}
              selected={selection.kind === 'zone' && selection.key === zone.key}
              selectedVertex={selection.kind === 'zone' && selection.key === zone.key ? selection.vertexIndex : null}
              invalid={invalidKeys.has(zone.key)}
              readOnly={readOnly}
              tool={tool}
              onSelect={() => onSelect?.({ kind: 'zone', key: zone.key, vertexIndex: null })}
              onVertexPointerDown={(event, vertexIndex) => startDrag(event, { kind: 'vertex', key: zone.key, vertexIndex })}
            />
          ))}

          {draft.tripLines.map((line) => (
            <LineShape
              key={line.key}
              line={line}
              project={project}
              selected={selection.kind === 'line' && selection.key === line.key}
              selectedEndpoint={selection.kind === 'line' && selection.key === line.key ? selection.endpoint : null}
              invalid={invalidKeys.has(line.key)}
              readOnly={readOnly}
              tool={tool}
              onSelect={() => onSelect?.({ kind: 'line', key: line.key, endpoint: null })}
              onEndpointPointerDown={(event, endpoint) => startDrag(event, { kind: 'endpoint', key: line.key, endpoint })}
            />
          ))}

          <DrawingPreview
            drawing={drawing}
            pointer={pointer}
            nearFirstVertex={nearFirstVertex}
            project={project}
          />
        </svg>
      ) : null}

      {overlay}
    </div>
  );
}

type Projector = (point: ScenePoint) => { x: number; y: number };

/** The visible marker, and the larger area a pointer may grab it by. */
const HANDLE_R = 3.5;
const HANDLE_HIT_R = 11;

function ZoneShape({
  zone,
  project,
  selected,
  selectedVertex,
  invalid,
  readOnly,
  tool,
  onSelect,
  onVertexPointerDown,
}: {
  zone: DraftZone;
  project: Projector;
  selected: boolean;
  selectedVertex: number | null;
  invalid: boolean;
  readOnly: boolean;
  tool: EditorTool;
  onSelect: () => void;
  onVertexPointerDown: (event: ReactPointerEvent<SVGElement>, vertexIndex: number) => void;
}) {
  const points = zone.vertices.map(project);
  const classes = [
    'scene-zone',
    selected ? 'is-selected' : '',
    zone.enabled ? '' : 'is-disabled',
    invalid ? 'is-invalid' : '',
  ].filter(Boolean).join(' ');

  return (
    <g className={classes} data-testid={`scene-zone-${zone.key}`}>
      <polygon
        points={points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')}
        onPointerDown={(event) => {
          // With a drawing tool armed the click belongs to the surface: a zone
          // drawn over or inside an existing one must still be drawable.
          if (readOnly || tool !== 'select') return;
          event.stopPropagation();
          onSelect();
        }}
      />
      {selected && !readOnly
        ? points.map((point, index) => (
          <g key={`${zone.key}-vertex-${index}`} className={`scene-handle${selectedVertex === index ? ' is-selected' : ''}`}>
            <circle
              className="scene-handle__hit"
              cx={point.x}
              cy={point.y}
              r={HANDLE_HIT_R}
              onPointerDown={(event) => onVertexPointerDown(event, index)}
            />
            <circle className="scene-handle__mark" cx={point.x} cy={point.y} r={HANDLE_R} />
          </g>
        ))
        : null}
    </g>
  );
}

function LineShape({
  line,
  project,
  selected,
  selectedEndpoint,
  invalid,
  readOnly,
  tool,
  onSelect,
  onEndpointPointerDown,
}: {
  line: DraftTripLine;
  project: Projector;
  selected: boolean;
  selectedEndpoint: 'a' | 'b' | null;
  invalid: boolean;
  readOnly: boolean;
  tool: EditorTool;
  onSelect: () => void;
  onEndpointPointerDown: (event: ReactPointerEvent<SVGElement>, endpoint: 'a' | 'b') => void;
}) {
  const a = project(line.a);
  const b = project(line.b);
  const centre = project(midpoint(line.a, line.b));
  // The normal is taken in the space the line is drawn in. Projection scales x
  // and y by different amounts, so a normal computed in normalised space and
  // used as a pixel offset would sit visibly off the perpendicular for any
  // line that is not axis-aligned. Projection is a positive axis-aligned
  // scaling, so the side the normal points to is unchanged: this stays the
  // side the engine calls A to B.
  const toB = aToBNormal(a, b);
  const toA = bToANormal(a, b);
  const along = alongLine(a, b);
  const classes = [
    'scene-line',
    selected ? 'is-selected' : '',
    line.enabled ? '' : 'is-disabled',
    invalid ? 'is-invalid' : '',
  ].filter(Boolean).join(' ');

  // Two different things, never conflated: the orientation A to B runs *along*
  // the segment, while a crossing direction runs *across* it.
  const arrow = 22;
  // Crossing indicators assert that direction matters. On an undirected line it
  // does not — both ways count the same — so drawing them there would state
  // something false about the line.
  const showCrossings = line.directed;

  return (
    <g className={classes} data-testid={`scene-line-${line.key}`}>
      <line
        className="scene-line__segment"
        x1={a.x}
        y1={a.y}
        x2={b.x}
        y2={b.y}
        onPointerDown={(event) => {
          if (readOnly || tool !== 'select') return;
          event.stopPropagation();
          onSelect();
        }}
      />

      {along ? (
        <>
          <text className="scene-line__endpoint" x={a.x - along.x * 12} y={a.y - along.y * 12}>A</text>
          <text className="scene-line__endpoint" x={b.x + along.x * 12} y={b.y + along.y * 12}>B</text>
        </>
      ) : null}

      {showCrossings && toB ? (
        <g className="scene-line__crossing scene-line__crossing--atob" data-testid={`scene-line-atob-${line.key}`}>
          <line x1={centre.x} y1={centre.y} x2={centre.x + toB.x * arrow} y2={centre.y + toB.y * arrow} />
          <polygon
            points={arrowHead(centre.x + toB.x * arrow, centre.y + toB.y * arrow, toB.x, toB.y)}
          />
          {selected ? (
            <text x={centre.x + toB.x * (arrow + 14)} y={centre.y + toB.y * (arrow + 14)}>{line.aToBLabel}</text>
          ) : null}
        </g>
      ) : null}
      {showCrossings && toA ? (
        <g className="scene-line__crossing scene-line__crossing--btoa" data-testid={`scene-line-btoa-${line.key}`}>
          <line x1={centre.x} y1={centre.y} x2={centre.x + toA.x * arrow} y2={centre.y + toA.y * arrow} />
          <polygon
            points={arrowHead(centre.x + toA.x * arrow, centre.y + toA.y * arrow, toA.x, toA.y)}
          />
          {selected ? (
            <text x={centre.x + toA.x * (arrow + 14)} y={centre.y + toA.y * (arrow + 14)}>{line.bToALabel}</text>
          ) : null}
        </g>
      ) : null}

      {selected && !readOnly ? (
        <>
          <g className={`scene-handle${selectedEndpoint === 'a' ? ' is-selected' : ''}`}>
            <circle
              className="scene-handle__hit"
              cx={a.x}
              cy={a.y}
              r={HANDLE_HIT_R}
              onPointerDown={(event) => onEndpointPointerDown(event, 'a')}
            />
            <circle className="scene-handle__mark" cx={a.x} cy={a.y} r={HANDLE_R} />
          </g>
          <g className={`scene-handle${selectedEndpoint === 'b' ? ' is-selected' : ''}`}>
            <circle
              className="scene-handle__hit"
              cx={b.x}
              cy={b.y}
              r={HANDLE_HIT_R}
              onPointerDown={(event) => onEndpointPointerDown(event, 'b')}
            />
            <circle className="scene-handle__mark" cx={b.x} cy={b.y} r={HANDLE_R} />
          </g>
        </>
      ) : null}
    </g>
  );
}

/** A small filled head at the tip of a direction indicator. */
function arrowHead(x: number, y: number, dx: number, dy: number): string {
  const size = 5;
  const nx = -dy;
  const ny = dx;
  return [
    `${x + dx * size},${y + dy * size}`,
    `${x - dx * size + nx * size * 0.7},${y - dy * size + ny * size * 0.7}`,
    `${x - dx * size - nx * size * 0.7},${y - dy * size - ny * size * 0.7}`,
  ].join(' ');
}

function DrawingPreview({
  drawing,
  pointer,
  nearFirstVertex,
  project,
}: {
  drawing: Drawing;
  pointer: ScenePoint | null;
  nearFirstVertex: boolean;
  project: Projector;
}) {
  if (drawing.kind === 'zone' && drawing.vertices.length > 0) {
    const points = drawing.vertices.map(project);
    const last = points[points.length - 1];
    const cursor = pointer ? project(pointer) : null;
    const closeable = drawing.vertices.length >= SCENE_LIMITS.minimumZoneVertices;
    return (
      <g className="scene-drawing" data-testid="scene-drawing">
        <polyline points={points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')} />
        {cursor ? (
          <line className="scene-drawing__lead" x1={last.x} y1={last.y} x2={cursor.x} y2={cursor.y} />
        ) : null}
        {closeable && cursor ? (
          <line className="scene-drawing__close" x1={cursor.x} y1={cursor.y} x2={points[0].x} y2={points[0].y} />
        ) : null}
        {points.map((point, index) => (
          <circle
            key={`draw-${index}`}
            className={index === 0 && closeable && nearFirstVertex ? 'scene-drawing__anchor is-armed' : 'scene-drawing__anchor'}
            cx={point.x}
            cy={point.y}
            r={index === 0 && closeable ? 6 : 3.5}
          />
        ))}
      </g>
    );
  }

  if (drawing.kind === 'line') {
    const a = project(drawing.a);
    const cursor = pointer ? project(pointer) : null;
    return (
      <g className="scene-drawing" data-testid="scene-drawing">
        {cursor ? <line className="scene-drawing__lead" x1={a.x} y1={a.y} x2={cursor.x} y2={cursor.y} /> : null}
        <circle className="scene-drawing__anchor" cx={a.x} cy={a.y} r={3.5} />
      </g>
    );
  }

  return null;
}
