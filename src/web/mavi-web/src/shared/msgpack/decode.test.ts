import { describe, expect, it } from 'vitest';
import { decodeMsgpack, MsgpackError } from './decode';

// Tiny encoder covering only what the tests need, so fixtures stay readable.
function str(value: string): number[] {
  const bytes = Array.from(new TextEncoder().encode(value));
  return [0xa0 | bytes.length, ...bytes];
}
function f64(value: number): number[] {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value);
  return [0xcb, ...Array.from(new Uint8Array(view.buffer))];
}
function u16(value: number): number[] {
  return [0xcd, value >> 8, value & 0xff];
}
const bytes = (...parts: Array<number | number[]>) => new Uint8Array(parts.flat());

describe('decodeMsgpack', () => {
  it('decodes the trajectory shape the worker writes', () => {
    const payload = bytes(
      0x82, str('v'), 0x01,
      str('points'), 0x92,
      0x93, 0x00, f64(0.25), f64(0.5),
      0x93, u16(1_000), f64(0.75), f64(1),
    );
    expect(decodeMsgpack(payload)).toEqual({ v: 1, points: [[0, 0.25, 0.5], [1_000, 0.75, 1]] });
  });

  it('decodes nil, booleans, negative fixints and str8', () => {
    expect(decodeMsgpack(bytes(0x93, 0xc0, 0xc3, 0xff))).toEqual([null, true, -1]);
    expect(decodeMsgpack(bytes(0xd9, 0x02, 0x68, 0x69))).toBe('hi');
  });

  it('rejects binary and ext families the worker never emits', () => {
    expect(() => decodeMsgpack(bytes(0xc4, 0x01, 0x00))).toThrow(MsgpackError);
    expect(() => decodeMsgpack(bytes(0xd4, 0x01, 0x00))).toThrow(MsgpackError);
  });

  it('rejects truncated and trailing payloads', () => {
    expect(() => decodeMsgpack(bytes(0x92, 0x01))).toThrow(/Truncated/);
    expect(() => decodeMsgpack(bytes(0x01, 0x02))).toThrow(/Trailing/);
  });

  it('refuses non-string and prototype-polluting map keys', () => {
    expect(() => decodeMsgpack(bytes(0x81, 0x01, 0x01))).toThrow(/keys must be strings/);
    expect(() => decodeMsgpack(bytes(0x81, str('__proto__'), 0x01))).toThrow(/Forbidden/);
  });

  it('refuses 64-bit integers outside the safe range', () => {
    expect(() => decodeMsgpack(bytes(0xcf, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff))).toThrow(/safe range/);
  });
});
