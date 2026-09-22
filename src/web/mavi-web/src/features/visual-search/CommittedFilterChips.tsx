import type { Camera } from '../../api/cameras';
import type { VideoAsset } from '../../api/videos';
import { displayTimestamp } from '../../shared/format/format';
import {
  ZONE_RELATION_LABELS,
  crossingDirectionLabel,
  engineLabel,
  lineLabel,
  motionDirectionLabel,
  shortId,
  zoneLabel,
  type GeometryNames,
} from '../../shared/evidence/analyticsLabels';
import {
  confidenceFractionToPercentText,
  millisecondsToSecondsText,
  type CommittedTrackSearch,
} from './searchState';

/**
 * What this result set is actually a search for (§11).
 *
 * The chips sit at the head of the results column rather than in the rail,
 * because they describe the results beneath them and not the query the operator
 * is composing. Keeping the two apart is what makes the rail's Search button
 * mean one thing: the rail is the draft, the chips are the fact.
 *
 * Every committed criterion appears, including the ones the rail has no control
 * for — a `processingRunId` arrives only from a link out of Processing, and a
 * scope the operator cannot see is a scope they cannot account for. `track` is
 * not here: it is which result is open, not what was searched for.
 *
 * Identifiers are resolved to the names the operator knows. When the metadata
 * that resolves them is unavailable the chip shortens the identifier instead of
 * dropping the criterion, so a metadata outage narrows what the chip can say
 * and never what it claims is in force.
 */

export type ChipCriterion = keyof CommittedTrackSearch;

type Props = {
  filters: CommittedTrackSearch;
  cameras: Camera[] | undefined;
  videos: VideoAsset[] | undefined;
  displayTimeZoneId: string | undefined;
  /** The scene geometry that names committed zones and lines, when it is known. */
  geometry?: GeometryNames;
  onRemove: (keys: ReadonlyArray<ChipCriterion>) => void;
};

type Chip = { key: ChipCriterion; label: string; value: string; removes: ChipCriterion[] };

export function committedChips(
  filters: CommittedTrackSearch,
  cameras: Camera[] | undefined,
  videos: VideoAsset[] | undefined,
  displayTimeZoneId: string | undefined,
  geometry?: GeometryNames,
): Chip[] {
  const chips: Chip[] = [];

  if (filters.cameraId) {
    const camera = cameras?.find((item) => item.id.toLowerCase() === filters.cameraId);
    chips.push({
      key: 'cameraId',
      label: 'Camera',
      value: camera ? `${camera.code} · ${camera.name}` : shortId(filters.cameraId),
      removes: ['cameraId'],
    });
  }

  if (filters.videoAssetId) {
    const video = videos?.find((item) => item.id.toLowerCase() === filters.videoAssetId);
    chips.push({
      key: 'videoAssetId',
      label: 'Video',
      value: video ? video.originalFileName : shortId(filters.videoAssetId),
      removes: ['videoAssetId'],
    });
  }

  // Processing runs have no inventory endpoint this surface loads, so this one
  // is always an identifier. It is still shown, and still removable.
  if (filters.processingRunId) {
    chips.push({
      key: 'processingRunId',
      label: 'Processing run',
      value: shortId(filters.processingRunId),
      removes: ['processingRunId'],
    });
  }

  if (filters.objectClass) {
    chips.push({ key: 'objectClass', label: 'Class', value: filters.objectClass, removes: ['objectClass'] });
  }

  // §24 and ADR-004: an absolute time is shown in the configured display zone,
  // or explicitly labelled UTC when that zone is not known. Never the browser's.
  if (filters.fromUtc) {
    chips.push({ key: 'fromUtc', label: 'From', value: displayTimestamp(filters.fromUtc, displayTimeZoneId), removes: ['fromUtc'] });
  }
  if (filters.toUtc) {
    chips.push({ key: 'toUtc', label: 'To', value: displayTimestamp(filters.toUtc, displayTimeZoneId), removes: ['toUtc'] });
  }

  if (filters.minimumDurationMs !== undefined) {
    chips.push({
      key: 'minimumDurationMs',
      label: 'Minimum duration',
      // Stated to the precision it was committed with. `formatConfidence` and
      // `formatOffset` both round for scanning, and a threshold that reads
      // 7.1% when 7.05% is in force is a chip that lies about the search.
      value: millisecondsToSecondsText(filters.minimumDurationMs) + ' s',
      removes: ['minimumDurationMs'],
    });
  }

  if (filters.minimumConfidence !== undefined) {
    chips.push({
      key: 'minimumConfidence',
      label: 'Minimum confidence',
      value: confidenceFractionToPercentText(filters.minimumConfidence) + '%',
      removes: ['minimumConfidence'],
    });
  }

  // The analytics criteria (plan §S). Each chip removes only itself; the page
  // settles the dependency graph, so removing the zone also drops its relation
  // and dwell, and removing the revision drops the engine version pinned to it.
  // Identity keys arrive only from links and have no rail control, which makes
  // the chip the one place they are visible — and removable.
  if (filters.sceneRevisionId) {
    const number = geometry?.revisionNumber;
    chips.push({
      key: 'sceneRevisionId',
      label: 'Scene revision',
      value: number !== null && number !== undefined ? `Revision ${number}` : shortId(filters.sceneRevisionId),
      removes: ['sceneRevisionId'],
    });
  }
  if (filters.analyticsAlgorithmVersion) {
    chips.push({
      key: 'analyticsAlgorithmVersion',
      label: 'Analytics engine',
      value: engineLabel(filters.analyticsAlgorithmVersion),
      removes: ['analyticsAlgorithmVersion'],
    });
  }
  if (filters.zoneId) {
    chips.push({
      key: 'zoneId',
      label: ZONE_RELATION_LABELS[filters.zoneRelation ?? 'dwelled'],
      value: zoneLabel(filters.zoneId, geometry),
      removes: ['zoneId'],
    });
  }
  if (filters.minDwellMs !== undefined) {
    chips.push({
      key: 'minDwellMs',
      label: 'Minimum dwell',
      value: millisecondsToSecondsText(filters.minDwellMs) + ' s',
      removes: ['minDwellMs'],
    });
  }
  if (filters.lineId) {
    const line = geometry?.lines.get(filters.lineId.toLowerCase());
    chips.push({
      key: 'lineId',
      label: 'Crossed',
      value: lineLabel(filters.lineId, geometry)
        + (filters.crossingDirection ? ` · ${crossingDirectionLabel(filters.crossingDirection, line)}` : ''),
      removes: ['lineId'],
    });
    if (filters.crossingDirection) {
      chips.push({
        key: 'crossingDirection',
        label: 'Direction',
        value: crossingDirectionLabel(filters.crossingDirection, line),
        removes: ['crossingDirection'],
      });
    }
  }
  if (filters.motionDirection) {
    chips.push({
      key: 'motionDirection',
      label: 'Moving',
      value: motionDirectionLabel(filters.motionDirection),
      removes: ['motionDirection'],
    });
  }
  if (filters.minStationaryMs !== undefined) {
    chips.push({
      key: 'minStationaryMs',
      label: 'Stationary for',
      value: millisecondsToSecondsText(filters.minStationaryMs) + ' s',
      removes: ['minStationaryMs'],
    });
  }
  if (filters.loitering) {
    chips.push({
      key: 'loitering',
      label: 'Loitering',
      value: filters.zoneId ? 'in the zone' : 'in any zone',
      removes: ['loitering'],
    });
  }

  return chips;
}

export default function CommittedFilterChips({ filters, cameras, videos, displayTimeZoneId, geometry, onRemove }: Props) {
  const chips = committedChips(filters, cameras, videos, displayTimeZoneId, geometry);
  if (chips.length === 0) return null;

  return (
    <div className="results__chips chip-row" role="group" aria-label="Committed filters">
      {chips.map((chip) => (
        <span className="chip" key={chip.key}>
          <span className="truncate" title={`${chip.label}: ${chip.value}`}>
            <span className="chip__label">{chip.label}</span> {chip.value}
          </span>
          <button type="button" onClick={() => onRemove(chip.removes)} aria-label={`Remove ${chip.label.toLowerCase()} filter`}>
            ×
          </button>
        </span>
      ))}
    </div>
  );
}
