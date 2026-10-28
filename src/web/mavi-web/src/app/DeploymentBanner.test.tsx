import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getDeploymentDisclosure, type DeploymentDisclosure } from '../api/deployment';
import DeploymentBanner from './DeploymentBanner';
import { createMaviQueryClient } from './queryClient';

vi.mock('../api/deployment', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/deployment')>()),
  getDeploymentDisclosure: vi.fn(),
}));

const poc: DeploymentDisclosure = {
  schemaVersion: 'mavi-deployment-disclosure-v1',
  profile: 'poc-single-host',
  productionQualified: false,
  evidenceClass: 'Development',
  statement: 'Proof-of-concept installation (profile poc-single-host). Not Production-qualified. Evidence class: Development.',
  metadataStatus: 'verified',
  applicationRevision: 'a'.repeat(40),
  installedAtUtc: '2026-10-28T00:00:00Z',
  deviceStatus: 'reported',
  device: {
    requestedPolicy: 'auto',
    resolvedPolicy: 'cuda',
    reason: 'cuda_selected',
    runtimePackId: 'mavi-runtime-v2-cuda',
    runtimeVariant: 'windows-x86_64-cuda',
    resolvedAtUtc: '2026-10-28T00:00:00Z',
    verifyOnly: false,
  },
  packs: [],
};

function renderBanner() {
  const client = createMaviQueryClient();
  client.setDefaultOptions({ queries: { retry: false } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DeploymentBanner />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.mocked(getDeploymentDisclosure).mockReset());

/** ADR-020 §3: the PoC disclosure is on every surface and cannot be dismissed. */
describe('the PoC deployment banner', () => {
  it('states the profile, the qualification, the evidence class and the resolved device with its reason', async () => {
    vi.mocked(getDeploymentDisclosure).mockResolvedValue(poc);
    renderBanner();

    const banner = await screen.findByRole('note', { name: 'Deployment disclosure' });
    expect(banner).toHaveTextContent('Proof of concept');
    expect(banner).toHaveTextContent('Profile poc-single-host');
    expect(banner).toHaveTextContent('Not Production-qualified');
    expect(banner).toHaveTextContent('Evidence class Development');
    expect(banner).toHaveTextContent('Device CUDA (cuda_selected)');
    expect(within(banner).getByRole('link', { name: 'About this installation' })).toHaveAttribute('href', '/system');
  });

  it('offers no control that dismisses or hides it', async () => {
    vi.mocked(getDeploymentDisclosure).mockResolvedValue(poc);
    renderBanner();

    const banner = await screen.findByRole('note', { name: 'Deployment disclosure' });
    expect(within(banner).queryByRole('button')).not.toBeInTheDocument();
    // Its only interactive element is the link to the full disclosure.
    expect(within(banner).getAllByRole('link')).toHaveLength(1);
  });

  it('says the device is not yet resolved rather than omitting the clause', async () => {
    vi.mocked(getDeploymentDisclosure).mockResolvedValue({ ...poc, deviceStatus: 'not-reported', device: null });
    renderBanner();

    expect(await screen.findByRole('note', { name: 'Deployment disclosure' })).toHaveTextContent('Device not yet resolved');
  });

  it('renders nothing on a host that declares no PoC profile', async () => {
    vi.mocked(getDeploymentDisclosure).mockResolvedValue({ ...poc, profile: 'unspecified', statement: null, evidenceClass: null });
    renderBanner();

    await vi.waitFor(() => expect(getDeploymentDisclosure).toHaveBeenCalled());
    expect(screen.queryByRole('note', { name: 'Deployment disclosure' })).not.toBeInTheDocument();
  });
});
