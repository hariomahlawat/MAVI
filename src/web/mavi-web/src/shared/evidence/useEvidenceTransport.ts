import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { contentRect, type PixelRect } from './projection';

/**
 * The source frame rate as a rational, exactly as the media metadata reports it.
 *
 * A frame step has to be the real frame duration. Assuming 25 or 30, or rounding
 * a rational rate to an integer, walks the playhead off the frame grid a little
 * more with every press — and NTSC-derived rates such as 30000/1001 are the
 * common case where that shows up first.
 */
export type SourceFrameRate = { numerator: number; denominator: number };

/** Seconds per frame, or null when the metadata does not describe a usable rate. */
export function frameDurationSeconds(rate: SourceFrameRate | undefined): number | null {
  if (!rate) return null;
  const { numerator, denominator } = rate;
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator)) return null;
  if (numerator <= 0 || denominator <= 0) return null;
  return denominator / numerator;
}

/** The playback speeds offered. Bounded on purpose: evidence review, not a media player. */
export const PLAYBACK_RATES = [0.25, 0.5, 1, 2] as const;
export type PlaybackRate = (typeof PLAYBACK_RATES)[number];

export type EvidenceTransport = {
  /** Attach to the media element. */
  videoRef: React.RefObject<HTMLVideoElement | null>;
  /** Current media position in milliseconds, published at frame rate while playing. */
  currentOffsetMs: number;
  /** Media duration in milliseconds: the element's once known, else the declared one. */
  durationMs: number;
  playing: boolean;
  /** The media element reported an error; the source could not be played. */
  failed: boolean;
  rate: PlaybackRate;
  /** The element box, for the overlay viewBox. */
  box: PixelRect;
  /** Where the frame actually sits inside that box: letterbox and pillarbox aware. */
  frame: PixelRect;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seekTo: (offsetMs: number) => void;
  /** Step whole source frames; negative steps backwards. Pauses first. */
  stepFrames: (frames: number) => void;
  nudgeSeconds: (seconds: number) => void;
  setRate: (rate: PlaybackRate) => void;
  onError: () => void;
};

type Options = {
  /** Changing this is a source replacement: media state resets. */
  sourceUrl: string;
  /** Duration declared by the evidence record, used until the element knows its own. */
  declaredDurationMs: number;
  /** Intrinsic frame size declared by the evidence record, used until metadata arrives. */
  declaredWidth: number;
  declaredHeight: number;
  frameRate?: SourceFrameRate;
  /** Where the playhead starts, and where it returns to on a source replacement. */
  initialOffsetMs: number;
  /**
   * The identity of the subject being reviewed.
   *
   * When it changes the playhead returns to `initialOffsetMs`, even on the same
   * media: stepping from one Track to the next on one video is a new subject and
   * must open at the new subject, not wherever the previous one left the
   * playhead. A seek issued before metadata cannot land, so it is applied once
   * metadata arrives instead.
   */
  seekKey: string;
};

/**
 * The media controller: one media element, one clock, one animation-frame loop.
 *
 * The `<video>` is the authoritative playback engine. Nothing here keeps a second
 * clock; `currentOffsetMs` is a published copy of `video.currentTime`, refreshed
 * from an animation frame only while the element reports that it is playing,
 * because `timeupdate` alone is ~250ms coarse and the representative box is
 * visible for 400ms.
 *
 * Exactly one loop exists at a time. `start` always cancels a previous handle,
 * seeking and time updates only publish, and pause, end, emptied, source
 * replacement and unmount all stop it.
 */
export function useEvidenceTransport({
  sourceUrl,
  declaredDurationMs,
  declaredWidth,
  declaredHeight,
  frameRate,
  initialOffsetMs,
  seekKey,
}: Options): EvidenceTransport {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [currentOffsetMs, setCurrentOffsetMs] = useState(initialOffsetMs);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const [elementDurationMs, setElementDurationMs] = useState<number | null>(null);
  const [rate, setRateState] = useState<PlaybackRate>(1);
  const [box, setBox] = useState<PixelRect>({ x: 0, y: 0, width: 0, height: 0 });
  const [frame, setFrame] = useState<PixelRect>({ x: 0, y: 0, width: 0, height: 0 });

  // A source replacement is a new media lifecycle: nothing learned about the old
  // element describes the new one, so readiness, failure and the element's own
  // duration all go back to unknown rather than being carried over.
  useEffect(() => {
    setFailed(false);
    setPlaying(false);
    setElementDurationMs(null);
    setRateState(1);
    setCurrentOffsetMs(initialOffsetMs);
    // `initialOffsetMs` is deliberately not a dependency: moving the subject
    // interval within the same media must not reset the media lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceUrl]);

  const durationMs = elementDurationMs ?? declaredDurationMs;

  const measure = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const width = video.clientWidth;
    const height = video.clientHeight;
    const intrinsicWidth = video.videoWidth || declaredWidth;
    const intrinsicHeight = video.videoHeight || declaredHeight;
    setBox({ x: 0, y: 0, width, height });
    setFrame(contentRect(width, height, intrinsicWidth, intrinsicHeight));
  }, [declaredWidth, declaredHeight]);

  // Keyed on the source as well as on `measure`. The element is keyed by source
  // in the DOM, so a replacement mounts a new one — and when the new media
  // declares the same dimensions, `measure` keeps its identity and this effect
  // would not re-run, leaving the metadata listener and the resize observer
  // attached to the detached element. The overlay would then keep the old
  // element's geometry and misproject every box and path on the new one.
  useLayoutEffect(() => {
    measure();
    const video = videoRef.current;
    if (!video) return;
    video.addEventListener('loadedmetadata', measure);
    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(measure);
      observer.observe(video);
    } else {
      window.addEventListener('resize', measure);
    }
    return () => {
      video.removeEventListener('loadedmetadata', measure);
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [measure, sourceUrl]);

  // Media truth and the single frame loop. Keyed on the source so a replacement
  // tears the old subscription down before the new element is observed.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let handle = 0;

    const publish = () => setCurrentOffsetMs(video.currentTime * 1000);
    const stop = () => {
      if (handle !== 0) window.cancelAnimationFrame(handle);
      handle = 0;
    };
    const tick = () => {
      publish();
      handle = !video.paused && !video.ended ? window.requestAnimationFrame(tick) : 0;
    };
    const start = () => {
      stop();
      handle = window.requestAnimationFrame(tick);
    };

    const onPlay = () => {
      setPlaying(true);
      start();
    };
    const onStop = () => {
      setPlaying(false);
      stop();
      publish();
    };
    const onSeeked = () => {
      publish();
      // A seek during playback keeps one loop; a seek while paused needs none.
      if (!video.paused && !video.ended && handle === 0) start();
    };
    const onMetadata = () => {
      if (Number.isFinite(video.duration) && video.duration > 0) {
        setElementDurationMs(video.duration * 1000);
      }
      publish();
    };
    const onDurationChange = () => {
      if (Number.isFinite(video.duration) && video.duration > 0) {
        setElementDurationMs(video.duration * 1000);
      }
    };
    const onRateChange = () => {
      const applied = PLAYBACK_RATES.find((value) => value === video.playbackRate);
      if (applied !== undefined) setRateState(applied);
    };

    video.addEventListener('play', onPlay);
    video.addEventListener('playing', onPlay);
    video.addEventListener('pause', onStop);
    video.addEventListener('ended', onStop);
    video.addEventListener('emptied', onStop);
    video.addEventListener('seeked', onSeeked);
    video.addEventListener('timeupdate', publish);
    video.addEventListener('loadedmetadata', onMetadata);
    video.addEventListener('durationchange', onDurationChange);
    video.addEventListener('ratechange', onRateChange);

    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) onMetadata();

    return () => {
      stop();
      video.removeEventListener('play', onPlay);
      video.removeEventListener('playing', onPlay);
      video.removeEventListener('pause', onStop);
      video.removeEventListener('ended', onStop);
      video.removeEventListener('emptied', onStop);
      video.removeEventListener('seeked', onSeeked);
      video.removeEventListener('timeupdate', publish);
      video.removeEventListener('loadedmetadata', onMetadata);
      video.removeEventListener('durationchange', onDurationChange);
      video.removeEventListener('ratechange', onRateChange);
    };
  }, [sourceUrl]);

  // Open at the subject. Runs on mount, on a source replacement and whenever the
  // subject changes, and waits for metadata when the element does not have it
  // yet, because a currentTime written before metadata is discarded.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let active = true;
    const apply = () => {
      if (!active) return;
      const seconds = Number.isFinite(video.duration) && video.duration > 0
        ? video.duration
        : declaredDurationMs / 1000;
      const limit = Number.isFinite(seconds) && seconds > 0 ? Math.max(0, seconds - 0.001) : 0;
      video.currentTime = Math.min(Math.max(0, initialOffsetMs / 1000), limit);
      setCurrentOffsetMs(video.currentTime * 1000);
    };
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) apply();
    else video.addEventListener('loadedmetadata', apply, { once: true });
    return () => {
      active = false;
      video.removeEventListener('loadedmetadata', apply);
    };
  }, [seekKey, sourceUrl, initialOffsetMs, declaredDurationMs]);

  const seekTo = useCallback((offsetMs: number) => {
    const video = videoRef.current;
    if (!video) return;
    // The element's duration when it knows one, else the declared duration: a
    // seek issued before metadata still has to land somewhere sensible.
    const seconds = Number.isFinite(video.duration) && video.duration > 0
      ? video.duration
      : declaredDurationMs / 1000;
    const limit = Number.isFinite(seconds) && seconds > 0 ? Math.max(0, seconds - 0.001) : 0;
    const target = Math.min(Math.max(0, offsetMs / 1000), limit);
    video.currentTime = target;
    setCurrentOffsetMs(target * 1000);
  }, [declaredDurationMs]);

  const play = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    // A rejected play (autoplay policy, missing source) must not leave the UI
    // claiming playback, and is not an error worth a dialog.
    void Promise.resolve(video.play()).catch(() => setPlaying(false));
  }, []);

  const pause = useCallback(() => {
    videoRef.current?.pause();
  }, []);

  const toggle = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused || video.ended) play();
    else pause();
  }, [play, pause]);

  const stepFrames = useCallback((frames: number) => {
    const video = videoRef.current;
    if (!video) return;
    const step = frameDurationSeconds(frameRate);
    // Without a usable rate there is no frame grid to step along; refusing is
    // honest, and guessing 25fps would move the playhead somewhere the source
    // has no frame boundary.
    if (step === null) return;
    if (!video.paused) video.pause();
    seekTo((video.currentTime + frames * step) * 1000);
  }, [frameRate, seekTo]);

  const nudgeSeconds = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    seekTo((video.currentTime + seconds) * 1000);
  }, [seekTo]);

  const setRate = useCallback((next: PlaybackRate) => {
    const video = videoRef.current;
    setRateState(next);
    if (video) video.playbackRate = next;
  }, []);

  const onError = useCallback(() => {
    setFailed(true);
    setPlaying(false);
  }, []);

  return {
    videoRef,
    currentOffsetMs,
    durationMs,
    playing,
    failed,
    rate,
    box,
    frame,
    play,
    pause,
    toggle,
    seekTo,
    stepFrames,
    nudgeSeconds,
    setRate,
    onError,
  };
}
