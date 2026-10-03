namespace Mavi.Domain.Intelligence;

/// <summary>
/// The detector-native vehicle subclass vocabulary (Stage 3, ADR-016). A Track's
/// subclass is a fact of the processing run that produced it, recorded with the
/// vocabulary and the source that resolved it; a later source never rewrites it.
/// </summary>
public static class VehicleSubclass
{
    public const string VocabularyV1 = "mavi-vehicle-subclass-v1";

    public static IReadOnlyList<string> ValuesV1 { get; } = ["car", "truck", "bus", "motorcycle"];

    public const int MaximumSourceLength = 128;

    /// <summary>Prefix of the only source v1 knows; the rest is the pipeline profile SHA-256.</summary>
    public const string DetectorNativeSourcePrefix = "detector-native:";

    /// <summary>Whether a source names one pipeline profile's detector-native vote.</summary>
    public static bool IsDetectorNativeSource(string? source) =>
        source is not null &&
        source.Length == DetectorNativeSourcePrefix.Length + 64 &&
        source.StartsWith(DetectorNativeSourcePrefix, StringComparison.Ordinal) &&
        source[DetectorNativeSourcePrefix.Length..].All(character => char.IsAsciiDigit(character) || character is >= 'a' and <= 'f');
}
