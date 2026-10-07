import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Alert from './Alert';
import EmptyState from './EmptyState';
import LoadingState, { DEFAULT_SKELETON_ROWS } from './LoadingState';

/**
 * The shared state presentations. Section 14 treats conflating "unavailable"
 * with "empty" as a defect class, so the accessibility semantics that tell them
 * apart are asserted here rather than left to review.
 */

describe('Alert', () => {
  it('announces an error assertively and everything else politely', () => {
    const { unmount } = render(<Alert tone="error">Processing failed</Alert>);
    expect(screen.getByRole('alert')).toHaveTextContent('Processing failed');
    unmount();
    render(<Alert tone="info">Four of seven runs analysed</Alert>);
    expect(screen.getByRole('status')).toHaveTextContent('Four of seven runs analysed');
  });

  it('carries a retry beside the sentence that explains it', () => {
    render(<Alert tone="error" actions={<button type="button">Retry</button>}>Unavailable</Alert>);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('renders the stale tone with its own class so the dashed edge applies', () => {
    const { container } = render(<Alert tone="stale">Analysed with revision 3</Alert>);
    expect(container.querySelector('.alert--stale')).not.toBeNull();
  });
});

describe('EmptyState', () => {
  it('is a status region, not an alert: nothing has gone wrong', () => {
    render(<EmptyState title="No videos imported yet" />);
    expect(screen.getByRole('status')).toHaveTextContent('No videos imported yet');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('hatches the not-configured and unavailable placeholders', () => {
    // The hatch is the non-colour cue that separates "not set up" from
    // "nothing here yet" (section 8.2).
    const { container } = render(<EmptyState title="No scene configured" hatched />);
    expect(container.querySelector('.empty--hatched')).not.toBeNull();
  });
});

describe('LoadingState', () => {
  it('announces itself with its label', () => {
    render(<LoadingState label="Loading videos…" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading videos…');
  });

  it('renders skeleton rows when the row height is known, still labelled', () => {
    render(<LoadingState label="Loading videos…" rows={3} />);
    const region = screen.getByRole('status');
    expect(region).toHaveTextContent('Loading videos…');
    expect(region.querySelectorAll('.skeleton__row')).toHaveLength(3);
  });

  it('renders the confirmed default row count on request', () => {
    render(<LoadingState label="Loading videos…" rows="default" />);
    expect(screen.getByRole('status').querySelectorAll('.skeleton__row')).toHaveLength(DEFAULT_SKELETON_ROWS);
    expect(DEFAULT_SKELETON_ROWS).toBe(8);
  });

  it('announces the load as text inside its live region, not only as a name', () => {
    render(<LoadingState label="Loading videos…" rows={2} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading videos…');
  });

  it('renders a skeleton row as geometry only: no text, no icon, no spinner', () => {
    const { container } = render(<LoadingState rows={2} />);
    expect(container.querySelector('.spinner')).toBeNull();
    for (const row of container.querySelectorAll('.skeleton__row')) {
      expect(row).toBeEmptyDOMElement();
    }
  });
});

describe('EmptyState geometry', () => {
  it('is content-sized: no wrapper beyond the presentation itself', () => {
    const { container } = render(<EmptyState icon="video" title="No videos imported yet">Import one.</EmptyState>);
    const empty = container.querySelector('.empty');
    expect(empty).not.toBeNull();
    expect(empty?.children).toHaveLength(3);
    expect(container.firstElementChild).toBe(empty);
  });
});
