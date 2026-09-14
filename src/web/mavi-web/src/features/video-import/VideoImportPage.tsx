import { useMutation, useQuery } from '@tanstack/react-query';
import { useMemo, useState, type FormEvent } from 'react';
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
import Alert from '../../shared/components/Alert';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';

type ImportWorkflowInput = {
  cameraId: string;
  recordingStartLocal: string;
  file: File;
};

type ImportWorkflowOutcome = {
  videoAssetId: string;
  recovered: boolean;
  queueWarning?: string;
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
  return `${known[error.code] ?? error.detail} (${error.code})`;
}

async function runImportWorkflow(input: ImportWorkflowInput): Promise<ImportWorkflowOutcome> {
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
    const existingStatus = await getProcessingStatus(videoAssetId);
    if (isProcessingActive(existingStatus) || existingStatus.videoStatus === 'Processed') {
      return { videoAssetId, recovered };
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
        queueWarning: `${error.detail} (${error.code})`,
      };
    }
    return {
      videoAssetId,
      recovered,
      queueWarning: 'The video was imported, but processing could not be queued.',
    };
  }
}

export default function VideoImportPage() {
  const navigate = useNavigate();
  const cameras = useQuery({
    queryKey: queryKeys.cameras,
    queryFn: ({ signal }) => listCameras(signal),
  });
  const activeCameras = useMemo(() => cameras.data?.filter((camera) => camera.isActive) ?? [], [cameras.data]);

  const [cameraId, setCameraId] = useState('');
  const [recordingStartLocal, setRecordingStartLocal] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const selectedCamera = activeCameras.find((camera) => camera.id === cameraId);

  const workflow = useMutation({
    mutationFn: runImportWorkflow,
    onSuccess: (result) => {
      navigate(`/processing/${result.videoAssetId}`, {
        state: {
          notice: result.queueWarning
            ? `Import is safe, but processing was not queued: ${result.queueWarning}`
            : result.recovered
              ? 'Existing import recovered. Authoritative processing state was resumed.'
              : 'Video imported and processing queued.',
        },
      });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);
    if (!cameraId || !recordingStartLocal || !file) {
      setValidationError('Camera, recording local date/time and MP4 file are required.');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.mp4')) {
      setValidationError('Select an MP4 file.');
      return;
    }
    if (file.size > MAXIMUM_VIDEO_FILE_SIZE_BYTES) {
      setValidationError('The selected video exceeds the 3 GiB import limit.');
      return;
    }
    if (workflow.isPending) return;
    workflow.mutate({ cameraId, recordingStartLocal, file });
  }

  return (
    <section className="page-stack">
      <PageHeader
        title="Import video"
        description="Register source MP4 media and queue authoritative processing without converting camera-local wall time in the browser."
      />

      <section className="panel panel--form panel--narrow">
        {cameras.isPending ? <LoadingState label="Loading active cameras…" /> : null}
        {cameras.isError ? <Alert tone="error">Camera inventory is unavailable.</Alert> : null}
        {validationError ? <Alert tone="warning">{validationError}</Alert> : null}
        {workflow.isError ? <Alert tone="error">{importError(workflow.error)}</Alert> : null}

        <form className="form-stack" onSubmit={submit}>
          <label>
            Camera
            <select value={cameraId} onChange={(event) => setCameraId(event.target.value)} required>
              <option value="">Select active camera</option>
              {activeCameras.map((camera) => (
                <option key={camera.id} value={camera.id}>
                  {camera.code} — {camera.name}
                </option>
              ))}
            </select>
          </label>

          <label>
            Recording local date/time
            <input
              type="datetime-local"
              value={recordingStartLocal}
              onChange={(event) => setRecordingStartLocal(event.target.value)}
              required
            />
          </label>

          <div className="field-help field-help--boxed">
            {selectedCamera
              ? <>Interpreted in <code>{selectedCamera.timeZoneId}</code> for {selectedCamera.code}.</>
              : 'Select a camera to see the authoritative recording timezone.'}
          </div>

          <label>
            MP4 file
            <input
              type="file"
              accept=".mp4,video/mp4"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              required
            />
          </label>
          <p className="field-help">Phase-1 single-request import limit: 3 GiB. Backend media validation remains authoritative.</p>

          <button className="button button--primary" type="submit" disabled={workflow.isPending || cameras.isPending}>
            {workflow.isPending ? 'Importing and queueing…' : 'Import and process'}
          </button>
        </form>
      </section>
    </section>
  );
}
