import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import componentsCss from '../../styles/components.css?raw';
import ToggleChip from './ToggleChip';

function Harness({ initial = false, disabled = false }: { initial?: boolean; disabled?: boolean }) {
  const [on, setOn] = useState(initial);
  return (
    <>
      <ToggleChip pressed={on} disabled={disabled} aria-describedby={disabled ? 'why' : undefined} onClick={() => setOn(!on)}>
        Trajectory
      </ToggleChip>
      {disabled ? <span id="why">No trajectory was recorded.</span> : null}
    </>
  );
}

describe('ToggleChip (§12, §27)', () => {
  it('is a native button that always states aria-pressed', () => {
    render(<Harness />);
    const chip = screen.getByRole('button', { name: 'Trajectory', pressed: false });
    expect(chip.tagName).toBe('BUTTON');
    expect(chip).toHaveAttribute('type', 'button');
    expect(chip).toHaveAttribute('aria-pressed', 'false');
  });

  it('toggles by pointer, Enter and Space', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const chip = screen.getByRole('button', { name: 'Trajectory' });
    await user.click(chip);
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    chip.focus();
    await user.keyboard('{Enter}');
    expect(chip).toHaveAttribute('aria-pressed', 'false');
    await user.keyboard(' ');
    expect(chip).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows the pressed state by shape as well as colour: a check in a filled mark only when on', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const chip = screen.getByRole('button', { name: 'Trajectory' });
    const mark = chip.querySelector('.toggle-chip__mark');
    expect(mark).toHaveAttribute('aria-hidden', 'true');
    expect(mark?.querySelector('svg')).toBeNull();
    await user.click(chip);
    expect(chip.querySelector('.toggle-chip__mark svg')).not.toBeNull();
    // The accessible name is the label alone; the mark adds nothing to it.
    expect(chip).toHaveAccessibleName('Trajectory');
  });

  it('is disabled by the shared Button contract, keeps its reason bound, and carries no tooltip', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <>
        <ToggleChip pressed disabled aria-describedby="reason" onClick={onClick}>Zones</ToggleChip>
        <span id="reason">This Track has no zone analytics.</span>
      </>,
    );
    const chip = screen.getByRole('button', { name: 'Zones', pressed: true });
    expect(chip).toBeDisabled();
    expect(chip).toHaveClass('btn');
    expect(chip).toHaveAccessibleDescription('This Track has no zone analytics.');
    await user.click(chip);
    expect(onClick).not.toHaveBeenCalled();
    expect(document.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('is painted only by the shared rules: no chip-specific disabled, opacity or hover-colour rule', () => {
    const rules = Array.from(componentsCss.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g))
      .filter((match) => match[1].includes('.toggle-chip'));
    expect(rules.length).toBeGreaterThan(0);
    for (const [, selector, body] of rules) {
      expect(body, selector).not.toMatch(/opacity/);
      // Hover belongs to `.btn` (a surface step); the chip adds none of its own.
      expect(selector, selector).not.toMatch(/:hover/);
      // The chip itself is never a disabled subject: `.btn:disabled` paints it.
      const subjects = selector.split(',').map((sel) => sel.trim().split(/[\s>+~]+/).pop() ?? '');
      for (const subject of subjects) {
        if (/:disabled|aria-disabled/.test(subject)) expect(subject, selector).not.toMatch(/^\.toggle-chip(?!__)/);
      }
    }
  });
});
