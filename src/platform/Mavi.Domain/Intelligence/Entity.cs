using Mavi.Domain.Common;

namespace Mavi.Domain.Intelligence;

/// <summary>
/// An operator-confirmed group of Tracks of one class (ADR-023 §1). It is an operator decision, never an
/// identification: <see cref="IdentityStatus"/> stays <see cref="IdentityStatus.Unknown"/> and nothing names it.
/// It comes into existence only when an operator confirms an Entity candidate.
/// </summary>
public sealed class Entity
{
    public const int DisplayCodeLength = 14;

    private Entity() { }

    /// <summary>Created by the confirmation of an Entity candidate whose two Tracks belong to no Entity yet.</summary>
    public static Entity CreateByConfirmation(EntityType entityType, DateTimeOffset nowUtc)
    {
        if (!Enum.IsDefined(entityType))
            throw new DomainValidationException("entity_invalid", "The entity type is invalid.");
        var id = Guid.CreateVersion7();
        var now = nowUtc.ToUniversalTime();
        return new Entity
        {
            Id = id,
            EntityType = entityType,
            DisplayCode = DisplayCodeFor(entityType, id),
            IdentityStatus = IdentityStatus.Unknown,
            ReviewStatus = ReviewStatus.Confirmed,
            CreatedAtUtc = now,
            UpdatedAtUtc = now,
        };
    }

    /// <summary>A Track joined the Entity by a later confirmation.</summary>
    public void Extend(DateTimeOffset nowUtc) => UpdatedAtUtc = nowUtc.ToUniversalTime();

    /// <summary>A member Track left the Entity or joined it by a merge (ADR-027 §4); the membership itself is in the history.</summary>
    public void Touch(DateTimeOffset nowUtc) => UpdatedAtUtc = nowUtc.ToUniversalTime();

    /// <summary>
    /// Records that every member moved to <paramref name="target"/> by an operator's merge (ADR-027 §4). The Entity is kept,
    /// with its history, as <see cref="EntityMergeState.Merged"/>; it never becomes active again.
    /// </summary>
    public void MergeInto(Entity target, DateTimeOffset nowUtc)
    {
        ArgumentNullException.ThrowIfNull(target);
        if (State != EntityMergeState.Active || target.State != EntityMergeState.Active || target.Id == Id || target.EntityType != EntityType)
            throw new DomainValidationException("entity_merge_invalid", "Only two different active Entities of one type can be merged.");
        State = EntityMergeState.Merged;
        MergedIntoEntityId = target.Id;
        UpdatedAtUtc = nowUtc.ToUniversalTime();
        target.UpdatedAtUtc = UpdatedAtUtc;
    }

    /// <summary><c>P-</c> or <c>V-</c> and the last twelve hex digits of the id (the random part of a UUIDv7).</summary>
    public static string DisplayCodeFor(EntityType entityType, Guid id) =>
        (entityType == EntityType.Person ? "P-" : "V-") + id.ToString("N")[^12..];

    // Properties
    public Guid Id { get; private set; }
    public EntityType EntityType { get; private set; }
    public string DisplayCode { get; private set; } = string.Empty;
    public IdentityStatus IdentityStatus { get; private set; }
    public ReviewStatus ReviewStatus { get; private set; }
    public Guid? RepresentativeArtifactId { get; private set; }
    public EntityMergeState State { get; private set; }
    public Guid? MergedIntoEntityId { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public DateTimeOffset UpdatedAtUtc { get; private set; }
}
