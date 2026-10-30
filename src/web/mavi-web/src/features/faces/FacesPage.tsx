import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { ApiError } from '../../api/client';
import { listCameras, type Camera } from '../../api/cameras';
import {
  FACE_CANDIDATES_LABEL,
  addGalleryTemplate,
  deleteGalleryEntry,
  deleteGalleryTemplate,
  formatFaceScore,
  getFaceQuery,
  listGallery,
  readQueryImage,
  setCameraFaceAnalysis,
  updateGalleryEntry,
  uploadFaceQuery,
  type FaceQueryResponse,
  type GalleryEntry,
} from '../../api/faces';
import { queryKeys } from '../../app/queryClient';
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import FileInput from '../../shared/components/FileInput';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import Dialog from '../../shared/overlay/Dialog';
import { ContextBar } from '../../shared/workspace';
import FaceActions from './FaceActions';
import FaceCrop, { FaceThumbnail } from './FaceCrop';

const QUERY_POLL_MS = 1000;

function operatorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
    return 'Faces are available to operators only (ADR-010).';
  }
  return describeError(error, fallback);
}

// --- Query image ------------------------------------------------------------------

function AddToGallery({ queryId, faceIndex, entries }: { queryId: string; faceIndex: number; entries: GalleryEntry[] }) {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState('');
  const add = useMutation({
    mutationFn: () => addGalleryTemplate(target, { queryId, faceIndex }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.faceGallery }),
  });
  if (entries.length === 0) return null;
  return (
    <div className="row">
      <Field label="Add this face to a gallery entry">
        {(control) => (
          <select {...control} value={target} onChange={(event) => setTarget(event.target.value)}>
            <option value="">Choose an entry</option>
            {entries.map((entry) => <option key={entry.enrolledPersonId} value={entry.enrolledPersonId}>{entry.label}</option>)}
          </select>
        )}
      </Field>
      <Button size="sm" disabled={!target || add.isPending} onClick={() => add.mutate()}>Add template</Button>
      {add.isSuccess ? <p className="small" role="status">Template added.</p> : null}
      {add.isError ? <Alert tone="error">{operatorMessage(add.error, 'The template could not be added.')}</Alert> : null}
    </div>
  );
}

function QueryFaces({ data, entries }: { data: FaceQueryResponse; entries: GalleryEntry[] }) {
  const usable = data.faces.filter((face) => face.usable);
  const [selected, setSelected] = useState<number | null>(null);
  const active = usable.find((face) => face.faceIndex === selected) ?? usable[0] ?? null;
  if (data.status === 'pending') return <p className="small muted" role="status">Detecting faces in the query image…</p>;
  if (data.status === 'failed') {
    return <Alert tone="warning">The query image could not be analysed{data.failureCode ? ` (${data.failureCode})` : ''}.</Alert>;
  }
  if (data.faces.length === 0) return <Alert tone="info">Unknown — no face detected in the query image.</Alert>;
  return (
    <div className="stack">
      <ul className="row" aria-label="Faces in the query image">
        {data.faces.map((face) => (
          <li key={face.faceIndex} className="stack">
            <FaceThumbnail src={face.thumbnailDataUrl} label={`Query face ${face.faceIndex + 1}`} />
            <span className="small">{face.usable ? 'Usable' : 'Too small'} · {formatFaceScore(face.score)}</span>
            {face.usable && usable.length > 1 ? (
              <Button size="sm" variant="ghost" aria-pressed={active?.faceIndex === face.faceIndex} onClick={() => setSelected(face.faceIndex)}>
                Use this face
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      {active ? (
        <>
          <FaceActions key={active.faceIndex} source={{ queryId: data.queryId, faceIndex: active.faceIndex }} />
          <AddToGallery queryId={data.queryId} faceIndex={active.faceIndex} entries={entries} />
        </>
      ) : (
        <Alert tone="info">Unknown — no usable face: every face in the query image is smaller than 32 px.</Alert>
      )}
      <p className="small muted">The query image is erased once analysed; its faces are kept for at most one hour.</p>
    </div>
  );
}

function QueryImagePanel({ entries }: { entries: GalleryEntry[] }) {
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [queryId, setQueryId] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: async (chosen: File) => {
      const image = await readQueryImage(chosen);
      return uploadFaceQuery(image.imageBase64, image.mimeType);
    },
    onSuccess: (response) => setQueryId(response.queryId),
  });
  const query = useQuery({
    queryKey: queryKeys.faceQuery(queryId ?? ''),
    queryFn: ({ signal }) => getFaceQuery(queryId!, signal),
    enabled: queryId !== null,
    refetchInterval: (current) => (current.state.data?.status === 'pending' ? QUERY_POLL_MS : false),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!file) {
      setFileError('Choose a JPEG or PNG image.');
      return;
    }
    setFileError(null);
    setQueryId(null);
    upload.mutate(file);
  };
  return (
    <Panel title="Find a face from an image">
      <form className="stack" onSubmit={submit} aria-label="Find a face from an image">
        <Field label="Query image" error={fileError} help="JPEG or PNG, at most 2 MB. It is analysed on this machine and erased once analysed.">
          {(control) => <FileInput {...control} file={file} accept="image/jpeg,image/png" onChange={(chosen) => { setFile(chosen); setFileError(null); }} />}
        </Field>
        <div className="row">
          <Button variant="primary" type="submit" icon="upload" disabled={upload.isPending}>Analyse image</Button>
        </div>
        {upload.isError ? (
          <Alert tone="error">
            {upload.error instanceof ApiError ? operatorMessage(upload.error, 'The image could not be uploaded.') : (upload.error as Error).message}
          </Alert>
        ) : null}
      </form>
      {queryId ? (
        <StateRegion
          kind="panel"
          state={fromQuery(query)}
          label="query image"
          loadingLabel="Detecting faces in the query image…"
          unavailableMessage={(error) => operatorMessage(error, 'The query image could not be read.')}
          onRetry={() => void query.refetch()}
        >
          {(data) => <QueryFaces data={data} entries={entries} />}
        </StateRegion>
      ) : null}
    </Panel>
  );
}

// --- Gallery ----------------------------------------------------------------------

function EditEntry({ entry, onDone }: { entry: GalleryEntry; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState(entry.label);
  const [note, setNote] = useState(entry.note ?? '');
  const save = useMutation({
    mutationFn: () => updateGalleryEntry(entry.enrolledPersonId, { label: label.trim(), note: note.trim() ? note.trim() : null }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.faceGallery });
      onDone();
    },
  });
  const labelError = label.trim() ? null : 'Enter a gallery label.';
  return (
    <form className="stack" aria-label={`Edit ${entry.label}`} onSubmit={(event) => { event.preventDefault(); if (!labelError) save.mutate(); }}>
      <Field label="Gallery label" error={labelError}>
        {(control) => <input {...control} value={label} maxLength={100} onChange={(event) => setLabel(event.target.value)} />}
      </Field>
      <Field label="Note" optional>
        {(control) => <textarea {...control} value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} />}
      </Field>
      <div className="row">
        <Button size="sm" variant="primary" type="submit" disabled={save.isPending}>Save</Button>
        <Button size="sm" variant="ghost" type="button" onClick={onDone}>Cancel</Button>
      </div>
      {save.isError ? <Alert tone="error">{operatorMessage(save.error, 'The gallery entry could not be saved.')}</Alert> : null}
    </form>
  );
}

type PendingDelete = { kind: 'entry'; entry: GalleryEntry } | { kind: 'template'; entry: GalleryEntry; templateId: string };

function GalleryPanel() {
  const queryClient = useQueryClient();
  const gallery = useQuery({ queryKey: queryKeys.faceGallery, queryFn: ({ signal }) => listGallery(signal) });
  const [editing, setEditing] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingDelete | null>(null);
  const remove = useMutation({
    mutationFn: (target: PendingDelete) => target.kind === 'entry'
      ? deleteGalleryEntry(target.entry.enrolledPersonId)
      : deleteGalleryTemplate(target.entry.enrolledPersonId, target.templateId),
    onSettled: () => {
      setPending(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.faceGallery });
    },
  });
  return (
    <Panel title="Gallery">
      <p className="small muted">
        Enrolled persons are operator-entered labels with face templates, stored only in this installation. A comparison
        lists candidate gallery matches above the reference threshold; it never states who a person is.
      </p>
      {remove.isError ? <Alert tone="error">{operatorMessage(remove.error, 'The deletion failed.')}</Alert> : null}
      <StateRegion
        kind="panel"
        state={fromQuery(gallery)}
        label="gallery"
        loadingLabel="Loading the gallery…"
        isEmpty={(data) => data.entries.length === 0}
        empty={{ title: 'The gallery is empty', body: 'Enrol a usable face from a Track or a query image.' }}
        unavailableMessage={(error) => operatorMessage(error, 'The gallery could not be loaded.')}
        onRetry={() => void gallery.refetch()}
      >
        {(data) => (
          <ul className="stack" aria-label="Gallery entries">
            {data.entries.map((entry) => (
              <li key={entry.enrolledPersonId} className="stack">
                <div className="row">
                  <strong>{entry.label}</strong>
                  <StatusBadge tone="neutral">{`${entry.templates.length} template${entry.templates.length === 1 ? '' : 's'}`}</StatusBadge>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(entry.enrolledPersonId)}>Edit</Button>
                  <Button size="sm" variant="danger" onClick={() => setPending({ kind: 'entry', entry })}>Delete entry</Button>
                </div>
                {entry.note ? <p className="small">{entry.note}</p> : null}
                {editing === entry.enrolledPersonId ? <EditEntry entry={entry} onDone={() => setEditing(null)} /> : null}
                <ul className="row" aria-label={`Templates of ${entry.label}`}>
                  {entry.templates.map((template) => (
                    <li key={template.templateId} className="stack">
                      {template.thumbnailDataUrl ? (
                        <FaceThumbnail src={template.thumbnailDataUrl} size={56} label="Template from an uploaded image" />
                      ) : (
                        <FaceCrop src={template.evidenceCropUrl} box={template.box} size={56} label="Template from evidence" />
                      )}
                      <Button size="sm" variant="ghost" onClick={() => setPending({ kind: 'template', entry, templateId: template.templateId })}>
                        Remove template
                      </Button>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </StateRegion>
      <Dialog
        open={pending !== null}
        title={pending?.kind === 'entry' ? `Delete the gallery entry ${pending.entry.label}?` : 'Remove this template?'}
        confirmLabel={pending?.kind === 'entry' ? 'Delete entry' : 'Remove template'}
        destructive
        onConfirm={() => { if (pending) remove.mutate(pending); }}
        onCancel={() => setPending(null)}
      >
        {pending?.kind === 'entry'
          ? 'The label, note and every face template of this entry are permanently deleted. The audit record keeps only the entry id.'
          : 'The face template is permanently deleted from the gallery.'}
      </Dialog>
    </Panel>
  );
}

// --- Camera opt-in ----------------------------------------------------------------

function CameraSwitches() {
  const cameras = useQuery({ queryKey: queryKeys.cameras, queryFn: ({ signal }) => listCameras(signal) });
  const [known, setKnown] = useState<Record<string, boolean>>({});
  const [pending, setPending] = useState<{ camera: Camera; enabled: boolean } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const set = useMutation({
    mutationFn: (target: { camera: Camera; enabled: boolean }) => setCameraFaceAnalysis(target.camera.id, target.enabled),
    onSuccess: (response, target) => {
      setKnown((current) => ({ ...current, [target.camera.id]: response.faceAnalysisEnabled }));
      void cameras.refetch();
      setMessage(response.faceAnalysisEnabled
        ? `Face analysis switched on for ${target.camera.code}.`
        : `Face analysis switched off for ${target.camera.code}; ${response.faceAnalysesDeleted} face analys${response.faceAnalysesDeleted === 1 ? 'is' : 'es'} deleted.`);
    },
    onSettled: () => setPending(null),
  });
  return (
    <Panel title="Face analysis (opt-in)">
      <p className="small muted">
        Face analysis is off by default and runs only on cameras switched on here. Switching a camera off deletes that
        camera&apos;s face data (detected faces, their face vectors and the Tracks&apos; face outcomes); gallery entries are kept. Each switch is audited.
      </p>
      {message ? <p className="small" role="status">{message}</p> : null}
      {set.isError ? <Alert tone="error">{operatorMessage(set.error, 'The camera switch failed.')}</Alert> : null}
      <StateRegion
        kind="panel"
        state={fromQuery(cameras)}
        label="cameras"
        loadingLabel="Loading cameras…"
        isEmpty={(data) => data.length === 0}
        empty={{ title: 'No cameras' }}
        unavailableMessage={(error) => describeError(error, 'Cameras could not be loaded.')}
        onRetry={() => void cameras.refetch()}
      >
        {(data) => (
          <ul className="stack" aria-label="Cameras">
            {data.map((camera) => {
              const state = known[camera.id] ?? camera.faceAnalysisEnabled;
              return (
                <li key={camera.id} className="row">
                  <span>{camera.code} · {camera.name}</span>
                  <StatusBadge tone={state ? 'info' : 'neutral'}>
                    {state === undefined ? 'Not set here' : state ? 'On' : 'Off'}
                  </StatusBadge>
                  {state !== true ? (
                    <Button size="sm" onClick={() => setPending({ camera, enabled: true })}>Switch on</Button>
                  ) : null}
                  {state !== false ? (
                    <Button size="sm" variant="ghost" onClick={() => setPending({ camera, enabled: false })}>Switch off</Button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </StateRegion>
      <Dialog
        open={pending !== null}
        title={pending?.enabled ? `Switch face analysis on for ${pending.camera.code}?` : `Switch face analysis off for ${pending?.camera.code ?? ''}?`}
        confirmLabel={pending?.enabled ? 'Switch on' : 'Switch off and delete face data'}
        destructive={pending?.enabled === false}
        onConfirm={() => { if (pending) set.mutate(pending); }}
        onCancel={() => setPending(null)}
      >
        {pending?.enabled
          ? 'Person Tracks of this camera are analysed for faces, and their face templates are stored in this installation only.'
          : "This camera's face data is deleted now. Its Tracks, evidence and other analyses are unchanged."}
      </Dialog>
    </Panel>
  );
}

/**
 * Faces (PoC S6; ADR-022): find a face from an image, the gallery, and the
 * per-camera opt-in. Every result here is a face candidate with its score and
 * the reference threshold; nothing on this page states who a person is.
 */
export default function FacesPage() {
  const gallery = useQuery({ queryKey: queryKeys.faceGallery, queryFn: ({ signal }) => listGallery(signal) });
  return (
    <section className="page">
      <ContextBar surface="faces" />
      <div className="stack">
        <Alert tone="info">{gallery.data?.label ?? FACE_CANDIDATES_LABEL}</Alert>
        <QueryImagePanel entries={gallery.data?.entries ?? []} />
        <GalleryPanel />
        <CameraSwitches />
      </div>
    </section>
  );
}
