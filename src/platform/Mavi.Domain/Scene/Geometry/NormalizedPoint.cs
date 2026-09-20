using Mavi.Domain.Common;

namespace Mavi.Domain.Scene.Geometry;

/// <summary>
/// A point in the normalised source-frame coordinate system: origin top-left,
/// x to the right, y downwards, both in [0, 1].
/// </summary>
/// <remarks>
/// Values are rounded to <see cref="Decimals"/> decimal places on construction so
/// that the same geometry compares, hashes and persists identically on every host.
/// Equality below <see cref="Epsilon"/> after that rounding is exact equality.
/// </remarks>
public readonly record struct NormalizedPoint
{
    /// <summary>Fixed persisted precision of a coordinate component.</summary>
    public const int Decimals = 6;

    /// <summary>Equality tolerance applied after rounding to <see cref="Decimals"/>.</summary>
    public const double Epsilon = 1e-9;

    private NormalizedPoint(double x, double y)
    {
        X = x;
        Y = y;
    }

    public double X { get; }

    public double Y { get; }

    /// <summary>Rounds a raw coordinate component to the persisted precision.</summary>
    /// <remarks>
    /// <see cref="MidpointRounding.ToEven"/> is stated explicitly rather than left to
    /// the default so the result cannot drift with a future platform default.
    /// </remarks>
    public static double Round(double value) => Math.Round(value, Decimals, MidpointRounding.ToEven);

    /// <summary>True when a raw component is finite and inside the unit interval once rounded.</summary>
    public static bool IsInRange(double value) => double.IsFinite(value) && Round(value) is >= 0 and <= 1;

    /// <summary>Rounds and range-checks a pair of raw components.</summary>
    /// <exception cref="DomainValidationException">
    /// Thrown with <paramref name="errorCode"/> when either component is not finite or
    /// falls outside the unit interval after rounding.
    /// </exception>
    public static NormalizedPoint Create(double x, double y, string errorCode)
    {
        if (!IsInRange(x) || !IsInRange(y))
        {
            throw new DomainValidationException(
                errorCode,
                "Normalised coordinates must be finite and within [0, 1].");
        }

        return new NormalizedPoint(Round(x), Round(y));
    }

    /// <summary>
    /// Rounds a pair of components that the caller has already established to be
    /// in range, for engine-internal points such as an interpolated crossing.
    /// </summary>
    public static NormalizedPoint FromRounded(double x, double y) => new(Round(x), Round(y));

    /// <summary>Squared distance, for comparisons that never need the square root.</summary>
    public double SquaredDistanceTo(NormalizedPoint other)
    {
        var dx = X - other.X;
        var dy = Y - other.Y;
        return (dx * dx) + (dy * dy);
    }

    public double DistanceTo(NormalizedPoint other) => Math.Sqrt(SquaredDistanceTo(other));

    /// <summary>Linear interpolation towards <paramref name="other"/> at <paramref name="t"/> in [0, 1].</summary>
    public NormalizedPoint Lerp(NormalizedPoint other, double t) =>
        FromRounded(X + ((other.X - X) * t), Y + ((other.Y - Y) * t));
}
