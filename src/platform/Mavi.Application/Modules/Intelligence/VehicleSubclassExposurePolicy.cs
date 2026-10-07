using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// The one authority on which persisted vehicle subclasses an operator may see (Stage 3, X1).
/// </summary>
/// <remarks>
/// <para>
/// X1 (acceptance register, 2026-10-07) approved one global allowlist, <c>{car}</c>, for
/// Tracks resolved by the release pipeline profile <c>phase1-detection-tracking-v1</c>
/// (<c>1.3.0-candidate</c>, SHA-256 <c>afb03b6c…18bf</c>). A subclass is operator-facing
/// only when the persisted Track is a Vehicle, its subclass is on the allowlist and its
/// source is that profile's detector-native vote. Everything else — truck, bus,
/// motorcycle, a <c>car</c> resolved by any other profile (the Development-only A2
/// profile included), a Track with no subclass — is not exposed.
/// </para>
/// <para>
/// This is profile/source gating, not benchmark-domain gating: the allowlist is global.
/// Persistence is untouched; the stored facts keep every vocabulary value. Search
/// filtering, search results and Track detail all ask this policy, so they cannot
/// disagree.
/// </para>
/// </remarks>
public static class VehicleSubclassExposurePolicy
{
    /// <summary>The release pipeline profile X1 approved, as its detector-native subclass source.</summary>
    public const string ApprovedSource =
        VehicleSubclass.DetectorNativeSourcePrefix +
        "afb03b6c4da61fbf6021ef855307f80c5b7206996e7e21c8d297394b091a18bf";

    /// <summary>The operator-facing subclasses, in vocabulary order. X1: car only.</summary>
    public static IReadOnlyList<string> ExposedSubclasses { get; } = ["car"];

    /// <summary>Whether a requested subclass may be searched for. Exact, case-sensitive match.</summary>
    public static bool IsExposable(string? subclass)
    {
        if (subclass is null)
            return false;
        foreach (var exposed in ExposedSubclasses)
        {
            if (string.Equals(exposed, subclass, StringComparison.Ordinal))
                return true;
        }

        return false;
    }

    /// <summary>
    /// The subclass an operator may see on a persisted Track, or null. Fails closed: any
    /// value or source the policy does not name is hidden.
    /// </summary>
    public static string? Expose(ObjectClass objectClass, string? subclass, string? source) =>
        objectClass == ObjectClass.Vehicle &&
        IsExposable(subclass) &&
        string.Equals(source, ApprovedSource, StringComparison.Ordinal)
            ? subclass
            : null;
}
