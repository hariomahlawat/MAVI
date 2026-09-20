using System.Buffers.Binary;
using System.Text;

namespace Mavi.Application.Tests.SceneAnalytics;

/// <summary>
/// A minimal MessagePack writer used only by tests, so that a malformed payload can
/// be built deliberately rather than by editing bytes by hand.
/// </summary>
internal sealed class MsgPackWriter
{
    private readonly List<byte> _bytes = [];

    public byte[] ToArray() => [.. _bytes];

    public MsgPackWriter Raw(params byte[] values)
    {
        _bytes.AddRange(values);
        return this;
    }

    public MsgPackWriter MapHeader(int count) => Raw((byte)(0x80 | count));

    public MsgPackWriter ArrayHeader(int count) => count <= 15
        ? Raw((byte)(0x90 | count))
        : Raw(0xdc, (byte)(count >> 8), (byte)(count & 0xff));

    public MsgPackWriter String(string value)
    {
        var utf8 = Encoding.UTF8.GetBytes(value);
        Raw((byte)(0xa0 | utf8.Length));
        _bytes.AddRange(utf8);
        return this;
    }

    public MsgPackWriter Integer(long value)
    {
        if (value is >= 0 and <= 0x7f)
        {
            return Raw((byte)value);
        }

        Span<byte> buffer = stackalloc byte[8];
        BinaryPrimitives.WriteInt64BigEndian(buffer, value);
        Raw(0xd3);
        _bytes.AddRange(buffer.ToArray());
        return this;
    }

    public MsgPackWriter Double(double value)
    {
        Span<byte> buffer = stackalloc byte[8];
        BinaryPrimitives.WriteDoubleBigEndian(buffer, value);
        Raw(0xcb);
        _bytes.AddRange(buffer.ToArray());
        return this;
    }

    public MsgPackWriter Boolean(bool value) => Raw(value ? (byte)0xc3 : (byte)0xc2);

    public MsgPackWriter Nil() => Raw(0xc0);

    /// <summary>A well-formed v1 payload built from the supplied samples.</summary>
    public static byte[] Trajectory(params (long OffsetMs, double X, double Y)[] points)
    {
        var writer = new MsgPackWriter().MapHeader(2).String("v").Integer(1).String("points");
        writer.ArrayHeader(points.Length);
        foreach (var (offsetMs, x, y) in points)
        {
            writer.ArrayHeader(3).Integer(offsetMs).Double(x).Double(y);
        }

        return writer.ToArray();
    }
}
