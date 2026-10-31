import { ApiError, apiRequest } from './client';

/**
 * The audit read surface (PoC S11-full; ADR-027 §3, ADR-010 §4): read-only,
 * operator-only, newest first. The submitted payload is not stored, only its
 * SHA-256, so the surface shows the hash and the subject's own view shows the state.
 */

/** The identity source of the labelled Development fallback: actions are not attributable to a person. */
export const UNATTRIBUTED_IDENTITY_SOURCE = 'development-unattributed';

/** The platform's bound on repeated `subject` filters. */
export const AUDIT_MAXIMUM_SUBJECTS = 50;

export type AuditEntry = {
  entryId: string;
  operatorId: string;
  operatorDisplayName: string;
  identitySource: string;
  action: string;
  subjectType: string;
  subjectId: string;
  recordedAtUtc: string;
  payloadSha256: string;
  correlationId: string;
};

/** The Entity scope a page was read for (ADR-027): resolved by the server, with no subject limit. */
export type AuditEntityScope = { entityId: string; entityCount: number; candidateCount: number };

export type AuditPage = { statement: string; items: AuditEntry[]; nextCursor: string | null; entityScope: AuditEntityScope | null };

export type AuditFilter = {
  /** `type:id`, e.g. `track:<id>` or `case:<id>`. */
  subjects: string[];
  /**
   * An Entity's whole audit scope, resolved by the server from the append-only histories: the Entity, every Entity merged into
   * it and every candidate ever linked to them. Exclusive with `subjects`.
   */
  entityId?: string;
  action?: string;
  operatorId?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

const str = (value: unknown): value is string => typeof value === 'string';

function fault(): ApiError {
  return new ApiError({ status: 502, code: 'audit_contract_invalid', detail: 'The audit page did not have the expected shape.' });
}

function narrowEntry(value: unknown): AuditEntry {
  if (!isRecord(value)) throw fault();
  const fields = ['entryId', 'operatorId', 'operatorDisplayName', 'identitySource', 'action', 'subjectType', 'subjectId', 'recordedAtUtc',
    'payloadSha256', 'correlationId'] as const;
  for (const field of fields) if (!str(value[field])) throw fault();
  return Object.fromEntries(fields.map((field) => [field, value[field]])) as AuditEntry;
}

export function narrowAuditPage(value: unknown): AuditPage {
  if (!isRecord(value) || !Array.isArray(value.items)) throw fault();
  return {
    statement: str(value.statement) ? value.statement : '',
    items: value.items.map(narrowEntry),
    nextCursor: str(value.nextCursor) && value.nextCursor ? value.nextCursor : null,
    entityScope: isRecord(value.entityScope) && str(value.entityScope.entityId) && typeof value.entityScope.entityCount === 'number'
      && typeof value.entityScope.candidateCount === 'number'
      ? { entityId: value.entityScope.entityId, entityCount: value.entityScope.entityCount, candidateCount: value.entityScope.candidateCount }
      : null,
  };
}

/** The query string the platform reads; repeated `subject`, in the order given. */
export function auditQueryString(filter: AuditFilter, cursor?: string | null, limit = 50): string {
  const params = new URLSearchParams();
  if (filter.entityId) params.set('entityId', filter.entityId);
  else for (const subject of filter.subjects) params.append('subject', subject);
  if (filter.action?.trim()) params.set('action', filter.action.trim());
  if (filter.operatorId?.trim()) params.set('operatorId', filter.operatorId.trim());
  params.set('limit', String(limit));
  if (cursor) params.set('cursor', cursor);
  return params.toString();
}

export async function readAudit(filter: AuditFilter, cursor?: string | null, limit = 50, signal?: AbortSignal): Promise<AuditPage> {
  return narrowAuditPage(await apiRequest<unknown>('/api/audit?' + auditQueryString(filter, cursor, limit), { signal }));
}

/** The Audit page's own path for a set of subjects: the link every subject view carries. */
export function auditPath(...subjects: string[]): string {
  const params = new URLSearchParams();
  for (const subject of subjects) params.append('subject', subject);
  return '/audit' + (subjects.length > 0 ? '?' + params.toString() : '');
}

/** The Audit page for an Entity's whole trail: the server resolves its scope, so the link names only the Entity. */
export function entityAuditPath(entityId: string): string {
  return '/audit?' + new URLSearchParams({ entityId: entityId.toLowerCase() }).toString();
}

export function isUnattributed(identitySource: string): boolean {
  return identitySource === UNATTRIBUTED_IDENTITY_SOURCE;
}
