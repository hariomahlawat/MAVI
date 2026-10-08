/**
 * The keys the Search results implement (`VisualSearchPage`'s window handler),
 * as the `?` shortcut sheet lists them (§17, §22). Kept beside the handler, and
 * `VisualSearchPage.test.tsx` presses every key listed here and checks it does
 * what its description says, so the sheet and the handler fail together.
 */
export const SEARCH_SHORTCUTS: ReadonlyArray<{ keys: readonly string[]; description: string }> = [
  { keys: ['j', '↓'], description: 'Select the next result' },
  { keys: ['k', '↑'], description: 'Select the previous result' },
  { keys: ['Enter'], description: 'Open the selected result in Review' },
  { keys: ['Esc'], description: 'Close the inspector' },
];
