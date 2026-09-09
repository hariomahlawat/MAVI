using Mavi.Application.Modules.Cameras;
using Mavi.Domain.Cameras;

namespace Mavi.Application.Tests;

public sealed class CameraServiceTests
{
    // Duplicate handling
    [Fact]
    public async Task CreateRejectsDuplicateNormalizedCameraCode()
    {
        var repository = new FakeCameraRepository(Camera.Create("CAM-0001", "Existing", "UTC"));
        var service = new CameraService(repository);

        var result = await service.CreateAsync(
            new CreateCameraCommand(" cam-0001 ", "Main Gate", "UTC"),
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(CameraErrorCodes.CodeDuplicate, result.ErrorCode);
        Assert.Equal("CAM-0001", repository.LastCodeLookup);
        Assert.Equal(0, repository.SaveCount);
    }

    [Fact]
    public async Task CreateTranslatesPersistenceDuplicateRace()
    {
        var repository = new FakeCameraRepository { ThrowDuplicateOnSave = true };
        var service = new CameraService(repository);

        var result = await service.CreateAsync(
            new CreateCameraCommand("CAM-0002", "Side Gate", "UTC"),
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(CameraErrorCodes.CodeDuplicate, result.ErrorCode);
    }

    // Repository test double
    private sealed class FakeCameraRepository(params Camera[] cameras) : ICameraRepository
    {
        private readonly List<Camera> _cameras = [.. cameras];

        public string? LastCodeLookup { get; private set; }
        public int SaveCount { get; private set; }
        public bool ThrowDuplicateOnSave { get; init; }

        public Task AddAsync(Camera camera, CancellationToken cancellationToken)
        {
            _cameras.Add(camera);
            return Task.CompletedTask;
        }

        public Task<Camera?> GetAsync(Guid id, CancellationToken cancellationToken) =>
            Task.FromResult(_cameras.SingleOrDefault(camera => camera.Id == id));

        public Task<Camera?> GetByCodeAsync(string code, CancellationToken cancellationToken)
        {
            LastCodeLookup = code;
            return Task.FromResult(_cameras.SingleOrDefault(camera => camera.Code == code));
        }

        public Task<IReadOnlyList<Camera>> ListAsync(CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<Camera>>(_cameras.OrderBy(camera => camera.Code).ToArray());

        public Task SaveChangesAsync(CancellationToken cancellationToken)
        {
            SaveCount++;
            return ThrowDuplicateOnSave
                ? Task.FromException(new CameraCodeDuplicateException())
                : Task.CompletedTask;
        }
    }
}
