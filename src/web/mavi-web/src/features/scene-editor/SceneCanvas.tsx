import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import type { ScenePoint } from '../../api/scene';
import { contentRect, isInsideFrame, projectPoint, unprojectPoint, type PixelRect } from '../video-review/overlay';
import { aToBNormal, alongLine, bToANormal, midpoint } from './lineDirection';
import type { Drawing, EditorTool, Selection } from './editorState';
import type { DraftTripLine, DraftZone, SceneDraft } from './sceneDraft';

type Props = {
  draft: SceneDraft;
  tool: EditorTool;
  selection: Selection;
  drawing: Drawing;
  /** Read-only when a historical revision is on screen. */
  readOnly?: boolean;
  videoSrc: string | null;
  /** Intrinsic frame size, used until the media reports its own. */
  frameWidth: number;
  frameHeight: number;
  seekToMs: number | null;
  onMediaFailed?: (failed: boolean) => void;
  onFrameClick?: (point: ScenePoint) => void;
  onSelect?: (selection: Selection) => void;
  onMoveVertex?: (key: string, vertexIndex: number, point: ScenePoint) => void;
  onMoveEndpoint?: (key: string, endpoint: 'a' | 'b', point: ScenePoint) => void;
};

type Drag =
  | { kind: 'vertex'; key: string; vertexIndex: number }
  | { kind: 'endpoint'; key: string; endpoint: 'a' | 'b' };

/**
 * The reference frame with the scene drawn over it.
 *
 * Geometry is projected through the same content rectangle the evidence player
 * uses, so a zone drawn here sits exactly where the engine will evaluate it
 * even when the video is letterboxed. Pointer positions travel the other way
 * through `unprojectPoint`; a click on a letterbox bar is ignored rather than
 * snapped to the nearest edge, because the operator did not click on the image.
 */
export default function SceneCanvas({
  draft,
  tool,
  selection,
  drawing,
  readOnly = false,
  videoSrc,
  frameWidth,
  frameHeight,
  seekToMs,
  onMediaFailed,
  onFrameClick,
  onSelect,
  onMoveVertex,
  onMoveEndpoint,
}: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const [box, setBox] = useState<PixelRect>({ x: 0, y: 0, width: 0, height: 0 });
  const [frame, setFrame] = useState<PixelRect>({ x: 0, y: 0, width: 0, height: 0 });
  // Where the pointer is while a shape is being drawn, for the preview segment.
  // Kept here so a pointer move re-renders the canvas and nothing else.
  const [preview, setPreview] = useState<ScenePoint | null>(null);

  // Overlay geometry follows the rendered surface, not the intrinsic frame.
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
  }, [frameWidth, frameHeight]);

  useLayoutEffect(() => {
    measure();
    const surface = surfaceRef.current;
    if (!surface) return;
    const video = videoRef.current;
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
  }, [measure, videoSrc]);

  useEffect(() => {
    onMediaFailed?.(false);
  }, [videoSrc, onMediaFailed]);

  useEffect(() => {
    if (drawing.kind === 'none') setPreview(null);
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
  }, [seekToMs, videoSrc]);

  const pixelFromEvent = useCallback((event: ReactPointerEvent<Element>) => {
    const surface = surfaceRef.current;
    if (!surface) return null;
    const rect = surface.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }, []);

  const handleSurfacePointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (readOnly || tool === 'select') return;
    const pixel = pixelFromEvent(event);
    if (!pixel) return;
    // A click on a letterbox bar is not a click on the image.
    if (!isInsideFrame(pixel.x, pixel.y, frame)) return;
    event.preventDefault();
    onFrameClick?.(unprojectPoint(pixel.x, pixel.y, frame));
  }, [readOnly, tool, pixelFromEvent, frame, onFrameClick]);

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
    setPreview(isInsideFrame(pixel.x, pixel.y, frame) ? unprojectPoint(pixel.x, pixel.y, frame) : null);
  }, [pixelFromEvent, frame, drawing.kind, onMoveVertex, onMoveEndpoint]);

  const endDrag = useCallback((event: ReactPointerEvent<Element>) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    const target = event.currentTarget;
    if (target instanceof Element && target.hasPointerCapture?.(event.pointerId)) {
      target.releasePointerCapture(event.pointerId);
    }
  }, []);

  const startDrag = useCallback((event: ReactPointerEvent<SVGElement>, drag: Drag) => {
    if (readOnly) return;
    event.stopPropagation();
    event.preventDefault();
    dragRef.current = drag;
    // Pointer capture keeps the drag alive outside the element and guarantees
    // the matching up event, so no listener outlives the gesture.
    event.currentTarget.setPointerCapture?.(event.pointerId);
    if (drag.kind === 'vertex') onSelect?.({ kind: 'zone', key: drag.key, vertexIndex: drag.vertexIndex });
    else onSelect?.({ kind: 'line', key: drag.key, endpoint: drag.endpoint });
  }, [readOnly, onSelect]);

  const project = useCallback((point: ScenePoint) => projectPoint(point.x, point.y, frame), [frame]);
  const hasSurface = box.width > 0 && box.height > 0;

  return (
    <div
      className={`scene-canvas${readOnly ? ' scene-canvas--readonly' : ''} scene-canvas--${tool}`}
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
          className="scene-canvas__video"
          src={videoSrc}
          controls
          preload="metadata"
          aria-label="Reference frame video"
          onError={() => onMediaFailed?.(true)}
        >
          Your browser does not support HTML video playback.
        </video>
      ) : (
        <div className="scene-canvas__placeholder" aria-hidden="true" />
      )}

      {hasSurface ? (
        <svg
          className="scene-canvas__overlay"
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
              readOnly={readOnly}
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
              readOnly={readOnly}
              onSelect={() => onSelect?.({ kind: 'line', key: line.key, endpoint: null })}
              onEndpointPointerDown={(event, endpoint) => startDrag(event, { kind: 'endpoint', key: line.key, endpoint })}
            />
          ))}

          <DrawingPreview drawing={drawing} pointer={preview} project={project} />
        </svg>
      ) : null}
    </div>
  );
}

type Projector = (point: ScenePoint) => { x: number; y: number };

function ZoneShape({
  zone,
  project,
  selected,
  selectedVertex,
  readOnly,
  onSelect,
  onVertexPointerDown,
}: {
  zone: DraftZone;
  project: Projector;
  selected: boolean;
  selectedVertex: number | null;
  readOnly: boolean;
  onSelect: () => void;
  onVertexPointerDown: (event: ReactPointerEvent<SVGElement>, vertexIndex: number) => void;
}) {
  const points = zone.vertices.map(project);
  const classes = [
    'scene-zone',
    selected ? 'is-selected' : '',
    zone.enabled ? '' : 'is-disabled',
  ].filter(Boolean).join(' ');

  return (
    <g className={classes} data-testid={`scene-zone-${zone.key}`}>
      <polygon
        points={points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')}
        onPointerDown={(event) => {
          if (readOnly) return;
          event.stopPropagation();
          onSelect();
        }}
      />
      {selected && !readOnly
        ? points.map((point, index) => (
          <circle
            key={`${zone.key}-vertex-${index}`}
            className={`scene-handle${selectedVertex === index ? ' is-selected' : ''}`}
            cx={point.x}
            cy={point.y}
            r={6}
            onPointerDown={(event) => onVertexPointerDown(event, index)}
          />
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
  readOnly,
  onSelect,
  onEndpointPointerDown,
}: {
  line: DraftTripLine;
  project: Projector;
  selected: boolean;
  selectedEndpoint: 'a' | 'b' | null;
  readOnly: boolean;
  onSelect: () => void;
  onEndpointPointerDown: (event: ReactPointerEvent<SVGElement>, endpoint: 'a' | 'b') => void;
}) {
  const a = project(line.a);
  const b = project(line.b);
  const centre = project(midpoint(line.a, line.b));
  const toB = aToBNormal(line.a, line.b);
  const toA = bToANormal(line.a, line.b);
  const along = alongLine(line.a, line.b);
  const classes = [
    'scene-line',
    selected ? 'is-selected' : '',
    line.enabled ? '' : 'is-disabled',
  ].filter(Boolean).join(' ');

  // The crossing indicators are perpendicular to the line, because a direction
  // of crossing is a direction of travel across it, never along it.
  const arrowLength = 26;

  return (
    <g className={classes} data-testid={`scene-line-${line.key}`}>
      <line
        x1={a.x}
        y1={a.y}
        x2={b.x}
        y2={b.y}
        onPointerDown={(event) => {
          if (readOnly) return;
          event.stopPropagation();
          onSelect();
        }}
      />
      {along ? (
        <text className="scene-line__endpoint-label" x={a.x} y={a.y - 8}>A</text>
      ) : null}
      {along ? (
        <text className="scene-line__endpoint-label" x={b.x} y={b.y - 8}>B</text>
      ) : null}

      {toB ? (
        <g className="scene-line__crossing scene-line__crossing--atob" data-testid={`scene-line-atob-${line.key}`}>
          <line x1={centre.x} y1={centre.y} x2={centre.x + toB.x * arrowLength} y2={centre.y + toB.y * arrowLength} />
          <text x={centre.x + toB.x * (arrowLength + 12)} y={centre.y + toB.y * (arrowLength + 12)}>
            {line.aToBLabel}
          </text>
        </g>
      ) : null}
      {toA ? (
        <g className="scene-line__crossing scene-line__crossing--btoa" data-testid={`scene-line-btoa-${line.key}`}>
          <line x1={centre.x} y1={centre.y} x2={centre.x + toA.x * arrowLength} y2={centre.y + toA.y * arrowLength} />
          <text x={centre.x + toA.x * (arrowLength + 12)} y={centre.y + toA.y * (arrowLength + 12)}>
            {line.bToALabel}
          </text>
        </g>
      ) : null}

      {selected && !readOnly ? (
        <>
          <circle
            className={`scene-handle${selectedEndpoint === 'a' ? ' is-selected' : ''}`}
            cx={a.x}
            cy={a.y}
            r={6}
            onPointerDown={(event) => onEndpointPointerDown(event, 'a')}
          />
          <circle
            className={`scene-handle${selectedEndpoint === 'b' ? ' is-selected' : ''}`}
            cx={b.x}
            cy={b.y}
            r={6}
            onPointerDown={(event) => onEndpointPointerDown(event, 'b')}
          />
        </>
      ) : null}
    </g>
  );
}

function DrawingPreview({
  drawing,
  pointer,
  project,
}: {
  drawing: Drawing;
  pointer: ScenePoint | null;
  project: Projector;
}) {
  if (drawing.kind === 'zone' && drawing.vertices.length > 0) {
    const points = drawing.vertices.map(project);
    const last = points[points.length - 1];
    const cursor = pointer ? project(pointer) : null;
    return (
      <g className="scene-drawing" data-testid="scene-drawing">
        <polyline points={points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')} />
        {cursor ? (
          <line className="scene-drawing__preview" x1={last.x} y1={last.y} x2={cursor.x} y2={cursor.y} />
        ) : null}
        {points.map((point, index) => (
          <circle key={`draw-${index}`} cx={point.x} cy={point.y} r={4} />
        ))}
      </g>
    );
  }

  if (drawing.kind === 'line') {
    const a = project(drawing.a);
    const cursor = pointer ? project(pointer) : null;
    return (
      <g className="scene-drawing" data-testid="scene-drawing">
        {cursor ? (
          <line className="scene-drawing__preview" x1={a.x} y1={a.y} x2={cursor.x} y2={cursor.y} />
        ) : null}
        <circle cx={a.x} cy={a.y} r={4} />
      </g>
    );
  }

  return null;
}
