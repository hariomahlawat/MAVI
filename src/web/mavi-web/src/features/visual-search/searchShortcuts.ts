/**
 * The keys the Search results implement (`VisualSearchPage`'s window handler),
 * as the `?` shortcut sheet lists them (§17, §22). Owned here, beside the
 * handler, so the sheet cannot drift from what the keys do.
 */
export const SEARCH_SHORTCUTS: ReadonlyArray<{ keys: readonly string[]; description: string }> = [
  { keys: ['j', '↓'], description: 'Select the next result' },
  { keys: ['k', '↑'], description: 'Select the previous result' },
  { keys: ['Enter'], description: 'Open the selected result in Review' },
  { keys: ['Esc'], description: 'Close the inspector' },
];
