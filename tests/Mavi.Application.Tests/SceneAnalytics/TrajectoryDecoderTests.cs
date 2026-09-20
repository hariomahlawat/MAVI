using Mavi.Application.Modules.SceneAnalytics.Engine;

namespace Mavi.Application.Tests.SceneAnalytics;

public sealed class TrajectoryDecoderTests
{
    // Valid payloads
    [Fact]
    public void ValidPayloadDecodesEverySample()
    {
        var payload = MsgPackWriter.Trajectory((0, 0.1, 0.2), (40, 0.3, 0.4), (80, 0.5, 0.6));

        var samples = TrajectoryDecoder.Decode(payload);

        Assert.Equal(3, samples.Count);
        Assert.Equal(40, samples[1].OffsetMs);
        Assert.Equal(0.3, samples[1].Position.X, 9);
        Assert.Equal(0.6, samples[2].Position.Y, 9);
    }

    [Fact]
    public void PayloadFromTheWorkerDecodesToTheSamePoints()
    {
        // Produced by the worker's own serialize_trajectory, so this pins the decoder
        // against the real producer rather than against the test writer below.
        var payload = File.ReadAllBytes(FixturePath("worker-trajectory-v1.msgpack"));
        using var expected = System.Text.Json.JsonDocument.Parse(
            File.ReadAllText(FixturePath("worker-trajectory-v1.json")));

        var samples = TrajectoryDecoder.Decode(payload);
        var points = expected.RootElement.GetProperty("points");

        Assert.Equal(points.GetArrayLength(), samples.Count);
        for (var index = 0; index < samples.Count; index++)
        {
            Assert.Equal(points[index][0].GetInt64(), samples[index].OffsetMs);
            Assert.Equal(points[index][1].GetDouble(), samples[index].Position.X, 9);
            Assert.Equal(points[index][2].GetDouble(), samples[index].Position.Y, 9);
        }
    }

    [Fact]
    public void IntegerCoordinatesAreAccepted()
    {
        var payload = new MsgPackWriter()
            .MapHeader(2).String("v").Integer(1).String("points")
            .ArrayHeader(2)
            .ArrayHeader(3).Integer(0).Integer(0).Integer(1)
            .ArrayHeader(3).Integer(40).Integer(1).Integer(0)
            .ToArray();

        var samples = TrajectoryDecoder.Decode(payload);

        Assert.Equal(0, samples[0].Position.X);
        Assert.Equal(1, samples[0].Position.Y);
    }

    [Fact]
    public void LongTrajectoryDecodesWithoutLoss()
    {
        var points = Enumerable.Range(0, 2_000)
            .Select(index => ((long)(index * 40), 0.5, index / 4_000d))
            .ToArray();

        var samples = TrajectoryDecoder.Decode(MsgPackWriter.Trajectory(points));

        Assert.Equal(2_000, samples.Count);
        Assert.Equal(79_960, samples[^1].OffsetMs);
    }

    // Structural rejection
    [Fact]
    public void EmptyPayloadIsInvalid() => AssertReason(TrajectoryFailureReasons.Invalid, []);

    [Fact]
    public void PayloadThatIsNotAMapIsInvalid() =>
        AssertReason(TrajectoryFailureReasons.Invalid, new MsgPackWriter().ArrayHeader(2).ToArray());

    [Fact]
    public void UnsupportedVersionIsInvalid()
    {
        var payload = new MsgPackWriter()
            .MapHeader(2).String("v").Integer(2).String("points").ArrayHeader(0).ToArray();

        AssertReason(TrajectoryFailureReasons.Invalid, payload);
    }

    [Fact]
    public void MissingPointsMemberIsInvalid()
    {
        var payload = new MsgPackWriter().MapHeader(1).String("v").Integer(1).ToArray();

        AssertReason(TrajectoryFailureReasons.Invalid, payload);
    }

    [Fact]
    public void UnexpectedMemberIsInvalid()
    {
        var payload = new MsgPackWriter()
            .MapHeader(2).String("v").Integer(1).String("extra").Integer(0).ToArray();

        AssertReason(TrajectoryFailureReasons.Invalid, payload);
    }

    [Fact]
    public void RepeatedMemberIsInvalid()
    {
        var payload = new MsgPackWriter()
            .MapHeader(2).String("v").Integer(1).String("v").Integer(1).ToArray();

        AssertReason(TrajectoryFailureReasons.Invalid, payload);
    }

    [Fact]
    public void TrailingDataIsInvalid()
    {
        var payload = MsgPackWriter.Trajectory((0, 0.1, 0.2), (40, 0.3, 0.4)).Concat<byte>([0xc0]).ToArray();

        AssertReason(TrajectoryFailureReasons.Invalid, payload);
    }

    [Fact]
    public void TruncatedPayloadIsInvalid()
    {
        var payload = MsgPackWriter.Trajectory((0, 0.1, 0.2), (40, 0.3, 0.4));

        AssertReason(TrajectoryFailureReasons.Invalid, payload[..^3]);
    }

    [Fact]
    public void DeclaredLengthBeyondThePayloadIsInvalid()
    {
        // An array header claiming a thousand points in a buffer that holds none.
        var payload = new MsgPackWriter()
            .MapHeader(2).String("v").Integer(1).String("points").ArrayHeader(1_000).ToArray();

        AssertReason(TrajectoryFailureReasons.Invalid, payload);
    }

    // Point rejection
    [Fact]
    public void PointWithTheWrongArityIsInvalid()
    {
        var payload = new MsgPackWriter()
            .MapHeader(2).String("v").Integer(1).String("points")
            .ArrayHeader(1).ArrayHeader(2).Integer(0).Double(0.1)
            .ToArray();

        AssertReason(TrajectoryFailureReasons.Invalid, payload);
    }

    [Fact]
    public void DecreasingOffsetIsInvalid() =>
        AssertReason(
            TrajectoryFailureReasons.Invalid,
            MsgPackWriter.Trajectory((0, 0.1, 0.2), (80, 0.3, 0.4), (40, 0.5, 0.6)));

    [Fact]
    public void RepeatedOffsetIsInvalid() =>
        AssertReason(
            TrajectoryFailureReasons.Invalid,
            MsgPackWriter.Trajectory((0, 0.1, 0.2), (40, 0.3, 0.4), (40, 0.5, 0.6)));

    [Fact]
    public void NegativeOffsetIsInvalid() =>
        AssertReason(TrajectoryFailureReasons.Invalid, MsgPackWriter.Trajectory((-1, 0.1, 0.2), (40, 0.3, 0.4)));

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    public void NonFiniteCoordinateIsInvalid(double value) =>
        AssertReason(TrajectoryFailureReasons.Invalid, MsgPackWriter.Trajectory((0, value, 0.2), (40, 0.3, 0.4)));

    [Theory]
    [InlineData(-0.01)]
    [InlineData(1.01)]
    public void CoordinateOutsideTheFrameIsInvalid(double value) =>
        AssertReason(TrajectoryFailureReasons.Invalid, MsgPackWriter.Trajectory((0, value, 0.2), (40, 0.3, 0.4)));

    [Fact]
    public void BooleanWhereACoordinateBelongsIsInvalid()
    {
        var payload = new MsgPackWriter()
            .MapHeader(2).String("v").Integer(1).String("points")
            .ArrayHeader(1).ArrayHeader(3).Integer(0).Boolean(true).Double(0.2)
            .ToArray();

        AssertReason(TrajectoryFailureReasons.Invalid, payload);
    }

    [Fact]
    public void NilWhereACoordinateBelongsIsInvalid()
    {
        var payload = new MsgPackWriter()
            .MapHeader(2).String("v").Integer(1).String("points")
            .ArrayHeader(1).ArrayHeader(3).Integer(0).Nil().Double(0.2)
            .ToArray();

        AssertReason(TrajectoryFailureReasons.Invalid, payload);
    }

    [Fact]
    public void BooleanWhereAnOffsetBelongsIsInvalid()
    {
        var payload = new MsgPackWriter()
            .MapHeader(2).String("v").Integer(1).String("points")
            .ArrayHeader(1).ArrayHeader(3).Boolean(false).Double(0.1).Double(0.2)
            .ToArray();

        AssertReason(TrajectoryFailureReasons.Invalid, payload);
    }

    // Too short
    [Fact]
    public void EmptyTrajectoryIsTooShort() =>
        AssertReason(TrajectoryFailureReasons.TooShort, MsgPackWriter.Trajectory());

    [Fact]
    public void SingleSampleIsTooShort() =>
        AssertReason(TrajectoryFailureReasons.TooShort, MsgPackWriter.Trajectory((0, 0.1, 0.2)));

    // Helpers
    private static void AssertReason(string reason, byte[] payload)
    {
        var exception = Assert.Throws<TrajectoryFormatException>(() => TrajectoryDecoder.Decode(payload));
        Assert.Equal(reason, exception.Reason);
    }

    internal static string FixturePath(string name)
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "tests", "fixtures", "scene-analytics", name);
            if (File.Exists(candidate))
            {
                return candidate;
            }

            directory = directory.Parent;
        }

        throw new FileNotFoundException($"Could not locate the scene-analytics fixture '{name}'.");
    }
}
