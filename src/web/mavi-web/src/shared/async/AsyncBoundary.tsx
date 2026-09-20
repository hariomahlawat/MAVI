import type { ReactNode } from 'react';
import Alert from '../components/Alert';
import Button from '../components/Button';
import LoadingState from '../components/LoadingState';
import type { AsyncState } from './asyncState';

/**
 * Renders exactly one of Loading, Unavailable, Empty or Content — never two,
 * never the wrong one (section 14.1).
 *
 * The emptiness question is the caller's, because only the caller knows what
 * "nothing" means for its payload, but it is asked *after* the request is known
 * to have succeeded. That ordering is the whole point: `isEmpty` is only ever
 * handed real data, so a failure can never be mistaken for an empty result.
 */
export default function AsyncBoundary<T>({
  state,
  children,
  empty,
  isEmpty,
  loadingLabel = 'Loading…',
  loading,
  unavailable,
  unavailableLabel = 'This information is unavailable.',
  degradedLabel = 'Showing the last known values; refreshing failed.',
  onRetry,
}: {
  state: AsyncState<T>;
  /** Rendered only when the request succeeded and the result is not empty. */
  children: (data: T) => ReactNode;
  empty?: ReactNode;
  isEmpty?: (data: T) => boolean;
  loadingLabel?: string;
  /** Replaces the default spinner, for surfaces with a known row height. */
  loading?: ReactNode;
  /** Replaces the default alert, for surfaces that phrase failure themselves. */
  unavailable?: (error: unknown) => ReactNode;
  unavailableLabel?: string;
  degradedLabel?: string;
  onRetry?: () => void;
}) {
  if (state.kind === 'loading') {
    return <>{loading ?? <LoadingState label={loadingLabel} />}</>;
  }

  if (state.kind === 'unavailable') {
    if (unavailable) return <>{unavailable(state.error)}</>;
    return (
      <Alert
        tone="error"
        actions={onRetry ? <Button size="sm" onClick={onRetry}>Retry</Button> : undefined}
      >
        {unavailableLabel}
      </Alert>
    );
  }

  const body = isEmpty?.(state.data) && empty !== undefined ? empty : children(state.data);

  if (state.degraded) {
    return (
      <>
        <Alert
          tone="warning"
          actions={onRetry ? <Button size="sm" onClick={onRetry}>Retry</Button> : undefined}
        >
          {degradedLabel}
        </Alert>
        {body}
      </>
    );
  }

  return <>{body}</>;
}
