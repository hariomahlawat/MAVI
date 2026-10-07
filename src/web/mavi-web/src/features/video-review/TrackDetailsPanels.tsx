import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError } from '../../api/client';
import { getRunAttestation } from '../../api/processing';
import { objectClassLabel, type TrackDetail } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import KeyValue from '../../shared/components/KeyValue';
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatConfidence, formatOffset, frameRateText } from '../../shared/format/format';
import { representativeObservation } from './evidenceSet';

export function TrackSummary({ detail, displayTimeZoneId }: { detail: TrackDetail; displayTimeZoneId?: string }) {
  return (
    <KeyValue
      grid
      items={[
        { label: 'Object class', value: objectClassLabel(detail) },
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
  // The Evidence Set's rank 0, the same Observation the strip and the player use.
  const representative = representativeObservation(detail);
  return (
    <KeyValue
      items={[
        { label: 'Track ID', value: detail.id, mono: true },
        { label: 'Local track', value: detail.localTrackNumber },
        { label: 'Review status', value: <StatusBadge status={detail.reviewStatus} /> },
        { label: 'Video duration', value: formatDuration(detail.video.durationMs) },
        { label: 'Resolution', value: `${detail.video.width}×${detail.video.height} · ${frameRateText(detail.video.frameRateNumerator, detail.video.frameRateDenominator)}` },
        { label: 'Display timezone', value: displayTimeZoneId ?? 'UTC fallback', mono: true },
        ...(representative
          ? [
            { label: 'Source frame', value: representative.sourceFrameNumber },
            { label: 'Video offset', value: formatOffset(representative.videoOffsetMs, 'tenths') },
            { label: 'Representative confidence', value: formatConfidence(representative.confidence) },
            { label: 'Quality score', value: representative.qualityScore.toFixed(3) },
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
            {/* Requested only once the disclosure opens, so it is a region
                only from then on (§37.1, panel). */}
            {open || attestation.data !== undefined ? (
              <StateRegion
                kind="panel"
                state={fromQuery(attestation)}
                label="run attestation"
                loadingLabel="Loading attestation…"
                unavailableMessage={(error) => describeError(error, 'Run attestation could not be loaded.')}
                degradedMessage="Showing the last known run attestation; refreshing failed."
                onRetry={() => void attestation.refetch()}
              >
                {(record) => (
              <div className="stack">
                <KeyValue
                  items={[
                    { label: 'Verification', value: <StatusBadge status={record.verificationStatus === 'verified' ? 'Confirmed' : undefined} tone={record.verificationStatus === 'verified' ? 'ok' : 'neutral'}>{record.verificationStatus}</StatusBadge> },
                    { label: 'Device', value: `${record.actualDevice} · policy ${record.configuredDevicePolicy}${record.deviceResolutionReason ? ` (${record.deviceResolutionReason})` : ''}` },
                    { label: 'GPU', value: record.gpu ? `${record.gpu.name} · driver ${record.gpu.driverVersion} · CUDA ${record.gpu.cudaRuntimeVersion}` : 'CPU only' },
                    { label: 'Runtime variant', value: record.runtimeVariant, mono: true },
                    { label: 'Model', value: `${record.modelId} ${record.modelVersion}` },
                    { label: 'Checkpoint', value: record.checkpointSha256, mono: true },
                    { label: 'Runtime profile', value: `${record.runtimeProfileId} · ${record.runtimeProfileSha256.slice(0, 12)}…`, mono: true },
                    { label: 'Platform', value: `${record.platform.system} ${record.platform.release} · Python ${record.platform.pythonVersion}` },
                    { label: 'Frames / tracks', value: `${record.framesProcessed.toLocaleString()} / ${record.tracksCreated}` },
                    { label: 'Processing time', value: formatDuration(record.processingDurationMs) },
                    { label: 'Build', value: `${record.maviBuild} @ ${record.maviCommit.slice(0, 12)}`, mono: true },
                  ]}
                />
              </div>
                )}
              </StateRegion>
            ) : null}
          </div>
        </details>
      </div>
    </Panel>
  );
}
