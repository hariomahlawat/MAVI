using System.Security.Cryptography;
using System.Text.Json;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Entities;

/// <summary>One catalogue parameter with the source it comes from (ADR-023 §3): <c>catalogue</c> or <c>owner-decision</c>.</summary>
public sealed record EntityCandidateParameter(string Name, string Value, string Source, string Rationale);

/// <summary>
/// A whole, immutable Entity-candidate catalogue version (ADR-023 §3). Changing any parameter is a new version; a
/// version once shipped is never edited. Its SHA-256 over the canonical JSON is recorded with every derivation.
/// </summary>
/// <param name="CrossCameraOnly">Pairs on one camera are never proposed (v2).</param>
/// <param name="RequireSharedSite">Both cameras must declare the same site; a camera with no site pairs with nothing (v2).</param>
public sealed record EntityCandidateCatalogueDefinition(
    string CatalogueVersion,
    double AppearanceFloor,
    long ConcurrencyToleranceMs,
    IReadOnlyList<EntityCandidateParameter> Parameters,
    bool CrossCameraOnly = false,
    bool RequireSharedSite = false)
{
    private static readonly JsonSerializerOptions CanonicalJson = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = false,
    };

    /// <summary>Computed from the values each time, so a copy made with <c>with</c> never carries a stale digest.</summary>
    public string Sha256 => Convert.ToHexStringLower(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(
        new
        {
            catalogueVersion = CatalogueVersion, appearanceFloor = AppearanceFloor, concurrencyToleranceMs = ConcurrencyToleranceMs,
            crossCameraOnly = CrossCameraOnly, requireSharedSite = RequireSharedSite, parameters = Parameters,
        },
        CanonicalJson)));
}

public static class EntityCandidateCatalogue
{
    public const string SourceCatalogue = "catalogue";
    public const string SourceOwnerDecision = "owner-decision";

    public static EntityCandidateCatalogueDefinition V1 { get; } = new(
        "mavi-entity-candidates-v1",
        0.85,
        2_000,
        [
            new("classes", "Person-Person, Vehicle-Vehicle", SourceCatalogue, "The classes ADR-021 embeds; a pair is always of one class."),
            new("appearanceFloor", "0.85", SourceOwnerDecision,
                "D-S7-2. From the frozen s4-confirm-80-v1 record before any demo pair was scored: 5th percentile of same-Track crop pairs 0.850; " +
                "about 10% of different-object vehicle pairs from different videos also reach it (90th percentile 0.855). A workload control, not a match threshold."),
            new("sameCameraConcurrent", "excluded", SourceCatalogue, "Two Tracks visible at once on one camera are two objects."),
            new("concurrentElsewhere", "excluded beyond the tolerance", SourceCatalogue, "One object cannot be in two places at once."),
            new("concurrencyToleranceMs", "2000", SourceOwnerDecision,
                "D-S7-2. Recording starts are set to the second and a tracker starts or ends a Track a few frames off the true boundary."),
            new("minimumTravelMs", "0", SourceOwnerDecision, "D-S7-2. MAVI has no camera topology to take a travel time from."),
            new("maximumGap", "none", SourceCatalogue, "The gap is shown as a factor, never used as a gate."),
        ]);

    /// <summary>
    /// v2 (owner decision D-S7-3, 2026-10-30; ADR-023 amendment): on the demo corpus v1 proposed 48,898 pairs, 84 % of them
    /// one night-highway camera pairing every car with every later car, and the rest look-alikes from unrelated places.
    /// v2 pairs only different cameras that share a declared site; floor and tolerance are unchanged.
    /// </summary>
    public static EntityCandidateCatalogueDefinition V2 { get; } = new(
        "mavi-entity-candidates-v2",
        0.85,
        2_000,
        [
            new("classes", "Person-Person, Vehicle-Vehicle", SourceCatalogue, "The classes ADR-021 embeds; a pair is always of one class."),
            new("appearanceFloor", "0.85", SourceOwnerDecision,
                "D-S7-2, kept by D-S7-3. From the frozen s4-confirm-80-v1 record before any demo pair was scored: 5th percentile of same-Track crop pairs 0.850; " +
                "about 10% of different-object vehicle pairs from different videos also reach it (90th percentile 0.855). It does not bound the list by itself: the site rule does."),
            new("cameras", "different cameras only", SourceOwnerDecision,
                "D-S7-3. Same-camera pairs are not proposed: on a traffic stream they pair every vehicle with every later one. Same-camera revisit and fragment linking are given up."),
            new("site", "both cameras declare the same site_code; a camera with no site pairs with nothing", SourceOwnerDecision,
                "D-S7-3. MAVI has no topology; a site is declared camera configuration, never inferred. Cameras of unrelated places are never paired."),
            new("concurrentElsewhere", "excluded beyond the tolerance", SourceCatalogue, "One object cannot be in two places at once."),
            new("concurrencyToleranceMs", "2000", SourceOwnerDecision,
                "D-S7-2. Recording starts are set to the second and a tracker starts or ends a Track a few frames off the true boundary."),
            new("minimumTravelMs", "0", SourceOwnerDecision, "D-S7-2. MAVI has no camera topology to take a travel time from."),
            new("maximumGap", "none", SourceCatalogue, "The gap is shown as a factor, never used as a gate."),
            new("perTrackBound", "none", SourceOwnerDecision,
                "D-S7-3. A deterministic per-Track bound (k = 3 over the whole snapshot, total tie-break) is a recorded follow-up option, not part of v2."),
        ],
        CrossCameraOnly: true,
        RequireSharedSite: true);

    public static EntityCandidateCatalogueDefinition Current => V2;
}

/// <summary>
/// What the plausibility model reads of a Track: its camera, the camera's declared site and its UTC interval, nothing
/// else (ADR-023 §4 and its amendment).
/// </summary>
public sealed record PlausibilityTrack(Guid TrackId, Guid CameraId, DateTimeOffset StartUtc, DateTimeOffset EndUtc, string? SiteCode = null);

/// <param name="Reason">Null when plausible, else <c>same_camera_concurrent</c> or <c>concurrent_elsewhere</c>.</param>
/// <param name="GapMs">The later start minus the earlier end; negative when the intervals overlap.</param>
public sealed record PlausibilityVerdict(bool Plausible, string? Reason, bool SameCamera, long GapMs);

/// <summary>
/// The time and camera plausibility model (ADR-023 §4): a deterministic function of the two cameras and intervals.
/// It knows no geography, no view overlap, no travel time and no clock error, and says so on every surface.
/// </summary>
public static class EntityCandidatePlausibility
{
    public const string SameCameraConcurrent = "same_camera_concurrent";
    public const string ConcurrentElsewhere = "concurrent_elsewhere";

    public static PlausibilityVerdict Evaluate(PlausibilityTrack first, PlausibilityTrack second, EntityCandidateCatalogueDefinition catalogue)
    {
        ArgumentNullException.ThrowIfNull(first);
        ArgumentNullException.ThrowIfNull(second);
        ArgumentNullException.ThrowIfNull(catalogue);
        var latestStart = first.StartUtc > second.StartUtc ? first.StartUtc : second.StartUtc;
        var earliestEnd = first.EndUtc < second.EndUtc ? first.EndUtc : second.EndUtc;
        var gapMs = (long)Math.Floor((latestStart - earliestEnd).TotalMilliseconds);
        var sameCamera = first.CameraId == second.CameraId;
        if (sameCamera && gapMs < 0) return new PlausibilityVerdict(false, SameCameraConcurrent, true, gapMs);
        if (!sameCamera && -gapMs > catalogue.ConcurrencyToleranceMs) return new PlausibilityVerdict(false, ConcurrentElsewhere, false, gapMs);
        return new PlausibilityVerdict(true, null, sameCamera, gapMs);
    }

    /// <summary>
    /// Whether the catalogue proposes a pair at all (its scope, before plausibility): v2 proposes only different cameras
    /// that declare the same site. Confirmation does not use this: an Entity may hold two Tracks of one camera when an
    /// operator linked each through another camera; only physical plausibility applies there.
    /// </summary>
    public static bool InScope(PlausibilityTrack first, PlausibilityTrack second, EntityCandidateCatalogueDefinition catalogue)
    {
        ArgumentNullException.ThrowIfNull(first);
        ArgumentNullException.ThrowIfNull(second);
        ArgumentNullException.ThrowIfNull(catalogue);
        if (catalogue.CrossCameraOnly && first.CameraId == second.CameraId) return false;
        if (catalogue.RequireSharedSite && (first.SiteCode is null || !string.Equals(first.SiteCode, second.SiteCode, StringComparison.Ordinal)))
            return false;
        return true;
    }
}

/// <summary>What a confirmation does, decided from the locked state (ADR-023 §6).</summary>
public enum EntityConfirmationKind { CreateEntity, ExtendEntity, AlreadyLinked, Refused }

public sealed record EntityConfirmationPlan(EntityConfirmationKind Kind, Guid? EntityId, Guid? JoiningTrackId, string? RefusalCode, Guid? ConflictingTrackId);

/// <summary>The member Tracks of an Entity as the plausibility model sees them.</summary>
public sealed record EntityMembers(Guid EntityId, EntityType EntityType, IReadOnlyList<PlausibilityTrack> Tracks);

/// <summary>
/// The confirmation rule (ADR-023 §6), a pure function of the locked state so it is tested without a database:
/// create, extend (the joining Track must be plausible against every member), already linked, or refuse a merge.
/// </summary>
public static class EntityConfirmationRules
{
    public const string AlreadyDecided = "entity_candidate_already_decided";
    public const string NotVisible = "entity_candidate_not_visible";
    public const string MergeUnsupported = "entity_merge_unsupported";
    public const string ExtensionImplausible = "entity_extension_implausible";
    public const string Superseded = "entity_candidate_superseded";

    public static EntityConfirmationPlan Plan(
        PlausibilityTrack lower, Guid? lowerEntityId, PlausibilityTrack higher, Guid? higherEntityId,
        EntityMembers? members, EntityCandidateCatalogueDefinition catalogue)
    {
        ArgumentNullException.ThrowIfNull(lower);
        ArgumentNullException.ThrowIfNull(higher);
        ArgumentNullException.ThrowIfNull(catalogue);
        if (lowerEntityId is null && higherEntityId is null) return new(EntityConfirmationKind.CreateEntity, null, null, null, null);
        if (lowerEntityId is { } a && higherEntityId is { } b)
            return a == b
                ? new(EntityConfirmationKind.AlreadyLinked, a, null, null, null)
                : new(EntityConfirmationKind.Refused, null, null, MergeUnsupported, null);

        var entityId = (lowerEntityId ?? higherEntityId)!.Value;
        var joining = lowerEntityId is null ? lower : higher;
        if (members is null || members.EntityId != entityId) throw new ArgumentException("The members of the Entity are required.", nameof(members));
        foreach (var member in members.Tracks.OrderBy(track => track.TrackId))
        {
            if (member.TrackId == joining.TrackId) continue;
            if (!EntityCandidatePlausibility.Evaluate(joining, member, catalogue).Plausible)
                return new(EntityConfirmationKind.Refused, entityId, joining.TrackId, ExtensionImplausible, member.TrackId);
        }

        return new(EntityConfirmationKind.ExtendEntity, entityId, joining.TrackId, null, null);
    }
}
