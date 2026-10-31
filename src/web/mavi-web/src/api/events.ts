import { apiRequest } from './client';
import type { AnalyticsBucket } from './analytics';
import type { AnalyticsCoverage } from './tracks';

/**
 * The Events client (ADR-025): the versioned rule catalogue, one camera's event
 * timeline, and one event with its provenance envelope.
 *
 * Every event is a deterministic derivation from persisted scene-analytics facts by
 * one catalogue rule. Nothing here is a model output or an identity claim, and the
 * client recomputes nothing: counts and coverage are what the server transported.
 */

export const EVENT_RULE_IDS = [
  'line-crossing',
  'zone-dwell',
  'stopped-vehicle',
  'wrong-way',
  'co-occurrence',
  'repeated-visit',
] as const;
export type EventRuleId = (typeof EVENT_RULE_IDS)[number];

export const EVENTS_DEFAULT_LIMIT = 1_000;
export const EVENTS_QUERY_INVALID = 'analytic_events_query_invalid';
export const EVENT_NOT_FOUND = 'analytic_event_not_found';

export type RuleParameter = {
  name: string;
  value: string | null;
  unit: string | null;
  source: 'scene-revision' | 'owner-decision' | 'catalogue' | string;
  reference: string;
};

export type RuleDefinition = {
  ruleId: string;
  ruleVersion: number;
  title: string;
  description: string;
  enabled: boolean;
  disabledReason: string | null;
  parameters: RuleParameter[];
};

export type RuleCatalogue = {
  catalogueVersion: string;
  catalogueSha256: string;
  rules: RuleDefinition[];
};

export type EventCoverage = {
  analytics: AnalyticsCoverage;
  derivedRuns: number;
  eventsPendingRuns: number;
  complete: boolean;
};

export type EventSummary = {
  eventId: string;
  ruleId: string;
  ruleVersion: number;
  startUtc: string;
  endUtc: string;
  startOffsetMs: number;
  endOffsetMs: number;
  videoAssetId: string;
  processingRunId: string;
  primaryTrackId: string | null;
  objectClass: string | null;
  zoneId: string | null;
  zoneName: string | null;
  lineId: string | null;
  lineName: string | null;
  direction: string | null;
  directionLabel: string | null;
  participantCount: number;
};

export type EventCrossingCounts = {
  lineId: string;
  name: string;
  aToBLabel: string;
  bToALabel: string;
  aToBCounts: number[];
  bToACounts: number[];
};

export type EventTimeline = {
  cameraId: string;
  sceneRevisionId: string | null;
  sceneRevisionNumber: number | null;
  analyticsAlgorithmVersion: string;
  catalogueVersion: string;
  snapshotVisibilitySequence: number;
  fromUtc: string;
  toUtc: string;
  bucketSeconds: number;
  coverage: EventCoverage;
  buckets: AnalyticsBucket[];
  ruleCounts: { ruleId: string; count: number }[];
  crossingCounts: EventCrossingCounts[];
  events: EventSummary[];
  limit: number;
  truncated: boolean;
};

export type EventParticipant = {
  trackId: string;
  role: string;
  objectClass: string;
  videoAssetId: string;
  startOffsetMs: number;
  endOffsetMs: number;
  thumbnailContentUrl: string | null;
};

export type EventDetail = {
  event: EventSummary;
  cameraId: string;
  sceneAnalysisId: string;
  sceneRevisionId: string;
  sceneRevisionNumber: number;
  analyticsAlgorithmVersion: string;
  catalogueVersion: string;
  catalogueSha256: string;
  inputSha256: string;
  derivedAtUtc: string;
  participants: EventParticipant[];
  inputs: { kind: string; reference: string; startOffsetMs: number | null; endOffsetMs: number | null }[];
  parameters: { name: string; value: string; unit: string | null; source: string; reference: string }[];
  details: { name: string; value: string }[];
};

export type EventTimelineQuery = {
  fromUtc: string;
  toUtc: string;
  bucketSeconds: number;
  ruleIds: readonly string[];
  limit?: number;
};

/** Canonical query text: also the cache key, so one question is one cache entry. */
export function serializeEventTimelineQuery(query: EventTimelineQuery): string {
  const params = new URLSearchParams();
  params.set('fromUtc', query.fromUtc);
  params.set('toUtc', query.toUtc);
  params.set('bucketSeconds', String(query.bucketSeconds));
  for (const ruleId of [...query.ruleIds].sort()) params.append('ruleId', ruleId);
  if (query.limit !== undefined) params.set('limit', String(query.limit));
  return params.toString();
}

export function getEventCatalogue(signal?: AbortSignal): Promise<RuleCatalogue> {
  return apiRequest<RuleCatalogue>('/api/events/catalogue', { signal });
}

export function getEventTimeline(cameraId: string, query: EventTimelineQuery, signal?: AbortSignal): Promise<EventTimeline> {
  return apiRequest<EventTimeline>(
    `/api/cameras/${encodeURIComponent(cameraId)}/events?${serializeEventTimelineQuery(query)}`,
    { signal },
  );
}

export function getEvent(eventId: string, signal?: AbortSignal): Promise<EventDetail> {
  return apiRequest<EventDetail>(`/api/events/${encodeURIComponent(eventId)}`, { signal });
}

/**
 * Review of one participant Track at the event's instant, read against the exact
 * revision and engine version the event was derived from (ADR-011 decision 8).
 */
export function eventReviewPath(detail: Pick<EventDetail, 'sceneRevisionId' | 'analyticsAlgorithmVersion' | 'event'>, participant: Pick<EventParticipant, 'trackId' | 'videoAssetId'>): string {
  const params = new URLSearchParams();
  params.set('trackId', participant.trackId.toLowerCase());
  params.set('sceneRevisionId', detail.sceneRevisionId.toLowerCase());
  params.set('analyticsAlgorithmVersion', detail.analyticsAlgorithmVersion);
  params.set('seekMs', String(Math.max(0, Math.trunc(detail.event.startOffsetMs))));
  return `/review/video/${participant.videoAssetId.toLowerCase()}?${params.toString()}`;
}

/** Plain-language disabled reasons. Unknown codes are shown as they are, never hidden. */
export function disabledReasonText(reason: string | null): string | null {
  if (reason === null) return null;
  if (reason === 'requires_entity_confirmation') {
    // Confirmed Entities exist since S7; the entity-conditioned rule runs only in the next catalogue (ADR-023 §9).
    return 'Disabled: needs operator-confirmed Entities and runs only in the next rule catalogue (mavi-events-v2). Defined and tested, not run.';
  }
  return `Disabled: ${reason}`;
}

export function parameterSourceText(source: string): string {
  switch (source) {
    case 'scene-revision': return 'from the scene revision';
    case 'owner-decision': return 'owner decision';
    case 'catalogue': return 'catalogue constant';
    default: return source;
  }
}
