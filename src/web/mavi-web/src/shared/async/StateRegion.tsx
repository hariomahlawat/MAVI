import type { ReactNode } from 'react';
import Alert from '../components/Alert';
import Button from '../components/Button';
import EmptyState from '../components/EmptyState';
import type { IconName } from '../components/Icon';
import LoadingState from '../components/LoadingState';
import EvidencePlaceholder from '../evidence/EvidencePlaceholder';
import TruncatedText from '../overlay/Truncated';
import type { AsyncState } from './asyncState';

/**
 * The one presentation of a region's async state (specification §14.1, §37.1).
 *
 * Two things are kept apart on purpose. *Selection* — whether a request is
 * loading, unavailable, empty or content — is the `AsyncState` the caller
 * hands in, produced by `fromQuery` or by any other adapter; the union makes a
 * failure unrepresentable as empty data, which is the correctness rule this
 * boundary exists for. *Presentation* — what each of those states looks like
 * and where it sits — is decided here, once, by the **kind of region** being
 * replaced, so that an unavailable Ledger column, an unavailable facts panel
 * and an unavailable row are each presented the way §37.1 fixes for that
 * region kind and never the way a page happened to write them.
 *
 * The region renders exactly one of Loading, Unavailable, Empty or Content, and
 * a degraded result (data on screen, a later refetch failed) renders content
 * beneath one warning that carries the retry. The emptiness question is the
 * caller's, because only the caller knows what "nothing" means for its
 * payload, and it is asked only *after* the request is known to have
 * succeeded: `isEmpty` is handed real data, never a failure.
 *
 * What is deliberately *not* here: domain states. "Not configured", "not
 * analysed", "too much to map" and the other §14 states a successful answer
 * can carry are rendered by the caller inside `children`, with their own
 * words — the region's four outcomes are about the request, not about what
 * the answer means.
 *
 * It knows nothing about TanStack Query (§14.1).
 */

/** The §37.1 region kinds. Each fixes the geometry of the four presentations. */
export type RegionKind = 'page' | 'column' | 'panel' | 'row' | 'media';

/** The §37.1 "empty" presentation: one icon, one title, one sentence, one secondary action. */
export type EmptySpec = {
  icon?: IconName;
  title: string;
  body?: ReactNode;
  action?: ReactNode;
  /** Not-configured and unavailable-looking placeholders carry the §14 hatch. */
  hatched?: boolean;
};

export type StateRegionProps<T> = {
  /** Which §37.1 presentation set applies. */
  kind: RegionKind;
  state: AsyncState<T>;
  /**
   * What the region holds, as the operator would name it — "videos", "the
   * scene", "Track evidence". It completes the default loading and
   * unavailable sentences, so a caller that says nothing else still gets
   * operator copy rather than a generic word.
   */
  label: string;
  /** Rendered only when the request succeeded and the result is not empty. */
  children: (data: T) => ReactNode;
  /** Asked only of real data. Without it, every successful result is content. */
  isEmpty?: (data: T) => boolean;
  /** The empty presentation. A spec renders the shared EmptyState; a node is the caller's own. */
  empty?: EmptySpec | ReactNode;
  /**
   * Loading as skeleton rows, where the geometry is known (§37.1): a column at
   * the Ledger row pitch (`--table-row-h`) or the result-row pitch, a panel as
   * key/value rows. Without it the region loads as the labelled inline
   * presentation, which is honest for a region whose shape is not known in
   * advance — §37.1 asks for a skeleton only where the shape is.
   */
  skeleton?: { rows: number | 'default'; pitch?: 'table' | 'ledger' | 'list' | 'compactList' | 'keyValue' };
  /** The operator sentence for a first-load failure. Defaults to "{Label} could not be loaded." */
  unavailableMessage?: (error: unknown) => string;
  /**
   * The failure is already announced, with its retry, by another region on the
   * same request — Overview's one notice for the summary band names the video
   * inventory, and the media panel below draws from the same request. One cause
   * is one alert (§14.1), so this region states only that it cannot be drawn,
   * as text, and offers no second retry.
   */
  causeAnnouncedElsewhere?: boolean;
  /** The sentence over retained data whose refresh failed. */
  degradedMessage?: string;
  /** Re-requests the region. Rendered as the trailing action of the unavailable or degraded alert. */
  onRetry?: () => void;
  /** Overrides the loading label; defaults to "Loading {label}…". */
  loadingLabel?: string;
  /**
   * The retry control's text where `Retry` alone would be ambiguous — a row
   * whose own action is also called Retry. Defaults to `Retry`.
   */
  retryLabel?: string;
  /**
   * A row region in a dense cell (a Ledger status cell) retries with a
   * 26×26 icon-only control (§36.3, in-row) named by `retryLabel`, so the
   * message — not the control — is what gives way to the column's cap.
   */
  compactRetry?: boolean;
  /**
   * A failure retrying cannot mend — a 404, a refusal — keeps its sentence and
   * loses the control that would only fail again.
   */
  retryable?: (error: unknown) => boolean;
};

function sentenceCase(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function isEmptySpec(value: unknown): value is EmptySpec {
  return typeof value === 'object' && value !== null && 'title' in value && typeof (value as EmptySpec).title === 'string';
}

export default function StateRegion<T>({
  kind,
  state,
  label,
  children,
  isEmpty,
  empty,
  skeleton,
  unavailableMessage,
  degradedMessage,
  onRetry,
  loadingLabel,
  retryable,
  causeAnnouncedElsewhere = false,
  retryLabel = 'Retry',
  compactRetry = false,
}: StateRegionProps<T>) {
  const rowRetry = (action: () => void) => (
    <Button size="sm" variant="ghost" icon="refresh" iconOnly={compactRetry} title={compactRetry ? retryLabel : undefined} onClick={action}>
      {retryLabel}
    </Button>
  );
  const loadingText = loadingLabel ?? `Loading ${label}…`;

  if (state.kind === 'loading') {
    if (kind === 'media') return <EvidencePlaceholder label="Loading image" pending />;
    if (kind === 'row') return <span className="state-row state-row--loading">{loadingText}</span>;
    if ((kind === 'column' || kind === 'panel') && skeleton) {
      return (
        <div className={`state-region state-region--${kind}`}>
          <LoadingState label={loadingText} rows={skeleton.rows} pitch={skeleton.pitch} />
        </div>
      );
    }
    return (
      <div className={`state-region state-region--${kind} state-region--inline`}>
        <LoadingState label={loadingText} />
      </div>
    );
  }

  if (state.kind === 'unavailable') {
    const message = unavailableMessage?.(state.error) ?? `${sentenceCase(label)} could not be loaded.`;
    const canRetry = onRetry !== undefined && (retryable?.(state.error) ?? true);
    if (kind === 'media') return <EvidencePlaceholder label="No image" reason={message} />;
    if (causeAnnouncedElsewhere) {
      return (
        <div className={`state-region state-region--${kind} state-region--inline`}>
          <p className="state-region__note">{message}</p>
        </div>
      );
    }
    if (kind === 'row') {
      // Row identity is the caller's cells; this is the one cell's content.
      return (
        <span className="state-row">
          {/* In a capped cell the message is what gives way, so it truncates
              with its full sentence reachable by pointer and keyboard (§16). */}
          <span className="text-err"><TruncatedText text={message} /></span>
          {canRetry && onRetry ? rowRetry(onRetry) : null}
        </span>
      );
    }
    return (
      <div className={`state-region state-region--${kind} state-region--inline`}>
        <Alert tone="error" actions={canRetry ? <Button size="sm" onClick={onRetry}>{retryLabel}</Button> : undefined}>
          {message}
        </Alert>
      </div>
    );
  }

  const body = isEmpty?.(state.data) && empty !== undefined
    ? (
      <div className={`state-region state-region--${kind} state-region--inline`}>
        {isEmptySpec(empty)
          ? (
            <EmptyState icon={empty.icon} title={empty.title} actions={empty.action} hatched={empty.hatched} compact={kind === 'panel' || kind === 'row'}>
              {empty.body}
            </EmptyState>
          )
          : empty}
      </div>
    )
    : children(state.data);

  if (state.degraded) {
    const canRetry = onRetry !== undefined && (retryable?.(state.degraded.error) ?? true);
    const message = degradedMessage ?? `Showing the last known ${label}; refreshing failed.`;
    // The cause is announced, with its retry, by the region that owns it.
    if (causeAnnouncedElsewhere || kind === 'media') return <>{body}</>;
    if (kind === 'row') {
      // A row keeps its content and says, in its own cell, that it may be stale.
      return (
        <>
          {body}
          <span className="state-row state-row--degraded">
            <span className="faint"><TruncatedText text={message} /></span>
            {canRetry && onRetry ? rowRetry(onRetry) : null}
          </span>
        </>
      );
    }
    return (
      <>
        <div className={`state-region state-region--${kind} state-region--degraded`}>
          <Alert tone="warning" actions={canRetry ? <Button size="sm" onClick={onRetry}>{retryLabel}</Button> : undefined}>
            {message}
          </Alert>
        </div>
        {body}
      </>
    );
  }

  return <>{body}</>;
}


/**
 * The page notice for a *supporting* request (§37.1, page).
 *
 * Some requests have no region of their own: camera names beside a video list,
 * the display timezone, the video list a search rail offers. Their loading is
 * shown by the content that uses them (an identifier until the name arrives),
 * and their failure degrades the surface rather than replacing anything, so it
 * is one warning at the top of the workspace with its retry trailing — and,
 * once the data has arrived, a failed refresh says the values may be stale
 * rather than claiming they are missing. Same selector, same alert grammar as
 * a region; nothing at all while the request loads or is current.
 */
export function SupportingRequestNotice<T>({
  state,
  unavailableMessage,
  degradedMessage,
  onRetry,
  retryLabel = 'Retry',
}: {
  state: AsyncState<T>;
  /** What the surface does without the data, in the operator's words. */
  unavailableMessage: ReactNode;
  /** What the surface does with the last known data. */
  degradedMessage: ReactNode;
  onRetry?: () => void;
  /** Names the request when several notices can be on screen together. */
  retryLabel?: string;
}) {
  if (state.kind === 'loading') return null;
  if (state.kind === 'ready' && state.degraded === undefined) return null;
  return (
    <Alert tone="warning" actions={onRetry ? <Button size="sm" onClick={onRetry}>{retryLabel}</Button> : undefined}>
      {state.kind === 'unavailable' ? unavailableMessage : degradedMessage}
    </Alert>
  );
}
