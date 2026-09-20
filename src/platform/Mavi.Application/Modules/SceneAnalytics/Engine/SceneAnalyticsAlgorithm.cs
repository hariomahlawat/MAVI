using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.SceneAnalytics.Engine;

/// <summary>
/// The thresholds that decide every derived fact, gathered in one place so that
/// nothing in the engine carries a magic number.
/// </summary>
/// <remarks>
/// <para>
/// These are the values frozen by section K to M of the Spatial and Temporal Track
/// Analytics plan. Changing any of them changes results, so a change must raise
/// <see cref="SceneAnalyticsAlgorithm.Version"/>; <see cref="ParametersSha256"/>
/// records the set actually used alongside each analysis.
/// </para>
/// <para>All distances are normalised frame units and all durations are milliseconds.</para>
/// </remarks>
public sealed record SceneAnalyticsParameters
{
    /// <summary>Jitter tolerance: the half-width of the on-line band and the zone-exit margin.</summary>
    public double Epsilon { get; init; } = 0.005;

    /// <summary>Samples a side change must be sustained for before it is believed.</summary>
    public int ConfirmationSamples { get; init; } = 3;

    /// <summary>Two crossings of one line in one direction closer than this are one crossing.</summary>
    public long RepeatSuppressionMs { get; init; } = 1_000;

    /// <summary>The longest sample gap the engine will reason across.</summary>
    public long MaximumGapMs { get; init; } = 2_000;

    /// <summary>Width, in samples, of the centred median filter applied before stationarity.</summary>
    public int SmoothingWindowSamples { get; init; } = 5;

    /// <summary>Trailing window over which stationarity is judged.</summary>
    public long StationaryWindowMs { get; init; } = 3_000;

    /// <summary>Largest movement a person may make inside the window and still count as still.</summary>
    public double PersonStationaryDisplacement { get; init; } = 0.015;

    /// <summary>Shortest run that counts as a person standing still.</summary>
    public long PersonStationaryMinimumMs { get; init; } = 5_000;

    /// <summary>Largest movement a vehicle may make inside the window and still count as stopped.</summary>
    public double VehicleStationaryDisplacement { get; init; } = 0.010;

    /// <summary>Shortest run that counts as a stopped vehicle.</summary>
    public long VehicleStationaryMinimumMs { get; init; } = 10_000;

    /// <summary>Dwell that counts as loitering when a zone sets no threshold of its own.</summary>
    public int LoiteringDefaultSeconds { get; init; } = 120;

    /// <summary>Below this total displacement a Track has no meaningful heading.</summary>
    public double HeadingMinimumDisplacement { get; init; } = 0.02;

    public static SceneAnalyticsParameters Default { get; } = new();

    /// <summary>The stationarity thresholds that apply to an object class.</summary>
    public (double Displacement, long MinimumMs) StationaryThresholdsFor(ObjectClass objectClass) =>
        objectClass switch
        {
            ObjectClass.Vehicle => (VehicleStationaryDisplacement, VehicleStationaryMinimumMs),
            _ => (PersonStationaryDisplacement, PersonStationaryMinimumMs),
        };

    /// <summary>
    /// The canonical JSON of this parameter set: members in a fixed order, numbers
    /// in the invariant culture, no whitespace.
    /// </summary>
    /// <remarks>
    /// Written by hand rather than serialised so that the bytes hashed below cannot
    /// change because a serializer's defaults changed.
    /// </remarks>
    public string ToCanonicalJson()
    {
        var builder = new StringBuilder(512);
        builder.Append('{');
        AppendString(builder, "algorithmVersion", SceneAnalyticsAlgorithm.Version);
        builder.Append(',');
        AppendNumber(builder, "confirmationSamples", ConfirmationSamples);
        builder.Append(',');
        AppendNumber(builder, "epsilon", Epsilon);
        builder.Append(',');
        AppendNumber(builder, "headingMinimumDisplacement", HeadingMinimumDisplacement);
        builder.Append(',');
        AppendNumber(builder, "loiteringDefaultSeconds", LoiteringDefaultSeconds);
        builder.Append(',');
        AppendNumber(builder, "maximumGapMs", MaximumGapMs);
        builder.Append(',');
        AppendNumber(builder, "personStationaryDisplacement", PersonStationaryDisplacement);
        builder.Append(',');
        AppendNumber(builder, "personStationaryMinimumMs", PersonStationaryMinimumMs);
        builder.Append(',');
        AppendString(builder, "referencePoint", AnalysisReferencePoint.BoundingBoxCentre);
        builder.Append(',');
        AppendNumber(builder, "repeatSuppressionMs", RepeatSuppressionMs);
        builder.Append(',');
        AppendNumber(builder, "smoothingWindowSamples", SmoothingWindowSamples);
        builder.Append(',');
        AppendNumber(builder, "stationaryWindowMs", StationaryWindowMs);
        builder.Append(',');
        AppendNumber(builder, "vehicleStationaryDisplacement", VehicleStationaryDisplacement);
        builder.Append(',');
        AppendNumber(builder, "vehicleStationaryMinimumMs", VehicleStationaryMinimumMs);
        builder.Append('}');
        return builder.ToString();
    }

    /// <summary>Lowercase hexadecimal SHA-256 of <see cref="ToCanonicalJson"/>.</summary>
    public string ParametersSha256()
    {
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(ToCanonicalJson()));
        return Convert.ToHexStringLower(hash);
    }

    private static void AppendString(StringBuilder builder, string name, string value) =>
        builder.Append('"').Append(name).Append("\":\"").Append(value).Append('"');

    private static void AppendNumber(StringBuilder builder, string name, double value) =>
        builder.Append('"').Append(name).Append("\":")
            .Append(value.ToString("R", CultureInfo.InvariantCulture));

    private static void AppendNumber(StringBuilder builder, string name, long value) =>
        builder.Append('"').Append(name).Append("\":")
            .Append(value.ToString(CultureInfo.InvariantCulture));
}

/// <summary>The engine's identity, recorded on every analysis it produces.</summary>
public static class SceneAnalyticsAlgorithm
{
    /// <summary>
    /// The analytics engine's version. A change to any frozen rule or default
    /// parameter raises the major number, which makes existing facts stale for
    /// readiness without deleting them. The Git commit is never used for this.
    /// </summary>
    public const string Version = "scene-analytics-v1";
}
