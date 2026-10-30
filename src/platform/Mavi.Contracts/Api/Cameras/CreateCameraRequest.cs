namespace Mavi.Contracts.Api.Cameras;

/// <param name="SiteCode">Optional declared site (ADR-023 amendment 2026-10-30); fixed at creation.</param>
public sealed record CreateCameraRequest(string? Code, string? Name, string? TimeZoneId, string? SiteCode = null);
