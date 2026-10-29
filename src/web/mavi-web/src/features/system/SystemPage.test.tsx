import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { getDeploymentDisclosure } from '../../api/deployment';
import { createMaviQueryClient } from '../../app/queryClient';
import { SurfaceSlotProvider } from '../../shared/workspace';
import SystemPage from './SystemPage';

vi.mock('../../api/deployment', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/deployment')>()),
  getDeploymentDisclosure: vi.fn(),
}));

function renderPage() {
  const client = createMaviQueryClient();
  client.setDefaultOptions({ queries: { retry: false } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SurfaceSlotProvider>{() => <SystemPage />}</SurfaceSlotProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('the About page (ADR-020 §3)', () => {
  it('lists the profile, device and reason, and every pack with its verification status', async () => {
    vi.mocked(getDeploymentDisclosure).mockResolvedValue({
      schemaVersion: 'mavi-deployment-disclosure-v1',
      profile: 'poc-single-host',
      productionQualified: false,
      evidenceClass: 'Development',
      statement: 'Proof-of-concept installation (profile poc-single-host). Not Production-qualified. Evidence class: Development.',
      metadataStatus: 'verified',
      applicationRevision: 'b'.repeat(40),
      installedAtUtc: '2026-10-28T00:00:00Z',
      deviceStatus: 'reported',
      device: {
        requestedPolicy: 'auto',
        resolvedPolicy: 'cpu',
        reason: 'cuda_pack_absent',
        runtimePackId: 'mavi-runtime-v2-cpu',
        runtimeVariant: 'windows-x86_64-cpu',
        resolvedAtUtc: '2026-10-28T00:00:00Z',
        verifyOnly: true,
      },
      packs: [
        { kind: 'runtime', role: 'vision', capabilityId: null, packId: 'mavi-runtime-v2-cpu', variant: 'windows-x86_64-cpu', verificationStatus: 'qualified-development', note: null },
        { kind: 'model', role: 'vision', capabilityId: 'detector', packId: 'mavi-model-v2-rtmdet', variant: null, verificationStatus: 'verified', note: null },
      ],
      identity: {
        mode: 'windows-negotiate',
        attributable: true,
        operatorsConfigured: true,
        statement: 'Operators are identified by their Windows account; every recorded action names the account.',
        installedMode: 'windows-negotiate',
      },
    });
    renderPage();

    expect(await screen.findByText('Not Production-qualified')).toBeInTheDocument();
    expect(screen.getByText('poc-single-host')).toBeInTheDocument();
    expect(screen.getByText('cuda_pack_absent')).toBeInTheDocument();
    const rows = within(screen.getByRole('table')).getAllByRole('row');
    expect(rows).toHaveLength(3);
    expect(rows[2]).toHaveTextContent('mavi-model-v2-rtmdet');
    expect(rows[2]).toHaveTextContent('verified');
    expect(screen.getByText('Windows account (Negotiate)')).toBeInTheDocument();
    expect(screen.getByText('Attributed to a Windows account')).toBeInTheDocument();
  });

  it('labels the development fallback identity as unattributed (ADR-010 §3)', async () => {
    vi.mocked(getDeploymentDisclosure).mockResolvedValue({
      schemaVersion: 'mavi-deployment-disclosure-v1',
      profile: 'poc-single-host',
      productionQualified: false,
      evidenceClass: 'Development',
      statement: 'Proof-of-concept installation (profile poc-single-host). Not Production-qualified. Evidence class: Development.',
      metadataStatus: 'verified',
      applicationRevision: null,
      installedAtUtc: null,
      deviceStatus: 'not-reported',
      device: null,
      packs: [],
      identity: {
        mode: 'development-unattributed',
        attributable: false,
        operatorsConfigured: true,
        statement: "Development fallback identity: actions are recorded as 'development-unattributed' and are not attributable to a person.",
        installedMode: 'windows-negotiate',
      },
    });
    renderPage();

    expect(await screen.findByText('Development fallback (unattributed)')).toBeInTheDocument();
    expect(screen.getByText('Not attributable')).toBeInTheDocument();
    expect(screen.getByText(/not attributable to a person/)).toBeInTheDocument();
    expect(screen.getByText('windows-negotiate')).toBeInTheDocument();
  });
});
