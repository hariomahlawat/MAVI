using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;

namespace Mavi.IntegrationTests;

/// <summary>
/// Encodes the v1 trajectory artefact the vision worker seals:
/// <c>{"v": 1, "points": [[offsetMs, centreX, centreY], …]}</c> in MessagePack.
/// </summary>
/// <remarks>
/// Written out by hand so the analytics tests feed the decoder real bytes rather than a
/// stub. A test that hands the engine a pre-decoded list proves nothing about whether the
/// platform can read what the worker actually writes.
/// </remarks>
internal static class TrajectoryPayload
{
    public static byte[] Encode(IEnumerable<(long OffsetMs, double X, double Y)> points)
    {
        var buffer = new List<byte>(256);
        buffer.Add(0x82);                       // fixmap, 2 members
        WriteString(buffer, "v");
        buffer.Add(0x01);                       // positive fixint 1
        WriteString(buffer, "points");

        var samples = points.ToArray();
        WriteArrayHeader(buffer, samples.Length);
        foreach (var (offsetMs, x, y) in samples)
        {
            buffer.Add(0x93);                   // fixarray, 3 values
            WriteInt64(buffer, offsetMs);
            WriteDouble(buffer, x);
            WriteDouble(buffer, y);
        }

        return [.. buffer];
    }

    /// <summary>
    /// A straight descent through the middle of the frame, which crosses the fixture trip
    /// line exactly once.
    /// </summary>
    /// <remarks>
    /// The line runs horizontally at y = 0.5, so the path must travel in y. A path along
    /// y = 0.5 would be collinear with it and produce no crossing at all — which is the
    /// engine behaving correctly, and a fixture that would silently assert nothing.
    /// </remarks>
    public static byte[] StraightCrossing(int samples = 40, long stepMs = 200) =>
        Encode(Enumerable.Range(0, samples)
            .Select(index => ((long)index * stepMs, 0.5, Math.Round(0.1 + (0.8 * index / (samples - 1)), 6))));

    /// <summary>Enters the fixture zone, stays put inside it, then leaves.</summary>
    public static byte[] DwellThenLeave(int samples = 60, long stepMs = 500)
    {
        var points = new List<(long, double, double)>(samples);
        for (var index = 0; index < samples; index++)
        {
            var offset = (long)index * stepMs;
            // The fixture zone is the square from (0.1, 0.1) to (0.4, 0.4).
            var (x, y) = index switch
            {
                < 6 => (0.05 + (0.01 * index), 0.25),          // approaching
                < 48 => (0.25, 0.25),                           // stationary inside
                _ => (0.25 + (0.03 * (index - 47)), 0.25),      // leaving
            };
            points.Add((offset, Math.Round(Math.Min(x, 0.99), 6), y));
        }

        return Encode(points);
    }

    public static string Sha256Hex(byte[] payload) => Convert.ToHexStringLower(SHA256.HashData(payload));

    private static void WriteString(List<byte> buffer, string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value);
        buffer.Add((byte)(0xa0 | bytes.Length));   // fixstr
        buffer.AddRange(bytes);
    }

    private static void WriteArrayHeader(List<byte> buffer, int count)
    {
        if (count <= 15)
        {
            buffer.Add((byte)(0x90 | count));
            return;
        }

        buffer.Add(0xdc);                          // array16
        Span<byte> header = stackalloc byte[2];
        BinaryPrimitives.WriteUInt16BigEndian(header, (ushort)count);
        buffer.AddRange(header);
    }

    private static void WriteInt64(List<byte> buffer, long value)
    {
        buffer.Add(0xd3);                          // int64
        Span<byte> bytes = stackalloc byte[8];
        BinaryPrimitives.WriteInt64BigEndian(bytes, value);
        buffer.AddRange(bytes);
    }

    private static void WriteDouble(List<byte> buffer, double value)
    {
        buffer.Add(0xcb);                          // float64
        Span<byte> bytes = stackalloc byte[8];
        BinaryPrimitives.WriteDoubleBigEndian(bytes, value);
        buffer.AddRange(bytes);
    }
}
