import { apiJson, apiRequest } from './client';
import type { FaceBox, FaceIdentity, ReferenceThreshold } from './faces';

/**
 * Entity candidates and operator-confirmed Entities (PoC S7; ADR-023). Every
 * route requires the operator (ADR-010). A candidate is a machine proposal
 * with its factors shown separately; an Entity exists only because an operator
 * confirmed it, and is never an identification. Nothing merges automatically.
 */

export const ENTITY_CANDIDATES_LABEL = 'Entity candidates — not identification — Development';
export const ENTITY_LABEL = 'Operator-confirmed Entity — not identification — Development';

export type EntityCandidateStatus = 'open' | 'confirmed' | 'dismissed';

export type CatalogueParameter = { name: string; value: string; source: string; rationale: string };

export type EntityCandidateCatalogue = {
  version: string;
  sha256: string;
  appearanceFloor: number;
  concurrencyToleranceMs: number;
  parameters: CatalogueParameter[];
  plausibilityDisclosure: string;
};

export type EntityTrack = {
  trackId: string;
  processingRunId: string;
  videoAssetId: string;
  cameraId: string;
  cameraCode: string;
  cameraName: string;
  objectClass: 'Person' | 'Vehicle';
  startTimestampUtc: string;
  endTimestampUtc: string;
  startOffsetMs: number;
  endOffsetMs: number;
  thumbnailUrl: string | null;
  entityId: string | null;
  visible: boolean;
};

export type EntityCandidateDecision = {
  decidedAtUtc: string;
  operatorId: string;
  displayName: string;
  identitySource: string;
  note: string | null;
  auditEntryId: string | null;
};

export type EntityCandidate = {
  candidateId: string;
  label: string;
  objectClass: 'Person' | 'Vehicle';
  status: EntityCandidateStatus;
  catalogueVersion: string;
  identityFingerprint: string;
  factors: {
    appearance: { score: number; floor: number; source: string };
    plausibility: { verdict: 'plausible'; sameCamera: boolean; gapMs: number; concurrencyToleranceMs: number; disclosure: string };
    face: { available: boolean; note: string } | null;
  };
  decision: EntityCandidateDecision | null;
  entityId: string | null;
  lower: EntityTrack;
  higher: EntityTrack;
};

export type EntityCandidateList = {
  label: string;
  catalogue: EntityCandidateCatalogue;
  identity: { fingerprint: string; modelId: string; modelVersion: string };
  total: number;
  limit: number;
  offset: number;
  candidates: EntityCandidate[];
};

export type EntityCandidatePairCount = {
  cameraId: string;
  cameraCode: string;
  otherCameraId: string;
  otherCameraCode: string;
  objectClass: 'Person' | 'Vehicle';
  open: number;
  confirmed: number;
  dismissed: number;
};

export type EntityCandidateSummary = {
  label: string;
  catalogue: EntityCandidateCatalogue;
  identity: { fingerprint: string; modelId: string; modelVersion: string } | null;
  derivations: number;
  pendingDerivations: number;
  pairs: EntityCandidatePairCount[];
};

export type EntityDecisionResponse = { label: string; candidate: EntityCandidate; entityId: string | null; entityCreated: boolean };

export type FaceFactorSide = { trackId: string; state: string; reason: string | null };

export type FaceFactorResponse = {
  label: string;
  state: 'observed' | 'unknown';
  identity: FaceIdentity;
  referenceThreshold: ReferenceThreshold;
  lower: FaceFactorSide;
  higher: FaceFactorSide;
  pair: {
    score: number;
    aboveThreshold: boolean;
    lowerFaceId: string;
    lowerObservationId: string;
    lowerEvidenceCropUrl: string | null;
    lowerBox: FaceBox;
    higherFaceId: string;
    higherObservationId: string;
    higherEvidenceCropUrl: string | null;
    higherBox: FaceBox;
  } | null;
  note: string;
};

export type EntityResponse = {
  label: string;
  entityId: string;
  displayCode: string;
  entityType: 'Person' | 'Vehicle';
  identityStatus: 'Unknown';
  createdAtUtc: string;
  updatedAtUtc: string;
  members: EntityTrack[];
  /** Includes the candidates of Entities merged into this one (ADR-027 §4). */
  confirmations: EntityCandidate[];
  /** `Merged` once merged into another Entity; a merged Entity keeps its history and no longer changes. */
  state: EntityState;
  mergedIntoEntityId: string | null;
  /** Every join and leave of a Track, append-only, in sequence order. */
  history: EntityMembershipChange[];
  /** The Entities merged into this one, directly or through another merge: their merges are recorded under their own ids. */
  mergedFromEntityIds: string[];
  /**
   * Every candidate ever linked to this Entity or one merged into it, from the append-only histories (ADR-027): a candidate since
   * unlinked, reopened or confirmed elsewhere still carries this Entity's decisions in its audit trail.
   */
  relatedCandidateIds: string[];
};

export type EntityState = 'Active' | 'Merged';

export type EntityMembershipChange = {
  sequence: number;
  trackId: string;
  entityId: string;
  change: 'Joined' | 'Left';
  cause: 'CandidateConfirmed' | 'Unlinked' | 'Merged';
  candidateId: string | null;
  note: string | null;
  operatorId: string;
  operatorDisplayName: string;
  identitySource: string;
  atUtc: string;
  auditEntryId: string;
};

export type EntityCandidateDecisionRecord = {
  sequence: number;
  decision: 'Confirmed' | 'Dismissed' | 'Reopened';
  entityId: string | null;
  note: string | null;
  operatorId: string;
  operatorDisplayName: string;
  identitySource: string;
  atUtc: string;
  auditEntryId: string;
};

export type EntityCandidateHistory = { candidateId: string; decisions: EntityCandidateDecisionRecord[] };

/** The note limit of every Entity decision and correction (`EntityCandidate.NormaliseNote`). */
export const ENTITY_NOTE_MAXIMUM = 500;

export type EntityCandidateFilter = {
  status?: EntityCandidateStatus;
  objectClass?: 'Person' | 'Vehicle';
  cameraId?: string;
  otherCameraId?: string;
  limit?: number;
  offset?: number;
};

const enc = encodeURIComponent;

export function listEntityCandidates(filter: EntityCandidateFilter, signal?: AbortSignal): Promise<EntityCandidateList> {
  const params = new URLSearchParams();
  if (filter.status) params.set('status', filter.status);
  if (filter.objectClass) params.set('objectClass', filter.objectClass);
  if (filter.cameraId) params.set('cameraId', filter.cameraId);
  if (filter.cameraId && filter.otherCameraId) params.set('otherCameraId', filter.otherCameraId);
  if (filter.limit !== undefined) params.set('limit', String(filter.limit));
  if (filter.offset) params.set('offset', String(filter.offset));
  const query = params.toString();
  return apiRequest<EntityCandidateList>('/api/entity-candidates' + (query ? '?' + query : ''), { signal });
}

export function getEntityCandidateSummary(signal?: AbortSignal): Promise<EntityCandidateSummary> {
  return apiRequest<EntityCandidateSummary>('/api/entity-candidates/summary', { signal });
}

export function confirmEntityCandidate(candidateId: string, note: string | null): Promise<EntityDecisionResponse> {
  return apiJson<EntityDecisionResponse>('/api/entity-candidates/' + enc(candidateId) + '/confirm', 'POST', { note });
}

export function dismissEntityCandidate(candidateId: string, note: string | null): Promise<EntityDecisionResponse> {
  return apiJson<EntityDecisionResponse>('/api/entity-candidates/' + enc(candidateId) + '/dismiss', 'POST', { note });
}

/** The face factor is a separate, audited 1:1 comparison: it is fetched only when the operator asks. */
export function compareCandidateFaces(candidateId: string): Promise<FaceFactorResponse> {
  return apiJson<FaceFactorResponse>('/api/entity-candidates/' + enc(candidateId) + '/face-factor', 'POST', {});
}

export async function getEntity(entityId: string, signal?: AbortSignal): Promise<EntityResponse> {
  return normaliseEntity(await apiRequest<EntityResponse>('/api/entities/' + enc(entityId), { signal }));
}

/** A server without the S11-full fields reads as an active Entity with no recorded history, never as a crash. */
function normaliseEntity(entity: EntityResponse): EntityResponse {
  return {
    ...entity,
    state: entity.state === 'Merged' ? 'Merged' : 'Active',
    mergedIntoEntityId: entity.mergedIntoEntityId ?? null,
    history: Array.isArray(entity.history) ? entity.history : [],
    mergedFromEntityIds: Array.isArray(entity.mergedFromEntityIds) ? entity.mergedFromEntityIds.filter((id) => typeof id === 'string') : [],
    // An older server has no history to read: its current confirmations are the closest it can say.
    relatedCandidateIds: Array.isArray(entity.relatedCandidateIds)
      ? entity.relatedCandidateIds.filter((id) => typeof id === 'string')
      : (entity.confirmations ?? []).map((item) => item.candidateId),
    confirmations: Array.isArray(entity.confirmations) ? entity.confirmations : [],
    members: Array.isArray(entity.members) ? entity.members : [],
  };
}

// --- Corrections (PoC S11-full; ADR-027 §4): recorded as new rows, never edits ---------------

/** The Track leaves the Entity; the Entity is kept with whatever members remain, even one or none. */
export async function unlinkEntityTrack(entityId: string, trackId: string, note: string | null): Promise<EntityResponse> {
  return normaliseEntity(await apiJson<EntityResponse>('/api/entities/' + enc(entityId) + '/unlink', 'POST', { trackId, note }));
}

/** Every member of `entityId` joins `intoEntityId`, which is kept; the source becomes Merged. Answers the kept Entity. */
export async function mergeEntity(entityId: string, intoEntityId: string, note: string | null): Promise<EntityResponse> {
  return normaliseEntity(await apiJson<EntityResponse>('/api/entities/' + enc(entityId) + '/merge', 'POST', { intoEntityId, note }));
}

export function reopenEntityCandidate(candidateId: string, note: string | null): Promise<EntityDecisionResponse> {
  return apiJson<EntityDecisionResponse>('/api/entity-candidates/' + enc(candidateId) + '/reopen', 'POST', { note });
}

export function getEntityCandidateHistory(candidateId: string, signal?: AbortSignal): Promise<EntityCandidateHistory> {
  return apiRequest<EntityCandidateHistory>('/api/entity-candidates/' + enc(candidateId) + '/history', { signal });
}

/** The gap between the two Tracks, in words: "6.0 s later", "1.5 s overlap (within tolerance)". */
export function describeGap(gapMs: number): string {
  const seconds = Math.abs(gapMs) / 1000;
  const text = seconds >= 120 ? `${(seconds / 60).toFixed(1)} min` : `${seconds.toFixed(1)} s`;
  return gapMs < 0 ? `${text} overlap (within tolerance)` : `${text} apart`;
}

/** Plain-language refusals of a correction (ADR-027 §4). Unknown codes are shown as they are. */
export function correctionRefusalText(code: string | undefined): string {
  switch (code) {
    case 'entity_track_not_member':
      return 'Not unlinked: the Track is no longer a member of this Entity; the view now shows its current members.';
    case 'entity_not_active':
      return 'Not changed: the Entity was merged into another and no longer changes.';
    case 'entity_not_found':
      return 'The Entity does not exist.';
    case 'entity_merge_invalid':
      return 'Not merged: only two different active Entities of one type can be merged.';
    case 'entity_changed_concurrently':
      return 'Not merged: the Entities changed while merging; they have been read again.';
    case 'entity_merge_implausible':
      return 'Not merged: a member of one Entity was seen at a time and camera that rule out being the same object as a member of the other.';
    case 'entity_candidate_not_decided':
      return 'Not reopened: the candidate is open; there is nothing to reopen.';
    case 'entity_candidate_still_linked':
      return 'Not reopened: both Tracks are still in one Entity. Unlink one of the two Tracks first.';
    case 'entity_candidate_superseded':
      return 'Not reopened: this candidate belongs to an earlier candidate rule or appearance model; only current candidates can be reopened.';
    default:
      return code ? `The correction was refused (${code}).` : 'The correction failed.';
  }
}

/** Plain-language refusals of a decision (ADR-023 §6). Unknown codes are shown as they are. */
export function decisionRefusalText(code: string | undefined): string {
  switch (code) {
    case 'entity_candidate_already_decided':
      return 'Another decision was recorded for this candidate first; the list now shows it.';
    case 'entity_extension_implausible':
      return 'Not linked: the Track would join an Entity with a member seen at the same time (an object cannot be in two places at once).';
    case 'entity_merge_unsupported':
      return 'Not linked: the two Tracks already belong to different Entities. Merge the Entities explicitly to bring them together.';
    case 'entity_candidate_superseded':
      return 'Not decided: this candidate belongs to an earlier candidate rule or appearance model; only current candidates can be decided.';
    case 'entity_candidate_not_visible':
      return 'Not linked: a Track of this candidate is no longer in the latest run of its video.';
    default:
      return code ? `The decision was refused (${code}).` : 'The decision failed.';
  }
}
