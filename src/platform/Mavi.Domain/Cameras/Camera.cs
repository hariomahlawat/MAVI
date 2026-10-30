using Mavi.Domain.Common;

namespace Mavi.Domain.Cameras;

public sealed class Camera
{
    // Construction
    private Camera() { }

    public static Camera Create(string? code, string? name, string? timeZoneId) =>
        Create(code, name, timeZoneId, DateTimeOffset.UtcNow);

    public static Camera Create(string? code, string? name, string? timeZoneId, DateTimeOffset createdAtUtc) =>
        Create(code, name, timeZoneId, createdAtUtc, null);

    /// <param name="siteCode">
    /// The declared site the camera belongs to, or none (ADR-023 amendment 2026-10-30): Entity candidates pair only
    /// different cameras of one declared site. Set at creation; a camera with no site pairs with nothing.
    /// </param>
    public static Camera Create(string? code, string? name, string? timeZoneId, DateTimeOffset createdAtUtc, string? siteCode)
    {
        var normalizedCode = Required(code, 32, "camera_code_required", "camera_code_too_long").ToUpperInvariant();
        var normalizedName = Required(name, 128, "camera_name_required", "camera_name_too_long");
        var normalizedTimeZone = Required(timeZoneId, 64, "camera_timezone_required", "camera_timezone_too_long");
        var normalizedSite = NormaliseSiteCode(siteCode);

        var now = createdAtUtc.ToUniversalTime();
        return new Camera
        {
            Id = Guid.CreateVersion7(),
            Code = normalizedCode,
            Name = normalizedName,
            TimeZoneId = normalizedTimeZone,
            SiteCode = normalizedSite,
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

    /// <summary>The declared site (lower-case token), or null when none is declared (ADR-023 amendment 2026-10-30).</summary>
    public string? SiteCode { get; private set; }
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

    public const int MaximumSiteCodeLength = 64;

    /// <summary>Null for none; otherwise a lower-case token of letters, digits, '.', '_' and '-' starting with a letter or digit.</summary>
    public static string? NormaliseSiteCode(string? siteCode)
    {
        if (siteCode is null) return null;
        var normalized = siteCode.Trim().ToLowerInvariant();
        if (normalized.Length is 0 or > MaximumSiteCodeLength || !char.IsAsciiLetterOrDigit(normalized[0]) ||
            !normalized.All(c => char.IsAsciiLetterLower(c) || char.IsAsciiDigit(c) || c is '.' or '_' or '-'))
            throw new DomainValidationException("camera_site_code_invalid",
                $"A site code is 1 to {MaximumSiteCodeLength} letters, digits, '.', '_' or '-', starting with a letter or digit.");
        return normalized;
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
