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
}
