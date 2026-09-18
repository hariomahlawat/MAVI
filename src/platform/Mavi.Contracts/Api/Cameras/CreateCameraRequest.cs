namespace Mavi.Contracts.Api.Cameras;

public sealed record CreateCameraRequest(string? Code, string? Name, string? TimeZoneId);
