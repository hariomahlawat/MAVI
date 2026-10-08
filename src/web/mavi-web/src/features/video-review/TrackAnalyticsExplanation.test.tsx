import { cleanup, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TrackDetailAnalytics } from '../../api/tracks';
import {
  ZONE_B,
  analysedAnalytics,
  lineCrossing,
  notConfiguredAnalytics,
  sceneRevision,
  sceneTripLine,
  sceneZone,
  zoneSummary,
  zoneVisit,
} from '../../test/analyticsFixtures';
import { geometryNames } from '../../shared/evidence/analyticsLabels';
import TrackAnalyticsExplanation, { referencePointLabel } from './TrackAnalyticsExplanation';
import type { AnalyticsSceneState } from './useAnalyticsScene';

const revision = sceneRevision({
  zones: [sceneZone(), sceneZone({ zoneId: ZONE_B, name: 'Loading bay' })],
  tripLines: [sceneTripLine()],
});
const names = geometryNames(revision.zones, revision.tripLines, revision.revisionNumber);
const ready: AnalyticsSceneState = { status: 'ready', revision, names };

function show(analytics: TrackDetailAnalytics, scene: AnalyticsSceneState = ready, compact = false) {
  render(
    <TrackAnalyticsExplanation
      analytics={analytics}
      scene={scene}
      geometry={scene.status === 'ready' ? scene.names : undefined}
      compact={compact}
    />,
  );
  return screen.getByRole('region', { name: 'Scene analytics' });
}

describe('analytical identity', () => {
  it('leads with the revision and engine the facts were measured against', () => {
    const panel = show(analysedAnalytics());
    expect(panel).toHaveTextContent('Scene revision 4 · Engine v1');
    expect(panel).toHaveTextContent('Reference point');
    // An image reference point in operator words, not the wire value, and not
    // a claim about position on the ground.
    expect(panel).toHaveTextContent('Box centre');
    expect(panel).not.toHaveTextContent('bbox-centre');
  });

  it('states the identity once, in its rows, on both surfaces: no footer repeats it (F18)', () => {
    for (const compact of [false, true]) {
      const panel = show(analysedAnalytics(), ready, compact);
      expect(within(panel).getAllByText(/Scene revision 4/)).toHaveLength(1);
      expect(within(panel).getAllByText('Box centre')).toHaveLength(1);
      expect(panel).not.toHaveTextContent('reference point:');
      cleanup();
    }
    expect(show(notConfiguredAnalytics())).not.toHaveTextContent('Scene revision');
  });

  it('is titled by its host in Review and names itself in the inspector', () => {
    expect(within(show(analysedAnalytics())).queryByRole('heading', { name: 'Scene analytics' })).not.toBeInTheDocument();
    cleanup();
    expect(within(show(analysedAnalytics(), ready, true)).getByRole('heading', { name: 'Scene analytics' })).toBeInTheDocument();
  });

  it('keeps the stable revision id available without putting it in the headline', () => {
    const panel = show(analysedAnalytics());
    const disclosure = within(panel).getByText('Measurement detail').closest('details')!;
    expect(disclosure).not.toHaveAttribute('open');
    expect(disclosure).toHaveTextContent('018f3f5a-2f70-7a2b-8a12-2d02f4c21460');
    // Engineering diagnostics are subordinate, not operator headline copy.
    expect(disclosure).toHaveTextContent('Samples');
    expect(disclosure).toHaveTextContent('Gaps');
  });

  it('renders the reference point vocabulary it knows and passes through what it does not', () => {
    expect(referencePointLabel('bbox-centre')).toBe('Box centre');
    expect(referencePointLabel('bbox_centre')).toBe('Box centre');
    expect(referencePointLabel(null)).toBe('Not stated');
    expect(referencePointLabel('foot-point')).toBe('foot-point');
  });

  it('shows other identities as context without replacing the selected one', () => {
    const panel = show(analysedAnalytics({
      otherIdentities: [{
        sceneRevisionId: 'x', sceneRevisionNumber: 7, algorithmVersion: 'scene-analytics-v1',
        unitStatus: 'Completed', outcome: 'Analysed',
      }],
    }));
    expect(panel).toHaveTextContent('Also analysed');
    expect(panel).toHaveTextContent('Revision 7');
    // The selected identity still leads, and is the only one stated as the identity.
    expect(panel).toHaveTextContent('IdentityScene revision 4');
    expect(within(panel).getAllByText(/Scene revision 4/)).toHaveLength(1);
  });
});

describe('facts', () => {
  const rich = analysedAnalytics({
    zoneSummaries: [
      zoneSummary({ visitCount: 2, totalDwellMs: 140_000, loitering: true, loiteringDwellMs: 140_000 }),
      zoneSummary({ zoneId: ZONE_B, visitCount: 1, totalDwellMs: 4_000 }),
    ],
    zoneVisits: [
      zoneVisit({ visitIndex: 0, entryOffsetMs: 11_000, exitOffsetMs: 81_000, dwellMs: 70_000 }),
      zoneVisit({ visitIndex: 1, entryOffsetMs: 90_000, exitOffsetMs: 160_000, dwellMs: 70_000, closedByGap: true }),
      zoneVisit({ zoneId: ZONE_B, visitIndex: 0, entryOffsetMs: 20_000, exitOffsetMs: 24_000, dwellMs: 4_000 }),
    ],
    lineCrossings: [
      lineCrossing({ crossingIndex: 0, offsetMs: 12_500, direction: 'aToB' }),
      lineCrossing({ crossingIndex: 1, offsetMs: 30_000, direction: 'bToA' }),
    ],
    motion: {
      heading: 'NE', pathLengthNormalised: 0.42, meanDisplacementRate: 0.01,
      longestStationaryMs: 9_000, totalStationaryMs: 12_000,
      stationaryIntervals: [{ startOffsetMs: 1_000, endOffsetMs: 10_000 }, { startOffsetMs: 20_000, endOffsetMs: 23_000 }],
      stationaryZoneIds: [],
    },
  });

  it('names zones, counts visits and totals dwell', () => {
    const panel = show(rich);
    expect(panel).toHaveTextContent('Forecourt · 2 visits · dwell 2m 20s');
    expect(panel).toHaveTextContent('Loading bay · 1 visit · dwell 4s');
  });

  it('states loitering as total dwell against the threshold, not as excess', () => {
    // `loiteringDwellMs` is the *total* dwell the rule measured. Calling all of
    // it "past" the threshold overstated the excess by a whole threshold's
    // worth: 140s against a 60s rule read as though the Track had loitered 140s
    // too long, when it was 80s. The two numbers differ materially here, which
    // is the point of the case.
    const panel = show(rich);
    expect(panel).toHaveTextContent('Loitering: 2m 20s dwell against a 1m 00s threshold');
    expect(panel.textContent).not.toContain('2m 20s past');

    // Both figures are present and distinguishable, so an operator can work out
    // the excess; the UI does not silently assert it.
    expect(panel).toHaveTextContent('2m 20s');
    expect(panel).toHaveTextContent('1m 00s');
  });

  it('does not call a dwell that barely passed the threshold a long one', () => {
    const panel = show(analysedAnalytics({
      zoneSummaries: [zoneSummary({
        visitCount: 1, totalDwellMs: 61_000, loitering: true,
        loiteringDwellMs: 61_000, loiteringThresholdSeconds: 60,
      })],
    }));
    // One second over. The wording has to make that visible rather than
    // reading as "61 seconds past a 60 second threshold".
    expect(panel).toHaveTextContent('Loitering: 1m 01s dwell against a 1m 00s threshold');
  });

  it('lists each visit of a zone that was entered more than once', () => {
    // Two short visits and one long one are different behaviour with the same
    // total dwell, so the individual intervals are not collapsed.
    // Review lists them inline, as a bounded list (nothing to open).
    const panel = show(rich);
    for (const visit of [/00:11\.0 to 01:21\.0 · 1m 10s/, /01:30\.0 to 02:40\.0/]) {
      expect(within(panel).getByText(visit).closest('details')).toBeNull();
    }
    // And a visit cut short by missing samples says so rather than reading as
    // though the Track left the zone.
    expect(panel).toHaveTextContent('closed by a gap in the samples, not by leaving');
  });

  it('gives every crossing its own direction and media time', () => {
    const panel = show(rich);
    expect(panel).toHaveTextContent('Gate line · 2 crossings');
    expect(panel).toHaveTextContent('Inbound at 00:12.5');
    expect(panel).toHaveTextContent('Outbound at 00:30.0');
  });

  it('keeps a short list of crossings inline on both surfaces: direction and media time are the answer', () => {
    for (const compact of [false, true]) {
      const panel = show(rich, ready, compact);
      expect(within(panel).getByText(/Inbound at 00:12\.5/).closest('details')).toBeNull();
      expect(within(panel).getByText(/Outbound at 00:30\.0/).closest('details')).toBeNull();
      cleanup();
    }
  });

  it('bounds the crossings at five inline per panel on both surfaces, the rest behind one closed disclosure (§37.1 large data)', () => {
    const many = analysedAnalytics({
      lineCrossings: Array.from({ length: 7 }, (_, index) => lineCrossing({ crossingIndex: index, offsetMs: 10_000 + index * 1_000, direction: 'aToB' })),
    });
    for (const compact of [false, true]) {
      const panel = show(many, ready, compact);
      expect(panel).toHaveTextContent('Gate line · 7 crossings');
      const rest = within(panel).getByText('2 more crossings').closest('details')!;
      expect(rest).not.toHaveAttribute('open');
      for (const second of ['10', '11', '12', '13', '14']) {
        expect(within(panel).getByText(new RegExp(`at 00:${second}\\.0`)).closest('details')).toBeNull();
      }
      for (const second of ['15', '16']) {
        expect(within(panel).getByText(new RegExp(`at 00:${second}\\.0`)).closest('details')).toBe(rest);
      }
      cleanup();
    }
  });

  it('shares the five across lines, so a panel never lists more than five crossings inline', () => {
    const twoLines = analysedAnalytics({
      lineCrossings: [
        ...Array.from({ length: 4 }, (_, index) => lineCrossing({ crossingIndex: index, offsetMs: 10_000 + index * 1_000 })),
        ...Array.from({ length: 3 }, (_, index) => lineCrossing({ lineId: '018f3f5a-2f70-7a2b-8a12-2d02f4c214b0', crossingIndex: index, offsetMs: 30_000 + index * 1_000 })),
      ],
    });
    const panel = show(twoLines);
    const inline = Array.from(panel.querySelectorAll('li li')).filter((item) => /at \d\d:\d\d\.\d/.test(item.textContent ?? '') && !item.closest('details'));
    expect(inline).toHaveLength(5);
    expect(within(panel).getByText('2 more crossings').closest('details')).not.toHaveAttribute('open');
  });

  it('bounds Review\'s visits at five inline per panel, the rest behind one closed disclosure', () => {
    const dense = analysedAnalytics({
      zoneSummaries: [zoneSummary({ visitCount: 8, totalDwellMs: 16_000 })],
      zoneVisits: Array.from({ length: 8 }, (_, index) => zoneVisit({
        visitIndex: index, entryOffsetMs: 10_000 + index * 10_000, exitOffsetMs: 12_000 + index * 10_000, dwellMs: 2_000,
      })),
    });
    const review = show(dense);
    const rest = within(review).getByText('3 more visits').closest('details')!;
    expect(rest).not.toHaveAttribute('open');
    expect(within(review).getByText(/^00:10\.0 to 00:12\.0/).closest('details')).toBeNull();
    expect(within(review).getByText(/^00:50\.0 to 00:52\.0/).closest('details')).toBeNull();
    expect(within(review).getByText(/^01:00\.0 to 01:02\.0/).closest('details')).toBe(rest);
    cleanup();
    // The inspector keeps every visit one disclosure away, as R5 accepted.
    const inspector = show(dense, ready, true);
    expect(within(inspector).getByText('8 visits').closest('details')).not.toHaveAttribute('open');
  });

  it('names the reference point of a revision with no facts as a row, on both surfaces', () => {
    const pending = analysedAnalytics({ status: 'Pending', zoneSummaries: [], zoneVisits: [], lineCrossings: [], motion: null });
    for (const compact of [false, true]) {
      const panel = show(pending, ready, compact);
      expect(within(panel).getByText('Reference point').nextElementSibling).toHaveTextContent('Box centre');
      cleanup();
    }
  });

  it('states heading as an image direction and never as a compass bearing', () => {
    const panel = show(rich);
    expect(panel).toHaveTextContent('Up-right (image direction)');
    for (const compass of ['north', 'North', 'NE', 'north-east']) {
      expect(panel.textContent).not.toContain(compass);
    }
  });

  it('summarises stationary time with its interval count', () => {
    expect(show(rich)).toHaveTextContent('9s longest · 12s total · 2 intervals');
  });

  it('never claims an interval count the facts do not contain', () => {
    // A longest stationary period beside "0 intervals" contradicts itself.
    const panel = show(analysedAnalytics({
      motion: {
        heading: 'E', pathLengthNormalised: 0, meanDisplacementRate: 0,
        longestStationaryMs: 3_000, totalStationaryMs: 3_000,
        stationaryIntervals: [], stationaryZoneIds: [],
      },
    }));
    expect(panel).toHaveTextContent('3s longest · 3s total');
    expect(panel.textContent).not.toContain('0 intervals');
  });

  it('falls back to stable ids when the pinned geometry could not be loaded', () => {
    const panel = show(rich, { status: 'unavailable', revisionNumber: 4, reason: 'request-failed' });
    // The facts are unchanged; only their names degrade, and to an identifier
    // rather than to some other revision's wording. The operator's own words
    // for the two directions lived on the line, so those degrade with it — to
    // the neutral A/B, never to another revision's labels.
    expect(panel).toHaveTextContent('018f3f5a… · 2 visits · dwell 2m 20s');
    expect(panel).toHaveTextContent('A → B at 00:12.5');
    expect(panel).toHaveTextContent('B → A at 00:30.0');
    expect(panel.textContent).not.toContain('Inbound');
  });
});

describe('every state keeps its own words', () => {
  const states: [TrackDetailAnalytics['status'], string][] = [
    ['Unavailable', 'The analysis ran for this Track but produced no facts.'],
    ['Pending', 'This processing run has not been analysed yet'],
    ['Failed', 'The analysis of this run did not complete'],
    ['Stale', 'measured against an earlier revision or engine'],
    ['NotConfigured', 'This camera has no scene configuration'],
    ['Disabled', 'has no enabled geometry'],
  ];

  it.each(states)('explains %s distinctly', (status, expected) => {
    const panel = show(notConfiguredAnalytics({ status }), { status: 'none' });
    expect(panel).toHaveTextContent(expected);
  });

  it('never collapses two states into one generic empty message', () => {
    const messages = states.map(([status]) => {
      const { unmount } = render(
        <TrackAnalyticsExplanation analytics={notConfiguredAnalytics({ status })} scene={{ status: 'none' }} />,
      );
      const text = screen.getByRole('region', { name: 'Scene analytics' }).textContent ?? '';
      unmount();
      return text;
    });
    expect(new Set(messages).size).toBe(states.length);
  });

  it('keeps the persisted unavailable reason verbatim', () => {
    // `trajectory_too_short` is what the engine recorded; paraphrasing it would
    // lose the term an operator can search for and an engineer can trace.
    const panel = show(
      analysedAnalytics({ status: 'Unavailable', unavailableReason: 'trajectory_too_short' }),
      { status: 'none' },
    );
    expect(panel).toHaveTextContent('trajectory_too_short');
    expect(panel).toHaveTextContent('Evidence could not be analysed');
  });

  it('states a geometry failure as its own condition, not as missing facts', () => {
    const loading = show(analysedAnalytics(), { status: 'loading', revisionNumber: 4 });
    expect(loading).toHaveTextContent('Loading scene revision 4');

    render(
      <TrackAnalyticsExplanation
        analytics={analysedAnalytics()}
        scene={{ status: 'unavailable', revisionNumber: 4, reason: 'identity-mismatch' }}
      />,
    );
    const mismatch = screen.getAllByRole('region', { name: 'Scene analytics' })[1];
    // The two geometry failures are different facts: one revision could not be
    // fetched, the other came back as the wrong revision.
    expect(mismatch).toHaveTextContent('is not the one these facts were measured against');
    expect(mismatch).toHaveTextContent('The facts below are unaffected');
  });

  it('refuses to draw geometry for facts that name no complete revision', () => {
    const panel = show(
      analysedAnalytics({ sceneRevisionNumber: null }),
      { status: 'incomplete-identity' },
    );
    expect(panel).toHaveTextContent('do not name a complete scene revision');
  });
});

describe('compact mode changes density, not facts', () => {
  const analytics = analysedAnalytics({
    zoneSummaries: [zoneSummary({ visitCount: 2, totalDwellMs: 8_000 })],
    zoneVisits: [
      zoneVisit({ visitIndex: 0 }),
      zoneVisit({ visitIndex: 1, entryOffsetMs: 20_000, exitOffsetMs: 25_000, dwellMs: 5_000 }),
    ],
    lineCrossings: [lineCrossing()],
  });

  it('shows the same facts in both densities', () => {
    const readOnce = (tight: boolean) => {
      const view = render(
        <TrackAnalyticsExplanation analytics={analytics} scene={ready} geometry={names} compact={tight} />,
      );
      const text = view.getByRole('region', { name: 'Scene analytics' }).textContent ?? '';
      view.unmount();
      return text;
    };
    const full = readOnce(false);
    const compact = readOnce(true);
    for (const fact of ['Forecourt · 2 visits', 'Gate line · 1 crossing', 'Inbound at 00:12.5', '00:20.0 to 00:25.0']) {
      expect(full).toContain(fact);
      expect(compact).toContain(fact);
    }
  });

  it('only changes what starts open', () => {
    const { container } = render(<TrackAnalyticsExplanation analytics={analytics} scene={ready} geometry={names} />);
    const { container: tight } = render(
      <TrackAnalyticsExplanation analytics={analytics} scene={ready} geometry={names} compact />,
    );
    const visit = (root: HTMLElement) => Array.from(root.querySelectorAll('li'))
      .find((item) => item.textContent?.startsWith('00:20.0 to 00:25.0'))!;
    expect(visit(container).closest('details')).toBeNull();
    expect(visit(tight).closest('details')).not.toHaveAttribute('open');
  });
});
