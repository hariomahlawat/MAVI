import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { ApiError } from '../../api/client';
import { createCamera, listCameras, type CreateCameraInput } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';

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
    mutationFn: (input: CreateCameraInput) => createCamera(input),
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
    <section className="page">
      <PageHeader
        title="Cameras"
        description="The authoritative camera inventory used to interpret recording-local timestamps."
      />

      <div className="split">
        <Panel
          headingId="camera-list-title"
          title="Camera inventory"
          description={`${cameras.data?.length ?? 0} registered`}
          body="flush"
        >
          {cameras.isPending ? <LoadingState label="Loading cameras…" /> : null}
          {cameras.isError ? (
            <div className="panel__body">
              <Alert tone="error">
                {cameras.error instanceof ApiError
                  ? `${cameras.error.detail} (${cameras.error.code})`
                  : 'Camera inventory is unavailable.'}
              </Alert>
            </div>
          ) : null}

          {cameras.data && cameras.data.length === 0 ? (
            <EmptyState icon="camera" title="No cameras registered">Add the first camera using the form.</EmptyState>
          ) : null}

          {cameras.data && cameras.data.length > 0 ? (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Code</th>
                    <th scope="col">Name</th>
                    <th scope="col">Timezone</th>
                    <th scope="col">State</th>
                    <th scope="col"><span className="visually-hidden">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {cameras.data.map((camera) => (
                    <tr key={camera.id}>
                      <td><strong>{camera.code}</strong></td>
                      <td>{camera.name}</td>
                      <td><code>{camera.timeZoneId}</code></td>
                      <td>
                        <StatusBadge tone={camera.isActive ? 'ok' : 'neutral'}>{camera.isActive ? 'Active' : 'Inactive'}</StatusBadge>
                      </td>
                      <td>
                        <ButtonLink size="sm" variant="ghost" icon="layers" to={`/cameras/${camera.id}/scene`}>
                          Scene
                        </ButtonLink>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </Panel>

        <Panel headingId="add-camera-title" title="Add camera" description="Code, name and IANA timezone are required.">
          <div className="stack">
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
              <div className="row">
                <Button variant="primary" type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending ? 'Adding…' : 'Add camera'}
                </Button>
              </div>
            </form>
          </div>
        </Panel>
      </div>
    </section>
  );
}
