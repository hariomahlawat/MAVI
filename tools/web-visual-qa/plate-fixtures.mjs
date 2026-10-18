/**
 * Stage 4 PR-5 (UI spec §17.2.8, plan PR-5): the plate fixtures the §26 sweep
 * and the "plate search → inspect → seek" journey are served.
 *
 * Shaped to the backend's wire contracts, not to the client's types:
 * `TrackPlateContracts.cs` (TrackPlatesResponse, TrackPlateObservationResponse,
 * TrackPlateReadingResponse, TrackItemPlateResponse, PlateCoverageResponse),
 * `TrackSearchResponse.cs` and `TrackEndpoints.ToPlates`:
 *  - a run that is not Ready carries only its readiness, empty `texts` and
 *    `observations`, and no outcome, agreement or provenance;
 *  - a Ready Track carries its outcome and provenance; `agreement` only when
 *    Analysed; `unavailableReason` only when Unavailable;
 *  - a rejected reading has no `normalisedText` and no `formatClass`; an
 *    Unreadable plate has no readings;
 *  - `plateCoverage` is on every plate-filtered page, an empty one included;
 *    its five buckets partition `vehicleTracksInScope`;
 *  - every plate box is integer pixels inside its source crop's decoded size.
 *
 * The source crops are cut by the fixture server from the generated footage
 * (crops.json `eeeeeee4`–`eeeeeee7`), at boxes chosen so the 1920×1080
 * saturated footage cuts them at exactly `cropWidth × cropHeight`: the UI draws
 * a plate region only when the decoded size matches (§17.2.4).
 *
 * Every plate string here is synthetic (ZZ…/TS…): never a real registration
 * and never dataset text.
 */
import { readFileSync } from 'node:fs';

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), 'utf8'));

const BASE_DETAIL = fixture('tracks_55555550-5555-7555-8555-555555555550');
const TRACKS = fixture('tracks');
const VIDEO = '22222222-2222-7222-8222-222222222222';
const RUN = 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb';

/** The Vehicle Track every plate state inspects (tracks.json's second item). */
export const PLATE_TRACK = '55555551-5555-7555-8555-555555555551';
const CONFLICTING_TRACK = '55555553-5555-7555-8555-555555555553';
const SINGLE_TRACK = '55555555-5555-7555-8555-555555555555';

/** The searched text (contains) and the full synthetic reading it matches. */
export const PLATE_QUERY = 'TS00';
export const PLATE_TEXT = 'ZZ00TS0001';
const CONFLICT_TEXT = 'ZZ00TS0081';

/** The source crops' integer-exact boxes in the 1920×1080 footage (crops.json). */
const CROPS = {
  Representative: { artifact: 'eeeeeee4-eeee-7eee-8eee-eeeeeeeeeee4', box: { x: 0.3125, y: 0.25, width: 0.25, height: 0.5 }, size: [480, 540] },
  NearView: { artifact: 'eeeeeee5-eeee-7eee-8eee-eeeeeeeeeee5', box: { x: 0.375, y: 0.3, width: 0.25, height: 0.4 }, size: [480, 432] },
  EarlyDiverse: { artifact: 'eeeeeee6-eeee-7eee-8eee-eeeeeeeeeee6', box: { x: 0.25, y: 0.3, width: 0.125, height: 0.4 }, size: [240, 432] },
  LateDiverse: { artifact: 'eeeeeee7-eeee-7eee-8eee-eeeeeeeeeee7', box: { x: 0.5, y: 0.25, width: 0.1875, height: 0.5 }, size: [360, 540] },
};

/** The base Evidence Set, its crops re-cut at the integer-exact boxes. */
const OBSERVATIONS = BASE_DETAIL.observations.map((observation) => {
  const crop = CROPS[observation.evidenceRole];
  return {
    ...observation,
    boundingBox: crop.box,
    evidenceArtifactId: crop.artifact,
    evidenceContentUrl: `/api/artifacts/${crop.artifact}/content`,
  };
});
const byRole = (role) => OBSERVATIONS.find((observation) => observation.evidenceRole === role);
const representative = byRole('Representative');

/** The vehicle detail without its plate block, coherent with tracks.json's item. */
function vehicleDetail(id, localTrackNumber, plates) {
  return {
    ...BASE_DETAIL,
    id,
    objectClass: 'Vehicle',
    localTrackNumber,
    observations: OBSERVATIONS,
    representative: {
      ...BASE_DETAIL.representative,
      boundingBox: representative.boundingBox,
      thumbnailArtifactId: representative.evidenceArtifactId,
      thumbnailContentUrl: representative.evidenceContentUrl,
    },
    plates,
  };
}

const PROVENANCE = {
  analysisId: 'abababab-0000-7000-8000-00000000a001',
  plateDetectorModelPackId: 'mavi-model-v2-4444444444444444444444444444444444444444444444444444444444444444',
  ocrModelPackId: 'mavi-model-v2-3333333333333333333333333333333333333333333333333333333333333333',
  normalisation: { id: 'mavi-plate-normalisation-v1', sha256: '6e505158a735a1c4c5d96ad33d08e4ddb0b98d456f0dd532a6af25de120bf935' },
  summaryPolicy: { id: 'plate-track-text-rank0', version: '1.0.0', sha256: '1fb72dd2ce254a2190cd19290bc7304342d16bdacc417a03e7589cd202eecd1f' },
  completedAtUtc: '2026-09-14T03:12:00Z',
};
const IDENTITY = '521d596506f98622a5d4e49e8b8a6f7d51c0ec7d8199f257ef097e4db723eb25';

const PLATE_DIGIT = { Representative: '0', NearView: '1', EarlyDiverse: '2', LateDiverse: '3' };

/**
 * mavi-plate-normalisation-v1 as PlateNormalisation.cs applies it to a kept
 * reading: NFKC, the frozen separators removed, ASCII upper-case; anything
 * left outside A–Z and 0–9 (or nothing left) is rejected.
 */
/** TAB, LF, CR, SPACE, '.', '/', ':', U+00B7 and '-' (last, so literal). */
const SEPARATORS = new RegExp(`[${String.fromCharCode(9, 10, 13, 32, 46, 47, 58, 0xb7, 45)}]`, 'g');
function normalise(raw) {
  const text = raw.normalize('NFKC').replace(SEPARATORS, '').replace(/[a-z]/g, (c) => c.toUpperCase());
  if (!text || !/^[A-Z0-9]+$/.test(text)) return null;
  return text;
}
const formatClassOf = (text) => (/^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$/.test(text) ? 'in-bh'
  : /^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{1,4}$/.test(text) ? 'in-standard' : 'other');

/** A reading as TrackPlateReadingResponse writes it, normalised as the backend normalises it. */
export function reading(rank, rawText, confidence) {
  const normalisedText = normalise(rawText);
  return {
    rank,
    rawText,
    rawLineCount: rawText.split('\n').length,
    ...(normalisedText ? { normalisedText } : {}),
    normalisationOutcome: normalisedText ? 'ok' : 'rejected',
    confidence,
    ...(normalisedText ? { formatClass: formatClassOf(normalisedText) } : {}),
  };
}

/** One selected plate of one source crop, as TrackPlateObservationResponse writes it. */
function plateOn(role, { outcome = 'Read', readings = [], detectorConfidence = 0.9 } = {}) {
  const source = byRole(role);
  const [cropWidth, cropHeight] = CROPS[role].size;
  const width = Math.round(cropWidth / 3);
  const height = Math.round(cropHeight / 9);
  return {
    plateObservationId: `ffffffff-ffff-7fff-8fff-fffffffffff${PLATE_DIGIT[role]}`,
    sourceObservationId: source.observationId,
    role,
    offsetMs: source.videoOffsetMs,
    sourceFrameNumber: source.sourceFrameNumber,
    timestampUtc: source.timestampUtc,
    box: { x: Math.round((cropWidth - width) / 2), y: Math.round(cropHeight * 0.7), width, height, cropWidth, cropHeight },
    detectorConfidence,
    outcome,
    readings: outcome === 'Unreadable' ? [] : readings,
  };
}

const notReady = (readiness) => ({ readiness, texts: [], observations: [] });
const analysed = (agreement, texts, observations) => ({
  readiness: 'Ready', trackOutcome: 'Analysed', agreement, texts, observations, provenance: PROVENANCE,
});
const text = (normalisedText, supportCount, maxConfidence, best) => ({ normalisedText, supportCount, maxConfidence, bestPlateObservationId: best.plateObservationId });

// --- The §17.2.8 Track-detail states --------------------------------------------

const CONSISTENT_PLATES = (() => {
  const near = plateOn('NearView', { detectorConfidence: 0.95, readings: [reading(0, 'ZZ 00 TS 0001', 0.971), reading(1, 'ZZ00TS0O01', 0.212)] });
  const rep = plateOn('Representative', { detectorConfidence: 0.91, readings: [reading(0, 'ZZ00 TS0001', 0.934)] });
  const late = plateOn('LateDiverse', { detectorConfidence: 0.84, readings: [reading(0, 'ZZ-00-TS-0001', 0.882)] });
  return analysed('consistent', [text(PLATE_TEXT, 3, 0.971, near)], [rep, near, late]);
})();

const CONFLICTING_PLATES = (() => {
  const near = plateOn('NearView', { detectorConfidence: 0.93, readings: [reading(0, 'ZZ 00 TS 0001', 0.931), reading(1, 'ZZ 00 TS 0081', 0.402), reading(2, 'ZZ0OTS0001', 0.118)] });
  const rep = plateOn('Representative', { detectorConfidence: 0.88, readings: [reading(0, 'ZZ00TS0001', 0.774)] });
  const early = plateOn('EarlyDiverse', { detectorConfidence: 0.71, readings: [reading(0, 'ZZ 00 TS 0081', 0.413)] });
  const late = plateOn('LateDiverse', { outcome: 'Unreadable', detectorConfidence: 0.52 });
  return analysed('conflicting', [text(PLATE_TEXT, 2, 0.931, near), text(CONFLICT_TEXT, 1, 0.413, early)], [rep, near, early, late]);
})();

/** A 32-character raw reading that still normalises (to 15 characters). */
export const LONG_RAW = 'ZZ 00 · TS / 0001 : ZZ - 900 . .';
const LONG_RAW_PLATES = (() => {
  const near = plateOn('NearView', { readings: [reading(0, LONG_RAW, 0.664), reading(1, 'ZZ 00 · TS / 0001 : ZZ - 900 . 8', 0.301)] });
  return analysed('single', [text('ZZ00TS0001ZZ900', 1, 0.664, near)], [near]);
})();

/** A two-line plate, its lines joined by one LF as the contract writes it. */
export const TWO_LINE_RAW = 'ZZ 00\nTS 0001';
const TWO_LINE_PLATES = (() => {
  const near = plateOn('NearView', { detectorConfidence: 0.94, readings: [reading(0, TWO_LINE_RAW, 0.912), reading(1, 'ZZ 00\nTS 0081', 0.334)] });
  const rep = plateOn('Representative', { readings: [reading(0, 'ZZ00\nTS0001', 0.871)] });
  return analysed('consistent', [text(PLATE_TEXT, 2, 0.912, near)], [rep, near]);
})();

export const PLATE_DETAILS = {
  consistent: vehicleDetail(PLATE_TRACK, 2, CONSISTENT_PLATES),
  conflicting: vehicleDetail(PLATE_TRACK, 2, CONFLICTING_PLATES),
  unreadable: vehicleDetail(PLATE_TRACK, 2, analysed('none', [], [plateOn('NearView', { outcome: 'Unreadable', detectorConfidence: 0.61 })])),
  rejected: vehicleDetail(PLATE_TRACK, 2, analysed('none', [], [plateOn('NearView', { readings: [reading(0, 'ZZ#0?', 0.274)] })])),
  pending: vehicleDetail(PLATE_TRACK, 2, notReady('Pending')),
  failed: vehicleDetail(PLATE_TRACK, 2, notReady('Failed')),
  noPlate: vehicleDetail(PLATE_TRACK, 2, analysed('none', [], [])),
  unavailable: vehicleDetail(PLATE_TRACK, 2, {
    readiness: 'Ready', trackOutcome: 'Unavailable', unavailableReason: 'evidence_missing', texts: [], observations: [], provenance: PROVENANCE,
  }),
  notConfigured: vehicleDetail(PLATE_TRACK, 2, notReady('NotConfigured')),
  stale: vehicleDetail(PLATE_TRACK, 2, notReady('Stale')),
  longRaw: vehicleDetail(PLATE_TRACK, 2, LONG_RAW_PLATES),
  twoLine: vehicleDetail(PLATE_TRACK, 2, TWO_LINE_PLATES),
};

// --- Search pages ----------------------------------------------------------------

/** A tracks.json item as TrackSearchItemResponse writes it, every required member present. */
function item(id, plate) {
  const base = TRACKS.items.find((track) => track.id === id);
  // Each vehicle row has its Representative thumbnail (a crop the fixture
  // server can cut), so "No image" on a plate surface can only be a plate
  // region the UI refused to draw.
  const thumbnail = THUMBNAILS[id];
  return {
    ...base,
    processingRunId: RUN,
    thumbnailArtifactId: thumbnail,
    thumbnailContentUrl: `/api/artifacts/${thumbnail}/content`,
    videoContentUrl: `/api/videos/${VIDEO}/content`,
    ...(plate ? { plate } : {}),
  };
}
const THUMBNAILS = {
  [PLATE_TRACK]: CROPS.Representative.artifact,
  [CONFLICTING_TRACK]: 'eeeeeee0-eeee-7eee-8eee-eeeeeeeeeee0',
  [SINGLE_TRACK]: 'eeeeeee1-eeee-7eee-8eee-eeeeeeeeeee1',
};
const itemPlate = (matchedText, matchKind, supportCount, plateObservationCount, distinctTextCount, maxConfidence, best) => ({
  matchedText, matchKind, supportCount, plateObservationCount, distinctTextCount, maxConfidence, bestPlateObservationId: best,
});

/** Partial coverage: 3 of 5 vehicle Tracks Ready, one pending, one from an earlier configuration. */
export const PARTIAL_PLATE_COVERAGE = { identityFingerprint: IDENTITY, vehicleTracksInScope: 5, ready: 3, pending: 1, failed: 0, stale: 1, notConfigured: 0 };

/** `plateText=TS00` (contains): a consistent, a conflicting and a single reading. */
export const PLATE_PAGE = {
  items: [
    item(PLATE_TRACK, itemPlate(PLATE_TEXT, 'contains', 3, 3, 1, 0.971, CONSISTENT_PLATES.texts[0].bestPlateObservationId)),
    item(CONFLICTING_TRACK, itemPlate(PLATE_TEXT, 'contains', 2, 4, 2, 0.931, CONFLICTING_PLATES.texts[0].bestPlateObservationId)),
    item(SINGLE_TRACK, itemPlate(CONFLICT_TEXT, 'contains', 1, 1, 1, 0.413, 'ffffffff-ffff-7fff-8fff-fffffffffff9')),
  ],
  nextCursor: null,
  plateCoverage: PARTIAL_PLATE_COVERAGE,
};

/** `plateText=ZZ00TS0001&plateMatch=exact`: the journey's one match. */
export const EXACT_PLATE_PAGE = {
  items: [item(PLATE_TRACK, itemPlate(PLATE_TEXT, 'exact', 3, 3, 1, 0.971, CONSISTENT_PLATES.texts[0].bestPlateObservationId))],
  nextCursor: null,
  plateCoverage: PARTIAL_PLATE_COVERAGE,
};

/** A plate search that matched nothing while coverage is incomplete: never "no such vehicle". */
export const EMPTY_PARTIAL_PLATE_PAGE = { items: [], nextCursor: null, plateCoverage: PARTIAL_PLATE_COVERAGE };

/** An ordinary vehicle search (no plate predicate): no plate members, no plate coverage. */
export const VEHICLE_PAGE = {
  items: TRACKS.items.filter((track) => track.objectClass === 'Vehicle').map((track) => item(track.id)),
  nextCursor: null,
};

/** The crops.json entries the plate details' source crops need (asserted against the file by the harness tests). */
export const PLATE_CROPS = Object.fromEntries(Object.values(CROPS).map((crop) => {
  const observation = OBSERVATIONS.find((o) => o.evidenceArtifactId === crop.artifact);
  return [crop.artifact, { offsetMs: observation.videoOffsetMs, boundingBox: crop.box, size: crop.size }];
}));
