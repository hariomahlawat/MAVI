import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

// A StatusSlot's announcer repeats, visually hidden, the sentence its
// presentation shows (§23). Text queries look for the presentation; the
// announcer is asserted by role where a test is about announcing.
configure({ defaultIgnore: 'script, style, .status-slot__announcer' });

afterEach(() => {
  cleanup();
});
