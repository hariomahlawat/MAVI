import { apiJson, apiRequest } from './client';
import type { StructuredQuery } from './query';

/**
 * The Ask MAVI client (ADR-026).
 *
 * A question goes to the server whole; the server's language role translates it into
 * one structured query of contract `mavi-query-v1` or refuses. Ask proposes and the
 * operator confirms (D-S10-10): the response carries the interpreted query only, never
 * an answer; the operator runs it through `POST /api/query`. Nothing here, and nothing in
 * a response, is model text: the interpretation is the server's canonical query, and
 * every message is platform text.
 */

export type AskStage = 'runtime' | 'question' | 'model' | 'translation' | 'contract';

export type AskReference = {
  kind: 'camera' | 'zone' | 'line';
  id: string;
  name: string;
  cameraId: string;
  cameraName: string;
  aToBLabel: string | null;
  bToALabel: string | null;
};

export type AskModel = {
  modelPackId: string | null;
  modelId: string | null;
  quantisation: string | null;
  runtimeId: string | null;
  device: string | null;
  promptTemplateVersion: string;
  promptSha256: string | null;
  temperature: number;
  topK: number;
  seed: number;
  promptTokens: number | null;
  generatedTokens: number | null;
};

export type AskResponse = {
  question: string;
  referenceDate: string;
  siteTimeZoneId: string;
  outcome: 'interpreted' | 'refused';
  interpretation: { resolvedQuery: StructuredQuery; queryFingerprint: string; references: AskReference[] } | null;
  refusal: { stage: AskStage; code: string; path: string; message: string } | null;
  model: AskModel;
  timings: { translationMs: number; totalMs: number };
  disclosure: string;
};

export type AskStatus = {
  bound: boolean;
  answering: boolean;
  reason: string | null;
  modelPackId: string | null;
  modelId: string | null;
  quantisation: string | null;
  runtimeId: string | null;
  device: string | null;
  deviceReason: string | null;
  promptTemplateVersion: string;
  siteTimeZoneId: string | null;
  disclosure: string;
};

export function getAskStatus(signal?: AbortSignal): Promise<AskStatus> {
  return apiRequest<AskStatus>('/api/ask/status', { signal });
}

export function ask(question: string, referenceDate: string | null, signal?: AbortSignal): Promise<AskResponse> {
  // Not bounded by the read timeout: a translation on a CPU or a small GPU can take minutes.
  return apiJson<AskResponse>('/api/ask', 'POST', referenceDate ? { question, referenceDate } : { question }, signal);
}

/** Where a refusal came from, in the operator's words. */
export function stageText(stage: AskStage): string {
  switch (stage) {
    case 'runtime': return 'Ask MAVI is not available';
    case 'question': return 'MAVI cannot ask that';
    case 'model': return 'MAVI cannot ask that';
    case 'translation': return 'The question could not be turned into a query';
    case 'contract': return 'The interpreted query is outside the query contract';
  }
}
