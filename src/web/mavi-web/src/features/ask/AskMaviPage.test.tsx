import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ask, getAskStatus, type AskResponse, type AskStatus } from '../../api/ask';
import { ApiError } from '../../api/client';
import { runQuery, type QueryEnvelope } from '../../api/query';
import { displayTimestamp, formatOffset } from '../../shared/format/format';
import { renderWithApp } from '../../test/renderWithApp';
import AskMaviPage, { ACCURACY, AskAnswer, AskResult } from './AskMaviPage';
import { answerSentence, describeQuery } from './interpretation';

vi.mock('../../api/ask', async () => {
  const actual = await vi.importActual<typeof import('../../api/ask')>('../../api/ask');
  return { ...actual, ask: vi.fn(), getAskStatus: vi.fn() };
});
vi.mock('../../api/query', async () => {
  const actual = await vi.importActual<typeof import('../../api/query')>('../../api/query');
  return { ...actual, runQuery: vi.fn() };
});

const zone = 'Asia/Kolkata';
const cameraId = '01a18a8b-f792-71a6-9330-423b120b5197';
const lineId = '01a18a8b-fb1d-712e-905e-73b8fc3837d1';
const videoId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21420';

const status: AskStatus = {
  bound: true, answering: true, reason: null, modelPackId: 'mavi-language-v1-abc', modelId: 'qwen2-5-1-5b-instruct',
  quantisation: 'Q8_0', runtimeId: 'llamacpp-b12000-win-x64', device: 'cuda:0', deviceReason: 'auto_cuda_gpu_present',
  promptTemplateVersion: 'mavi-ask-prompt-v2', siteTimeZoneId: zone, disclosure: 'PoC profile, Development evidence, not Production-qualified.',
};

const resolvedQuery: AskResponse['interpretation'] extends infer T ? T extends { resolvedQuery: infer Q } ? Q : never : never = {
  contractVersion: 'mavi-query-v1',
  unit: 'track',
  where: {
    timeWindow: { fromUtc: '2026-10-01T03:30:00.000Z', toUtc: '2026-10-01T04:30:00.000Z' },
    cameraIds: [cameraId],
    objectClass: 'Vehicle',
    line: { lineId, direction: 'bToA' },
  },
  operation: { op: 'timeBucket', bucketSeconds: 900 },
  requireCompleteCoverage: false,
};

function envelope(result: QueryEnvelope['result'], unit: QueryEnvelope['unit'] = 'track'): QueryEnvelope {
  return {
    contractVersion: 'mavi-query-v1',
    resolvedQuery,
    queryFingerprint: 'ab12'.repeat(16),
    unit,
    operation: resolvedQuery.operation.op,
    snapshot: { visibilitySequence: 77, evaluatedAtUtc: '2026-10-30T10:00:00Z', similaritySnapshot: null },
    identity: {
      cameras: [{ cameraId, cameraCode: 'POC-S2-05', cameraName: 'PoC demo 05 - Archway gate', sceneRevisionId: null, sceneRevisionNumber: 1, algorithmVersion: 'stage3-v1' }],
      attributeIdentityFingerprint: null, attributeDisclosure: null, plateIdentityFingerprint: null, embeddingIdentityFingerprint: null, eventCatalogueVersion: null,
    },
    coverage: { complete: true, components: [] },
    result,
    disclosure: 'PoC profile, Development evidence, not Production-qualified.',
  };
}

const empty = { tracks: null, events: null, truncation: null, value: null, dimension: null, groups: null, bucketSeconds: null, buckets: null, comparison: null, reason: null, message: null };

const RESULTS: Record<string, QueryEnvelope['result']> = {
  value: { ...empty, kind: 'value', value: 37 },
  distinct: { ...empty, kind: 'value', value: 4, dimension: 'camera' },
  groups: { ...empty, kind: 'groups', dimension: 'camera', groups: [{ key: cameraId, label: 'POC-S2-05', count: 19 }, { key: 'x', label: 'POC-S2-07', count: 233 }] },
  buckets: {
    ...empty, kind: 'buckets', bucketSeconds: 900,
    buckets: [
      { startUtc: '2026-10-01T03:30:00Z', endUtc: '2026-10-01T03:45:00Z', count: 3 },
      { startUtc: '2026-10-01T03:45:00Z', endUtc: '2026-10-01T04:00:00Z', count: 11 },
      { startUtc: '2026-10-01T04:00:00Z', endUtc: '2026-10-01T04:15:00Z', count: 0 },
      { startUtc: '2026-10-01T04:15:00Z', endUtc: '2026-10-01T04:30:00Z', count: 5 },
    ],
  },
  comparison: { ...empty, kind: 'comparison', comparison: { current: 41, baseline: 29, difference: 12 } },
  rows: {
    ...empty, kind: 'rows',
    truncation: { truncated: true, returned: 1, total: 58, limit: 1, totalIsLowerBound: false },
    tracks: [{
      trackId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21430', cameraId, cameraCode: 'POC-S2-05', cameraName: 'PoC demo 05 - Archway gate',
      videoAssetId: videoId, processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21440', objectClass: 'Vehicle', objectSubclass: 'car',
      startTimestampUtc: '2026-10-01T03:51:07.250Z', endTimestampUtc: '2026-10-01T03:51:40Z', startOffsetMs: 67_250, durationMs: 32_750,
      meanConfidence: 0.83, thumbnailArtifactId: null, similarityScore: null,
    }],
  },
  withheld: { ...empty, kind: 'withheld', reason: 'coverage_incomplete', message: 'not every part of the scope has been analysed.' },
  emptyEntity: { ...empty, kind: 'empty', reason: 'entity_data_unavailable', message: 'No Entity exists until ReID candidates are confirmed.' },
};

/** What Ask returns (D-S10-10): the proposed query only, never an answer. */
function proposed(): AskResponse {
  return {
    question: 'How many vehicles entered through the Arch gate between 09:00 and 10:00, per 15 minutes?',
    referenceDate: '2026-10-01',
    siteTimeZoneId: zone,
    outcome: 'interpreted',
    interpretation: {
      resolvedQuery,
      queryFingerprint: 'ab12'.repeat(16),
      references: [
        { kind: 'camera', id: cameraId, name: 'PoC demo 05 - Archway gate', cameraId, cameraName: 'PoC demo 05 - Archway gate', aToBLabel: null, bToALabel: null },
        { kind: 'line', id: lineId, name: 'Arch gate', cameraId, cameraName: 'PoC demo 05 - Archway gate', aToBLabel: 'Exit', bToALabel: 'Entry' },
      ],
    },
    refusal: null,
    model: {
      modelPackId: 'mavi-language-v1-abc', modelId: 'qwen2-5-1-5b-instruct', quantisation: 'Q8_0', runtimeId: 'llamacpp-b12000-win-x64',
      device: 'cuda:0', promptTemplateVersion: 'mavi-ask-prompt-v2', promptSha256: 'c'.repeat(64), temperature: 0, topK: 1, seed: 42,
      promptTokens: 6400, generatedTokens: 120,
    },
    timings: { translationMs: 4321, totalMs: 4333 },
    disclosure: 'PoC profile, Development evidence, not Production-qualified.',
  };
}

/**
 * The numbers the answer may show: the envelope's numeric fields, the declared formatting of its instants (site-local
 * timestamps) and durations, and the digits inside its display names (camera codes and names, group labels). Ids and
 * fingerprints contribute nothing, so a figure the browser computed cannot hide among their digits.
 */
const OPAQUE = /^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32,})$/i;
const INSTANT = /^\d{4}-\d{2}-\d{2}T/;
const NAME_KEYS = new Set(['label', 'cameraCode', 'cameraName', 'zoneName', 'lineName', 'key', 'message']);

function groundedNumbers(value: QueryEnvelope): Set<string> {
  const allowed = new Set<string>();
  const add = (text: string) => { for (const token of text.match(/\d+(?:\.\d+)?/g) ?? []) allowed.add(token); };
  const walk = (node: unknown, key = '') => {
    if (Array.isArray(node)) node.forEach((item) => walk(item, key));
    else if (node && typeof node === 'object') Object.entries(node).forEach(([name, item]) => walk(item, name));
    else if (typeof node === 'number') {
      add(String(node));
      if (key.endsWith('Ms')) add(formatOffset(node));
      if (key === 'similarityScore') add(node.toFixed(3));
    } else if (typeof node === 'string' && !OPAQUE.test(node)) {
      if (INSTANT.test(node)) add(displayTimestamp(node, zone));
      else if (NAME_KEYS.has(key)) add(node);
    }
  };
  walk(value);
  return allowed;
}

/** Each rendered text node on its own, so adjacent cells do not run together into one token. */
function textNodes(root: Element): string[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts: string[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) texts.push(node.textContent ?? '');
  return texts;
}

function renderAnswer(response: AskResponse) {
  return renderWithApp(<AskAnswer response={response} />);
}

/** The answer of a query the operator ran. */
function renderResult(value: QueryEnvelope) {
  return render(<MemoryRouter><AskResult envelope={value} timeZoneId={zone} /></MemoryRouter>);
}

describe('Ask MAVI grounding (ADR-026 §5)', () => {
  it.each(Object.keys(RESULTS))('shows no number in the %s answer that the envelope does not carry', (name) => {
    const value = envelope(RESULTS[name]);
    renderResult(value);
    const answerPanel = screen.getByRole('heading', { name: 'Answer' }).closest('section') ?? document.body;
    const allowed = groundedNumbers(value);
    const shown = textNodes(answerPanel).flatMap((text) => text.match(/\d+(?:\.\d+)?/g) ?? []);
    expect(shown.filter((token) => !allowed.has(token))).toEqual([]);
  });

  it('would catch a figure the browser computed (a sum is not an envelope value)', () => {
    const groups = groundedNumbers(envelope(RESULTS.groups));
    expect(groups.has('252')).toBe(false); // 19 + 233
    const buckets = groundedNumbers(envelope(RESULTS.buckets));
    expect(buckets.has('19')).toBe(false); // 3 + 11 + 0 + 5
    expect(groups.has('233') && buckets.has('11')).toBe(true);
  });

  it('writes the summary sentence only from envelope values: a selection, never a sum', () => {
    expect(answerSentence(envelope(RESULTS.value), zone)).toBe('37 Tracks match.');
    expect(answerSentence(envelope(RESULTS.groups), zone)).toBe('The largest group is POC-S2-07, with 233 Tracks.');
    expect(answerSentence(envelope(RESULTS.buckets), zone)).toContain('with 11 Tracks');
    expect(answerSentence(envelope(RESULTS.buckets), zone)).not.toContain('19');
    expect(answerSentence(envelope(RESULTS.comparison), zone)).toBe('41 Tracks in this window against 29 in the baseline (+12).');
    expect(answerSentence(envelope(RESULTS.withheld), zone)).toMatch(/^No figure/);
    expect(answerSentence(envelope(RESULTS.rows), zone)).toBeNull();
  });

  it('never shows a figure for a withheld or empty answer', () => {
    for (const name of ['withheld', 'emptyEntity']) {
      const { unmount } = renderResult(envelope(RESULTS[name]));
      const answerPanel = screen.getByRole('heading', { name: 'Answer' }).closest('section')!;
      expect(answerPanel.textContent).not.toMatch(/\b0\b/);
      unmount();
    }
  });

  it('interprets the query in site time with names from the catalogue references only', () => {
    const response = proposed();
    const lines = Object.fromEntries(describeQuery(response.interpretation!.resolvedQuery, response.interpretation!.references, zone).map((line) => [line.label, line.value]));
    expect(lines.What).toBe('Vehicle Tracks');
    expect(lines.Cameras).toBe('PoC demo 05 - Archway gate');
    expect(lines.Line).toBe('Arch gate, Entry');
    expect(lines.When).toContain(displayTimestamp('2026-10-01T03:30:00.000Z', zone));
    expect(lines.When).toContain(zone);
    expect(lines.How).toContain('per 15 min');
  });

  it('drills through from Track rows to Review', () => {
    renderResult(envelope(RESULTS.rows));
    const link = screen.getByRole('link', { name: 'Review Track' });
    expect(link.getAttribute('href')).toContain(`/review/video/${videoId}`);
  });
});

describe('Ask MAVI refusals', () => {
  it.each([
    ['question', 'unknown_reference', 'MAVI cannot ask that'],
    ['model', 'outside_contract', 'MAVI cannot ask that'],
    ['translation', 'plate_text_ungrounded', 'The question could not be turned into a query'],
    ['translation', 'time_offset_mismatch', 'The question could not be turned into a query'],
    ['contract', 'geometry_requires_single_camera', 'The interpreted query is outside the query contract'],
    ['runtime', 'language_unavailable', 'Ask MAVI is not available'],
  ] as const)('shows a %s refusal plainly, with no interpretation and no answer', (stage, code, heading) => {
    renderAnswer({
      ...proposed(),
      outcome: 'refused',
      interpretation: null,
      refusal: { stage, code, path: '/where/cameraIds', message: 'Platform text.' },
    });
    const refusal = screen.getByRole('alert', { name: 'Refusal' });
    expect(within(refusal).getByText(heading)).toBeInTheDocument();
    expect(within(refusal).getByText(code)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Answer' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Interpreted as' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Run' })).toBeNull();
    expect(runQuery).not.toHaveBeenCalled();
  });
});

describe('Ask MAVI proposes, the operator confirms (D-S10-10)', () => {
  beforeEach(() => {
    vi.mocked(runQuery).mockReset();
    vi.mocked(runQuery).mockResolvedValue(envelope(RESULTS.buckets));
  });

  it('shows the proposal, the accuracy and the two actions, and computes no answer before Run', () => {
    renderAnswer(proposed());
    expect(screen.getByRole('heading', { name: 'Interpreted as' })).toBeInTheDocument();
    expect(screen.getByText(new RegExp(ACCURACY.slice(0, 40)))).toBeInTheDocument();
    expect(ACCURACY).toContain('20');
    expect(ACCURACY).toContain('19');
    expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Open in Advanced Search' })).toBeEnabled();
    expect(screen.queryByRole('heading', { name: 'Answer' })).toBeNull();
    expect(runQuery).not.toHaveBeenCalled();
  });

  it('runs exactly the proposed query on Run, and only then shows the answer', async () => {
    renderAnswer(proposed());
    await userEvent.click(screen.getByRole('button', { name: 'Run' }));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(runQuery).mock.calls[0][0]).toEqual(resolvedQuery);
    expect(await screen.findByLabelText('Answer summary')).toHaveTextContent('with 11 Tracks');
  });

  it('shows a refusal of the run plainly, with no answer', async () => {
    vi.mocked(runQuery).mockRejectedValue(new ApiError({
      status: 400, code: 'query_refused', detail: 'x',
      extensions: { refusal: { code: 'unknown_reference', path: '/where/cameraIds', message: 'Unknown camera.' } },
    }));
    renderAnswer(proposed());
    await userEvent.click(screen.getByRole('button', { name: 'Run' }));
    expect(await screen.findByText('Refused: unknown_reference')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Answer' })).toBeNull();
  });

  it('says an Entity Run refused to a caller who is not an operator is for operators only', async () => {
    vi.mocked(runQuery).mockRejectedValue(new ApiError({ status: 401, code: 'unauthorized', detail: 'x', extensions: {} }));
    renderAnswer(proposed());
    await userEvent.click(screen.getByRole('button', { name: 'Run' }));
    expect(await screen.findByText('Operators only')).toBeInTheDocument();
    expect(screen.queryByText(/could not be reached/)).toBeNull();
  });

  it('cannot open a query in Advanced Search that the builder cannot hold, and says why', () => {
    const withDuration = proposed();
    withDuration.interpretation!.resolvedQuery = { ...resolvedQuery, where: { ...resolvedQuery.where, minDurationMs: 120_000 } };
    renderAnswer(withDuration);
    expect(screen.getByRole('button', { name: 'Open in Advanced Search' })).toBeDisabled();
    expect(screen.getByText(/cannot build a minimum duration/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open in Advanced Search' })).toHaveAttribute('aria-describedby', 'ask-open-reason');
    expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled();
  });
});

describe('Ask MAVI page', () => {
  beforeEach(() => {
    vi.mocked(getAskStatus).mockResolvedValue(status);
    vi.mocked(ask).mockResolvedValue(proposed());
    vi.mocked(runQuery).mockReset();
    vi.mocked(runQuery).mockResolvedValue(envelope(RESULTS.buckets));
  });

  it('asks the question as typed, with the reference date, proposes the query, and answers only after Run', async () => {
    renderWithApp(<AskMaviPage />);
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'Vehicles entering via the Arch gate per 15 minutes');
    await userEvent.type(screen.getByLabelText(/Today/), '2026-10-01');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));

    await waitFor(() => expect(ask).toHaveBeenCalledWith('Vehicles entering via the Arch gate per 15 minutes', '2026-10-01'));
    expect(await screen.findByRole('heading', { name: 'Interpreted as' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Answer summary')).toBeNull();
    expect(runQuery).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Run' }));
    expect(await screen.findByLabelText('Answer summary')).toHaveTextContent('with 11 Tracks');
    expect(screen.getAllByText(/Development evidence, not Production-qualified/).length).toBeGreaterThan(0);
  });

  it('never shows the previous answer under a new proposal', async () => {
    renderWithApp(<AskMaviPage />);
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'Vehicles per 15 minutes');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Run' }));
    await screen.findByLabelText('Answer summary');

    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), ' again');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByLabelText('Answer summary')).toBeNull());
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('shows no model branding, prompt or decoding detail on the surface (spec §17.1)', async () => {
    renderWithApp(<AskMaviPage />);
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'Vehicles per 15 minutes');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));
    await screen.findByRole('heading', { name: 'Interpreted as' });
    const text = document.body.textContent ?? '';
    for (const forbidden of ['qwen', 'Qwen', 'llama', 'Q8_0', 'prompt', 'seed', 'mavi-language-v1']) expect(text).not.toContain(forbidden);
  });

  it('says plainly when no language pack answers, and offers Advanced Search', async () => {
    vi.mocked(getAskStatus).mockResolvedValue({ ...status, answering: false, reason: 'language_unavailable' });
    renderWithApp(<AskMaviPage />);
    expect(await screen.findByText('Ask MAVI is not available on this installation.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Advanced Search' })).toHaveAttribute('href', '/query');
  });
});
