import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError } from '../../api/client';
import { getRunAttestation } from '../../api/processing';
import type { TrackDetail } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import KeyValue from '../../shared/components/KeyValue';
import LoadingState from '../../shared/components/LoadingState';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatConfidence, formatOffset, frameRateText } from '../../shared/format/format';

export function RepresentativeEvidence({ detail }: { detail: TrackDetail }) {
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  useEffect(() => {
    setThumbnailFailed(false);
  }, [detail.representative?.thumbnailContentUrl]);

  const url = detail.representative?.thumbnailContentUrl;
  return url && !thumbnailFailed ? (
    <img
      className="evidence-thumb"
      src={url}
      alt={detail.objectClass + ' representative evidence from ' + detail.camera.code}
      onError={() => setThumbnailFailed(true)}
    />
  ) : (
    <div className="evidence-thumb-placeholder" role="img" aria-label="Representative evidence unavailable">
      Representative evidence unavailable
    </div>
  );
}

export function TrackSummary({ detail, displayTimeZoneId }: { detail: TrackDetail; displayTimeZoneId?: string }) {
  return (
    <KeyValue
      grid
      items={[
        { label: 'Object class', value: detail.objectClass },
        { label: 'Camera', value: `${detail.camera.code} · ${detail.camera.name}` },
        { label: 'Track start', value: displayTimestamp(detail.startTimestampUtc, displayTimeZoneId) },
        { label: 'Track end', value: displayTimestamp(detail.endTimestampUtc, displayTimeZoneId) },
        { label: 'Track duration', value: formatDuration(detail.durationMs) },
        { label: 'In video', value: `${formatOffset(detail.startOffsetMs)} – ${formatOffset(detail.endOffsetMs)}` },
        { label: 'Detections', value: detail.detectionCount },
        { label: 'Mean confidence', value: formatConfidence(detail.meanConfidence) },
        { label: 'Max confidence', value: formatConfidence(detail.maxConfidence) },
      ]}
    />
  );
}

export function TrackIdentity({ detail, displayTimeZoneId }: { detail: TrackDetail; displayTimeZoneId?: string }) {
  return (
    <KeyValue
      items={[
        { label: 'Track ID', value: detail.id, mono: true },
        { label: 'Local track', value: detail.localTrackNumber },
        { label: 'Review status', value: <StatusBadge status={detail.reviewStatus} /> },
        { label: 'Video duration', value: formatDuration(detail.video.durationMs) },
        { label: 'Resolution', value: `${detail.video.width}×${detail.video.height} · ${frameRateText(detail.video.frameRateNumerator, detail.video.frameRateDenominator)}` },
        { label: 'Display timezone', value: displayTimeZoneId ?? 'UTC fallback', mono: true },
        ...(detail.representative
          ? [
            { label: 'Source frame', value: detail.representative.sourceFrameNumber },
            { label: 'Video offset', value: formatOffset(detail.representative.videoOffsetMs, 'tenths') },
            { label: 'Representative confidence', value: formatConfidence(detail.representative.confidence) },
            { label: 'Quality score', value: detail.representative.qualityScore.toFixed(3) },
          ]
          : []),
      ]}
    />
  );
}

/**
 * Processing provenance. The stable operator-facing identities show
 * immediately; the full attestation (model, runtime, device, GPU) is loaded on
 * demand behind a disclosure so it informs without dominating the review.
 */
export function ProvenancePanel({ detail, displayTimeZoneId }: { detail: TrackDetail; displayTimeZoneId?: string }) {
  const [open, setOpen] = useState(false);
  const attestation = useQuery({
    queryKey: queryKeys.runAttestation(detail.processingRunId),
    queryFn: ({ signal }) => getRunAttestation(detail.processingRunId, signal),
    enabled: open,
    staleTime: Infinity,
    retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 1,
  });

  return (
    <Panel title="Processing provenance" description="Which pipeline, model and device produced this Track">
      <div className="stack">
        <KeyValue
          items={[
            { label: 'Pipeline', value: detail.processing.pipelineVersion },
            { label: 'Detector', value: `${detail.processing.detectorName ?? '—'} · ${detail.processing.detectorVersion ?? '—'}` },
            { label: 'Tracker', value: `${detail.processing.trackerName ?? '—'} · ${detail.processing.trackerVersion ?? '—'}` },
            { label: 'Completed', value: displayTimestamp(detail.processing.completedAtUtc, displayTimeZoneId) },
            { label: 'Processing run', value: detail.processingRunId, mono: true },
          ]}
        />

        <details className="disclosure" onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
          <summary>Runtime attestation</summary>
          <div className="disclosure__body">
            {attestation.isPending && open ? <LoadingState label="Loading attestation…" /> : null}
            {attestation.isError ? (
              <Alert tone="warning">
                {attestation.error instanceof ApiError
                  ? `${attestation.error.detail} (${attestation.error.code})`
                  : 'Run attestation could not be loaded.'}
              </Alert>
            ) : null}
            {attestation.data ? (
              <div className="stack">
                <KeyValue
                  items={[
                    { label: 'Verification', value: <StatusBadge status={attestation.data.verificationStatus === 'verified' ? 'Confirmed' : undefined} tone={attestation.data.verificationStatus === 'verified' ? 'ok' : 'neutral'}>{attestation.data.verificationStatus}</StatusBadge> },
                    { label: 'Device', value: `${attestation.data.actualDevice} · policy ${attestation.data.configuredDevicePolicy}${attestation.data.deviceResolutionReason ? ` (${attestation.data.deviceResolutionReason})` : ''}` },
                    { label: 'GPU', value: attestation.data.gpu ? `${attestation.data.gpu.name} · driver ${attestation.data.gpu.driverVersion} · CUDA ${attestation.data.gpu.cudaRuntimeVersion}` : 'CPU only' },
                    { label: 'Runtime variant', value: attestation.data.runtimeVariant, mono: true },
                    { label: 'Model', value: `${attestation.data.modelId} ${attestation.data.modelVersion}` },
                    { label: 'Checkpoint', value: attestation.data.checkpointSha256, mono: true },
                    { label: 'Runtime profile', value: `${attestation.data.runtimeProfileId} · ${attestation.data.runtimeProfileSha256.slice(0, 12)}…`, mono: true },
                    { label: 'Platform', value: `${attestation.data.platform.system} ${attestation.data.platform.release} · Python ${attestation.data.platform.pythonVersion}` },
                    { label: 'Frames / tracks', value: `${attestation.data.framesProcessed.toLocaleString()} / ${attestation.data.tracksCreated}` },
                    { label: 'Processing time', value: formatDuration(attestation.data.processingDurationMs) },
                    { label: 'Build', value: `${attestation.data.maviBuild} @ ${attestation.data.maviCommit.slice(0, 12)}`, mono: true },
                  ]}
                />
              </div>
            ) : null}
          </div>
        </details>
      </div>
    </Panel>
  );
}
