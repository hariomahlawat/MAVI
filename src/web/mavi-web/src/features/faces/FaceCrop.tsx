import { useEffect, useState } from 'react';
import type { FaceBox } from '../../api/faces';
import EvidencePlaceholder from '../../shared/evidence/EvidencePlaceholder';

/**
 * One face, shown by framing the existing evidence crop (ADR-022 §4: no face
 * image is ever stored or made). The browser loads the crop the Track already
 * has and positions it so the face box, with a quarter of its size around it,
 * fills the frame. Until the crop has loaded the frame is matte only; a crop
 * that cannot be loaded reads as the one missing-evidence vocabulary.
 */
export default function FaceCrop({
  src,
  box,
  size = 72,
  label,
}: {
  src: string | null;
  box: FaceBox | null;
  size?: number;
  label: string;
}) {
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setNatural(null);
    setFailed(false);
  }, [src]);

  const frame = { width: size, height: size, position: 'relative' as const, overflow: 'hidden' as const, display: 'inline-block' };
  if (!src || !box || failed) {
    return (
      <span className="thumb-frame" style={frame} role="img" aria-label={label}>
        <EvidencePlaceholder dense />
      </span>
    );
  }

  const side = Math.max(box.width, box.height) * 1.5;
  const scale = size / side;
  const left = -(box.x + box.width / 2 - side / 2) * scale;
  const top = -(box.y + box.height / 2 - side / 2) * scale;
  return (
    <span className="thumb-frame face-crop" style={frame} role="img" aria-label={label}>
      <img
        src={src}
        alt=""
        loading="lazy"
        onLoad={(event) => setNatural({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
        onError={() => setFailed(true)}
        style={{
          position: 'absolute',
          left,
          top,
          width: natural ? natural.width * scale : undefined,
          height: natural ? natural.height * scale : undefined,
          maxWidth: 'none',
          visibility: natural ? 'visible' : 'hidden',
        }}
      />
    </span>
  );
}

/** A worker-made aligned thumbnail (a gallery template or a query face), with the same missing-image fallback. */
export function FaceThumbnail({ src, size = 72, label }: { src: string | null; size?: number; label: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [src]);
  const frame = { width: size, height: size, display: 'inline-block' };
  return (
    <span className="thumb-frame" style={frame} role="img" aria-label={label}>
      {src && !failed ? (
        <img className="thumb" src={src} alt="" width={size} height={size} onError={() => setFailed(true)} />
      ) : (
        <EvidencePlaceholder dense />
      )}
    </span>
  );
}
