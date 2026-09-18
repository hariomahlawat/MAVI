namespace Mavi.Contracts.Api.Cameras;

public sealed record CameraResponse(
    Guid Id,
    string Code,
    string Name,
    string? Description,
    string? LocationName,
    string TimeZoneId,
    bool IsActive,
    DateTimeOffset CreatedAtUtc,
    DateTimeOffset UpdatedAtUtc);
