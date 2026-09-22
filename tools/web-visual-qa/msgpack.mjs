/**
 * The subset of MessagePack the MAVI trajectory artefact uses.
 *
 * Written here rather than pulled from npm: the harness has no dependencies by
 * design, and the format actually in play is a map of two keys holding an array
 * of three-number arrays. Encoding it is a few dozen lines, and a dependency
 * added for test tooling would still have to be carried through the offline
 * packaging policy.
 *
 * Only the encodings `shared/msgpack/decode.ts` accepts are emitted, so a
 * fixture that this produces and the browser refuses is a real disagreement
 * rather than an artefact of the harness writing something exotic.
 */

/** @param {number} value */
function encodeNumber(value) {
  if (Number.isInteger(value) && value >= 0 && value <= 0x7f) return Buffer.from([value]);
  if (Number.isInteger(value) && value >= 0 && value <= 0xffffffff) {
    const out = Buffer.alloc(5);
    out.writeUInt8(0xce, 0);
    out.writeUInt32BE(value, 1);
    return out;
  }
  if (Number.isInteger(value) && value < 0 && value >= -0x80000000) {
    const out = Buffer.alloc(5);
    out.writeUInt8(0xd2, 0);
    out.writeInt32BE(value, 1);
    return out;
  }
  // Doubles for everything else: normalised coordinates are fractional, and
  // float32 would round them away from the value the fixture states.
  const out = Buffer.alloc(9);
  out.writeUInt8(0xcb, 0);
  out.writeDoubleBE(value, 1);
  return out;
}

/** @param {string} value */
function encodeString(value) {
  const bytes = Buffer.from(value, 'utf8');
  if (bytes.length > 31) throw new Error('fixture strings stay in the fixstr range');
  return Buffer.concat([Buffer.from([0xa0 | bytes.length]), bytes]);
}

/** @param {unknown[]} items */
function encodeArray(items) {
  const head = items.length <= 15
    ? Buffer.from([0x90 | items.length])
    : (() => { const b = Buffer.alloc(3); b.writeUInt8(0xdc, 0); b.writeUInt16BE(items.length, 1); return b; })();
  return Buffer.concat([head, ...items.map(encode)]);
}

/** @param {Record<string, unknown>} value */
function encodeMap(value) {
  const entries = Object.entries(value);
  if (entries.length > 15) throw new Error('fixture maps stay in the fixmap range');
  return Buffer.concat([
    Buffer.from([0x80 | entries.length]),
    ...entries.flatMap(([key, item]) => [encodeString(key), encode(item)]),
  ]);
}

/** @param {unknown} value */
export function encode(value) {
  if (value === null) return Buffer.from([0xc0]);
  if (typeof value === 'boolean') return Buffer.from([value ? 0xc3 : 0xc2]);
  if (typeof value === 'number') return encodeNumber(value);
  if (typeof value === 'string') return encodeString(value);
  if (Array.isArray(value)) return encodeArray(value);
  if (typeof value === 'object') return encodeMap(/** @type {Record<string, unknown>} */ (value));
  throw new Error(`cannot encode ${typeof value}`);
}

/**
 * A trajectory artefact as the worker's `serialize_trajectory` writes it:
 * `{v: 1, points: [[offsetMs, centreX, centreY], ...]}` with strictly
 * increasing integer offsets.
 *
 * @param {[number, number, number][]} points
 */
export function encodeTrajectory(points) {
  let previous = -1;
  for (const [offsetMs, x, y] of points) {
    if (!Number.isInteger(offsetMs) || offsetMs <= previous) {
      throw new Error(`trajectory offsets must be increasing integers, got ${offsetMs} after ${previous}`);
    }
    if (x < 0 || x > 1 || y < 0 || y > 1) {
      throw new Error(`trajectory coordinates are normalised, got (${x}, ${y})`);
    }
    previous = offsetMs;
  }
  return encode({ v: 1, points });
}
