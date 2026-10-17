/**
 * Stage 4 PR-5 (UI spec §17.2.8): the plate fixtures hold the backend's plate
 * contracts (TrackPlateContracts.cs, TrackEndpoints.ToPlates), the sweep has a
 * state for every §17.2.8 condition, and every plate region can be drawn.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import {
  EMPTY_PARTIAL_PLATE_PAGE, EXACT_PLATE_PAGE, LONG_RAW, PLATE_CROPS, PLATE_DETAILS, PLATE_PAGE, TWO_LINE_RAW, VEHICLE_PAGE,
} from '../plate-fixtures.mjs';
import { STATES } from '../states.mjs';

const crops = JSON.parse(readFileSync(new URL('../fixtures/crops.json', import.meta.url), 'utf8')).crops;
const READINESS = ['NotConfigured', 'Pending', 'Ready', 'Failed', 'Stale'];
const AGREEMENT = ['none', 'single', 'consistent', 'conflicting'];
const keys = (o) => Object.keys(o).sort();

describe('plate fixtures, shaped to the backend contracts', () => {
  it('give every detail the TrackPlatesResponse members its readiness and outcome allow', () => {
    for (const [name, detail] of Object.entries(PLATE_DETAILS)) {
      const plates = detail.plates;
      assert.equal(detail.objectClass, 'Vehicle', name);
      assert.ok(READINESS.includes(plates.readiness), name);
      assert.ok(Array.isArray(plates.texts) && Array.isArray(plates.observations), name);
      if (plates.readiness !== 'Ready') {
        // Not Ready: no facts at all (ToPlates' null-facts branch).
        assert.deepEqual(keys(plates), ['observations', 'readiness', 'texts'], name);
        assert.equal(plates.texts.length + plates.observations.length, 0, name);
        continue;
      }
      assert.ok(plates.provenance, `${name}: a Ready detail names its analysis`);
      if (plates.trackOutcome === 'Analysed') {
        assert.ok(AGREEMENT.includes(plates.agreement), name);
        assert.equal(plates.unavailableReason, undefined, name);
      } else {
        assert.equal(plates.trackOutcome, 'Unavailable', name);
        assert.equal(typeof plates.unavailableReason, 'string', name);
      }
    }
  });

  it('keep each reading as TrackPlateReadingResponse writes it, and each box inside its decoded crop', () => {
    for (const [name, { plates, observations }] of Object.entries(PLATE_DETAILS)) {
      for (const plate of plates.observations) {
        const source = observations.find((o) => o.observationId === plate.sourceObservationId);
        assert.ok(source, `${name}: the plate's source is an Observation of the Track`);
        assert.equal(plate.role, source.evidenceRole, name);
        assert.equal(plate.offsetMs, source.videoOffsetMs, name);
        const crop = PLATE_CROPS[source.evidenceArtifactId];
        assert.ok(crop, `${name}: the source crop is one the fixture server can cut`);
        const { x, y, width, height, cropWidth, cropHeight } = plate.box;
        assert.deepEqual([cropWidth, cropHeight], crop.size, name);
        for (const v of [x, y, width, height]) assert.ok(Number.isInteger(v), name);
        assert.ok(x >= 0 && y >= 0 && width > 0 && height > 0 && x + width <= cropWidth && y + height <= cropHeight, name);
        if (plate.outcome === 'Unreadable') assert.deepEqual(plate.readings, [], name);
        for (const reading of plate.readings) {
          assert.equal(reading.rawLineCount, reading.rawText.split('\n').length, name);
          if (reading.normalisationOutcome === 'ok') assert.match(reading.normalisedText, /^[A-Z0-9]+$/, name);
          else assert.deepEqual([reading.normalisedText, reading.formatClass], [undefined, undefined], name);
        }
      }
    }
    assert.equal(LONG_RAW.length, 32);
    assert.equal(TWO_LINE_RAW.split('\n').length, 2);
  });

  it('serve the source crops at boxes the 1920x1080 footage divides exactly', () => {
    for (const [artifact, crop] of Object.entries(PLATE_CROPS)) {
      assert.deepEqual(crops[artifact], { offsetMs: crop.offsetMs, boundingBox: crop.boundingBox }, artifact);
      const { x, y, width, height } = crop.boundingBox;
      assert.deepEqual([1920 * width, 1080 * height], crop.size, artifact);
      for (const v of [1920 * x, 1080 * y, 1920 * width, 1080 * height]) assert.ok(Number.isInteger(v) && v % 2 === 0, artifact);
    }
  });

  it('carry plate coverage on every plate page, its buckets partitioning the scope, and none elsewhere', () => {
    for (const page of [PLATE_PAGE, EXACT_PLATE_PAGE, EMPTY_PARTIAL_PLATE_PAGE]) {
      const c = page.plateCoverage;
      assert.equal(c.ready + c.pending + c.failed + c.stale + c.notConfigured, c.vehicleTracksInScope);
      assert.match(c.identityFingerprint, /^[0-9a-f]{64}$/);
      for (const item of page.items) {
        assert.deepEqual(keys(item.plate), ['bestPlateObservationId', 'distinctTextCount', 'matchKind', 'matchedText', 'maxConfidence', 'plateObservationCount', 'supportCount']);
        assert.ok(item.plate.supportCount <= item.plate.plateObservationCount);
      }
    }
    assert.equal(VEHICLE_PAGE.plateCoverage, undefined);
    assert.ok(VEHICLE_PAGE.items.every((item) => item.plate === undefined && item.objectClass === 'Vehicle'));
  });

  it('give the sweep a state for every §17.2.8 condition', () => {
    const served = (state) => Object.values(state.api ?? {});
    const has = (fixture) => STATES.some((state) => served(state).includes(fixture));
    for (const name of Object.keys(PLATE_DETAILS)) assert.ok(has(PLATE_DETAILS[name]), `no state serves the ${name} plate detail`);
    assert.ok(has(PLATE_PAGE), 'no state serves the plate search with partial coverage');
    assert.ok(has(EMPTY_PARTIAL_PLATE_PAGE), 'no state serves the empty plate page');
    assert.ok(STATES.some((s) => s.name.startsWith('review-plate')), 'Review hosts the plate readings too');
  });
});
