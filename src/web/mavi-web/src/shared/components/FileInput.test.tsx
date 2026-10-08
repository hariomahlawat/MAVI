import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import Field from './Field';
import FileInput from './FileInput';

function Harness({
  error,
  disabled = false,
  onPick = () => {},
}: { error?: string; disabled?: boolean; onPick?: (file: File | null) => void }) {
  const [file, setFile] = useState<File | null>(null);
  return (
    <>
      <Field label="MP4 file" error={error} help="One MP4 per import.">
        {(control) => (
          <FileInput
            {...control}
            accept=".mp4,video/mp4"
            file={file}
            disabled={disabled}
            onChange={(next) => { setFile(next); onPick(next); }}
          />
        )}
      </Field>
      <button type="button" onClick={() => setFile(null)}>Clear</button>
    </>
  );
}

const mp4 = () => new File(['video'], 'north-gate-0800.mp4', { type: 'video/mp4' });

describe('FileInput (§27)', () => {
  it("is a native file input, labelled by its Field, with the caller's accept", () => {
    render(<Harness />);
    const input = screen.getByLabelText('MP4 file');
    expect(input.tagName).toBe('INPUT');
    expect(input).toHaveAttribute('type', 'file');
    expect(input).toHaveAttribute('accept', '.mp4,video/mp4');
    expect(input).not.toHaveAttribute('multiple');
  });

  it('says plainly when no file is chosen, and names the chosen file on screen', async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    render(<Harness onPick={onPick} />);
    const input = screen.getByLabelText('MP4 file');
    expect(screen.getByText('No file selected')).toBeVisible();

    const file = mp4();
    await user.upload(input, file);
    expect(onPick).toHaveBeenCalledWith(file);
    expect(screen.getByText('north-gate-0800.mp4')).toBeInTheDocument();
    expect(screen.queryByText('No file selected')).not.toBeInTheDocument();
    // The name is part of the field's description, after the help.
    expect(input).toHaveAccessibleDescription('One MP4 per import. north-gate-0800.mp4');
  });

  it('forgets the native selection when the caller clears the file', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByLabelText('MP4 file') as HTMLInputElement;
    await user.upload(input, mp4());
    expect(input.files).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(input.value).toBe('');
    expect(screen.getByText('No file selected')).toBeInTheDocument();
  });

  it('is reached by Tab and pressed by the keyboard as the native control', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByLabelText('MP4 file');
    const opened = vi.fn();
    input.addEventListener('click', opened);
    await user.tab();
    expect(input).toHaveFocus();
    // The frame draws the ring on any focus, so a programmatic move is visible too.
    expect(input.closest('.file-input')?.matches(':focus-within')).toBe(true);
    await user.keyboard('{Enter}');
    await user.keyboard(' ');
    expect(opened).toHaveBeenCalled();
  });

  it('passes the refusal to the native input and to the frame, error first in the description', () => {
    render(<Harness error="An MP4 file is required." />);
    const input = screen.getByLabelText('MP4 file');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription('An MP4 file is required. One MP4 per import. No file selected');
    expect(input.closest('.file-input')).toHaveAttribute('data-invalid', 'true');
  });

  it('is disabled on the native control and the frame, and takes no file', async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    render(<Harness disabled onPick={onPick} />);
    const input = screen.getByLabelText('MP4 file');
    expect(input).toBeDisabled();
    expect(input.closest('.file-input')).toHaveAttribute('data-disabled', 'true');
    await user.upload(input, mp4());
    expect(onPick).not.toHaveBeenCalled();
  });

  it('keeps the choose affordance out of the accessible name: the native input is the button', () => {
    render(<Harness />);
    expect(screen.getByLabelText('MP4 file')).toHaveAccessibleName('MP4 file');
    expect(screen.getByText('Choose file').closest('[aria-hidden="true"]')).not.toBeNull();
  });
});
