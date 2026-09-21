import type { FormEvent } from 'react';
import type { Camera } from '../../api/cameras';
import type { TrackObjectClass } from '../../api/tracks';
import type { VideoAsset } from '../../api/videos';
import Button from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import type { SearchFieldErrors } from './searchValidation';

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
  errors: SearchFieldErrors;
  onDraftChange: (patch: Partial<SearchDraft>, touched?: { time?: 'from' | 'to'; numeric?: 'duration' | 'confidence' }) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onReset: () => void;
  cameras: Camera[] | undefined;
  videos: VideoAsset[] | undefined;
  videosUnavailable?: boolean;
  displayTimeZoneId: string | undefined;
};

/**
 * The committed-filter form (§4.4): grouped field sections that scroll as one
 * column, with Search and Reset pinned at the foot.
 *
 * Three things changed in UI-4 and each is structural rather than cosmetic.
 *
 * The rail no longer scrolls itself. It used to be a `.panel` with its own
 * `overflow-y: auto` inside the region that also scrolls, which is two scroll
 * owners for one column: the section headings were laid out against one box and
 * painted against the other, which is how `THRESHOLDS` came to land on the
 * label beneath it at 1366 (§26's `RAIL_OVERLAP`). The archetype's
 * `.workspace__rail` owns the scroll now and the form simply flows.
 *
 * Every control is a `Field`, so a refused value is stated on the field that
 * earned it with `aria-invalid` and an associated message, rather than as one
 * page-level sentence about "search filters" (§10, §21, §23).
 *
 * No field is marked optional, which is a deliberate departure from §21's
 * "optional fields are marked". §21 marks the exception; in a filter rail every
 * field is optional and an empty rail is a valid search, so marking all seven
 * marks nothing while lengthening seven labels the operator scans.
 *
 * The committed-scope chips have left the rail entirely. They describe what the
 * *results* are, not what the operator is about to ask for, so they belong at
 * the head of the results column (§11) — putting them here made the rail read
 * as though removing a chip and editing a field were the same kind of act.
 */
export default function SearchFilterRail({
  draft,
  errors,
  onDraftChange,
  onSubmit,
  onReset,
  cameras,
  videos,
  videosUnavailable = false,
  displayTimeZoneId,
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

  const timeHelp = displayTimeZoneId
    ? <>Entered in <code>{displayTimeZoneId}</code>.</>
    : 'Display timezone is unavailable, so times cannot be edited.';

  return (
    <form className="filter-rail" onSubmit={onSubmit} noValidate aria-label="Search filters">
      <section className="filter-rail__section" aria-labelledby="filter-scope">
        <h2 id="filter-scope">Scope</h2>
        <Field label="Camera">
          {(control) => (
            <select {...control} value={draft.cameraId} onChange={(event) => onDraftChange({ cameraId: event.target.value })}>
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
          )}
        </Field>
        <Field
          label="Video"
          help={videosUnavailable ? 'Video list unavailable; a committed video identifier stays active.' : undefined}
        >
          {(control) => (
            <select {...control} value={draft.videoAssetId} onChange={(event) => onDraftChange({ videoAssetId: event.target.value })}>
              <option value="">Any video</option>
              {draft.videoAssetId && !selectedVideoKnown ? (
                <option value={draft.videoAssetId}>Video ID · {draft.videoAssetId}</option>
              ) : null}
              {videoOptions.map((video) => (
                <option key={video.id} value={video.id.toLowerCase()}>{video.originalFileName}</option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Object class">
          {(control) => (
            <select
              {...control}
              value={draft.objectClass}
              onChange={(event) => onDraftChange({ objectClass: event.target.value as '' | TrackObjectClass })}
            >
              <option value="">Any class</option>
              <option value="Person">Person</option>
              <option value="Vehicle">Vehicle</option>
            </select>
          )}
        </Field>
      </section>

      <section className="filter-rail__section" aria-labelledby="filter-time">
        <h2 id="filter-time">Time</h2>
        <Field label="From" error={errors.fromLocal} help={timeHelp}>
          {(control) => (
            <input
              {...control}
              type="datetime-local"
              step="1"
              value={draft.fromLocal}
              disabled={!displayTimeZoneId}
              onChange={(event) => onDraftChange({ fromLocal: event.target.value }, { time: 'from' })}
            />
          )}
        </Field>
        <Field label="To" error={errors.toLocal}>
          {(control) => (
            <input
              {...control}
              type="datetime-local"
              step="1"
              value={draft.toLocal}
              disabled={!displayTimeZoneId}
              onChange={(event) => onDraftChange({ toLocal: event.target.value }, { time: 'to' })}
            />
          )}
        </Field>
      </section>

      <section className="filter-rail__section" aria-labelledby="filter-thresholds">
        <h2 id="filter-thresholds">Thresholds</h2>
        <Field
          label="Minimum duration (seconds)"
          error={errors.minimumDurationSeconds}
          help="Up to three decimal places."
        >
          {(control) => (
            <input
              {...control}
              inputMode="decimal"
              value={draft.minimumDurationSeconds}
              onChange={(event) => onDraftChange({ minimumDurationSeconds: event.target.value }, { numeric: 'duration' })}
              placeholder="e.g. 2.5"
            />
          )}
        </Field>
        <Field
          label="Minimum confidence (%)"
          error={errors.minimumConfidencePercent}
          help="0 to 100, up to two decimal places."
        >
          {(control) => (
            <input
              {...control}
              inputMode="decimal"
              value={draft.minimumConfidencePercent}
              onChange={(event) => onDraftChange({ minimumConfidencePercent: event.target.value }, { numeric: 'confidence' })}
              placeholder="e.g. 80"
            />
          )}
        </Field>
      </section>

      {/* At the end of the column, in flow. It was briefly sticky to its
          bottom edge, which reads as free reachability and is not: the only
          moment stickiness does anything is when the rail is tall enough to
          scroll, and that is exactly the moment the bar covers the last field
          (§26 found it at 1366 with the video-outage hint in the rail). */}
      <div className="filter-rail__actions">
        <Button variant="primary" type="submit" icon="search">Search</Button>
        <Button type="button" onClick={onReset}>Reset</Button>
      </div>
    </form>
  );
}
