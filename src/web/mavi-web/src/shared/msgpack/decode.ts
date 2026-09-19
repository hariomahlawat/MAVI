/**
 * A minimal MessagePack decoder for the artefacts MAVI itself produces.
 *
 * The trajectory artefact is a map of a small string key set to arrays of
 * numbers, written by the Python worker with `use_bin_type=True`. Decoding it
 * needs maps, arrays, strings, integers, floats, booleans and nil — nothing
 * else — so this covers exactly the standard formats for those, refuses ext
 * types and binary, and never trusts a length prefix it cannot satisfy. Adding
 * a third-party decoder would change the offline dependency kit for ~150 lines.
 */

export class MsgpackError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MsgpackError';
  }
}

export type MsgpackValue = null | boolean | number | string | MsgpackValue[] | { [key: string]: MsgpackValue };

const MAX_DEPTH = 32;
const MAX_ITEMS = 1_000_000;

class Reader {
  private offset = 0;
  private readonly view: DataView;
  private readonly bytes: Uint8Array;
  private readonly text = new TextDecoder('utf-8', { fatal: true });

  constructor(buffer: ArrayBuffer | Uint8Array) {
    this.bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
    this.view = new DataView(this.bytes.buffer, this.bytes.byteOffset, this.bytes.byteLength);
  }

  get remaining(): number { return this.bytes.length - this.offset; }

  private need(count: number): void {
    if (this.offset + count > this.bytes.length) throw new MsgpackError('Truncated MessagePack payload.');
  }

  private u8(): number { this.need(1); return this.bytes[this.offset++]; }
  private u16(): number { this.need(2); const v = this.view.getUint16(this.offset); this.offset += 2; return v; }
  private u32(): number { this.need(4); const v = this.view.getUint32(this.offset); this.offset += 4; return v; }
  private i8(): number { this.need(1); const v = this.view.getInt8(this.offset); this.offset += 1; return v; }
  private i16(): number { this.need(2); const v = this.view.getInt16(this.offset); this.offset += 2; return v; }
  private i32(): number { this.need(4); const v = this.view.getInt32(this.offset); this.offset += 4; return v; }
  private f32(): number { this.need(4); const v = this.view.getFloat32(this.offset); this.offset += 4; return v; }
  private f64(): number { this.need(8); const v = this.view.getFloat64(this.offset); this.offset += 8; return v; }

  private u64(): number {
    this.need(8);
    const value = this.view.getBigUint64(this.offset);
    this.offset += 8;
    if (value > BigInt(Number.MAX_SAFE_INTEGER)) throw new MsgpackError('Integer exceeds the safe range.');
    return Number(value);
  }

  private i64(): number {
    this.need(8);
    const value = this.view.getBigInt64(this.offset);
    this.offset += 8;
    if (value > BigInt(Number.MAX_SAFE_INTEGER) || value < BigInt(Number.MIN_SAFE_INTEGER)) {
      throw new MsgpackError('Integer exceeds the safe range.');
    }
    return Number(value);
  }

  private str(length: number): string {
    this.need(length);
    const slice = this.bytes.subarray(this.offset, this.offset + length);
    this.offset += length;
    try {
      return this.text.decode(slice);
    } catch {
      throw new MsgpackError('Invalid UTF-8 string.');
    }
  }

  private array(length: number, depth: number): MsgpackValue[] {
    if (length > MAX_ITEMS) throw new MsgpackError('Array too large.');
    const items: MsgpackValue[] = new Array(length);
    for (let i = 0; i < length; i += 1) items[i] = this.value(depth + 1);
    return items;
  }

  private map(length: number, depth: number): { [key: string]: MsgpackValue } {
    if (length > MAX_ITEMS) throw new MsgpackError('Map too large.');
    const result: { [key: string]: MsgpackValue } = {};
    for (let i = 0; i < length; i += 1) {
      const key = this.value(depth + 1);
      if (typeof key !== 'string') throw new MsgpackError('Map keys must be strings.');
      if (key === '__proto__') throw new MsgpackError('Forbidden map key.');
      result[key] = this.value(depth + 1);
    }
    return result;
  }

  value(depth = 0): MsgpackValue {
    if (depth > MAX_DEPTH) throw new MsgpackError('Nesting too deep.');
    const byte = this.u8();

    if (byte <= 0x7f) return byte;                       // positive fixint
    if (byte >= 0xe0) return byte - 0x100;               // negative fixint
    if (byte >= 0x80 && byte <= 0x8f) return this.map(byte & 0x0f, depth);
    if (byte >= 0x90 && byte <= 0x9f) return this.array(byte & 0x0f, depth);
    if (byte >= 0xa0 && byte <= 0xbf) return this.str(byte & 0x1f);

    switch (byte) {
      case 0xc0: return null;
      case 0xc2: return false;
      case 0xc3: return true;
      case 0xca: return this.f32();
      case 0xcb: return this.f64();
      case 0xcc: return this.u8();
      case 0xcd: return this.u16();
      case 0xce: return this.u32();
      case 0xcf: return this.u64();
      case 0xd0: return this.i8();
      case 0xd1: return this.i16();
      case 0xd2: return this.i32();
      case 0xd3: return this.i64();
      case 0xd9: return this.str(this.u8());
      case 0xda: return this.str(this.u16());
      case 0xdb: return this.str(this.u32());
      case 0xdc: return this.array(this.u16(), depth);
      case 0xdd: return this.array(this.u32(), depth);
      case 0xde: return this.map(this.u16(), depth);
      case 0xdf: return this.map(this.u32(), depth);
      default:
        // bin, ext and the never-used 0xc1 are outside what MAVI writes.
        throw new MsgpackError(`Unsupported MessagePack type 0x${byte.toString(16)}.`);
    }
  }
}

/** Decode exactly one value; trailing bytes are an error, as in the worker. */
export function decodeMsgpack(buffer: ArrayBuffer | Uint8Array): MsgpackValue {
  const reader = new Reader(buffer);
  const value = reader.value();
  if (reader.remaining !== 0) throw new MsgpackError('Trailing bytes after MessagePack value.');
  return value;
}
