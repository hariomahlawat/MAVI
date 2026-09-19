import type { FormEvent } from 'react';
import type { Camera } from '../../api/cameras';
import type { TrackObjectClass } from '../../api/tracks';
import type { VideoAsset } from '../../api/videos';
import Button from '../../shared/components/Button';
import type { CommittedTrackSearch } from './searchState';

export type SearchDraft = {
  cameraId: string;
  videoAssetId: string;
  objectClass: '' | TrackObjectClass;
  fromLocal: string;
  toLocal: string;
  minimumDurationSeconds: string;
  minimumConfidencePercent: string;
};

export const emptyDraft: SearchDraft = {
  cameraId: '',
  videoAssetId: '',
  objectClass: '',
  fromLocal: '',
  toLocal: '',
  minimumDurationSeconds: '',
  minimumConfidencePercent: '',
};

type Props = {
  draft: SearchDraft;
  onDraftChange: (patch: Partial<SearchDraft>, touched?: { time?: 'from' | 'to'; numeric?: 'duration' | 'confidence' }) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onReset: () => void;
  cameras: Camera[] | undefined;
  videos: VideoAsset[] | undefined;
  videosUnavailable?: boolean;
  displayTimeZoneId: string | undefined;
  activeFilters: CommittedTrackSearch;
  onClearTimeScope: () => void;
  onRemoveScope: (key: 'videoAssetId' | 'processingRunId') => void;
};

/**
 * The committed-filter form. Edits stay local until Search commits them to the
 * URL; the labels are the contract the operator (and the tests) rely on.
 */
export default function SearchFilterRail({
  draft,
  onDraftChange,
  onSubmit,
  onReset,
  cameras,
  videos,
  videosUnavailable = false,
  displayTimeZoneId,
  activeFilters,
  onClearTimeScope,
  onRemoveScope,
}: Props) {
  const selectedCameraKnown = draft.cameraId
    ? cameras?.some((camera) => camera.id.toLowerCase() === draft.cameraId.toLowerCase()) ?? false
    : true;
  const selectedVideoKnown = draft.videoAssetId
    ? videos?.some((video) => video.id.toLowerCase() === draft.videoAssetId.toLowerCase()) ?? false
    : true;
  const videoOptions = (videos ?? [])
    .filter((video) => !draft.cameraId || video.cameraId.toLowerCase() === draft.cameraId.toLowerCase())
    .sort((left, right) => right.recordingStartUtc.localeCompare(left.recordingStartUtc));

  return (
    <form className="panel filter-rail" onSubmit={onSubmit} noValidate aria-label="Search filters">
      <div className="filter-rail__section">
        <h2>Scope</h2>
        <label>
          Camera
          <select value={draft.cameraId} onChange={(event) => onDraftChange({ cameraId: event.target.value })}>
            <option value="">Any camera</option>
            {draft.cameraId && !selectedCameraKnown ? (
              <option value={draft.cameraId}>Camera ID · {draft.cameraId}</option>
            ) : null}
            {cameras?.map((camera) => (
              <option key={camera.id} value={camera.id.toLowerCase()}>
                {camera.code} · {camera.name}{camera.isActive ? '' : ' · Inactive'}
              </option>
            ))}
          </select>
        </label>
        <label>
          Video
          <select value={draft.videoAssetId} onChange={(event) => onDraftChange({ videoAssetId: event.target.value })}>
            <option value="">Any video</option>
            {draft.videoAssetId && !selectedVideoKnown ? (
              <option value={draft.videoAssetId}>Video ID · {draft.videoAssetId}</option>
            ) : null}
            {videoOptions.map((video) => (
              <option key={video.id} value={video.id.toLowerCase()}>{video.originalFileName}</option>
            ))}
          </select>
        </label>
        {videosUnavailable ? <span className="field-help">Video list unavailable; a committed video identifier stays active.</span> : null}
        <label>
          Object class
          <select
            value={draft.objectClass}
            onChange={(event) => onDraftChange({ objectClass: event.target.value as '' | TrackObjectClass })}
          >
            <option value="">Any class</option>
            <option value="Person">Person</option>
            <option value="Vehicle">Vehicle</option>
          </select>
        </label>
      </div>

      <div className="filter-rail__section">
        <h2>Time</h2>
        <label>
          From
          <input
            type="datetime-local"
            step="1"
            value={draft.fromLocal}
            disabled={!displayTimeZoneId}
            onChange={(event) => onDraftChange({ fromLocal: event.target.value }, { time: 'from' })}
          />
        </label>
        <label>
          To
          <input
            type="datetime-local"
            step="1"
            value={draft.toLocal}
            disabled={!displayTimeZoneId}
            onChange={(event) => onDraftChange({ toLocal: event.target.value }, { time: 'to' })}
          />
        </label>
        <span className="field-help">Display timezone: <code>{displayTimeZoneId ?? 'Unavailable'}</code></span>
      </div>

      <div className="filter-rail__section">
        <h2>Thresholds</h2>
        <label>
          Minimum duration (seconds)
          <input
            inputMode="decimal"
            value={draft.minimumDurationSeconds}
            onChange={(event) => onDraftChange({ minimumDurationSeconds: event.target.value }, { numeric: 'duration' })}
            placeholder="e.g. 2.5"
          />
        </label>
        <label>
          Minimum confidence (%)
          <input
            inputMode="decimal"
            value={draft.minimumConfidencePercent}
            onChange={(event) => onDraftChange({ minimumConfidencePercent: event.target.value }, { numeric: 'confidence' })}
            placeholder="e.g. 80"
          />
        </label>
      </div>

      {(activeFilters.fromUtc || activeFilters.toUtc) ? (
        <div className="filter-rail__section chip-row" aria-label="Active time scope">
          <span className="chip">
            <span className="truncate">Time · {activeFilters.fromUtc ?? 'open start'} → {activeFilters.toUtc ?? 'open end'}</span>
            <button type="button" onClick={onClearTimeScope} aria-label="Remove time scope">×</button>
          </span>
        </div>
      ) : null}

      {(activeFilters.videoAssetId || activeFilters.processingRunId) ? (
        <div className="filter-rail__section chip-row" aria-label="Active advanced scopes">
          {activeFilters.videoAssetId ? (
            <span className="chip">
              <span className="truncate">Video · {activeFilters.videoAssetId}</span>
              <button type="button" onClick={() => onRemoveScope('videoAssetId')} aria-label="Remove video scope">×</button>
            </span>
          ) : null}
          {activeFilters.processingRunId ? (
            <span className="chip">
              <span className="truncate">Run · {activeFilters.processingRunId}</span>
              <button type="button" onClick={() => onRemoveScope('processingRunId')} aria-label="Remove processing run scope">×</button>
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="filter-rail__actions">
        <Button variant="primary" type="submit" icon="search">Search</Button>
        <Button type="button" onClick={onReset}>Reset</Button>
      </div>
    </form>
  );
}
