using Mavi.Domain.Common;

namespace Mavi.Domain.Cameras;

public sealed class Camera
{
    // Construction
    private Camera() { }

    public static Camera Create(string? code, string? name, string? timeZoneId) =>
        Create(code, name, timeZoneId, DateTimeOffset.UtcNow);

    public static Camera Create(string? code, string? name, string? timeZoneId, DateTimeOffset createdAtUtc)
    {
        var normalizedCode = Required(code, 32, "camera_code_required", "camera_code_too_long").ToUpperInvariant();
        var normalizedName = Required(name, 128, "camera_name_required", "camera_name_too_long");
        var normalizedTimeZone = Required(timeZoneId, 64, "camera_timezone_required", "camera_timezone_too_long");

        var now = createdAtUtc.ToUniversalTime();
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

    /// <summary>Face analysis runs only on this camera's runs when switched on; off by default (ADR-022 §3).</summary>
    public bool FaceAnalysisEnabled { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public DateTimeOffset UpdatedAtUtc { get; private set; }

    /// <summary>The attributable opt-in switch of ADR-022 §3; the caller deletes the camera's face rows on opt-out.</summary>
    public void SetFaceAnalysis(bool enabled, DateTimeOffset nowUtc)
    {
        if (FaceAnalysisEnabled == enabled) return;
        FaceAnalysisEnabled = enabled;
        UpdatedAtUtc = nowUtc.ToUniversalTime();
    }

    // Validation
    private static string Required(string? value, int maximumLength, string requiredCode, string lengthCode)
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
