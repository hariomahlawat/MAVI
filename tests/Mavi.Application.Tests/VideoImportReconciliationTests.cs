using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Abstractions.Time;
using Mavi.Application.Modules.Cameras;
using Mavi.Application.Modules.Media;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace Mavi.Application.Tests;

public sealed class VideoImportReconciliationTests
{
    [Fact]
    public async Task UniquenessRaceReturnsAuthoritativeWinningVideoId()
    {
        var nowUtc = new DateTimeOffset(2026, 9, 14, 2, 0, 0, TimeSpan.Zero);
        var camera = Camera.Create("CAM-RACE", "Race Camera", "UTC", nowUtc);
        var existing = VideoAsset.Create(
            camera.Id,
            Guid.NewGuid(),
            "existing.mp4",
            nowUtc,
            1_000,
            25,
            1,
            160,
            90,
            "h264",
            TimestampSource.Manual,
            1.0,
            "UTC",
            0,
            nowUtc);

        var catalog = new RaceVideoCatalog(existing);
        var service = new VideoImportService(
            new SingleCameraRepository(camera),
            catalog,
            new FixedMediaStore(),
            new FixedMetadataReader(),
            new UtcTimeZoneService(),
            new FixedTimeProvider(nowUtc),
            Options.Create(new VideoImportOptions
            {
                MaximumFileSizeBytes = 3L * 1024 * 1024 * 1024,
                MultipartOverheadBytes = 1024 * 1024,
                AllowedExtensions = [".mp4"],
            }),
            NullLogger<VideoImportService>.Instance);

        await using var content = new MemoryStream([1, 2, 3, 4]);
        var result = await service.ImportAsync(
            new ImportVideoCommand(
                camera.Id,
                new DateTime(2026, 9, 14, 7, 30, 0, DateTimeKind.Unspecified),
                "race.mp4",
                content),
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(VideoImportErrorCodes.Duplicate, result.ErrorCode);
        Assert.Equal(existing.Id, result.ExistingVideoAssetId);
        Assert.Equal(2, catalog.FindCalls);
    }

    private sealed class SingleCameraRepository(Camera camera) : ICameraRepository
    {
        public Task AddAsync(Camera value, CancellationToken cancellationToken) => Task.CompletedTask;
        public Task<Camera?> GetAsync(Guid id, CancellationToken cancellationToken) =>
            Task.FromResult<Camera?>(id == camera.Id ? camera : null);
        public Task<Camera?> GetByCodeAsync(string code, CancellationToken cancellationToken) =>
            Task.FromResult<Camera?>(string.Equals(code, camera.Code, StringComparison.Ordinal) ? camera : null);
        public Task<IReadOnlyList<Camera>> ListAsync(CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<Camera>>([camera]);
        public Task SaveChangesAsync(CancellationToken cancellationToken) => Task.CompletedTask;
    }

    private sealed class RaceVideoCatalog(VideoAsset existing) : IVideoCatalog
    {
        public int FindCalls { get; private set; }

        public Task<VideoAsset?> GetAsync(Guid id, CancellationToken cancellationToken) =>
            Task.FromResult<VideoAsset?>(id == existing.Id ? existing : null);

        public Task<IReadOnlyList<VideoAsset>> ListAsync(CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<VideoAsset>>([existing]);

        public Task<VideoAsset?> FindSourceVideoBySha256Async(string sha256, CancellationToken cancellationToken)
        {
            FindCalls++;
            return Task.FromResult<VideoAsset?>(FindCalls == 1 ? null : existing);
        }

        public Task AddAsync(Artifact artifact, VideoAsset video, CancellationToken cancellationToken) =>
            Task.CompletedTask;

        public Task SaveChangesAsync(CancellationToken cancellationToken) =>
            throw new DuplicateSourceVideoException(new InvalidOperationException("simulated uniqueness race"));
    }

    private sealed class FixedMediaStore : IMediaStore
    {
        public Task<MediaWriteResult> WriteAsync(string storageKey, Stream content, CancellationToken cancellationToken) =>
            Task.FromResult(new MediaWriteResult(4, new string('a', 64)));

        public Task<Stream> OpenReadAsync(string storageKey, CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<bool> ExistsAsync(string storageKey, CancellationToken cancellationToken) =>
            Task.FromResult(false);

        public Task DeleteAsync(string storageKey, CancellationToken cancellationToken) =>
            Task.CompletedTask;
    }

    private sealed class FixedMetadataReader : IVideoMetadataReader
    {
        public Task<VideoMetadata> ReadAsync(string storageKey, CancellationToken cancellationToken) =>
            Task.FromResult(new VideoMetadata(
                1_000,
                160,
                90,
                25,
                1,
                "h264",
                "mp4",
                "isom"));
    }

    private sealed class UtcTimeZoneService : ITimeZoneService
    {
        public bool IsValidIanaTimeZoneId(string? timeZoneId) => timeZoneId == "UTC";
        public TimeZoneInfo GetTimeZone(string timeZoneId) => TimeZoneInfo.Utc;
        public DateTimeOffset ConvertLocalToUtc(DateTime localDateTime, string timeZoneId) =>
            new(DateTime.SpecifyKind(localDateTime, DateTimeKind.Utc));
        public DateTimeOffset ConvertUtcToZone(DateTimeOffset utcInstant, string timeZoneId) =>
            utcInstant.ToUniversalTime();
        public bool IsAmbiguous(DateTime localDateTime, string timeZoneId) => false;
        public bool IsInvalid(DateTime localDateTime, string timeZoneId) => false;
        public TimeSpan GetUtcOffset(DateTime localDateTime, string timeZoneId) => TimeSpan.Zero;
    }

    private sealed class FixedTimeProvider(DateTimeOffset nowUtc) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => nowUtc;
    }
}
