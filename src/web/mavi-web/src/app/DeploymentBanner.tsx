import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getDeploymentDisclosure, POC_PROFILE, type DeploymentDisclosure } from '../api/deployment';
import Icon from '../shared/components/Icon';
import { queryKeys } from './queryClient';

/** The device clause of the disclosure: what the launcher resolved, and why (ADR-008). */
export function deviceClause(disclosure: DeploymentDisclosure): string {
  if (disclosure.device) {
    return `Device ${disclosure.device.resolvedPolicy.toUpperCase()} (${disclosure.device.reason})`;
  }
  return disclosure.deviceStatus === 'unavailable' ? 'Device record unreadable' : 'Device not yet resolved';
}

/**
 * The persistent PoC disclosure (ADR-020 §3; §15 Banner: a page-scope condition
 * that persists, never auto-dismissed). It has no close control and no
 * preference that hides it: whenever the platform reports the PoC profile, it
 * is on every surface. What it says — not Production-qualified, Development
 * evidence — comes from the API, where it is fixed by code for the profile.
 */
export default function DeploymentBanner() {
  const deployment = useQuery({
    queryKey: queryKeys.deployment,
    queryFn: ({ signal }) => getDeploymentDisclosure(signal),
    retry: 1,
    refetchInterval: 60_000,
  });

  // Data already received stays on screen through a failed refetch: once the
  // platform has said it is a PoC host, the banner does not disappear because a
  // later poll failed.
  const disclosure = deployment.data;
  if (!disclosure || disclosure.profile !== POC_PROFILE) return null;

  return (
    <div className="deployment-banner" role="note" aria-label="Deployment disclosure">
      <Icon name="alert" />
      <p className="deployment-banner__text">
        <strong>Proof of concept</strong>
        <span>Profile {disclosure.profile}</span>
        <span>{disclosure.productionQualified ? 'Production-qualified' : 'Not Production-qualified'}</span>
        <span>Evidence class {disclosure.evidenceClass ?? 'unknown'}</span>
        <span>{deviceClause(disclosure)}</span>
      </p>
      <Link className="deployment-banner__link" to="/system">About this installation</Link>
    </div>
  );
}
