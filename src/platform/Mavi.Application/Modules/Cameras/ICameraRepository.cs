using Mavi.Domain.Cameras;

namespace Mavi.Application.Modules.Cameras;

public interface ICameraRepository
{
    Task AddAsync(Camera camera, CancellationToken cancellationToken);
    Task<Camera?> GetAsync(Guid id, CancellationToken cancellationToken);
    Task<Camera?> GetByCodeAsync(string code, CancellationToken cancellationToken);
    Task<IReadOnlyList<Camera>> ListAsync(CancellationToken cancellationToken);
    Task SaveChangesAsync(CancellationToken cancellationToken);
}

public sealed class CameraCodeDuplicateException : Exception
{
    public CameraCodeDuplicateException() : base("A camera with this code already exists.") { }

    public CameraCodeDuplicateException(Exception innerException)
        : base("A camera with this code already exists.", innerException) { }
}
