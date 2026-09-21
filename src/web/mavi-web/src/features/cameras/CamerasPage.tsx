import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { ApiError } from '../../api/client';
import { createCamera, listCameras, type Camera, type CreateCameraInput } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { queryKeys } from '../../app/queryClient';
import AsyncBoundary from '../../shared/async/AsyncBoundary';
import { fromQuery } from '../../shared/async/fromQuery';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import Field from '../../shared/components/Field';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatCount } from '../../shared/format/format';
import { SortableColumn, sortRows, useLedgerSort } from '../../shared/table';
import { ContextBar, LedgerLayout, Toolbar } from '../../shared/workspace';

type CameraColumn = 'code' | 'name' | 'state';

type Draft = { code: string; name: string; timeZoneId: string };

const EMPTY: Draft = { code: '', name: '', timeZoneId: '' };

/** State reads as a word, so "ascending" can mean what the word means: Active first. */
const stateLabel = (camera: Camera) => (camera.isActive ? 'Active' : 'Inactive');

function compareCameras(left: Camera, right: Camera, column: CameraColumn): number {
  switch (column) {
    case 'name': return left.name.localeCompare(right.name);
    case 'state': return stateLabel(left).localeCompare(stateLabel(right));
    case 'code':
    default: return left.code.localeCompare(right.code, undefined, { numeric: true });
  }
}

/**
 * Cameras — a Ledger (§4.1).
 *
 * The inventory *is* the surface. Before UI-3 it shared the page with a
 * permanent "Add camera" card, which §21 names directly: routine create must
 * not require a modal, and an inline form is preferred over a second card
 * standing beside the list whether or not anyone is creating anything. So the
 * draft lives in the Ledger's transient editor region, opened from the Context
 * Bar and gone again once it is used or cancelled.
 *
 * Opening the form is not an edit. Dirty means the operator changed a value,
 * which is what makes the Context Bar's unsaved-changes state worth reading
 * and what makes Escape safe to accept while it is absent.
 */
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

  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [submitted, setSubmitted] = useState(false);
  /** Set from a 409 and cleared the moment the code is edited (§21). */
  const [codeConflict, setCodeConflict] = useState<string | null>(null);

  const openRef = useRef<HTMLButtonElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);
  const restoreFocus = useRef(false);

  const sort = useLedgerSort<CameraColumn>({ column: 'code', direction: 'asc' });

  // The camera's timezone defaults to the deployment display zone, which is
  // the authority the operator is most likely to mean and the one the product
  // already interprets everything else in. An untouched draft follows it as it
  // loads; a touched one does not, or the operator's typing would be undone.
  const defaultTimeZone = systemConfig.data?.displayTimeZoneId ?? '';
  const timeZoneValue = draft.timeZoneId || defaultTimeZone;

  const createMutation = useMutation({
    mutationFn: (input: CreateCameraInput) => createCamera(input),
    onSuccess: async () => {
      // The submit button the operator was on is about to leave the document,
      // so focus goes back to the action that opened the region rather than
      // falling to the body (§17 of the UI-3 brief, §23).
      close();
      await queryClient.invalidateQueries({ queryKey: queryKeys.cameras });
    },
    onError: (error) => {
      // A conflict attributable to a field highlights that field and keeps
      // every other value the operator typed (§21).
      if (error instanceof ApiError && error.code === 'camera_code_duplicate') {
        setCodeConflict('A camera with this code already exists.');
      }
    },
  });

  useEffect(() => {
    if (creating) codeRef.current?.focus();
  }, [creating]);

  // The action that opened the region is where focus belongs when it closes,
  // and it is only in the document again once the region has gone.
  useEffect(() => {
    if (creating || !restoreFocus.current) return;
    restoreFocus.current = false;
    openRef.current?.focus();
  }, [creating]);

  function open() {
    setDraft(EMPTY);
    setSubmitted(false);
    setCodeConflict(null);
    createMutation.reset();
    setCreating(true);
  }

  // Deliberately does not reset the mutation: it is called from the mutation's
  // own success handler, and resetting a mutation from inside its callback is
  // a needless way to find out how re-entrant that is. `open` clears it, which
  // is the only moment a previous attempt's error could still be on screen.
  function close(returnFocus = true) {
    restoreFocus.current = returnFocus;
    setCreating(false);
    setDraft(EMPTY);
    setSubmitted(false);
    setCodeConflict(null);
  }

  function edit(patch: Partial<Draft>) {
    if ('code' in patch) setCodeConflict(null);
    setDraft((current) => ({ ...current, ...patch }));
  }

  const code = draft.code.trim();
  const name = draft.name.trim();
  const timeZoneId = timeZoneValue.trim();

  /**
   * Dirty is a comparison, not a flag (§21).
   *
   * A boolean set on the first keystroke never comes back down, so it goes on
   * warning about work the operator has already undone — and here it would
   * also make Escape refuse to close a draft that is once again empty.
   *
   * The comparison is against what the draft *started* as, which for the
   * timezone is the deployment display zone rather than the empty string: that
   * value arrives asynchronously and fills the field on its own, so treating
   * the field's own default as a change would flip the form dirty while the
   * operator watched. What is compared is what the operator sees and what
   * `submit` would send.
   */
  const dirty = draft.code !== '' || draft.name !== '' || timeZoneValue !== defaultTimeZone;
  // Local validation is shown once the operator has tried to submit, so the
  // form does not start out scolding a field nobody has touched.
  const errors = {
    code: codeConflict ?? (submitted && !code ? 'A camera code is required.' : null),
    name: submitted && !name ? 'A camera name is required.' : null,
    timeZoneId: submitted && !timeZoneId ? 'An IANA timezone is required.' : null,
  };

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    if (!code || !name || !timeZoneId || createMutation.isPending) return;
    createMutation.mutate({ code, name, timeZoneId });
  }

  /** A failure the form cannot pin to a field, and so has to state as a whole. */
  const unattributableFailure = createMutation.isError
    && !(createMutation.error instanceof ApiError && createMutation.error.code === 'camera_code_duplicate')
    ? createMutation.error
    : null;

  const rows = useMemo(
    () => (cameras.data ? sortRows(cameras.data, sort.state, compareCameras, (camera) => camera.id) : []),
    [cameras.data, sort.state],
  );

  const createRegion = (
    <form
      className="camera-create"
      aria-label="Add camera"
      onSubmit={submit}
      noValidate
      onKeyDown={(event) => {
        // Escape closes the region, but never discards work the operator would
        // have to retype: while there is a draft, Cancel is the explicit way
        // out (§17 of the UI-3 brief).
        if (event.key !== 'Escape' || dirty) return;
        event.stopPropagation();
        close();
      }}
    >
      {/* A refusal that belongs to a field is stated on that field and
          nowhere else (§21). Deciding that from the error's own code rather
          than from whether `codeConflict` is currently set matters: editing the
          code clears the field message, and a condition that keyed on it
          brought the very same refusal back as a page-level alert about a code
          the operator had already changed. */}
      {unattributableFailure ? (
        <Alert tone="error">
          {unattributableFailure instanceof ApiError
            ? `${unattributableFailure.detail} (${unattributableFailure.code})`
            : 'Camera could not be created.'}
        </Alert>
      ) : null}

      <div className="camera-create__fields">
        <Field label="Camera code" error={errors.code}>
          {(control) => (
            <input
              {...control}
              ref={codeRef}
              value={draft.code}
              onChange={(event) => edit({ code: event.target.value })}
              maxLength={64}
              autoComplete="off"
              placeholder="CAM-01"
            />
          )}
        </Field>
        <Field label="Camera name" error={errors.name}>
          {(control) => (
            <input
              {...control}
              value={draft.name}
              onChange={(event) => edit({ name: event.target.value })}
              maxLength={128}
              autoComplete="off"
              placeholder="North Gate"
            />
          )}
        </Field>
        <Field
          label="Camera timezone"
          error={errors.timeZoneId}
          help="IANA identifier, for example Asia/Kolkata. Recording local time is interpreted in this zone; the browser's timezone is never used as the authority."
        >
          {(control) => (
            <input
              {...control}
              value={timeZoneValue}
              onChange={(event) => edit({ timeZoneId: event.target.value })}
              autoComplete="off"
              placeholder="Asia/Kolkata"
            />
          )}
        </Field>
      </div>

      <div className="camera-create__actions">
        <Button variant="primary" type="submit" disabled={createMutation.isPending}>
          {createMutation.isPending ? 'Adding…' : 'Add camera'}
        </Button>
        <Button variant="ghost" onClick={() => close()}>Cancel</Button>
      </div>
    </form>
  );

  return (
    <section className="page page--full page--workspace">
      <ContextBar
        crumbs={[{ label: 'Cameras' }]}
        status={dirty ? <StatusBadge tone="warn">Unsaved changes</StatusBadge> : null}
        actions={creating ? null : (
          <Button ref={openRef} variant="primary" icon="camera" onClick={open}>Add camera</Button>
        )}
      />

      <LedgerLayout
        // No filters here, so the band exists only while it has something to
        // say; an empty 32px strip is chrome, not a toolbar.
        toolbar={cameras.data ? (
          <Toolbar
            label="Camera inventory"
            hint={`${formatCount(cameras.data.length)} camera${cameras.data.length === 1 ? '' : 's'} registered`}
          />
        ) : undefined}
        editor={creating ? createRegion : null}
      >
        <AsyncBoundary
          state={fromQuery(cameras)}
          loadingLabel="Loading cameras…"
          isEmpty={(all) => all.length === 0}
          empty={(
            <EmptyState
              icon="camera"
              title="No cameras registered"
              actions={creating ? undefined : <Button variant="primary" onClick={open}>Add the first camera</Button>}
            >
              A camera has to exist before media can be imported against it.
            </EmptyState>
          )}
          unavailable={(error) => (
            <div className="panel__body">
              <Alert tone="error" actions={<Button size="sm" onClick={() => cameras.refetch()}>Retry</Button>}>
                {error instanceof ApiError ? `${error.detail} (${error.code})` : 'Camera inventory is unavailable.'}
              </Alert>
            </div>
          )}
          degradedLabel="Showing the last known camera inventory; refreshing failed."
          onRetry={() => cameras.refetch()}
        >
          {() => (
            <table className="table table--ledger">
              <caption className="visually-hidden">Camera inventory</caption>
              <thead>
                <tr>
                  <SortableColumn sort={sort} column="code">Code</SortableColumn>
                  <SortableColumn sort={sort} column="name">Name</SortableColumn>
                  <th scope="col">Timezone</th>
                  <SortableColumn sort={sort} column="state">State</SortableColumn>
                  <th scope="col"><span className="visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((camera) => (
                  <tr key={camera.id}>
                    <td><strong>{camera.code}</strong></td>
                    {/* A long name truncates rather than widening the column;
                        §10.2 keeps the full value on the element itself. */}
                    <td><span className="truncate cap-lg" title={camera.name}>{camera.name}</span></td>
                    <td><code>{camera.timeZoneId}</code></td>
                    <td>
                      <StatusBadge tone={camera.isActive ? 'ok' : 'neutral'}>{stateLabel(camera)}</StatusBadge>
                    </td>
                    <td>
                      <div className="table__actions">
                        <ButtonLink size="sm" variant="ghost" icon="layers" to={`/cameras/${camera.id}/scene`}>
                          Scene
                        </ButtonLink>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </AsyncBoundary>
      </LedgerLayout>
    </section>
  );
}
