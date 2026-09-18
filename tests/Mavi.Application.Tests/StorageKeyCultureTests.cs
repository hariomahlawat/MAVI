using System.Globalization;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Abstractions.Time;
using Mavi.Application.Modules.Cameras;
using Mavi.Application.Modules.Media;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace Mavi.Application.Tests;

public sealed class StorageKeyCultureTests
{
    [Fact]
    public async Task ImportUsesCanonicalForwardSlashStorageDateRegardlessOfCurrentCulture()
    {
        var previousCulture = CultureInfo.CurrentCulture;
        var culture = (CultureInfo)CultureInfo.InvariantCulture.Clone();
        culture.DateTimeFormat.DateSeparator = ".";
        CultureInfo.CurrentCulture = culture;

        try
        {
            var camera = Camera.Create("CAM-CULTURE", "Culture Test", "UTC");
            var media = new FakeMediaStore();
            var service = new VideoImportService(
                new FakeCameraRepository(camera),
                new FakeVideoCatalog(),
                media,
                new FakeMetadataReader(),
                new TestTimeZones(),
                TimeProvider.System,
                Options.Create(new VideoImportOptions { MaximumFileSizeBytes = 1024 }),
                NullLogger<VideoImportService>.Instance);

            var result = await service.ImportAsync(
                new ImportVideoCommand(
                    camera.Id,
                    new DateTime(2026, 9, 8, 12, 0, 0, DateTimeKind.Unspecified),
                    "video.mp4",
                    new MemoryStream([1, 2, 3])),
                CancellationToken.None);

            Assert.True(result.IsSuccess);
            Assert.NotNull(media.WrittenKey);
            Assert.Contains("/2026/09/08/", media.WrittenKey, StringComparison.Ordinal);
            Assert.DoesNotContain("2026.09.08", media.WrittenKey, StringComparison.Ordinal);
        }
        finally
        {
            CultureInfo.CurrentCulture = previousCulture;
        }
    }

    private sealed class FakeCameraRepository(Camera camera) : ICameraRepository
    {
        public Task<Camera?> GetAsync(Guid id, CancellationToken cancellationToken) => Task.FromResult<Camera?>(camera);
        public Task AddAsync(Camera value, CancellationToken cancellationToken) => Task.CompletedTask;
        public Task<Camera?> GetByCodeAsync(string code, CancellationToken cancellationToken) => Task.FromResult<Camera?>(null);
        public Task<IReadOnlyList<Camera>> ListAsync(CancellationToken cancellationToken) => Task.FromResult<IReadOnlyList<Camera>>([]);
        public Task SaveChangesAsync(CancellationToken cancellationToken) => Task.CompletedTask;
    }

    private sealed class FakeMediaStore : IMediaStore
    {
        public string? WrittenKey { get; private set; }

        public async Task<MediaWriteResult> WriteAsync(string storageKey, Stream content, CancellationToken cancellationToken)
        {
            WrittenKey = storageKey;
            using var sink = new MemoryStream();
            await content.CopyToAsync(sink, cancellationToken);
            return new MediaWriteResult(sink.Length, new string('a', 64));
        }

        public Task DeleteAsync(string storageKey, CancellationToken cancellationToken) => Task.CompletedTask;
        public Task<bool> ExistsAsync(string storageKey, CancellationToken cancellationToken) => Task.FromResult(true);
        public Task<Stream> OpenReadAsync(string storageKey, CancellationToken cancellationToken) =>
            Task.FromResult<Stream>(new MemoryStream());
    }

    private sealed class FakeMetadataReader : IVideoMetadataReader
    {
        public Task<VideoMetadata> ReadAsync(string storageKey, CancellationToken cancellationToken) =>
            Task.FromResult(new VideoMetadata(1_000, 160, 90, 25, 1, "h264", "mp4", "isom"));
    }

    private sealed class FakeVideoCatalog : IVideoCatalog
    {
        public Task<VideoAsset?> GetAsync(Guid id, CancellationToken cancellationToken) => Task.FromResult<VideoAsset?>(null);
        public Task<IReadOnlyList<VideoAsset>> ListAsync(CancellationToken cancellationToken) => Task.FromResult<IReadOnlyList<VideoAsset>>([]);
        public Task<VideoAsset?> FindSourceVideoBySha256Async(string sha256, CancellationToken cancellationToken) => Task.FromResult<VideoAsset?>(null);
        public Task AddAsync(Artifact artifact, VideoAsset video, CancellationToken cancellationToken) => Task.CompletedTask;
        public Task SaveChangesAsync(CancellationToken cancellationToken) => Task.CompletedTask;
    }

    private sealed class TestTimeZones : ITimeZoneService
    {
        public bool IsValidIanaTimeZoneId(string? id) => !string.IsNullOrWhiteSpace(id);
        public TimeZoneInfo GetTimeZone(string id) => TimeZoneInfo.FindSystemTimeZoneById(id);
        public DateTimeOffset ConvertLocalToUtc(DateTime value, string id) =>
            new(TimeZoneInfo.ConvertTimeToUtc(value, GetTimeZone(id)), TimeSpan.Zero);
        public DateTimeOffset ConvertUtcToZone(DateTimeOffset value, string id) => TimeZoneInfo.ConvertTime(value, GetTimeZone(id));
        public bool IsAmbiguous(DateTime value, string id) => GetTimeZone(id).IsAmbiguousTime(value);
        public bool IsInvalid(DateTime value, string id) => GetTimeZone(id).IsInvalidTime(value);
        public TimeSpan GetUtcOffset(DateTime value, string id) => GetTimeZone(id).GetUtcOffset(value);
    }
}
