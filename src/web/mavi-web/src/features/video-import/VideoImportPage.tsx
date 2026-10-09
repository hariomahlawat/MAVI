import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import {
  MAXIMUM_VIDEO_FILE_SIZE_BYTES,
  getProcessingStatus,
  importVideo,
  isProcessingActive,
  queueProcessing,
} from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import { useFocusFirstInvalid } from '../../shared/forms/useFocusFirstInvalid';
import Button, { ButtonLink } from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import FileInput from '../../shared/components/FileInput';
import KeyValue from '../../shared/components/KeyValue';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatBytes } from '../../shared/format/format';
import { ContextBar, RecordLayout } from '../../shared/workspace';

type ImportWorkflowInput = {
  cameraId: string;
  recordingStartLocal: string;
  file: File;
};

export type ImportWorkflowOutcome = {
  videoAssetId: string;
  recovered: boolean;
  workflowWarning?: string;
};

function importError(error: unknown): string {
  if (!(error instanceof ApiError)) return 'The video import could not be completed.';
  const known: Record<string, string> = {
    camera_not_found: 'The selected camera no longer exists.',
    camera_inactive: 'The selected camera is inactive.',
    invalid_recording_time: 'The recording time is invalid or ambiguous in the selected camera timezone.',
    video_format_unsupported: 'Only supported MP4 video files can be imported.',
    video_container_unsupported: 'The selected file is not a supported MP4 container.',
    video_file_too_large: 'The selected video exceeds the 3 GiB import limit.',
    video_filename_invalid: 'The selected filename is invalid.',
    video_metadata_invalid: 'The video metadata could not be validated.',
    video_duplicate_unresolved: 'A duplicate was detected but its existing video record could not be resolved.',
  };
  return known[error.code]
    ? `${known[error.code]} (${error.code})`
    : describeError(error, 'The video could not be imported.');
}

export async function runImportWorkflow(input: ImportWorkflowInput): Promise<ImportWorkflowOutcome> {
  let videoAssetId: string;
  let recovered = false;

  try {
    const imported = await importVideo(input);
    videoAssetId = imported.id;
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== 'video_duplicate' || !error.videoAssetId) throw error;
    videoAssetId = error.videoAssetId;
    recovered = true;
  }

  if (recovered) {
    try {
      const existingStatus = await getProcessingStatus(videoAssetId);
      if (isProcessingActive(existingStatus) || existingStatus.videoStatus === 'Processed') {
        return { videoAssetId, recovered };
      }
    } catch (error) {
      const statusWarning = error instanceof ApiError
        ? `Existing import recovered, but processing status could not be loaded: ${error.detail} (${error.code})`
        : 'Existing import recovered, but processing status could not be loaded.';

      return {
        videoAssetId,
        recovered,
        workflowWarning: statusWarning,
      };
    }
  }

  try {
    await queueProcessing(videoAssetId);
    return { videoAssetId, recovered };
  } catch (error) {
    if (error instanceof ApiError && error.code === 'processing_already_active') {
      return { videoAssetId, recovered };
    }
    if (error instanceof ApiError) {
      return {
        videoAssetId,
        recovered,
        workflowWarning: `${error.detail} (${error.code})`,
      };
    }
    return {
      videoAssetId,
      recovered,
      workflowWarning: 'The video was imported, but processing could not be queued.',
    };
  }
}

export default function VideoImportPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const cameras = useQuery({
    queryKey: queryKeys.cameras,
    queryFn: ({ signal }) => listCameras(signal),
  });
  const activeCameras = useMemo(() => cameras.data?.filter((camera) => camera.isActive) ?? [], [cameras.data]);

  const [cameraId, setCameraId] = useState('');
  const [recordingStartLocal, setRecordingStartLocal] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [submitted, setSubmitted] = useState(false);
  // Bumped on a submit the form itself refuses, and on nothing else (§12).
  const [refusals, setRefusals] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  useFocusFirstInvalid(formRef, refusals);

  const selectedCamera = activeCameras.find((camera) => camera.id === cameraId);

  const workflow = useMutation({
    mutationFn: runImportWorkflow,
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.videos }),
        queryClient.invalidateQueries({ queryKey: queryKeys.video(result.videoAssetId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.videoProcessing(result.videoAssetId) }),
      ]);
      navigate(`/processing/${result.videoAssetId}`, {
        state: {
          notice: result.workflowWarning
            ? `Import identity is safe: ${result.workflowWarning}`
            : result.recovered
              ? 'Existing import recovered. Authoritative processing state was resumed.'
              : 'Video imported and processing queued.',
        },
      });
    },
  });

  /**
   * Field-level validation (§21). The messages are computed rather than stored
   * so that correcting a field clears its message as the operator types, which
   * a stored error only does if something remembers to clear it.
   */
  function fileProblem(): string | null {
    if (!file) return 'An MP4 file is required.';
    if (!file.name.toLowerCase().endsWith('.mp4')) return 'Select an MP4 file.';
    if (file.size > MAXIMUM_VIDEO_FILE_SIZE_BYTES) return 'The selected video exceeds the 3 GiB import limit.';
    return null;
  }

  // §21: a background refetch must not leave the draft quietly wrong. A camera
  // chosen and then deactivated (or removed) is no longer an option, so the
  // select would show its placeholder while the draft still named it and a
  // submit sent it anyway. The draft is kept; the field says what changed.
  const cameraWithdrawn = cameraId !== '' && cameras.isSuccess && !selectedCamera;
  const errors = {
    camera: cameraWithdrawn
      ? 'The selected camera is no longer active. Select another.'
      : submitted && !cameraId ? 'Select the camera this recording came from.' : null,
    recordingStartLocal: submitted && !recordingStartLocal ? 'Enter the recording date and time.' : null,
    file: submitted ? fileProblem() : null,
  };

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    if (workflow.isPending) return;
    if (!cameraId || cameraWithdrawn || !recordingStartLocal || !file || fileProblem()) {
      setRefusals((count) => count + 1);
      return;
    }
    workflow.mutate({ cameraId, recordingStartLocal, file });
  }

  // Three different answers, and §14 refuses to let them look alike: the
  // request is in flight, the request failed, or the request succeeded and the
  // deployment genuinely has no camera that can receive media.
  const blocked = cameras.isSuccess && activeCameras.length === 0;

  /**
   * Dirty is a comparison against what the form started as (§21), not a flag
   * set on the first interaction: an operator who undoes their edit is told the
   * draft is gone, and one who never made one is not warned about nothing. This
   * form starts empty in all three of its editable values, so the comparison is
   * simply whether any of them is still empty — and it stays false while the
   * form is loading, blocked or unavailable, because nothing has been entered.
   */
  const dirty = cameraId !== '' || recordingStartLocal !== '' || file !== null;

  // Each fact is stated once (§30). The recording timezone is the wall-time
  // field's own help, beside the one value it interprets (§24); the rail holds
  // what bounds the file and what happens after, and the form does not repeat it.
  const facts = (
    <Panel title="Before you import">
      <KeyValue
        items={[
          { label: 'Accepted format', value: 'MP4 container only' },
          { label: 'Maximum size', value: formatBytes(MAXIMUM_VIDEO_FILE_SIZE_BYTES) },
          { label: 'After import', value: 'Processing is queued automatically.' },
        ]}
      />
    </Panel>
  );

  // §11: one containment level. The form's panel holds the region while it
  // loads, is unavailable or is the form; with no active camera there is no
  // form for it to hold, and the hatched not-configured statement is the
  // primary region itself rather than a bordered block inside an empty panel.
  const formPanel = (region: ReactNode) => (blocked ? region : <Panel title="New import">{region}</Panel>);

  return (
    <section className="page">
      <ContextBar
        surface="import"
        status={dirty ? <StatusBadge tone="warn">Unsaved changes</StatusBadge> : null}
      />

      <RecordLayout facts={blocked ? undefined : facts}>
        {formPanel(
          // The form is one region on the camera inventory (§37.1, panel): it
          // loads, is unavailable, is empty (no active camera — a
          // not-configured state, hatched) or is the form.
          <StateRegion
            kind="panel"
            state={fromQuery(cameras)}
            label="active cameras"
            isEmpty={(all) => !all.some((camera) => camera.isActive)}
            empty={{
              icon: 'camera',
              title: 'No active camera to import against',
              hatched: true,
              body: "Media is always imported against a camera, because the camera's timezone is what interprets the recording's local time. Register or reactivate one first.",
              action: <ButtonLink to="/cameras" variant="primary">Open Cameras</ButtonLink>,
            }}
            unavailableMessage={() => 'Camera inventory is unavailable, so an import cannot be attributed to a camera.'}
            degradedMessage="Showing the last known camera inventory; refreshing failed."
            onRetry={() => cameras.refetch()}
          >
            {() => (
            <form ref={formRef} className="form-stack" onSubmit={submit} noValidate>
              {workflow.isError ? <Alert tone="error">{importError(workflow.error)}</Alert> : null}

              <Field label="Camera" error={errors.camera}>
                {(control) => (
                  <select {...control} value={cameraId} onChange={(event) => setCameraId(event.target.value)}>
                    <option value="">Select active camera</option>
                    {activeCameras.map((camera) => (
                      <option key={camera.id} value={camera.id}>
                        {camera.code} — {camera.name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>

              {/* §24: the operative timezone is visible beside the wall-time
                  field, not only in the rail, because this is the one field
                  whose meaning depends on it. The browser's zone is never the
                  authority (ADR-004). */}
              <Field
                label="Recording local date/time"
                error={errors.recordingStartLocal}
                // The native control renders in the browser's locale, which
                // §24 forbids from silently differing from the product's
                // format. It cannot be restyled, so the field states outright
                // what the product read — the operator sees the value the
                // import will actually use.
                help={selectedCamera
                  ? (
                    <>
                      {recordingStartLocal
                        ? <>Read as <strong>{recordingStartLocal.replace('T', ' ')}</strong> local time in </>
                        : <>Read as local time in </>}
                      <code>{selectedCamera.timeZoneId}</code>, the timezone of {selectedCamera.code}.
                      {' '}Your browser's timezone is not used.
                    </>
                  )
                  : "Read as local time in the selected camera's timezone, never the browser's."}
              >
                {(control) => (
                  <input
                    {...control}
                    type="datetime-local"
                    value={recordingStartLocal}
                    onChange={(event) => setRecordingStartLocal(event.target.value)}
                  />
                )}
              </Field>

              <Field label="MP4 file" error={errors.file}>
                {(control) => (
                  <FileInput {...control} accept=".mp4,video/mp4" file={file} onChange={setFile} />
                )}
              </Field>

              <div className="row">
                <Button variant="primary" type="submit" icon="upload" disabled={workflow.isPending}>
                  {workflow.isPending ? 'Importing and queueing…' : 'Import and process'}
                </Button>
              </div>
            </form>
            )}
          </StateRegion>,
        )}
      </RecordLayout>
    </section>
  );
}
