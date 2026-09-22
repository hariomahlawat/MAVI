import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { ApiError, isGuid } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { ALGORITHM_VERSION_PATTERN, getTrack, type TrackAnalyticsIdentity } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { ContextBar, ReviewLayout } from '../../shared/workspace';
import { ProvenancePanel, RepresentativeEvidence, TrackIdentity, TrackSummary } from './TrackDetailsPanels';
import TrackEvidence from './TrackEvidence';
import TrackAnalyticsExplanation from './TrackAnalyticsExplanation';
import { buildAnalyticsEvidence } from './analyticsEvidence';
import { pinnedNames, pinnedRevision, useAnalyticsScene } from './useAnalyticsScene';
import { returnToSearchPath } from './returnContext';
import { useTrajectory } from './useTrajectory';

function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

function Invalid({ message }: { message: string }) {
  return (
    <section className="page">
      <PageHeader title="Evidence Review" />
      <Alert tone="error">{message}</Alert>
    </section>
  );
}

/**
 * What a review link says about the analytics the Track should be read against.
 *
 * Three states, because "asked for nothing" and "asked for something that cannot
 * be honoured" are different claims. A link with no identity is an ordinary
 * direct link and legitimately resolves the current revision and engine. A link
 * that *claims* an identity has made a statement about which evidence it refers
 * to, so if that statement is unreadable the only honest answers are to refuse
 * it or to ask the server about it — never to quietly answer a different
 * question with current analytics, which would make a historical link show
 * something other than what it names.
 */
type ParsedAnalyticsIdentity =
  | { kind: 'none' }
  | { kind: 'valid'; identity: TrackAnalyticsIdentity }
  | { kind: 'invalid' };

function readAnalyticsIdentity(params: URLSearchParams): ParsedAnalyticsIdentity {
  const revisions = params.getAll('sceneRevisionId');
  const versions = params.getAll('analyticsAlgorithmVersion');
  if (revisions.length === 0 && versions.length === 0) return { kind: 'none' };

  // Mirrors the API contract: exactly one well-formed revision, at most one
  // well-formed engine version, and a version never without a revision — an
  // engine alone does not name an identity, and the server refuses it too.
  if (revisions.length !== 1 || !isGuid(revisions[0])) return { kind: 'invalid' };
  if (versions.length > 1) return { kind: 'invalid' };
  const version = versions[0];
  if (version !== undefined && !ALGORITHM_VERSION_PATTERN.test(version)) return { kind: 'invalid' };

  // A revision with no version is a complete request, not a half one: it means
  // that revision read with the current engine, which the API accepts.
  return {
    kind: 'valid',
    identity: { sceneRevisionId: revisions[0].toLowerCase(), analyticsAlgorithmVersion: version },
  };
}

/** The cache key half of an identity; an unreadable claim never shares a key with "current". */
function analyticsIdentityKey(parsed: ParsedAnalyticsIdentity): string {
  if (parsed.kind === 'invalid') return 'invalid';
  if (parsed.kind === 'none' || !parsed.identity.sceneRevisionId) return '';
  const { sceneRevisionId, analyticsAlgorithmVersion } = parsed.identity;
  return sceneRevisionId + (analyticsAlgorithmVersion ? '@' + analyticsAlgorithmVersion : '');
}

export default function VideoReviewPage() {
  const { videoAssetId: rawVideoAssetId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const trackIds = searchParams.getAll('trackId');
  const rawTrackId = trackIds.length === 1 ? trackIds[0] : '';
  const validVideoId = isGuid(rawVideoAssetId);
  const validTrackId = trackIds.length === 1 && isGuid(rawTrackId);
  const videoAssetId = validVideoId ? rawVideoAssetId.toLowerCase() : '';
  const trackId = validTrackId ? rawTrackId.toLowerCase() : '';

  // The analytic identity the originating search pinned, when a link carried one
  // (plan §S; ADR-011 Decision 8): the facts reviewed are the facts that search
  // showed, never silently the camera's current revision. A link whose identity
  // cannot be read is refused rather than answered — falling back to current
  // analytics would show evidence the link does not name, and a historical or
  // superseded link would stop being reproducible.
  const parsedIdentity = readAnalyticsIdentity(searchParams);
  const analyticsIdentity = parsedIdentity.kind === 'valid' ? parsedIdentity.identity : undefined;
  const invalidIdentity = parsedIdentity.kind === 'invalid';

  const track = useQuery({
    queryKey: queryKeys.track(trackId, analyticsIdentityKey(parsedIdentity)),
    queryFn: ({ signal }) => getTrack(trackId, signal, analyticsIdentity),
    enabled: validVideoId && validTrackId && !invalidIdentity,
    retry: shouldRetryQuery,
  });

  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    enabled: validVideoId && validTrackId && !invalidIdentity,
    staleTime: 60_000,
  });

  const detail = track.data;
  const identityMismatch = Boolean(detail && detail.videoAssetId.toLowerCase() !== videoAssetId.toLowerCase());
  const trajectory = useTrajectory(
    detail && !identityMismatch ? detail.trajectoryArtifactId : null,
    detail && !identityMismatch ? detail.trajectoryContentUrl : null,
  );

  // The exact revision these facts were measured against, verified after it
  // arrives. Never the camera's current revision: a Track analysed under
  // revision 4 must be drawn over revision 4's geometry or over none.
  const usable = detail && !identityMismatch ? detail : undefined;
  const scene = useAnalyticsScene(usable?.camera.id, usable?.analytics);
  const analyticsEvidence = useMemo(
    () => buildAnalyticsEvidence(usable?.analytics, pinnedRevision(scene)),
    [usable?.analytics, scene],
  );

  if (!validVideoId) return <Invalid message="The video identifier in this route is invalid." />;
  if (!validTrackId) return <Invalid message="Exactly one valid Track identifier is required in the trackId query parameter." />;
  if (invalidIdentity) return <Invalid message="This review link names an invalid analytics identity, so the evidence it refers to cannot be identified. Open the Track again from search." />;
  if (track.error instanceof ApiError && track.error.status === 404) return <Invalid message="Track was not found." />;
  if (identityMismatch) return <Invalid message="The selected Track does not belong to the video identified by this review route." />;

  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId;
  const backToSearch = returnToSearchPath(searchParams.get('from'), videoAssetId, trackId);

  const notices = (
    <>
      {systemConfig.isError ? (
        <Alert tone="warning" actions={<Button size="sm" onClick={() => void systemConfig.refetch()}>Retry display config</Button>}>
          Display timezone is unavailable. Absolute timestamps are shown explicitly in UTC.
        </Alert>
      ) : null}
      {track.isError && !(track.error instanceof ApiError && track.error.status === 404) ? (
        <Alert tone="error">
          {track.error instanceof ApiError ? track.error.detail + ' (' + track.error.code + ')' : 'Track evidence could not be loaded.'}
        </Alert>
      ) : null}
    </>
  );
  const trackFailed = track.isError && !(track.error instanceof ApiError && track.error.status === 404);
  const hasNotice = systemConfig.isError || trackFailed;

  return (
    <section className="page page--full page--workspace">
      <ContextBar
        crumbs={detail
          ? [{ label: 'Evidence Review' }, { label: `${detail.objectClass} · Track ${detail.localTrackNumber}` }]
          : [{ label: 'Evidence Review' }]}
        status={detail ? <StatusBadge status={detail.reviewStatus} /> : undefined}
        actions={(
          <>
            <ButtonLink to={backToSearch} size="sm" icon="chevronLeft">Back to search</ButtonLink>
            <ButtonLink to="/search" size="sm" variant="ghost">Visual Search</ButtonLink>
          </>
        )}
      />

      {detail ? (
        <ReviewLayout
          notices={hasNotice ? notices : undefined}
          player={(
            <TrackEvidence
              detail={detail}
              analytics={analyticsEvidence}
              trajectory={trajectory.data}
              trajectoryError={trajectory.isError}
            />
          )}
          rail={(
            <>
              {/*
                The primary evidence summary leads the rail, so at 1366x768 it and
                the player are both in the initial viewport (section 4.5.1).
                Identity and provenance follow and may run below the fold, which
                Review is explicitly allowed to do.
              */}
              <Panel title="Track summary" description="What this Track asserts, from persisted evidence.">
                <TrackSummary detail={detail} displayTimeZoneId={displayTimeZoneId} />
              </Panel>
              {/* The analytical explanation follows the primary summary, so
                  section 4.5.1 still holds at 1366x768: the summary and the
                  player are both in the initial viewport, and the explanation
                  is the next thing the operator scrolls to. Guarded rather than
                  assumed: a detail from a server without the analytics block
                  degrades to the Slice-3 page rather than blanking it. */}
              {detail.analytics ? (
                <Panel title="Scene analytics" description="What the pinned scene revision says about this Track.">
                  <TrackAnalyticsExplanation
                    analytics={detail.analytics}
                    scene={scene}
                    geometry={pinnedNames(scene)}
                    displayTimeZoneId={displayTimeZoneId}
                  />
                </Panel>
              ) : null}
              <Panel title="Representative evidence" description="Persisted representative frame and stable Track identity.">
                <div className="stack">
                  <RepresentativeEvidence detail={detail} />
                  <TrackIdentity detail={detail} displayTimeZoneId={displayTimeZoneId} />
                </div>
              </Panel>
              <ProvenancePanel detail={detail} displayTimeZoneId={displayTimeZoneId} />
            </>
          )}
        />
      ) : (
        <div className="workspace__notices">
          {hasNotice ? notices : null}
          {track.isPending ? <LoadingState label="Loading Track evidence…" /> : null}
        </div>
      )}
    </section>
  );
}
