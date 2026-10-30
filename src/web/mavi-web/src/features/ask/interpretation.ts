import type { AskReference } from '../../api/ask';
import type { QueryEnvelope, StructuredQuery } from '../../api/query';
import { displayTimestamp } from '../../shared/format/format';
import { dimensionLabel, operationLabel } from '../advanced-search/queryBuilder';

/**
 * Ask MAVI's readable "Interpreted as" and its one-line answer (ADR-026 §5).
 *
 * Both are fixed templates over platform data only: the server's canonical query, the
 * names the server read from the site catalogue, and the S9 envelope. No text the
 * language model wrote reaches these functions — the response does not carry any.
 */

export type InterpretationLine = { label: string; value: string };

const UNIT_NOUNS: Record<StructuredQuery['unit'], string> = { track: 'Tracks', event: 'Events', entity: 'Entities' };

const RULE_LABELS: Record<string, string> = {
  'line-crossing': 'line crossing',
  'zone-dwell': 'zone dwell',
  'stopped-vehicle': 'stopped vehicle',
  'wrong-way': 'wrong way',
  'co-occurrence': 'co-occurrence',
  'repeated-visit': 'repeated visit',
};

function nameOf(references: AskReference[], kind: AskReference['kind'], id: string): string {
  return references.find((item) => item.kind === kind && item.id.toLowerCase() === id.toLowerCase())?.name ?? id;
}

function windowText(window: { fromUtc: string; toUtc: string }, timeZoneId: string): string {
  return `${displayTimestamp(window.fromUtc, timeZoneId)} to ${displayTimestamp(window.toUtc, timeZoneId)}`;
}

/** The query as label/value lines, in the order an operator reads a question. */
export function describeQuery(query: StructuredQuery, references: AskReference[], timeZoneId: string): InterpretationLine[] {
  const where = query.where;
  const operation = query.operation;
  const lines: InterpretationLine[] = [];

  const subject = where.objectClass
    ? `${where.objectClass}${where.objectSubclass ? ` (${where.objectSubclass})` : ''} ${UNIT_NOUNS[query.unit]}`
    : UNIT_NOUNS[query.unit];
  lines.push({ label: 'What', value: subject });

  let how = operationLabel(operation.op);
  if (operation.op === 'find') how += ` — up to ${operation.limit ?? 50}, ${operation.order ?? 'newest'} first`;
  if (operation.op === 'top') how += ` ${operation.k ?? 5} by ${dimensionLabel(operation.by ?? '').toLowerCase()}`;
  if (operation.op === 'groupBy') how += ` ${dimensionLabel(operation.by ?? '').toLowerCase()}`;
  if (operation.op === 'countDistinct') how += ` ${dimensionLabel(operation.field ?? '').toLowerCase()}`;
  if (operation.op === 'timeBucket' && operation.bucketSeconds) {
    how += operation.bucketSeconds % 3_600 === 0 ? ` per ${operation.bucketSeconds / 3_600} h` : ` per ${operation.bucketSeconds / 60} min`;
  }
  lines.push({ label: 'How', value: how });

  lines.push({ label: 'When', value: `${windowText(where.timeWindow, timeZoneId)} (${timeZoneId})` });
  if (operation.op === 'compare' && operation.baseline) {
    lines.push({ label: 'Compared with', value: windowText(operation.baseline, timeZoneId) });
  }

  lines.push({
    label: 'Cameras',
    value: where.cameraIds?.length ? where.cameraIds.map((id) => nameOf(references, 'camera', id)).join(', ') : 'every camera',
  });
  if (where.zone) {
    const relation = where.zone.relation ? ` (${where.zone.relation})` : '';
    const dwell = where.zone.minDwellMs !== undefined ? `, at least ${where.zone.minDwellMs / 1_000} s` : '';
    lines.push({ label: 'Zone', value: `${nameOf(references, 'zone', where.zone.zoneId)}${relation}${dwell}${where.zone.loitering ? ', loitering' : ''}` });
  }
  if (where.line) {
    const line = references.find((item) => item.kind === 'line' && item.id.toLowerCase() === where.line!.lineId.toLowerCase());
    const direction = where.line.direction === 'aToB' ? line?.aToBLabel ?? 'A → B' : where.line.direction === 'bToA' ? line?.bToALabel ?? 'B → A' : 'either direction';
    lines.push({ label: 'Line', value: `${line?.name ?? where.line.lineId}, ${direction}` });
  }
  if (where.attributes?.length) lines.push({ label: 'Attributes', value: where.attributes.map((item) => `${item.type} ${item.value}`).join(', ') });
  if (where.plateText) lines.push({ label: 'Plate text', value: `${where.plateText.match ?? 'contains'} "${where.plateText.text}"` });
  if (where.ruleIds?.length) lines.push({ label: 'Event rules', value: where.ruleIds.map((rule) => RULE_LABELS[rule] ?? rule).join(', ') });
  if (where.minDurationMs !== undefined) lines.push({ label: 'Duration', value: `at least ${where.minDurationMs / 1_000} s` });
  return lines;
}

/**
 * One sentence over the envelope, or null when the result needs no sentence (rows, which the table shows). It only
 * selects values the envelope carries — it never adds, counts or derives a figure — and a withheld or empty result
 * says so and states no figure.
 */
export function answerSentence(envelope: QueryEnvelope, timeZoneId: string): string | null {
  const noun = UNIT_NOUNS[envelope.unit];
  const result = envelope.result;
  switch (result.kind) {
    case 'value':
      return result.dimension
        ? `${result.value} distinct ${dimensionLabel(result.dimension).toLowerCase()} value(s) among the matching ${noun}.`
        : `${result.value} ${noun} match.`;
    case 'comparison':
      return `${result.comparison!.current} ${noun} in this window against ${result.comparison!.baseline} in the baseline (${result.comparison!.difference > 0 ? '+' : ''}${result.comparison!.difference}).`;
    case 'groups': {
      // A selection of envelope values, never a figure computed here.
      const groups = result.groups ?? [];
      if (groups.length === 0) return `No ${noun} match in this scope.`;
      const largest = [...groups].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))[0];
      return `The largest group is ${largest.label}, with ${largest.count} ${noun}.`;
    }
    case 'buckets': {
      const buckets = result.buckets ?? [];
      if (buckets.every((bucket) => bucket.count === 0)) return `No ${noun} match in any time bucket.`;
      const busiest = [...buckets].sort((a, b) => b.count - a.count || a.startUtc.localeCompare(b.startUtc))[0];
      return `The busiest bucket starts ${displayTimestamp(busiest.startUtc, timeZoneId)}, with ${busiest.count} ${noun}.`;
    }
    case 'withheld':
      return 'No figure: not every part of the scope has been analysed, and a gap is not shown as zero.';
    case 'empty':
      return `No data: ${result.message ?? 'this unit has none yet'}`;
    default:
      return null;
  }
}
