import { ButtonLink } from '../shared/components/Button';
import EmptyState from '../shared/components/EmptyState';
import { ContextBar } from '../shared/workspace';

/**
 * The one surface with no owning section (§5): rendered inside the shell, with
 * its Context Bar saying `Not found`, and no rail item highlighted.
 */
export default function NotFoundPage() {
  return (
    <section className="page">
      <ContextBar surface="not-found" />
      <EmptyState title="This page does not exist." actions={<ButtonLink to="/">Go to Overview</ButtonLink>}>
        The address may be mistyped, or the page may have moved.
      </EmptyState>
    </section>
  );
}
