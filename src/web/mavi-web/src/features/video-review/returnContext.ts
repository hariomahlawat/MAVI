import { isGuid } from '../../api/client';
import { canonicalSearchParams, parseCommittedSearch } from '../visual-search/searchState';

/**
 * Where "Back to search" goes. The Review page trusts only a `from` value that
 * re-parses as a valid committed search (plus an optional `track` selection);
 * anything else, including a missing value on a direct link or refresh, falls
 * back to the Track's own video scope. The committed filters are restored
 * exactly; the result snapshot is re-run, not resumed.
 */
export function returnToSearchPath(from: string | null, videoAssetId: string, trackId: string): string {
  const fallback = `/search?videoAssetId=${videoAssetId}&track=${trackId}`;
  if (from === null) return fallback;

  const params = new URLSearchParams(from);
  const trackValues = params.getAll('track');
  params.delete('track');
  if (trackValues.length > 1) return fallback;
  const selected = trackValues[0];
  if (selected !== undefined && !isGuid(selected)) return fallback;

  const parsed = parseCommittedSearch(params);
  if (!parsed.isValid) return fallback;
  // Every remaining key must be one the committed search understands.
  const canonical = canonicalSearchParams(parsed.filters);
  for (const key of params.keys()) {
    if (!canonical.has(key)) return fallback;
  }
  if (selected) canonical.set('track', selected.toLowerCase());
  const query = canonical.toString();
  return query ? `/search?${query}` : '/search';
}
