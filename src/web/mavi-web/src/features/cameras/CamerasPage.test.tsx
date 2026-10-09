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
    expect(container.querySelector('.workspace__body--ledger > .ledger-table > table.table--ledger')).not.toBeNull();
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

  describe('S1d: Ledger grammar, one primary and validation focus', () => {
    const primaries = (root: ParentNode) => Array.from(root.querySelectorAll('.btn--primary'));

    it('contains the ready table and only the ready table (§4.1, §37.1)', async () => {
      const ready = renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      expect(ready.container.querySelector('.workspace__body--ledger > .ledger-table > table')).not.toBeNull();
      ready.unmount();

      vi.mocked(listCameras).mockResolvedValue([]);
      const empty = renderWithApp(<CamerasPage />);
      await screen.findByText('No cameras registered');
      expect(empty.container.querySelector('.ledger-table')).toBeNull();
      expect(empty.container.querySelector('.workspace__body--ledger > .state-region')).not.toBeNull();
      empty.unmount();

      vi.mocked(listCameras).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Camera store unavailable.' }));
      const unavailable = renderWithApp(<CamerasPage />);
      await screen.findByText(/Camera store unavailable/);
      expect(unavailable.container.querySelector('.ledger-table')).toBeNull();
      expect(unavailable.container.querySelector('.workspace__body--ledger > .state-region [role="alert"], .workspace__body--ledger > .state-region .alert')).not.toBeNull();
      unavailable.unmount();

      vi.mocked(listCameras).mockReturnValue(new Promise(() => {}));
      const loading = renderWithApp(<CamerasPage />);
      expect(await screen.findByRole('status')).toBeInTheDocument();
      expect(loading.container.querySelector('.ledger-table')).toBeNull();
      expect(loading.container.querySelector('.workspace__body--ledger > .state-region .skeleton')).not.toBeNull();
      // S1e (D3, §38): the skeleton reserves the table header, and the band
      // the count will occupy is already there, so the rows do not move when
      // the inventory arrives.
      expect(loading.container.querySelectorAll('.workspace__body--ledger .skeleton__head')).toHaveLength(1);
      expect(loading.container.querySelector('.toolbar-band__hint')).toHaveTextContent('Loading cameras…');
    });

    it('gives each row one secondary text action and one named icon action (§16)', async () => {
      const { container } = renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      const row = container.querySelector('tbody tr') as HTMLElement;
      const actions = within(row).getAllByRole('link');
      expect(actions.map((link) => link.textContent?.trim())).toEqual(['Scene', 'Analytics for CAM-01']);
      expect(within(row).getByRole('link', { name: 'Analytics for CAM-01' })).toHaveAttribute('href', `/cameras/${camera.id}/analytics`);
      // Text action secondary; the icon action is icon-only; neither is the accent primary.
      expect(primaries(row)).toHaveLength(0);
      expect(within(row).getByRole('link', { name: 'Analytics for CAM-01' })).toHaveClass('btn--icon');
      expect(within(row).getByRole('link', { name: 'Scene' })).not.toHaveClass('btn--icon');
    });

    it('shows at most one accent-filled action in every state of the surface (§8.1)', async () => {
      const user = userEvent.setup();
      const ready = renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      expect(primaries(ready.container).map((button) => button.textContent)).toEqual(['Add camera']);
      // The create form is the surface's purpose while open: its submit is the
      // one primary, and the Context Bar's withdraws.
      await openCreate(user);
      expect(primaries(ready.container).map((button) => button.textContent)).toEqual(['Add camera']);
      expect(within(screen.getByRole('form', { name: 'Add camera' })).getByRole('button', { name: 'Add camera' })).toHaveClass('btn--primary');
      ready.unmount();

      vi.mocked(listCameras).mockResolvedValue([]);
      const empty = renderWithApp(<CamerasPage />);
      const first = await screen.findByRole('button', { name: 'Add the first camera' });
      expect(first).not.toHaveClass('btn--primary');
      expect(primaries(empty.container)).toHaveLength(1);
    });

    it('brings the first invalid field into view and focuses it on a refused submit (§12)', async () => {
      const user = userEvent.setup();
      const scrolled: Element[] = [];
      const original = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function scrollIntoView(this: Element) { scrolled.push(this); };
      try {
        renderWithApp(<CamerasPage />);
        await screen.findByText('North Gate');
        const form = await openCreate(user);
        await user.click(submit(form));
        // Reading order: Code is the first refused field.
        await waitFor(() => expect(screen.getByLabelText('Camera code')).toHaveFocus());
        expect(scrolled).toContain(screen.getByLabelText('Camera code'));

        // Code now valid: the next refusal goes to Name.
        await user.type(screen.getByLabelText('Camera code'), 'CAM-02');
        await user.click(submit(form));
        await waitFor(() => expect(screen.getByLabelText('Camera name')).toHaveFocus());
        expect(scrolled.at(-1)).toBe(screen.getByLabelText('Camera name'));
      } finally {
        Element.prototype.scrollIntoView = original;
      }
    });

    it('brings a field-owned server refusal into view and focuses that field (§12, §21)', async () => {
      const user = userEvent.setup();
      const scrolled: Element[] = [];
      const original = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function scrollIntoView(this: Element) { scrolled.push(this); };
      vi.mocked(createCamera).mockRejectedValueOnce(new ApiError({ status: 409, code: 'camera_code_duplicate', detail: 'A camera with this code already exists.' }));
      try {
        renderWithApp(<CamerasPage />);
        await screen.findByText('North Gate');
        const form = await openCreate(user);
        await user.type(screen.getByLabelText('Camera code'), 'CAM-01');
        await user.type(screen.getByLabelText('Camera name'), 'Duplicate');
        await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
        await user.click(submit(form));
        await screen.findByText('A camera with this code already exists.');
        const code = screen.getByLabelText('Camera code');
        await waitFor(() => expect(code).toHaveFocus());
        expect(scrolled.at(-1)).toBe(code);
      } finally {
        Element.prototype.scrollIntoView = original;
      }
    });

    it('states no conflict on a code the operator changed while the request was in flight', async () => {
      const user = userEvent.setup();
      let refuse: (error: unknown) => void = () => {};
      vi.mocked(createCamera).mockImplementationOnce(() => new Promise((_, reject) => { refuse = reject; }));
      renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      const form = await openCreate(user);
      await user.type(screen.getByLabelText('Camera code'), 'CAM-01');
      await user.type(screen.getByLabelText('Camera name'), 'Duplicate');
      await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
      await user.click(submit(form));
      await waitFor(() => expect(createCamera).toHaveBeenCalled());

      // The operator corrects the code before the server answers for the old one.
      const code = screen.getByLabelText('Camera code');
      await user.type(code, '9');
      refuse(new ApiError({ status: 409, code: 'camera_code_duplicate', detail: 'A camera with this code already exists.' }));
      await waitFor(() => expect(submit(form)).toBeEnabled());

      expect(screen.queryByText('A camera with this code already exists.')).not.toBeInTheDocument();
      expect(code).not.toHaveAttribute('aria-invalid', 'true');
      expect(code).toHaveValue('CAM-019');
    });

    it('states the conflict on Code but leaves focus where the operator is still typing', async () => {
      const user = userEvent.setup();
      let refuse: (error: unknown) => void = () => {};
      vi.mocked(createCamera).mockImplementationOnce(() => new Promise((_, reject) => { refuse = reject; }));
      renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      const form = await openCreate(user);
      await user.type(screen.getByLabelText('Camera code'), 'CAM-01');
      await user.type(screen.getByLabelText('Camera name'), 'Duplicate');
      await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
      await user.click(submit(form));
      await waitFor(() => expect(createCamera).toHaveBeenCalled());

      // Still editing the name when the refusal of the unchanged code arrives.
      const name = screen.getByLabelText('Camera name');
      await user.type(name, ' gate');
      refuse(new ApiError({ status: 409, code: 'camera_code_duplicate', detail: 'A camera with this code already exists.' }));

      await screen.findByText('A camera with this code already exists.');
      expect(screen.getByLabelText('Camera code')).toHaveAttribute('aria-invalid', 'true');
      expect(name).toHaveFocus();
    });

    it('moves no focus for a failure no field owns', async () => {
      const user = userEvent.setup();
      vi.mocked(createCamera).mockRejectedValueOnce(new ApiError({ status: 503, code: 'camera_store_unavailable', detail: 'The camera store is unavailable.' }));
      renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      const form = await openCreate(user);
      await user.type(screen.getByLabelText('Camera code'), 'CAM-02');
      await user.type(screen.getByLabelText('Camera name'), 'East Gate');
      await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
      const button = submit(form);
      await user.click(button);
      await screen.findByText(/camera store is unavailable/);
      expect(button).toHaveFocus();
    });
  });

  describe('M1: identities, sorting, create lifecycle and inventory states', () => {
    const LONG_CODE = 'SOUTH-DOCK-LOADING-BAY-EAST-APPROACH-SERVICE-ROAD-CAMERA-0000007';
    const LONG_ZONE = 'America/Argentina/ComodRivadavia';

    it('bounds a long code and timezone with a truncation the keyboard can reach, never a wider table (§16)', async () => {
      vi.mocked(listCameras).mockResolvedValue([{ ...camera, code: LONG_CODE, timeZoneId: LONG_ZONE }]);
      const { container } = renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      const cells = (container.querySelector('tbody tr') as HTMLElement).querySelectorAll('td');
      // The full value is the text; the cap is what keeps it from widening the table.
      const code = within(cells[0]).getByText(LONG_CODE);
      expect(code).toHaveClass('truncate', 'cap-md');
      const zone = within(cells[2]).getByText(LONG_ZONE);
      expect(zone).toHaveClass('truncate', 'cap-lg');
      // Still named for the camera it opens, whatever the code's length.
      expect(screen.getByRole('link', { name: `Analytics for ${LONG_CODE}` })).toHaveAttribute('href', `/cameras/${camera.id}/analytics`);
    });

    it('sorts names both ways and state by its word, and the actions of every row follow their camera', async () => {
      vi.mocked(listCameras).mockResolvedValue([
        { ...camera, id: 'id-b', code: 'CAM-02', name: 'Bravo', isActive: false },
        { ...camera, id: 'id-a', code: 'CAM-01', name: 'Alpha' },
        { ...camera, id: 'id-c', code: 'CAM-03', name: 'Charlie' },
      ]);
      const user = userEvent.setup();
      renderWithApp(<CamerasPage />);
      const rows = async () => within(await screen.findByRole('table')).getAllByRole('row').slice(1);
      const order = async () => (await rows()).map((row) => within(row).getAllByRole('cell')[1].textContent);
      await screen.findByRole('table');

      await user.click(screen.getByRole('button', { name: 'Name' }));
      expect(await order()).toEqual(['Alpha', 'Bravo', 'Charlie']);
      await user.click(screen.getByRole('button', { name: 'Name' }));
      expect(await order()).toEqual(['Charlie', 'Bravo', 'Alpha']);
      expect(screen.getByRole('columnheader', { name: /Name/ })).toHaveAttribute('aria-sort', 'descending');

      // Descending state: Inactive before Active (the words, not a boolean).
      await user.click(screen.getByRole('button', { name: 'State' }));
      await user.click(screen.getByRole('button', { name: 'State' }));
      expect(await order()).toEqual(['Bravo', 'Alpha', 'Charlie']);

      // After re-ordering, each row's links still open that row's camera.
      for (const row of await rows()) {
        const id = { Alpha: 'id-a', Bravo: 'id-b', Charlie: 'id-c' }[within(row).getAllByRole('cell')[1].textContent as 'Alpha'];
        expect(within(row).getByRole('link', { name: 'Scene' })).toHaveAttribute('href', `/cameras/${id}/scene`);
        expect(within(row).getByRole('link', { name: /^Analytics for / })).toHaveAttribute('href', `/cameras/${id}/analytics`);
      }

      // Sorting is keyboard-operable from the header control.
      screen.getByRole('button', { name: 'Name' }).focus();
      await user.keyboard('{Enter}');
      expect(screen.getByRole('columnheader', { name: /Name/ })).toHaveAttribute('aria-sort', 'ascending');
    });

    it('sends one create however often submit is pressed while it is pending', async () => {
      const user = userEvent.setup();
      let resolve: (value: unknown) => void = () => {};
      vi.mocked(createCamera).mockImplementationOnce(() => new Promise((done) => { resolve = done; }) as never);
      renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      const form = await openCreate(user);
      await user.type(screen.getByLabelText('Camera code'), 'CAM-02');
      await user.type(screen.getByLabelText('Camera name'), 'East Gate');
      await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
      await user.click(submit(form));

      const pending = within(form).getByRole('button', { name: 'Adding…' });
      expect(pending).toBeDisabled();
      // Enter in a field submits the form too; the pending create refuses it.
      await user.type(screen.getByLabelText('Camera name'), '{Enter}');
      expect(createCamera).toHaveBeenCalledTimes(1);
      resolve({ ...camera, id: 'new', code: 'CAM-02' });
      await waitFor(() => expect(screen.queryByRole('form', { name: 'Add camera' })).not.toBeInTheDocument());
    });

    it('names the subject of a failure no field owns, once, and keeps the draft', async () => {
      const user = userEvent.setup();
      vi.mocked(createCamera).mockRejectedValueOnce(new ApiError({ status: 503, code: 'camera_store_unavailable', detail: 'The camera store is unavailable.' }));
      renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      const form = await openCreate(user);
      await user.type(screen.getByLabelText('Camera code'), 'CAM-02');
      await user.type(screen.getByLabelText('Camera name'), 'East Gate');
      await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
      await user.click(submit(form));

      const alert = await within(form).findByText('The camera could not be created. The camera store is unavailable. (camera_store_unavailable)');
      expect(screen.getAllByText(/camera store is unavailable/)).toEqual([alert]);
      expect(screen.getByLabelText('Camera code')).toHaveValue('CAM-02');
      expect(screen.getByLabelText('Camera name')).toHaveValue('East Gate');
    });

    it('states an unreadable deployment timezone in the form, and puts no zone in its place (S4 carry)', async () => {
      const user = userEvent.setup();
      vi.mocked(getSystemConfig).mockRejectedValue(new ApiError({ status: 503, code: 'config_unavailable', detail: 'Configuration is unavailable.' }));
      renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      // Nothing is said while nobody is creating: the inventory does not use it.
      expect(screen.queryByText(/deployment timezone could not be read/)).not.toBeInTheDocument();

      const form = await openCreate(user);
      expect(await within(form).findByText(/deployment timezone could not be read/)).toBeInTheDocument();
      expect(screen.getByLabelText('Camera timezone')).toHaveValue('');
      // Empty and looking empty: no grey zone that reads as a default.
      expect(screen.getByLabelText('Camera timezone')).not.toHaveAttribute('placeholder');
      expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
      await user.type(screen.getByLabelText('Camera code'), 'CAM-02');
      await user.type(screen.getByLabelText('Camera name'), 'East Gate');
      await user.click(submit(form));
      expect(await screen.findByText('An IANA timezone is required.')).toBeInTheDocument();
      expect(createCamera).not.toHaveBeenCalled();

      // Recovery: the retry reads it, and the untouched field takes the default.
      vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
      await user.click(within(form).getByRole('button', { name: 'Retry display config' }));
      await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
      expect(within(form).queryByText(/deployment timezone could not be read/)).not.toBeInTheDocument();
    });

    it('keeps the last known inventory, said to be so, when the refresh after a create fails (§37.1 degraded)', async () => {
      const user = userEvent.setup();
      vi.mocked(listCameras)
        .mockResolvedValueOnce([camera])
        .mockRejectedValue(new ApiError({ status: 503, code: 'upstream_unavailable', detail: 'The upstream service did not respond.' }));
      renderWithApp(<CamerasPage />);
      await screen.findByText('North Gate');
      const form = await openCreate(user);
      await user.type(screen.getByLabelText('Camera code'), 'CAM-02');
      await user.type(screen.getByLabelText('Camera name'), 'East Gate');
      await waitFor(() => expect(screen.getByLabelText('Camera timezone')).toHaveValue('Asia/Kolkata'));
      await user.click(submit(form));

      expect(await screen.findByText('Showing the last known camera inventory; refreshing failed.')).toBeInTheDocument();
      // The rows stay, and stay usable; the recovery is the notice's retry.
      expect(screen.getByText('North Gate')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Scene' })).toHaveAttribute('href', `/cameras/${camera.id}/scene`);
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
      expect(screen.queryByText('No cameras registered')).not.toBeInTheDocument();
    });
  });
});
