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
    });
    renderPage();

    expect(await screen.findByText('Not Production-qualified')).toBeInTheDocument();
    expect(screen.getByText('poc-single-host')).toBeInTheDocument();
    expect(screen.getByText('cuda_pack_absent')).toBeInTheDocument();
    const rows = within(screen.getByRole('table')).getAllByRole('row');
    expect(rows).toHaveLength(3);
    expect(rows[2]).toHaveTextContent('mavi-model-v2-rtmdet');
    expect(rows[2]).toHaveTextContent('verified');
  });

  it('shows the plates role device and reason, each plate pack licence and the plate known limits (PoC S3)', async () => {
    vi.mocked(getDeploymentDisclosure).mockResolvedValue({
      schemaVersion: 'mavi-deployment-disclosure-v1',
      profile: 'poc-single-host',
      productionQualified: false,
      evidenceClass: 'Development',
      statement: 'Proof-of-concept installation (profile poc-single-host). Not Production-qualified. Evidence class: Development.',
      metadataStatus: 'verified',
      applicationRevision: 'b'.repeat(40),
      installedAtUtc: '2026-10-29T00:00:00Z',
      deviceStatus: 'reported',
      device: {
        requestedPolicy: 'auto', resolvedPolicy: 'cuda', reason: 'cuda_selected', runtimePackId: 'mavi-runtime-v2-cuda',
        runtimeVariant: 'windows-x86_64-cuda', resolvedAtUtc: '2026-10-29T00:00:00Z', verifyOnly: false,
      },
      roleDevices: [{
        role: 'plates',
        deviceStatus: 'reported',
        device: {
          requestedPolicy: 'auto', resolvedPolicy: 'cpu', reason: 'plates_runtime_cpu_only', runtimePackId: 'mavi-runtime-v2-plates',
          runtimeVariant: 'windows-x86_64-cpu', resolvedAtUtc: '2026-10-29T00:00:00Z', verifyOnly: false,
        },
      }],
      packs: [
        { kind: 'model', role: 'plates', capabilityId: 'ocr', packId: 'mavi-model-v2-ocr', variant: null, verificationStatus: 'unverified',
          note: 'fast-plate-ocr-cct-s-v2-global arg-plates-dev.1', licence: 'MIT, read from its LICENSE (SHA-256 a953e626)' },
        { kind: 'model', role: 'plates', capabilityId: 'plate-detector', packId: 'mavi-model-v2-det', variant: null, verificationStatus: 'unverified',
          note: null, licence: 'Apache-2.0, read from its LICENSE (SHA-256 3840c5c0)' },
      ],
    });
    renderPage();

    const plates = await screen.findByRole('region', { name: 'Plates device' });
    expect(within(plates).getByText('CPU')).toBeInTheDocument();
    expect(within(plates).getByText('plates_runtime_cpu_only')).toBeInTheDocument();
    // The Vision worker's own device stays its own.
    expect(within(screen.getByRole('region', { name: 'Vision device' })).getByText('cuda_selected')).toBeInTheDocument();
    const rows = within(screen.getByRole('table')).getAllByRole('row');
    expect(rows[1]).toHaveTextContent('MIT, read from its LICENSE');
    expect(rows[2]).toHaveTextContent('Apache-2.0, read from its LICENSE');

    const limits = screen.getByRole('region', { name: 'Known limits: plate reading' });
    expect(limits).toHaveTextContent('52/110');
    expect(limits).toHaveTextContent('45/79');
    expect(limits).toHaveTextContent('proxy data only');
    expect(limits).toHaveTextContent('No Indian plates');
    expect(limits).toHaveTextContent('Profile poc-single-host (ADR-020): not Production-qualified; evidence class Development.');
  });

  it('shows the plate known limits and the disclosure even when the platform reports no profile', async () => {
    vi.mocked(getDeploymentDisclosure).mockResolvedValue({
      schemaVersion: 'mavi-deployment-disclosure-v1', profile: 'unspecified', productionQualified: false, evidenceClass: null,
      statement: null, metadataStatus: 'not-configured', applicationRevision: null, installedAtUtc: null,
      deviceStatus: 'not-reported', device: null, packs: [],
    });
    renderPage();

    const limits = await screen.findByRole('region', { name: 'Known limits: plate reading' });
    expect(limits).toHaveTextContent('52/110');
    expect(limits).toHaveTextContent('not Production-qualified');
  });
});
