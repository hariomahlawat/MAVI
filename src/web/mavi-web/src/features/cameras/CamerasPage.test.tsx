import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createCamera, listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { renderWithApp } from '../../test/renderWithApp';
import CamerasPage from './CamerasPage';

vi.mock('../../api/cameras', () => ({
  listCameras: vi.fn(),
  createCamera: vi.fn(),
  getCamera: vi.fn(),
}));

vi.mock('../../api/system', () => ({
  getSystemConfig: vi.fn(),
}));

const camera = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
  code: 'CAM-01',
  name: 'North Gate',
  description: null,
  locationName: null,
  timeZoneId: 'Asia/Kolkata',
  isActive: true,
  createdAtUtc: '2026-09-14T02:30:00Z',
  updatedAtUtc: '2026-09-14T02:30:00Z',
};

/** Open the create region the way an operator does: from the Context Bar. */
async function openCreate(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Add camera' }));
  return screen.getByRole('form', { name: 'Add camera' });
}

const submit = (form: HTMLElement) => within(form).getByRole('button', { name: 'Add camera' });

describe('CamerasPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(createCamera).mockResolvedValue({ ...camera, id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21413', code: 'CAM-02' });
  });

  it('is a Ledger: a Context Bar, one scrolling table body and no second card beside it', async () => {
    const { container } = renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    expect(container.querySelector('.workspace--ledger')).not.toBeNull();
    expect(container.querySelector('.context-bar')).not.toBeNull();
    // The Ledger's body is the single scroll owner: the table is its direct
    // child, with no wrapper that could become a second scrolling container.
    expect(container.querySelector('.workspace__body--scroll > table.table--ledger')).not.toBeNull();
    // §4.1: full width, not the capped `.page`.
    expect(container.querySelector('.page--full')).not.toBeNull();
  });

  it('hides the create form until it is asked for, and returns focus when it closes', async () => {
    const user = userEvent.setup();
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    expect(screen.queryByRole('form', { name: 'Add camera' })).not.toBeInTheDocument();

    const form = await openCreate(user);
    expect(form).toBeInTheDocument();
    // Focus lands in the first field, not on nothing.
    expect(screen.getByLabelText('Camera code')).toHaveFocus();

    await user.click(within(form).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('form', { name: 'Add camera' })).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Add camera' })).toHaveFocus();
  });

  it('is not dirty merely because the form is open', async () => {
    const user = userEvent.setup();
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    await openCreate(user);
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('Camera code'), 'C');
    expect(await screen.findByText('Unsaved changes')).toBeInTheDocument();
  });

  it('clears the dirty state when the draft is reverted to what it started as', async () => {
    const user = userEvent.setup();
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    await openCreate(user);
    const code = screen.getByLabelText('Camera code');
    await user.type(code, 'CAM-02');
    expect(await screen.findByText('Unsaved changes')).toBeInTheDocument();

    // Dirty means "different from where this draft started", not "has been
    // touched": a latched flag would leave the operator warned about work they
    // have already undone, and would refuse the Escape below forever.
    await user.clear(code);
    await waitFor(() => expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument());

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('form', { name: 'Add camera' })).not.toBeInTheDocument());
  });

  it('does not treat the inherited timezone default as an operator edit', async () => {
    const user = userEvent.setup();
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    await openCreate(user);
    // The deployment display zone arrives asynchronously and fills the field.
    // That is the draft's starting point, not a change to it.
    await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();

    const timezone = screen.getByLabelText('Camera timezone');
    await user.clear(timezone);
    await user.type(timezone, 'Europe/London');
    expect(await screen.findByText('Unsaved changes')).toBeInTheDocument();

    // Emptying the field returns it to the inherited default rather than to a
    // blank — the operator always has a valid zone in front of them — and that
    // is the starting point again, so the draft is clean.
    await user.clear(timezone);
    expect(timezone).toHaveValue('Asia/Kolkata');
    await waitFor(() => expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument());
  });

  it('accepts Escape on a clean draft and refuses to discard a dirty one', async () => {
    const user = userEvent.setup();
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    await openCreate(user);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('form', { name: 'Add camera' })).not.toBeInTheDocument());

    await openCreate(user);
    await user.type(screen.getByLabelText('Camera name'), 'East Gate');
    await user.keyboard('{Escape}');
    expect(screen.getByRole('form', { name: 'Add camera' })).toBeInTheDocument();
    expect(screen.getByLabelText('Camera name')).toHaveValue('East Gate');
  });

  it('does not submit an incomplete camera, and says which field refused', async () => {
    const user = userEvent.setup();
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    const form = await openCreate(user);
    await user.click(submit(form));

    expect(createCamera).not.toHaveBeenCalled();
    const code = screen.getByLabelText('Camera code');
    expect(code).toHaveAttribute('aria-invalid', 'true');
    const message = screen.getByText('A camera code is required.');
    expect(code.getAttribute('aria-describedby')).toContain(message.id);
  });

  it('maps a duplicate-code conflict onto the Code field and keeps the other drafts', async () => {
    const user = userEvent.setup();
    vi.mocked(createCamera).mockRejectedValueOnce(new ApiError({
      status: 409,
      code: 'camera_code_duplicate',
      detail: 'A camera with this code already exists.',
    }));
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    const form = await openCreate(user);
    await user.type(screen.getByLabelText('Camera code'), 'CAM-01');
    await user.type(screen.getByLabelText('Camera name'), 'Duplicate');
    const timezone = screen.getByLabelText('Camera timezone');
    await waitFor(() => expect(timezone).toHaveValue('Asia/Kolkata'));
    await user.click(submit(form));

    const conflict = await screen.findByText('A camera with this code already exists.');
    const code = screen.getByLabelText('Camera code');
    expect(code).toHaveAttribute('aria-invalid', 'true');
    expect(code.getAttribute('aria-describedby')).toContain(conflict.id);
    // §21: a conflict preserves the operator's edits.
    expect(screen.getByLabelText('Camera name')).toHaveValue('Duplicate');
    expect(timezone).toHaveValue('Asia/Kolkata');
    expect(screen.getByRole('form', { name: 'Add camera' })).toBeInTheDocument();

    // Editing the code clears the conflict rather than leaving it to contradict
    // the value now in the field — and clears it everywhere, not just from the
    // field: the same refusal must not reappear as a page-level alert about a
    // code the operator has since changed.
    await user.type(code, '0');
    expect(screen.queryByText(/already exists/)).not.toBeInTheDocument();
    expect(screen.queryByText(/camera_code_duplicate/)).not.toBeInTheDocument();
  });

  it('never states a duplicate code as a page-level alert', async () => {
    const user = userEvent.setup();
    vi.mocked(createCamera).mockRejectedValueOnce(new ApiError({
      status: 409,
      code: 'camera_code_duplicate',
      detail: 'A camera with this code already exists.',
    }));
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    const form = await openCreate(user);
    await user.type(screen.getByLabelText('Camera code'), 'CAM-01');
    await user.type(screen.getByLabelText('Camera name'), 'Duplicate');
    await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
    await user.click(submit(form));

    await screen.findByText('A camera with this code already exists.');
    // §21: a conflict attributable to a field belongs on that field. Stating
    // it twice, once of them as a page-level alert, is the duplicate §30 names.
    expect(within(form).queryByRole('alert')).not.toBeInTheDocument();
    expect(form.querySelector('.alert')).toBeNull();
  });

  it('still reports a create failure that is not attributable to a field', async () => {
    const user = userEvent.setup();
    vi.mocked(createCamera).mockRejectedValueOnce(new ApiError({
      status: 503,
      code: 'camera_store_unavailable',
      detail: 'The camera store is unavailable.',
    }));
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    const form = await openCreate(user);
    await user.type(screen.getByLabelText('Camera code'), 'CAM-02');
    await user.type(screen.getByLabelText('Camera name'), 'East Gate');
    await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
    await user.click(submit(form));

    expect(await screen.findByText(/camera store is unavailable.*camera_store_unavailable/)).toBeInTheDocument();
    expect(screen.getByLabelText('Camera code')).not.toHaveAttribute('aria-invalid');
  });

  it('creates a camera with the confirmed timezone, then closes the form without a toast', async () => {
    const user = userEvent.setup();
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    const form = await openCreate(user);
    await user.type(screen.getByLabelText('Camera code'), 'CAM-02');
    await user.type(screen.getByLabelText('Camera name'), 'East Gate');
    const timezone = screen.getByLabelText('Camera timezone');
    await waitFor(() => expect(timezone).toHaveValue('Asia/Kolkata'));
    await user.click(submit(form));

    await waitFor(() => expect(createCamera).toHaveBeenCalledWith({
      code: 'CAM-02',
      name: 'East Gate',
      timeZoneId: 'Asia/Kolkata',
    }));
    // The inventory is refreshed, the draft is gone, and no transient banner
    // is the record of what happened (§15).
    await waitFor(() => expect(listCameras).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('form', { name: 'Add camera' })).not.toBeInTheDocument());
    expect(screen.queryByText('Camera registered.')).not.toBeInTheDocument();
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();

    // The control the operator was on has just been removed from the document,
    // so focus has to be put somewhere deliberate rather than left on <body>.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add camera' })).toHaveFocus());
  });

  it('sorts by code ascending by default and re-orders deterministically', async () => {
    vi.mocked(listCameras).mockResolvedValue([
      { ...camera, id: 'c', code: 'CAM-10', name: 'Zulu', isActive: false },
      { ...camera, id: 'a', code: 'CAM-02', name: 'Alpha' },
      { ...camera, id: 'b', code: 'CAM-01', name: 'Mike' },
    ]);
    const user = userEvent.setup();
    renderWithApp(<CamerasPage />);

    const codes = async () => {
      const table = await screen.findByRole('table');
      return within(table).getAllByRole('row').slice(1)
        .map((row) => within(row).getAllByRole('cell')[0].textContent);
    };

    // CAM-10 after CAM-02: a numeric-aware comparison, not a string one.
    expect(await codes()).toEqual(['CAM-01', 'CAM-02', 'CAM-10']);
    expect(screen.getByRole('columnheader', { name: /Code/ })).toHaveAttribute('aria-sort', 'ascending');

    await user.click(screen.getByRole('button', { name: 'Code' }));
    expect(await codes()).toEqual(['CAM-10', 'CAM-02', 'CAM-01']);

    await user.click(screen.getByRole('button', { name: 'Name' }));
    expect(await codes()).toEqual(['CAM-02', 'CAM-01', 'CAM-10']);
    expect(screen.getByRole('columnheader', { name: /Name/ })).toHaveAttribute('aria-sort', 'ascending');

    // State sorts Active before Inactive; the two active cameras keep the
    // deterministic tie-break (by id: 'a' then 'b'), not the response order.
    // Timezone is deliberately not sortable (§32 decision 5).
    await user.click(screen.getByRole('button', { name: 'State' }));
    expect(await codes()).toEqual(['CAM-02', 'CAM-01', 'CAM-10']);
    expect(screen.queryByRole('button', { name: 'Timezone' })).not.toBeInTheDocument();
  });

  it('links each camera to its scene editor and shows no identifier in a cell', async () => {
    const { container } = renderWithApp(<CamerasPage />);

    const link = await screen.findByRole('link', { name: 'Scene' });
    expect(link).toHaveAttribute('href', `/cameras/${camera.id}/scene`);
    const body = container.querySelector('tbody')?.textContent ?? '';
    expect(body).not.toContain(camera.id);
  });

  it('reports an unavailable inventory as unavailable, never as empty', async () => {
    vi.mocked(listCameras).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Camera store unavailable.' }));
    renderWithApp(<CamerasPage />);

    expect(await screen.findByText(/Camera store unavailable/)).toBeInTheDocument();
    expect(screen.queryByText('No cameras registered')).not.toBeInTheDocument();
  });

  it('offers the first camera from the empty state', async () => {
    const user = userEvent.setup();
    vi.mocked(listCameras).mockResolvedValue([]);
    renderWithApp(<CamerasPage />);

    await user.click(await screen.findByRole('button', { name: 'Add the first camera' }));
    expect(screen.getByRole('form', { name: 'Add camera' })).toBeInTheDocument();
  });
});
