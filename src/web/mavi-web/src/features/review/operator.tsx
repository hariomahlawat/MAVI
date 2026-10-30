import { ApiError } from '../../api/client';
import { isUnattributed } from '../../api/audit';
import Alert from '../../shared/components/Alert';
import StatusBadge from '../../shared/components/StatusBadge';
import { describeError } from '../../shared/async/fromQuery';

/**
 * PoC S11-full (ADR-027, ADR-010): review decisions, cases and the audit trail
 * are operator routes. With operator identity disabled they answer 401 (403 for
 * an authenticated non-operator); every surface states that once, as a state of
 * the installation rather than as a failure, and keeps the rest of the page.
 */
export const OPERATOR_REQUIRED = 'Operator identity is required for review, cases and audit.';

export function isOperatorRequired(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

/** A 4xx answer is the server's decision; retrying it would only be refused again. */
export function retryable(error: unknown): boolean {
  return !(error instanceof ApiError && error.status >= 400 && error.status < 500);
}

export function retryOnce(count: number, error: unknown): boolean {
  return retryable(error) && count < 1;
}

/** The operator sentence for a failure, with the identity state stated rather than shown as an error. */
export function operatorMessage(error: unknown, fallback: string): string {
  return isOperatorRequired(error) ? OPERATOR_REQUIRED : describeError(error, fallback);
}

export function OperatorRequiredNotice() {
  return (
    <Alert tone="info">
      {OPERATOR_REQUIRED} This installation is not identifying operators (ADR-010), so these actions and records are not
      available here; the rest of the product works as before.
    </Alert>
  );
}

/**
 * Who acted, and how they were identified. The Development fallback is labelled
 * visibly as not attributable to a person (ADR-010 §3): it is a recorded
 * placeholder, never a name.
 */
export function ActorIdentity({ displayName, operatorId, identitySource, showId = false }: {
  displayName: string;
  operatorId: string;
  identitySource: string;
  showId?: boolean;
}) {
  const unattributed = isUnattributed(identitySource);
  return (
    <span className="actor-identity">
      <span>{displayName}</span>
      {showId && operatorId !== displayName ? <code className="actor-identity__id">{operatorId}</code> : null}
      {unattributed ? (
        <StatusBadge tone="warn" title={identitySource}>Not attributable to a person</StatusBadge>
      ) : (
        <span className="muted small">via {identitySource}</span>
      )}
    </span>
  );
}
