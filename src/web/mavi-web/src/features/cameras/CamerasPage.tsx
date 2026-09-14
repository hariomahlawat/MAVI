import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { ApiError } from '../../api/client';
import { createCamera, listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';

function cameraError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'camera_code_duplicate') return 'A camera with this code already exists.';
    return `${error.detail} (${error.code})`;
  }
  return 'Camera could not be created.';
}

export default function CamerasPage() {
  const queryClient = useQueryClient();
  const cameras = useQuery({
    queryKey: queryKeys.cameras,
    queryFn: ({ signal }) => listCameras(signal),
  });
  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    staleTime: 60_000,
  });

  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [timeZoneId, setTimeZoneId] = useState('');

  const resolvedTimeZone = timeZoneId || systemConfig.data?.displayTimeZoneId || '';

  const createMutation = useMutation({
    mutationFn: createCamera,
    onSuccess: async () => {
      setCode('');
      setName('');
      await queryClient.invalidateQueries({ queryKey: queryKeys.cameras });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedCode = code.trim();
    const normalizedName = name.trim();
    const normalizedTimeZone = resolvedTimeZone.trim();
    if (!normalizedCode || !normalizedName || !normalizedTimeZone || createMutation.isPending) return;
    createMutation.mutate({
      code: normalizedCode,
      name: normalizedName,
      timeZoneId: normalizedTimeZone,
    });
  }

  return (
    <section className="page-stack">
      <PageHeader
        title="Cameras"
        description="Register and review the authoritative camera inventory used to interpret recording-local timestamps."
      />

      <div className="two-column-grid">
        <section className="panel" aria-labelledby="camera-list-title">
          <div className="panel__header">
            <div>
              <h2 id="camera-list-title">Camera inventory</h2>
              <p>{cameras.data?.length ?? 0} registered</p>
            </div>
          </div>

          {cameras.isPending ? <LoadingState label="Loading cameras…" /> : null}
          {cameras.isError ? (
            <Alert tone="error">
              {cameras.error instanceof ApiError
                ? `${cameras.error.detail} (${cameras.error.code})`
                : 'Camera inventory is unavailable.'}
            </Alert>
          ) : null}

          {cameras.data && cameras.data.length === 0 ? (
            <div className="empty-state">
              <strong>No cameras registered</strong>
              <span>Add the first camera using the form.</span>
            </div>
          ) : null}

          {cameras.data && cameras.data.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Code</th>
                    <th scope="col">Name</th>
                    <th scope="col">Timezone</th>
                    <th scope="col">State</th>
                  </tr>
                </thead>
                <tbody>
                  {cameras.data.map((camera) => (
                    <tr key={camera.id}>
                      <td><strong>{camera.code}</strong></td>
                      <td>{camera.name}</td>
                      <td><code>{camera.timeZoneId}</code></td>
                      <td>
                        <span className={`status-pill ${camera.isActive ? 'status-pill--ok' : 'status-pill--muted'}`}>
                          {camera.isActive ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>

        <section className="panel panel--form" aria-labelledby="add-camera-title">
          <div className="panel__header">
            <div>
              <h2 id="add-camera-title">Add camera</h2>
              <p>Code, name and IANA timezone are required.</p>
            </div>
          </div>

          {createMutation.isError ? <Alert tone="error">{cameraError(createMutation.error)}</Alert> : null}
          {createMutation.isSuccess ? <Alert tone="success">Camera registered.</Alert> : null}

          <form className="form-stack" onSubmit={submit}>
            <label>
              Camera code
              <input
                value={code}
                onChange={(event) => setCode(event.target.value)}
                required
                maxLength={64}
                autoComplete="off"
                placeholder="CAM-01"
              />
            </label>
            <label>
              Camera name
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                maxLength={128}
                autoComplete="off"
                placeholder="North Gate"
              />
            </label>
            <label>
              Camera timezone (IANA, e.g. Asia/Kolkata)
              <input
                value={resolvedTimeZone}
                onChange={(event) => setTimeZoneId(event.target.value)}
                required
                autoComplete="off"
                placeholder="Asia/Kolkata"
              />
            </label>
            <p className="field-help">
              Recording local time will be interpreted using this camera timezone. Browser timezone is not used as authority.
            </p>
            <button className="button button--primary" type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? 'Adding…' : 'Add camera'}
            </button>
          </form>
        </section>
      </div>
    </section>
  );
}
