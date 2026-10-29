import { useQuery } from '@tanstack/react-query';
import { getDeploymentDisclosure, type DeploymentDisclosure } from '../../api/deployment';
import { queryKeys } from '../../app/queryClient';
import { deviceClause } from '../../app/DeploymentBanner';
import { fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import KeyValue from '../../shared/components/KeyValue';
import Panel from '../../shared/components/Panel';
import { ContextBar } from '../../shared/workspace';

const metadataText: Record<DeploymentDisclosure['metadataStatus'], string> = {
  verified: 'Verified at platform start',
  unavailable: 'Unavailable — the release metadata could not be read',
  'not-configured': 'Not configured (no deployment profile declared)',
};

/**
 * System / About (ADR-020 §3): the installation's profile, its qualification
 * status and evidence class, the device the Vision launcher resolved and why,
 * and every bound pack's identity and verification status. Read-only.
 */
export default function SystemPage() {
  const deployment = useQuery({
    queryKey: queryKeys.deployment,
    queryFn: ({ signal }) => getDeploymentDisclosure(signal),
  });

  return (
    <section className="page">
      <ContextBar surface="system" />
      <StateRegion kind="page" state={fromQuery(deployment)} label="deployment disclosure">
        {(disclosure) => <SystemDetails disclosure={disclosure} />}
      </StateRegion>
    </section>
  );
}

function SystemDetails({ disclosure }: { disclosure: DeploymentDisclosure }) {
  const device = disclosure.device;
  return (
    <div className="system-page">
      {disclosure.statement ? <Alert tone="warning" announce={false}>{disclosure.statement}</Alert> : null}
      <Panel title="Deployment" headingId="system-deployment">
        <KeyValue
          items={[
            { label: 'Profile', value: disclosure.profile, mono: true },
            { label: 'Production qualification', value: disclosure.productionQualified ? 'Production-qualified' : 'Not Production-qualified' },
            { label: 'Evidence class', value: disclosure.evidenceClass ?? 'Not declared' },
            { label: 'Release metadata', value: metadataText[disclosure.metadataStatus] },
            { label: 'Application revision', value: disclosure.applicationRevision ?? 'Not recorded', mono: Boolean(disclosure.applicationRevision) },
            { label: 'Installed', value: disclosure.installedAtUtc ?? 'Not recorded' },
          ]}
        />
      </Panel>
      <Panel title="Vision device" headingId="system-device">
        {device ? (
          <KeyValue
            items={[
              { label: 'Requested policy', value: device.requestedPolicy, mono: true },
              { label: 'Resolved device', value: device.resolvedPolicy.toUpperCase() },
              { label: 'Reason', value: device.reason, mono: true },
              { label: 'Runtime Pack', value: device.runtimePackId ?? 'Not recorded', mono: Boolean(device.runtimePackId) },
              { label: 'Runtime variant', value: device.runtimeVariant ?? 'Not recorded', mono: Boolean(device.runtimeVariant) },
              { label: 'Resolved', value: `${device.resolvedAtUtc ?? 'time not recorded'} · ${device.verifyOnly ? 'readiness check' : 'worker launch'}` },
            ]}
          />
        ) : (
          <p>{deviceClause(disclosure)}.</p>
        )}
      </Panel>
      <Panel title="Packs" headingId="system-packs" body="flush">
        {disclosure.packs.length === 0 ? (
          <p className="system-page__none">No pack is recorded for this installation.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Kind</th>
                <th scope="col">Role</th>
                <th scope="col">Capability</th>
                <th scope="col">Pack identity</th>
                <th scope="col">Variant</th>
                <th scope="col">Verification</th>
              </tr>
            </thead>
            <tbody>
              {disclosure.packs.map((pack) => (
                <tr key={`${pack.kind}:${pack.packId}:${pack.variant ?? ''}`}>
                  <td>{pack.kind}</td>
                  <td>{pack.role}</td>
                  <td>{pack.capabilityId ?? '—'}</td>
                  <td><code title={pack.packId}>{pack.packId}</code>{pack.note ? <span className="system-page__note"> · {pack.note}</span> : null}</td>
                  <td>{pack.variant ?? '—'}</td>
                  <td>{pack.verificationStatus}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
