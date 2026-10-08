import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { AsyncState } from './asyncState';
import StateRegion, { type RegionKind } from './StateRegion';

/**
 * State *presentation* by region kind (§37.1). Each test pins one rule of the
 * catalogue: one presentation per state, inside the region, at its own height,
 * one alert per cause with its retry trailing, and media that cannot be shown
 * reading as missing evidence rather than as an error or an empty result.
 */

const rows = (list: string[]) => <ul aria-label="Rows">{list.map((row) => <li key={row}>{row}</li>)}</ul>;

function region(state: AsyncState<string[]>, kind: RegionKind = 'column', extra: Record<string, unknown> = {}) {
  return render(
    <StateRegion
      kind={kind}
      state={state}
      label="videos"
      isEmpty={(list) => list.length === 0}
      empty={{ icon: 'video', title: 'No videos imported yet', body: 'Import an MP4 recording to begin.' }}
      {...extra}
    >
      {rows}
    </StateRegion>,
  );
}

describe('StateRegion selects exactly one presentation', () => {
  it('loads, and shows neither empty nor content', () => {
    region({ kind: 'loading' });
    expect(screen.getByRole('status')).toHaveTextContent('Loading videos…');
    expect(screen.queryByText('No videos imported yet')).not.toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('shows the empty presentation only for a successful empty result', () => {
    region({ kind: 'ready', data: [] });
    expect(screen.getByText('No videos imported yet')).toBeInTheDocument();
    expect(screen.getByText('Import an MP4 recording to begin.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows content for a populated result', () => {
    region({ kind: 'ready', data: ['clip.mp4'] });
    expect(within(screen.getByRole('list', { name: 'Rows' })).getByText('clip.mp4')).toBeInTheDocument();
  });

  it('never asks the empty question of a failure, and never renders empty for one', () => {
    const isEmpty = vi.fn(() => true);
    region({ kind: 'unavailable', error: new Error('network') }, 'column', { isEmpty });
    expect(isEmpty).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Videos could not be loaded.');
    expect(screen.queryByText('No videos imported yet')).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('column (§37.1)', () => {
  it('loads as skeleton rows at the default count where the row geometry is known', () => {
    const { container } = region({ kind: 'loading' }, 'column', { skeleton: { rows: 'default' } });
    expect(screen.getByRole('status')).toHaveTextContent('Loading videos…');
    expect(container.querySelectorAll('.skeleton__row')).toHaveLength(8);
    expect(container.querySelector('.spinner')).toBeNull();
  });

  it('loads as a list skeleton at the result-row pitch when asked', () => {
    const { container } = region({ kind: 'loading' }, 'column', { skeleton: { rows: 3, pitch: 'list' } });
    expect(container.querySelector('.skeleton--list')).not.toBeNull();
    expect(container.querySelectorAll('.skeleton__row')).toHaveLength(3);
  });

  it('is one alert with its retry trailing inside it, never a detached button', async () => {
    const onRetry = vi.fn();
    region({ kind: 'unavailable', error: new Error('down') }, 'column', { onRetry });
    const alerts = screen.getAllByRole('alert');
    expect(alerts).toHaveLength(1);
    const retry = within(alerts[0]).getByRole('button', { name: 'Retry' });
    expect(screen.getAllByRole('button')).toEqual([retry]);
    await userEvent.click(retry);
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('states a failure retrying cannot mend without the control', () => {
    region({ kind: 'unavailable', error: new Error('gone') }, 'column', {
      onRetry: vi.fn(),
      retryable: () => false,
      unavailableMessage: () => 'Track was not found.',
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Track was not found.');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('keeps retained data on screen beneath one warning when a refresh failed, with no loading', async () => {
    const onRetry = vi.fn();
    region({ kind: 'ready', data: ['clip.mp4'], degraded: { error: new Error('later') } }, 'column', { onRetry });
    expect(screen.getByText('clip.mp4')).toBeInTheDocument();
    const warning = screen.getByRole('status');
    expect(warning).toHaveTextContent('Showing the last known videos; refreshing failed.');
    expect(screen.queryByText(/Loading/)).not.toBeInTheDocument();
    await userEvent.click(within(warning).getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('renders the empty presentation content-sized at the region top, uncontained', () => {
    const { container } = region({ kind: 'ready', data: [] });
    const wrapper = container.firstElementChild as HTMLElement;
    expect(wrapper).toHaveClass('state-region', 'state-region--column');
    expect(wrapper.querySelector('.empty')).not.toBeNull();
    expect(wrapper.querySelector('.panel')).toBeNull();
  });
});

describe('panel (§37.1)', () => {
  it('keeps its unavailable alert inside the panel body it replaces', () => {
    render(
      <section aria-label="Video panel">
        <StateRegion kind="panel" state={{ kind: 'unavailable', error: new Error('x') }} label="video metadata" onRetry={vi.fn()}>
          {() => <p>facts</p>}
        </StateRegion>
      </section>,
    );
    const panel = screen.getByRole('region', { name: 'Video panel' });
    expect(within(panel).getByRole('alert')).toHaveTextContent('Video metadata could not be loaded.');
    expect(within(within(panel).getByRole('alert')).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('states a failure announced by another region as text, with no second alert or retry', () => {
    render(
      <StateRegion
        kind="panel"
        state={{ kind: 'unavailable', error: new Error('x') }}
        label="media status"
        causeAnnouncedElsewhere
        unavailableMessage={() => 'Its distribution cannot be shown.'}
        onRetry={vi.fn()}
      >
        {() => null}
      </StateRegion>,
    );
    expect(screen.getByText('Its distribution cannot be shown.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('page (§37.1)', () => {
  it('presents one region and leaves independent siblings to their own state', () => {
    render(
      <>
        <StateRegion kind="page" state={{ kind: 'unavailable', error: new Error('x') }} label="the scene" onRetry={vi.fn()}>
          {() => null}
        </StateRegion>
        <StateRegion kind="panel" state={{ kind: 'ready', data: ['independent'] }} label="other">
          {(data) => <p>{data[0]}</p>}
        </StateRegion>
      </>,
    );
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByText('independent')).toBeInTheDocument();
  });
});

describe('row (§37.1)', () => {
  it('keeps the row and says why its cell is missing, with the retry as a row action', async () => {
    const onRetry = vi.fn();
    render(
      <table>
        <tbody>
          <tr>
            <td>clip-0001.mp4</td>
            <td>
              <StateRegion
                kind="row"
                state={{ kind: 'unavailable', error: new Error('x') }}
                label="run status"
                unavailableMessage={() => 'Run status unavailable'}
                onRetry={onRetry}
              >
                {() => null}
              </StateRegion>
            </td>
          </tr>
        </tbody>
      </table>,
    );
    const row = screen.getByRole('row');
    expect(within(row).getByText('clip-0001.mp4')).toBeInTheDocument();
    expect(within(row).getByText('Run status unavailable')).toBeInTheDocument();
    expect(within(row).queryByRole('alert')).not.toBeInTheDocument();
    await userEvent.click(within(row).getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it.each([
    ['unavailable', { kind: 'unavailable', error: new Error('x') } as AsyncState<null>],
    ['degraded', { kind: 'ready', data: null, degraded: { error: new Error('x') } } as AsyncState<null>],
  ])('in a dense cell retries %s with a 26×26 icon control named for what it reloads', async (_name, state) => {
    const onRetry = vi.fn();
    render(
      <StateRegion
        kind="row"
        state={state}
        label="failure detail"
        unavailableMessage={() => 'Failure detail unavailable'}
        degradedMessage="Failure detail may be out of date"
        onRetry={onRetry}
        retryLabel="Reload failure detail for clip-0001.mp4"
        compactRetry
      >
        {() => null}
      </StateRegion>,
    );
    const retry = screen.getByRole('button', { name: 'Reload failure detail for clip-0001.mp4' });
    // Icon-only (§36.3): the name is carried, not drawn, and the pointer gets it as a tooltip.
    expect(retry).toHaveClass('btn--icon');
    expect(retry).toHaveAttribute('title', 'Reload failure detail for clip-0001.mp4');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    await userEvent.click(retry);
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe('media (§37.1)', () => {
  it('renders an unavailable image as the evidence placeholder, not an alert, an empty block or a spinner', () => {
    const { container } = region({ kind: 'unavailable', error: new Error('x') }, 'media');
    expect(screen.getByRole('img', { name: /^No image/ })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(container.querySelector('.empty, .spinner, img')).toBeNull();
  });

  it('reserves the frame while an image is still expected: matte only, no spinner', () => {
    const { container } = region({ kind: 'loading' }, 'media');
    expect(container.querySelector('.evidence-placeholder--pending')).not.toBeNull();
    expect(container.querySelector('.spinner')).toBeNull();
  });
});
