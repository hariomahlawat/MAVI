using System.Buffers.Binary;
using System.Text;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Application.Modules.SceneAnalytics.Engine;

/// <summary>
/// Reads the sealed trajectory artefact written by the vision worker:
/// <c>{"v": 1, "points": [[offsetMs, centreX, centreY], …]}</c> in MessagePack.
/// </summary>
/// <remarks>
/// This is a deliberately narrow reader rather than a general MessagePack decoder.
/// It accepts only the handful of type codes the format can contain and refuses
/// everything else, which keeps the parser small enough to reason about and removes
/// any need for a third-party package (plan section AA). Its validation mirrors the
/// worker's <c>deserialize_trajectory</c> and the browser's <c>parseTrajectory</c>,
/// so all three refuse the same payloads, and additionally enforces the normalised
/// coordinate range that the worker enforces when it builds its points.
/// </remarks>
public static class TrajectoryDecoder
{
    /// <summary>The only payload version this engine understands.</summary>
    public const int SupportedVersion = 1;

    /// <summary>Fewer samples than this cannot describe motion, so no facts are derived.</summary>
    public const int MinimumSamples = 2;

    private const byte Nil = 0xc0;
    private const byte False = 0xc2;
    private const byte True = 0xc3;
    private const byte Float32 = 0xca;
    private const byte Float64 = 0xcb;
    private const byte UInt8 = 0xcc;
    private const byte UInt16 = 0xcd;
    private const byte UInt32 = 0xce;
    private const byte UInt64 = 0xcf;
    private const byte Int8 = 0xd0;
    private const byte Int16 = 0xd1;
    private const byte Int32 = 0xd2;
    private const byte Int64 = 0xd3;
    private const byte Str8 = 0xd9;
    private const byte Str16 = 0xda;
    private const byte Str32 = 0xdb;
    private const byte Array16 = 0xdc;
    private const byte Array32 = 0xdd;
    private const byte Map16 = 0xde;
    private const byte Map32 = 0xdf;

    /// <summary>Smallest number of bytes any encoded point array can occupy.</summary>
    /// <remarks>
    /// One array header plus three single-byte values. Used to reject an absurd
    /// declared length before anything is allocated for it.
    /// </remarks>
    private const int MinimumEncodedPointBytes = 4;

    /// <summary>Decodes a whole artefact into ordered samples.</summary>
    /// <exception cref="TrajectoryFormatException">
    /// The payload is not a valid v1 trajectory, or carries fewer than
    /// <see cref="MinimumSamples"/> samples.
    /// </exception>
    public static IReadOnlyList<TrajectorySample> Decode(ReadOnlySpan<byte> payload)
    {
        var reader = new Reader(payload);
        var memberCount = reader.ReadMapHeader();
        if (memberCount != 2)
        {
            throw Invalid("A trajectory payload must be a map of exactly two members.");
        }

        var sawVersion = false;
        var sawPoints = false;
        List<TrajectorySample>? samples = null;

        for (var member = 0; member < memberCount; member++)
        {
            var key = reader.ReadString();
            switch (key)
            {
                case "v" when !sawVersion:
                    sawVersion = true;
                    if (reader.ReadInt64() != SupportedVersion)
                    {
                        throw Invalid("Unsupported trajectory version.");
                    }

                    break;
                case "points" when !sawPoints:
                    sawPoints = true;
                    samples = ReadPoints(ref reader);
                    break;
                default:
                    throw Invalid("A trajectory payload has unexpected or repeated members.");
            }
        }

        if (!sawVersion || !sawPoints || samples is null)
        {
            throw Invalid("A trajectory payload must carry both a version and its points.");
        }

        if (!reader.IsAtEnd)
        {
            throw Invalid("A trajectory payload carries trailing data.");
        }

        if (samples.Count < MinimumSamples)
        {
            throw new TrajectoryFormatException(
                TrajectoryFailureReasons.TooShort,
                $"A trajectory needs at least {MinimumSamples} samples.");
        }

        return samples;
    }

    private static List<TrajectorySample> ReadPoints(ref Reader reader)
    {
        var count = reader.ReadArrayHeader();

        // A declared length that could not fit in what is left of the buffer is a
        // malformed payload, not an allocation request.
        if ((long)count * MinimumEncodedPointBytes > reader.Remaining)
        {
            throw Invalid("A trajectory declares more points than its payload can hold.");
        }

        var samples = new List<TrajectorySample>(count);
        var previousOffset = long.MinValue;
        for (var index = 0; index < count; index++)
        {
            if (reader.ReadArrayHeader() != 3)
            {
                throw Invalid("A trajectory point must carry exactly three values.");
            }

            var offsetMs = reader.ReadInt64();
            var x = reader.ReadDouble();
            var y = reader.ReadDouble();

            if (offsetMs < 0)
            {
                throw Invalid("A trajectory offset must not be negative.");
            }

            if (offsetMs <= previousOffset)
            {
                throw Invalid("Trajectory offsets must strictly increase.");
            }

            if (!NormalizedPoint.IsInRange(x) || !NormalizedPoint.IsInRange(y))
            {
                throw Invalid("A trajectory centre must be finite and within [0, 1].");
            }

            previousOffset = offsetMs;
            samples.Add(new TrajectorySample(offsetMs, NormalizedPoint.FromRounded(x, y)));
        }

        return samples;
    }

    private static TrajectoryFormatException Invalid(string message) =>
        new(TrajectoryFailureReasons.Invalid, message);

    /// <summary>A forward-only reader over the encoded payload.</summary>
    private ref struct Reader(ReadOnlySpan<byte> payload)
    {
        private readonly ReadOnlySpan<byte> _payload = payload;
        private int _position;

        public readonly bool IsAtEnd => _position >= _payload.Length;

        public readonly int Remaining => _payload.Length - _position;

        public int ReadMapHeader()
        {
            var code = ReadByte();
            if (code is >= 0x80 and <= 0x8f)
            {
                return code & 0x0f;
            }

            return code switch
            {
                Map16 => ReadUInt16(),
                Map32 => ReadLength32(),
                _ => throw Invalid("Expected a MessagePack map."),
            };
        }

        public int ReadArrayHeader()
        {
            var code = ReadByte();
            if (code is >= 0x90 and <= 0x9f)
            {
                return code & 0x0f;
            }

            return code switch
            {
                Array16 => ReadUInt16(),
                Array32 => ReadLength32(),
                _ => throw Invalid("Expected a MessagePack array."),
            };
        }

        public string ReadString()
        {
            var code = ReadByte();
            int length;
            if (code is >= 0xa0 and <= 0xbf)
            {
                length = code & 0x1f;
            }
            else
            {
                length = code switch
                {
                    Str8 => ReadByte(),
                    Str16 => ReadUInt16(),
                    Str32 => ReadLength32(),
                    _ => throw Invalid("Expected a MessagePack string."),
                };
            }

            var bytes = Take(length);
            try
            {
                return new UTF8Encoding(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true)
                    .GetString(bytes);
            }
            catch (DecoderFallbackException)
            {
                throw Invalid("A trajectory member name is not valid UTF-8.");
            }
        }

        /// <summary>Reads an integer; a boolean or a float is refused rather than coerced.</summary>
        public long ReadInt64()
        {
            var code = ReadByte();
            if (code <= 0x7f)
            {
                return code;
            }

            if (code >= 0xe0)
            {
                return unchecked((sbyte)code);
            }

            switch (code)
            {
                case UInt8:
                    return ReadByte();
                case UInt16:
                    return ReadUInt16();
                case UInt32:
                    return BinaryPrimitives.ReadUInt32BigEndian(Take(4));
                case UInt64:
                    var unsigned = BinaryPrimitives.ReadUInt64BigEndian(Take(8));
                    if (unsigned > long.MaxValue)
                    {
                        throw Invalid("A trajectory integer is out of range.");
                    }

                    return (long)unsigned;
                case Int8:
                    return unchecked((sbyte)ReadByte());
                case Int16:
                    return BinaryPrimitives.ReadInt16BigEndian(Take(2));
                case Int32:
                    return BinaryPrimitives.ReadInt32BigEndian(Take(4));
                case Int64:
                    return BinaryPrimitives.ReadInt64BigEndian(Take(8));
                default:
                    throw Invalid("Expected a MessagePack integer.");
            }
        }

        /// <summary>Reads a number; integers are accepted, booleans and nil are not.</summary>
        public double ReadDouble()
        {
            var code = Peek();
            switch (code)
            {
                case Float32:
                    _position++;
                    return BinaryPrimitives.ReadSingleBigEndian(Take(4));
                case Float64:
                    _position++;
                    return BinaryPrimitives.ReadDoubleBigEndian(Take(8));
                case Nil:
                case True:
                case False:
                    throw Invalid("Expected a MessagePack number.");
                default:
                    return ReadInt64();
            }
        }

        private byte Peek() => _position < _payload.Length
            ? _payload[_position]
            : throw Invalid("A trajectory payload ended unexpectedly.");

        private byte ReadByte()
        {
            var value = Peek();
            _position++;
            return value;
        }

        private int ReadUInt16() => BinaryPrimitives.ReadUInt16BigEndian(Take(2));

        private int ReadLength32()
        {
            var value = BinaryPrimitives.ReadUInt32BigEndian(Take(4));
            if (value > int.MaxValue)
            {
                throw Invalid("A trajectory payload declares an unsupported length.");
            }

            return (int)value;
        }

        private ReadOnlySpan<byte> Take(int length)
        {
            if (length < 0 || Remaining < length)
            {
                throw Invalid("A trajectory payload ended unexpectedly.");
            }

            var slice = _payload.Slice(_position, length);
            _position += length;
            return slice;
        }
    }
}
