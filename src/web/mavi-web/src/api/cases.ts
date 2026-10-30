import { ApiError, apiJson, apiRequest } from './client';

/**
 * Cases (PoC S11-full; ADR-027 §2). Every route requires the operator (ADR-010)
 * and every write is audited with the case as its subject. A case collects
 * evidence for investigation and asserts nothing about what its items show;
 * removing an item is a recorded change, never a delete.
 */

/** The sentence every case surface carries (the API sends the same text as `statement`). */
export const CASE_STATEMENT =
  'A case collects evidence for investigation. Items in one case are not asserted to show the same person or vehicle.';

export const CASE_ITEM_KINDS = ['Track', 'AnalyticEvent', 'Entity'] as const;
export type CaseItemKind = (typeof CASE_ITEM_KINDS)[number];

export const CASE_TITLE_MAXIMUM = 200;
export const CASE_PURPOSE_MAXIMUM = 2000;
export const CASE_ITEM_NOTE_MAXIMUM = 1000;
export const CASE_NOTE_MAXIMUM = 4000;

export const CASE_ITEM_ALREADY_PRESENT = 'case_item_already_present';

export type CaseActor = {
  operatorId: string;
  displayName: string;
  identitySource: string;
  atUtc: string;
  auditEntryId: string;
};

export type CaseSummary = {
  caseId: string;
  title: string;
  purpose: string | null;
  createdBy: CaseActor;
  activeItemCount: number;
  removedItemCount: number;
  noteCount: number;
};

/** What the case knows about an item's subject now; `available: false` when it no longer resolves. */
export type CaseSubject = {
  available: boolean;
  earlierRun: boolean;
  objectClass: string | null;
  cameraId: string | null;
  cameraName: string | null;
  startUtc: string | null;
  endUtc: string | null;
  reviewStatus: string | null;
  ruleId: string | null;
  entityDisplayCode: string | null;
  processingRunId: string | null;
  videoAssetId: string | null;
  startOffsetMs: number | null;
};

export type CaseItem = {
  itemId: string;
  kind: CaseItemKind | (string & {});
  subjectId: string;
  note: string | null;
  addedBy: CaseActor;
  removedBy: CaseActor | null;
  removalNote: string | null;
  subject: CaseSubject;
};

export type CaseNote = { noteId: string; body: string; author: CaseActor };

export type CaseList = { statement: string; cases: CaseSummary[] };

export type CaseDetail = { statement: string; case: CaseSummary; items: CaseItem[]; notes: CaseNote[] };

// --- Narrowing ----------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

const str = (value: unknown): value is string => typeof value === 'string';
const optionalText = (value: unknown): string | null => (typeof value === 'string' ? value : null);
const optionalNumber = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

function fault(what: string): ApiError {
  return new ApiError({ status: 502, code: 'case_contract_invalid', detail: `The ${what} did not have the expected shape.` });
}

function narrowActor(value: unknown): CaseActor {
  if (!isRecord(value) || !str(value.operatorId) || !str(value.displayName) || !str(value.identitySource) || !str(value.atUtc)
    || !str(value.auditEntryId)) throw fault('case actor');
  return { operatorId: value.operatorId, displayName: value.displayName, identitySource: value.identitySource, atUtc: value.atUtc,
    auditEntryId: value.auditEntryId };
}

export function narrowCaseSummary(value: unknown): CaseSummary {
  if (!isRecord(value) || !str(value.caseId) || !str(value.title)) throw fault('case');
  return {
    caseId: value.caseId,
    title: value.title,
    purpose: optionalText(value.purpose),
    createdBy: narrowActor(value.createdBy),
    activeItemCount: optionalNumber(value.activeItemCount) ?? 0,
    removedItemCount: optionalNumber(value.removedItemCount) ?? 0,
    noteCount: optionalNumber(value.noteCount) ?? 0,
  };
}

function narrowSubject(value: unknown): CaseSubject {
  const subject = isRecord(value) ? value : {};
  return {
    available: subject.available === true,
    earlierRun: subject.earlierRun === true,
    objectClass: optionalText(subject.objectClass),
    cameraId: optionalText(subject.cameraId),
    cameraName: optionalText(subject.cameraName),
    startUtc: optionalText(subject.startUtc),
    endUtc: optionalText(subject.endUtc),
    reviewStatus: optionalText(subject.reviewStatus),
    ruleId: optionalText(subject.ruleId),
    entityDisplayCode: optionalText(subject.entityDisplayCode),
    processingRunId: optionalText(subject.processingRunId),
    videoAssetId: optionalText(subject.videoAssetId),
    startOffsetMs: optionalNumber(subject.startOffsetMs),
  };
}

export function narrowCaseItem(value: unknown): CaseItem {
  if (!isRecord(value) || !str(value.itemId) || !str(value.kind) || !str(value.subjectId)) throw fault('case item');
  return {
    itemId: value.itemId,
    kind: value.kind,
    subjectId: value.subjectId,
    note: optionalText(value.note),
    addedBy: narrowActor(value.addedBy),
    removedBy: value.removedBy ? narrowActor(value.removedBy) : null,
    removalNote: optionalText(value.removalNote),
    subject: narrowSubject(value.subject),
  };
}

function narrowNote(value: unknown): CaseNote {
  if (!isRecord(value) || !str(value.noteId) || !str(value.body)) throw fault('case note');
  return { noteId: value.noteId, body: value.body, author: narrowActor(value.author) };
}

export function narrowCaseList(value: unknown): CaseList {
  if (!isRecord(value) || !Array.isArray(value.cases)) throw fault('case list');
  return { statement: str(value.statement) ? value.statement : CASE_STATEMENT, cases: value.cases.map(narrowCaseSummary) };
}

export function narrowCaseDetail(value: unknown): CaseDetail {
  if (!isRecord(value) || !Array.isArray(value.items) || !Array.isArray(value.notes)) throw fault('case');
  return {
    statement: str(value.statement) ? value.statement : CASE_STATEMENT,
    case: narrowCaseSummary(value.case),
    items: value.items.map(narrowCaseItem),
    notes: value.notes.map(narrowNote),
  };
}

// --- Routes ---------------------------------------------------------------------------

const enc = encodeURIComponent;

/** The subject a case list can be narrowed to: the cases that hold it as an active item. */
export type CaseSubjectRef = { kind: CaseItemKind; subjectId: string };

export async function listCases(subject?: CaseSubjectRef | null, limit = 200, signal?: AbortSignal): Promise<CaseList> {
  const params = new URLSearchParams();
  if (subject) {
    params.set('subjectKind', subject.kind);
    params.set('subjectId', subject.subjectId.toLowerCase());
  }
  params.set('limit', String(limit));
  return narrowCaseList(await apiRequest<unknown>('/api/cases?' + params.toString(), { signal }));
}

export async function getCase(caseId: string, signal?: AbortSignal): Promise<CaseDetail> {
  return narrowCaseDetail(await apiRequest<unknown>('/api/cases/' + enc(caseId), { signal }));
}

export async function createCase(title: string, purpose?: string | null): Promise<CaseSummary> {
  const body = { title, ...(purpose && purpose.trim() ? { purpose } : {}) };
  return narrowCaseSummary(await apiJson<unknown>('/api/cases', 'POST', body));
}

export async function addCaseItem(caseId: string, item: CaseSubjectRef & { note?: string | null }): Promise<CaseItem> {
  const body = { kind: item.kind, subjectId: item.subjectId.toLowerCase(), ...(item.note && item.note.trim() ? { note: item.note } : {}) };
  return narrowCaseItem(await apiJson<unknown>('/api/cases/' + enc(caseId) + '/items', 'POST', body));
}

export async function removeCaseItem(caseId: string, itemId: string, note?: string | null): Promise<CaseItem> {
  const body = note && note.trim() ? { note } : {};
  return narrowCaseItem(await apiJson<unknown>('/api/cases/' + enc(caseId) + '/items/' + enc(itemId) + '/remove', 'POST', body));
}

export async function addCaseNote(caseId: string, body: string): Promise<CaseNote> {
  return narrowNote(await apiJson<unknown>('/api/cases/' + enc(caseId) + '/notes', 'POST', { body }));
}

/** The operator's word for an item kind. */
export function caseItemKindLabel(kind: string): string {
  switch (kind) {
    case 'Track': return 'Track';
    case 'AnalyticEvent': return 'Event';
    case 'Entity': return 'Entity';
    default: return kind;
  }
}
