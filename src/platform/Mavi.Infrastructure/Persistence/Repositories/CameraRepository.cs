using Mavi.Application.Modules.Cameras;
using Mavi.Domain.Cameras;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed class CameraRepository(MaviDbContext dbContext) : ICameraRepository
{
    // Commands
    public async Task AddAsync(Camera camera, CancellationToken cancellationToken) =>
        await dbContext.Cameras.AddAsync(camera, cancellationToken);

    public async Task SaveChangesAsync(CancellationToken cancellationToken)
    {
        try
        {
            await dbContext.SaveChangesAsync(cancellationToken);
        }
        catch (DbUpdateException exception) when (
            exception.InnerException is PostgresException
            {
                SqlState: PostgresErrorCodes.UniqueViolation,
                ConstraintName: "IX_cameras_code",
            })
        {
            throw new CameraCodeDuplicateException(exception);
        }
    }

    // Queries
    public Task<Camera?> GetAsync(Guid id, CancellationToken cancellationToken) =>
        dbContext.Cameras.AsNoTracking().SingleOrDefaultAsync(camera => camera.Id == id, cancellationToken);

    public Task<Camera?> GetByCodeAsync(string code, CancellationToken cancellationToken) =>
        dbContext.Cameras.AsNoTracking().SingleOrDefaultAsync(camera => camera.Code == code, cancellationToken);

    public async Task<IReadOnlyList<Camera>> ListAsync(CancellationToken cancellationToken) =>
        await dbContext.Cameras.AsNoTracking().OrderBy(camera => camera.Code).ToArrayAsync(cancellationToken);
}
