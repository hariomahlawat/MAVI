import type { SVGProps } from 'react';

// A deliberately small, consistent line-icon set. All icons share one viewBox
// and stroke treatment so they read as a family at 14–20px.
const paths: Record<string, string> = {
  overview: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  camera: 'M3 8a2 2 0 0 1 2-2h2l2-3h6l2 3h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  video: 'M3 7a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM16 10l5-3v10l-5-3',
  upload: 'M12 16V4M6 10l6-6 6 6M4 20h16',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4.3-4.3',
  review: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  chevronLeft: 'M15 5l-7 7 7 7',
  chevronRight: 'M9 5l7 7-7 7',
  chevronDown: 'M5 9l7 7 7-7',
  chevronsLeft: 'M11 5l-7 7 7 7M18 5l-7 7 7 7',
  chevronsRight: 'M13 5l7 7-7 7M6 5l7 7-7 7',
  play: 'M7 4l12 8-12 8z',
  skipStart: 'M6 5v14M19 5l-11 7 11 7z',
  skipEnd: 'M18 5v14M5 5l11 7-11 7z',
  target: 'M12 3v3M12 18v3M3 12h3M18 12h3M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z',
  x: 'M6 6l12 12M18 6L6 18',
  check: 'M4 12l5 5L20 7',
  alert: 'M12 3l10 18H2zM12 9v5M12 17.5v.5',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v6M12 7.5v.5',
  external: 'M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5',
  refresh: 'M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5',
  filter: 'M3 5h18l-7 8v6l-4-2v-4z',
  list: 'M4 6h16M4 12h16M4 18h16',
  grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2',
  person: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0',
  vehicle: 'M3 13l2-5h14l2 5v5H3zM6 18v2M18 18v2M6 13h12',
  sidebar: 'M3 5h18v14H3zM9 5v14',
  layers: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5',
  box: 'M4 6h16v12H4z',
  path: 'M4 18c4 0 4-12 8-12s4 12 8 12',
};

export type IconName = keyof typeof paths;

type IconProps = SVGProps<SVGSVGElement> & {
  name: IconName;
  size?: 'sm' | 'md' | 'lg';
  /** Provide a label only when the icon stands alone; decorative icons stay hidden. */
  label?: string;
};

export default function Icon({ name, size = 'md', label, className = '', ...rest }: IconProps) {
  const d = paths[name];
  return (
    <svg
      viewBox="0 0 24 24"
      className={`icon icon--${size} ${className}`.trim()}
      aria-hidden={label ? undefined : true}
      role={label ? 'img' : undefined}
      aria-label={label}
      focusable="false"
      {...rest}
    >
      <path d={d} />
    </svg>
  );
}
