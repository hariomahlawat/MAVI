import { render } from '@testing-library/react';
import { describe, expect, expectTypeOf, it } from 'vitest';
import Icon, { type IconName } from './Icon';

describe('IconName (§27: a closed union of the shipped icons)', () => {
  it('is a union of literal names, not `string`', () => {
    expectTypeOf<string>().not.toMatchTypeOf<IconName>();
    expectTypeOf<'x'>().toMatchTypeOf<IconName>();
    expectTypeOf<'layers'>().toMatchTypeOf<IconName>();
  });

  it('refuses a name that is not drawn, at typecheck', () => {
    // @ts-expect-error `close` is not a shipped icon; the close glyph is `x`.
    const missing: IconName = 'close';
    expect(missing).toBe('close');
  });

  it('draws every name it accepts', () => {
    const names: IconName[] = ['overview', 'camera', 'video', 'upload', 'x', 'check', 'layers'];
    for (const name of names) {
      const { container, unmount } = render(<Icon name={name} />);
      expect(container.querySelector('path')?.getAttribute('d')).toBeTruthy();
      unmount();
    }
  });
});
