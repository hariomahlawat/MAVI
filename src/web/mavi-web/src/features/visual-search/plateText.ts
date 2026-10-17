/** Mirrors the frozen mavi-plate-normalisation-v1 search grammar (not OCR correction).
 * NFKC first; remove only the nine specified ASCII separators and middle dot.
 * Uppercase ASCII a-z only. Never fold O/0, I/1, B/8 or non-ASCII glyphs.
 * A null result is a refused search, never a fuzzy fallback.
 */
export function normalisePlateText(input: string): string | null {
  const canonical = input.normalize('NFKC')
    .replace(/[ \t\r\n\-./:\u00b7]/g, '')
    .replace(/[a-z]/g, (letter) => letter.toUpperCase());
  return /^[A-Z0-9]{3,15}$/.test(canonical) ? canonical : null;
}
