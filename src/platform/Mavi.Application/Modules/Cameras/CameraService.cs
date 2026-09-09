using Mavi.Domain.Cameras;
using Mavi.Application.Abstractions.Time;

namespace Mavi.Application.Modules.Cameras;

public sealed record CreateCameraCommand(string? Code, string? Name, string? TimeZoneId);

public sealed record CameraOperationResult(bool IsSuccess, Camera? Camera, string? ErrorCode)
{
    public static CameraOperationResult Success(Camera camera) => new(true, camera, null);
    public static CameraOperationResult Failure(string errorCode) => new(false, null, errorCode);
}

public static class CameraErrorCodes
{
    public const string CodeDuplicate = "camera_code_duplicate";
    public const string NotFound = "camera_not_found";
}

public sealed class CameraService(ICameraRepository repository, ITimeZoneService timeZones, TimeProvider timeProvider)
{
    // Commands
    public async Task<CameraOperationResult> CreateAsync(
        CreateCameraCommand command,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(command.TimeZoneId))
            throw new Mavi.Domain.Common.DomainValidationException("camera_timezone_required", "The camera time zone is required.");
        var normalizedTimeZoneId = command.TimeZoneId.Trim();
        if (normalizedTimeZoneId.Length > 64)
            throw new Mavi.Domain.Common.DomainValidationException("camera_timezone_too_long", "The camera time zone must not exceed 64 characters.");
        if (!timeZones.IsValidIanaTimeZoneId(normalizedTimeZoneId))
            throw new Mavi.Domain.Common.DomainValidationException("camera_timezone_invalid", "The camera time zone must be a recognized IANA identifier.");
        var camera = Camera.Create(command.Code, command.Name, normalizedTimeZoneId, timeProvider.GetUtcNow());
        if (await repository.GetByCodeAsync(camera.Code, cancellationToken) is not null)
        {
            return CameraOperationResult.Failure(CameraErrorCodes.CodeDuplicate);
        }

        await repository.AddAsync(camera, cancellationToken);
        try
        {
            await repository.SaveChangesAsync(cancellationToken);
        }
        catch (CameraCodeDuplicateException)
        {
            return CameraOperationResult.Failure(CameraErrorCodes.CodeDuplicate);
        }

        return CameraOperationResult.Success(camera);
    }

    // Queries
    public Task<Camera?> GetAsync(Guid id, CancellationToken cancellationToken) =>
        repository.GetAsync(id, cancellationToken);

    public Task<Camera?> GetByCodeAsync(string normalizedCode, CancellationToken cancellationToken) =>
        repository.GetByCodeAsync(normalizedCode, cancellationToken);

    public Task<IReadOnlyList<Camera>> ListAsync(CancellationToken cancellationToken) =>
        repository.ListAsync(cancellationToken);
}
