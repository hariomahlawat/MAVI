using Mavi.Domain.Common;

namespace Mavi.Domain.Cameras;

public sealed class Camera
{
    // Construction
    private Camera() { }

    public static Camera Create(string code, string name, string timeZoneId)
    {
        var normalizedCode = Required(code, 32, "camera_code_required", "camera_code_too_long").ToUpperInvariant();
        var normalizedName = Required(name, 128, "camera_name_required", "camera_name_too_long");
        var normalizedTimeZone = Required(timeZoneId, 64, "camera_timezone_required", "camera_timezone_too_long");

        try
        {
            _ = TimeZoneInfo.FindSystemTimeZoneById(normalizedTimeZone);
        }
        catch (TimeZoneNotFoundException exception)
        {
            throw new DomainValidationException("camera_timezone_invalid", "The camera time zone is not recognized.") { Source = exception.Source };
        }
        catch (InvalidTimeZoneException exception)
        {
            throw new DomainValidationException("camera_timezone_invalid", "The camera time zone is invalid.") { Source = exception.Source };
        }

        var now = DateTimeOffset.UtcNow;
        return new Camera
        {
            Id = Guid.CreateVersion7(),
            Code = normalizedCode,
            Name = normalizedName,
            TimeZoneId = normalizedTimeZone,
            IsActive = true,
            CreatedAtUtc = now,
            UpdatedAtUtc = now,
        };
    }

    // Properties
    public Guid Id { get; private set; }
    public string Code { get; private set; } = string.Empty;
    public string Name { get; private set; } = string.Empty;
    public string? Description { get; private set; }
    public string? LocationName { get; private set; }
    public string TimeZoneId { get; private set; } = string.Empty;
    public bool IsActive { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public DateTimeOffset UpdatedAtUtc { get; private set; }

    // Validation
    private static string Required(string value, int maximumLength, string requiredCode, string lengthCode)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new DomainValidationException(requiredCode, "A required camera value was not supplied.");
        }

        var normalized = value.Trim();
        if (normalized.Length > maximumLength)
        {
            throw new DomainValidationException(lengthCode, $"The value must not exceed {maximumLength} characters.");
        }

        return normalized;
    }
}
