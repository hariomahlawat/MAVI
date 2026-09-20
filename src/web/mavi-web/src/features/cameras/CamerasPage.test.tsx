import { screen, waitFor } from '@testing-library/react';
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

describe('CamerasPage', () => {
  beforeEach(() => {
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(createCamera).mockResolvedValue({ ...camera, id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21413', code: 'CAM-02' });
  });

  it('does not submit an incomplete camera form', async () => {
    const user = userEvent.setup();
    renderWithApp(<CamerasPage />);
    await screen.findByText('North Gate');

    await user.click(screen.getByRole('button', { name: 'Add camera' }));

    expect(createCamera).not.toHaveBeenCalled();
  });

  it('surfaces the stable duplicate-code conflict', async () => {
    const user = userEvent.setup();
    vi.mocked(createCamera).mockRejectedValueOnce(new ApiError({
      status: 409,
      code: 'camera_code_duplicate',
      detail: 'A camera with this code already exists.',
    }));
    renderWithApp(<CamerasPage />);

    await screen.findByText('North Gate');
    await user.type(screen.getByLabelText('Camera code'), 'CAM-01');
    await user.type(screen.getByLabelText('Camera name'), 'Duplicate');
    await waitFor(() => expect(screen.getByLabelText('Camera timezone (IANA, e.g. Asia/Kolkata)')).toHaveValue('Asia/Kolkata'));
    await user.click(screen.getByRole('button', { name: 'Add camera' }));

    expect(await screen.findByText('A camera with this code already exists.')).toBeInTheDocument();
  });

  it('renders inventory and creates a camera with confirmed timezone', async () => {
    const user = userEvent.setup();
    renderWithApp(<CamerasPage />);

    expect(await screen.findByText('North Gate')).toBeInTheDocument();
    expect(screen.getByText('Asia/Kolkata')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Camera code'), 'CAM-02');
    await user.type(screen.getByLabelText('Camera name'), 'East Gate');

    const timezone = screen.getByLabelText('Camera timezone (IANA, e.g. Asia/Kolkata)');
    await waitFor(() => expect(timezone).toHaveValue('Asia/Kolkata'));
    await user.click(screen.getByRole('button', { name: 'Add camera' }));

    await waitFor(() => expect(createCamera).toHaveBeenCalledWith({
      code: 'CAM-02',
      name: 'East Gate',
      timeZoneId: 'Asia/Kolkata',
    }));
  });

  it('links each camera to its scene editor', async () => {
    vi.mocked(listCameras).mockResolvedValue([camera]);
    renderWithApp(<CamerasPage />);

    const link = await screen.findByRole('link', { name: 'Scene' });
    expect(link).toHaveAttribute('href', `/cameras/${camera.id}/scene`);
  });
});
