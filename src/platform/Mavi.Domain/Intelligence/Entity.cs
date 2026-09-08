using Mavi.Domain.Common;

namespace Mavi.Domain.Intelligence;

public sealed class Entity
{
    private Entity() { }

    // Construction
    public static Entity Create(EntityType entityType, string displayCode)
    {
        if (string.IsNullOrWhiteSpace(displayCode) || displayCode.Trim().Length > 64)
            throw new DomainValidationException("entity_display_code_invalid", "A valid entity display code is required.");
        var now = DateTimeOffset.UtcNow;
        return new Entity { Id = Guid.CreateVersion7(), EntityType = entityType, DisplayCode = displayCode.Trim(),
            IdentityStatus = IdentityStatus.Unknown, ReviewStatus = ReviewStatus.Unreviewed, CreatedAtUtc = now, UpdatedAtUtc = now };
    }

    // Properties
    public Guid Id { get; private set; }
    public EntityType EntityType { get; private set; }
    public string DisplayCode { get; private set; } = string.Empty;
    public IdentityStatus IdentityStatus { get; private set; }
    public ReviewStatus ReviewStatus { get; private set; }
    public Guid? RepresentativeArtifactId { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public DateTimeOffset UpdatedAtUtc { get; private set; }
}
