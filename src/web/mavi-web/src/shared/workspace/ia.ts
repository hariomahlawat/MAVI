import type { IconName } from '../components/Icon';

/**
 * The one information-architecture map (§5, amended in v2.0).
 *
 * The audit found the shell describing one surface three ways — the rail said
 * *Search*, the Context Bar *Visual Search*; Import was a rail peer of Videos
 * but crumbed beneath it; Review highlighted nothing. Every one of those came
 * from a second table: a rail list, a section-title table, and a crumb trail
 * authored by each page. This module is the only table. The rail (label,
 * order, group, which item is active), the root crumb of every Context Bar, the
 * document title and the `g` destination keys are all derived from it, and
 * nothing else in the product spells them.
 *
 * It is deliberately small and closed: eleven surfaces, two sections. It is not
 * a routing framework — route paths stay in the router, which names each
 * route's surface through its `handle` — and a new surface is one row here by
 * amendment of §5, under its owning section.
 *
 * What stays dynamic is only the object a surface is about: a camera, a video.
 * A surface supplies that identity; it never re-authors the static vocabulary.
 */

/** A primary destination: one rail item, one root crumb, one `g` key. */
export type DestinationId = 'overview' | 'cameras' | 'videos' | 'import' | 'processing' | 'search';

/** Every surface the product renders, including the one that owns nothing. */
export type SurfaceId =
  | DestinationId
  | 'scene'
  | 'analytics'
  | 'processing-detail'
  | 'review'
  | 'not-found';

export type Destination = {
  id: DestinationId;
  /** The rail label, the root crumb and the root of the document title — one word, spelled once. */
  label: string;
  to: string;
  icon: IconName;
  /**
   * The letter that follows `g` (§22). Mnemonic, unique across destinations,
   * and kept with the destination it opens so the key handler, the shortcut
   * sheet and the rail cannot disagree about it.
   */
  key: string;
};

export type Section = { label: string; destinations: Destination[] };

/**
 * Grouped per §5 and ordered by operator workflow rather than alphabetically:
 * know what you have, bring media in, watch it process, then investigate what
 * came out. Investigate holds Search alone; Events, Entities and Cases join it
 * only when they are real routes.
 */
export const SECTIONS: readonly Section[] = [
  {
    label: 'Operate',
    destinations: [
      { id: 'overview', label: 'Overview', to: '/', icon: 'overview', key: 'o' },
      { id: 'cameras', label: 'Cameras', to: '/cameras', icon: 'camera', key: 'c' },
      { id: 'videos', label: 'Videos', to: '/videos', icon: 'video', key: 'v' },
      { id: 'import', label: 'Import', to: '/import', icon: 'upload', key: 'i' },
      { id: 'processing', label: 'Processing', to: '/processing', icon: 'activity', key: 'p' },
    ],
  },
  {
    label: 'Investigate',
    destinations: [
      { id: 'search', label: 'Search', to: '/search', icon: 'search', key: 's' },
    ],
  },
];

export const DESTINATIONS: readonly Destination[] = SECTIONS.flatMap((section) => section.destinations);

type SurfaceRow = {
  /** The destination whose rail item is highlighted; `null` only for Not found. */
  owner: DestinationId | null;
  /** The sub-surface word after the object (`Scene`, `Analytics`, `Review`). */
  child?: string;
};

/** The §5 table, one row per surface. */
export const SURFACES: Readonly<Record<SurfaceId, SurfaceRow>> = {
  overview: { owner: 'overview' },
  cameras: { owner: 'cameras' },
  scene: { owner: 'cameras', child: 'Scene' },
  analytics: { owner: 'cameras', child: 'Analytics' },
  videos: { owner: 'videos' },
  import: { owner: 'import' },
  processing: { owner: 'processing' },
  'processing-detail': { owner: 'processing' },
  search: { owner: 'search' },
  review: { owner: 'search', child: 'Review' },
  'not-found': { owner: null },
};

/** The one surface with no rail highlight and no owning section. */
export const NOT_FOUND_LABEL = 'Not found';

/** The product identity every document title ends with. */
export const PRODUCT_NAME = 'MAVI';

export function destination(id: DestinationId): Destination {
  const found = DESTINATIONS.find((entry) => entry.id === id);
  if (!found) throw new Error(`Unknown destination ${id}`);
  return found;
}

/** The rail item a surface highlights, or `null` for the surface that owns nothing. */
export function ownerOf(surface: SurfaceId): Destination | null {
  const owner = SURFACES[surface].owner;
  return owner ? destination(owner) : null;
}

export type Crumb = {
  label: string;
  /** A crumb links to an ancestor surface; the last crumb is where you are. */
  to?: string;
  /**
   * The object's own identity rather than a word from this map. It is the one
   * crumb that may give way when the bar is short of room: the static words
   * (`Cameras`, `Scene`) are short and are what orient the operator, while a
   * camera name or file name can be as long as the domain permits.
   */
  dynamic?: boolean;
};

/** The dynamic part of a surface's identity — the object it is about. */
export type SurfaceIdentity = {
  /**
   * The camera, video or other object this surface is about. While it is still
   * loading the surface passes what it knows (an identifier) or nothing; the
   * static vocabulary around it is the same either way.
   */
  object?: Crumb;
  /**
   * Where the root crumb returns to, when that is not the destination's own
   * path. Review uses it: opened from an Investigation, its `Search` crumb
   * returns to that Investigation with its URL state intact (§5).
   */
  rootTo?: string;
};

/**
 * `Section › Object › Sub-surface` (§5), derived. The root crumb is the rail
 * label, every crumb but the last links to its surface, and the last is where
 * the operator is.
 */
export function crumbsFor(surface: SurfaceId, identity: SurfaceIdentity = {}): Crumb[] {
  const owner = ownerOf(surface);
  if (!owner) return [{ label: NOT_FOUND_LABEL }];
  const row = SURFACES[surface];
  const trail: Crumb[] = [{ label: owner.label, to: identity.rootTo ?? owner.to }];
  if (identity.object) trail.push({ ...identity.object, dynamic: true });
  if (row.child) trail.push({ label: row.child });
  // The last crumb is where the operator is, so it never links.
  const last = trail.length - 1;
  return trail.map((crumb, index) => {
    if (index !== last) return crumb;
    return crumb.dynamic ? { label: crumb.label, dynamic: true } : { label: crumb.label };
  });
}

/**
 * The one document-title rule: the crumb trail read from where the operator is
 * outward, then the product — `Scene — CAM-01 · North Gate — Cameras — MAVI`.
 *
 * Most specific first, because a browser tab and a window list truncate from
 * the end; the full object identity is always present even when the Context
 * Bar has had to truncate it on screen (§37.1, long names).
 */
export function documentTitleFor(crumbs: readonly Crumb[]): string {
  return [...crumbs].reverse().map((crumb) => crumb.label).concat(PRODUCT_NAME).join(' — ');
}

/** The `g` destination for a key, if any (§22). */
export function destinationForKey(key: string): Destination | null {
  return DESTINATIONS.find((entry) => entry.key === key.toLowerCase()) ?? null;
}
