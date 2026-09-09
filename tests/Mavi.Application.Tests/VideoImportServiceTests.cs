using System.Reflection;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Abstractions.Time;
using Mavi.Application.Modules.Cameras;
using Mavi.Application.Modules.Media;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace Mavi.Application.Tests;

public sealed class VideoImportServiceTests
{
    // Time semantics
    [Fact]
    public async Task ConvertsCameraLocalKolkataTimeToUtcAndUsesLocalStorageDate()
    {
        var context = CreateContext("Asia/Kolkata");
        var local = new DateTime(2026, 9, 8, 14, 0, 0, DateTimeKind.Unspecified);

        var result = await context.Service.ImportAsync(Command(context.Camera, local, "gate.mp4"), CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(new DateTimeOffset(2026, 9, 8, 8, 30, 0, TimeSpan.Zero), result.Video!.RecordingStartUtc);
        Assert.Equal("Asia/Kolkata", result.Video.RecordingTimeZoneId);
        Assert.Equal(330, result.Video.RecordingUtcOffsetMinutes);
        Assert.Contains("/2026/09/08/", context.Media.WrittenKey, StringComparison.Ordinal);

        typeof(Camera).GetProperty(nameof(Camera.TimeZoneId))!.SetValue(context.Camera, "UTC");
        Assert.Equal("Asia/Kolkata", result.Video.RecordingTimeZoneId);
        Assert.Equal(330, result.Video.RecordingUtcOffsetMinutes);
    }

    [Theory]
    [InlineData(2026, 11, 1, 1, 30)]
    [InlineData(2026, 3, 8, 2, 30)]
    public async Task RejectsAmbiguousAndInvalidDstTimes(int year, int month, int day, int hour, int minute)
    {
        var context = CreateContext("America/New_York");

        var result = await context.Service.ImportAsync(
            Command(context.Camera, new DateTime(year, month, day, hour, minute, 0, DateTimeKind.Unspecified), "video.mp4"),
            CancellationToken.None);

        Assert.Equal(VideoImportErrorCodes.InvalidRecordingTime, result.ErrorCode);
        Assert.Null(context.Media.WrittenKey);
    }

    // Camera and filename validation
    [Fact]
    public async Task MissingAndInactiveCamerasAreRejectedBeforeWriting()
    {
        var missing = CreateContext();
        missing.Cameras.Camera = null;
        var missingResult = await missing.Service.ImportAsync(Command(missing.Camera), CancellationToken.None);
        var inactive = CreateContext();
        typeof(Camera).GetProperty(nameof(Camera.IsActive))!.SetValue(inactive.Camera, false);
        var inactiveResult = await inactive.Service.ImportAsync(Command(inactive.Camera), CancellationToken.None);

        Assert.Equal(VideoImportErrorCodes.CameraNotFound, missingResult.ErrorCode);
        Assert.Equal(VideoImportErrorCodes.CameraInactive, inactiveResult.ErrorCode);
        Assert.Null(missing.Media.WrittenKey);
        Assert.Null(inactive.Media.WrittenKey);
    }

    [Theory]
    [InlineData("C:\\fakepath\\gate.mp4", "gate.mp4")]
    [InlineData("C:/fakepath/gate.mp4", "gate.mp4")]
    public async Task SanitizesBothFilenameSeparatorStyles(string supplied, string expected)
    {
        var context = CreateContext();

        var result = await context.Service.ImportAsync(Command(context.Camera, fileName: supplied), CancellationToken.None);

        Assert.Equal(expected, result.Video!.OriginalFileName);
        Assert.DoesNotContain(expected, context.Media.WrittenKey!, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain(context.Camera.Code, context.Media.WrittenKey!, StringComparison.OrdinalIgnoreCase);
        Assert.Contains(result.Video.Id.ToString("D"), context.Media.WrittenKey!, StringComparison.Ordinal);
        Assert.Equal(7, result.Video.Id.Version);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public async Task BlankFilenameIsRejected(string fileName)
    {
        var context = CreateContext();
        var result = await context.Service.ImportAsync(Command(context.Camera, fileName: fileName), CancellationToken.None);
        Assert.Equal(VideoImportErrorCodes.InvalidFileName, result.ErrorCode);
    }

    [Fact]
    public async Task UnsupportedExtensionIsRejected()
    {
        var context = CreateContext();
        var result = await context.Service.ImportAsync(Command(context.Camera, fileName: "video.avi"), CancellationToken.None);
        Assert.Equal(VideoImportErrorCodes.FormatUnsupported, result.ErrorCode);
        Assert.Null(context.Media.WrittenKey);
    }

    [Theory]
    [InlineData("bad\0.mp4")]
    [InlineData("bad\u0001.mp4")]
    public async Task ControlCharactersInFilenameAreRejected(string fileName)
    {
        var context = CreateContext();
        var result = await context.Service.ImportAsync(Command(context.Camera, fileName: fileName), CancellationToken.None);
        Assert.Equal(VideoImportErrorCodes.InvalidFileName, result.ErrorCode);
    }

    [Fact]
    public async Task ApplicationRejectsOversizeStreamBeforeMetadataOrPersistence()
    {
        var context = CreateContext(maximumBytes: 2);
        var result = await context.Service.ImportAsync(Command(context.Camera), CancellationToken.None);
        Assert.Equal(VideoImportErrorCodes.FileTooLarge, result.ErrorCode);
        Assert.False(context.Catalog.Added);
    }

    [Fact]
    public async Task NonMp4ContainerIsRejectedAndManagedMediaIsDeleted()
    {
        var context = CreateContext();
        context.Metadata.Value = context.Metadata.Value with { FormatName = "matroska,webm" };
        var result = await context.Service.ImportAsync(Command(context.Camera), CancellationToken.None);
        Assert.Equal(VideoImportErrorCodes.ContainerUnsupported, result.ErrorCode);
        Assert.True(context.Media.Deleted);
        Assert.False(context.Catalog.Added);
    }

    // Managed ownership and compensation
    [Fact]
    public async Task MetadataPopulatesVideoAndVideoIdExistsBeforeStorageWrite()
    {
        var context = CreateContext();
        context.Metadata.Value = new VideoMetadata(2_500, 640, 360, 30000, 1001, "h264", "mov,mp4,m4a,3gp,3g2,mj2", "isom");

        var result = await context.Service.ImportAsync(Command(context.Camera), CancellationToken.None);

        Assert.Equal(2_500, result.Video!.DurationMs);
        Assert.Equal(640, result.Video.Width);
        Assert.Equal(30000, result.Video.FrameRateNumerator);
        Assert.True(Guid.TryParse(Path.GetFileNameWithoutExtension(context.Media.WrittenKey), out var writtenId));
        Assert.Equal(result.Video.Id, writtenId);
    }

    [Fact]
    public async Task DuplicateMetadataAndDatabaseFailuresDeleteOnlyAttemptedMedia()
    {
        var duplicate = CreateContext();
        duplicate.Catalog.Duplicate = VideoAsset.Create(Guid.CreateVersion7(), duplicate.Camera.Id, Guid.CreateVersion7(),
            "old.mp4", DateTimeOffset.UtcNow, 1000, 25, 1, 10, 10, "h264", TimestampSource.Manual, 1);
        var duplicateResult = await duplicate.Service.ImportAsync(Command(duplicate.Camera), CancellationToken.None);
        var invalid = CreateContext();
        invalid.Metadata.Exception = new VideoMetadataException("private diagnostic");
        var invalidResult = await invalid.Service.ImportAsync(Command(invalid.Camera), CancellationToken.None);
        var database = CreateContext();
        database.Catalog.SaveException = new InvalidOperationException("database failed");

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            database.Service.ImportAsync(Command(database.Camera), CancellationToken.None));
        Assert.Equal(VideoImportErrorCodes.Duplicate, duplicateResult.ErrorCode);
        Assert.Equal(VideoImportErrorCodes.MetadataInvalid, invalidResult.ErrorCode);
        Assert.True(duplicate.Media.Deleted && invalid.Media.Deleted && database.Media.Deleted);
    }

    [Fact]
    public async Task CancellationAfterWriteDeletesManagedMedia()
    {
        var context = CreateContext();
        context.Metadata.Exception = new OperationCanceledException();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            context.Service.ImportAsync(Command(context.Camera), CancellationToken.None));

        Assert.True(context.Media.Deleted);
    }

    // Test fixtures
    private static ImportVideoCommand Command(Camera camera, DateTime? local = null, string fileName = "video.mp4") =>
        new(camera.Id, local ?? new DateTime(2026, 9, 8, 12, 0, 0, DateTimeKind.Unspecified), fileName, new MemoryStream([1, 2, 3]));

    private static TestContext CreateContext(string timeZone = "UTC", long maximumBytes = 1024)
    {
        var camera = Camera.Create("CAM-SECRET", "Test", timeZone);
        var cameras = new FakeCameras { Camera = camera };
        var catalog = new FakeCatalog();
        var media = new FakeMediaStore();
        var metadata = new FakeMetadataReader();
        var service = new VideoImportService(cameras, catalog, media, metadata,
            new TestTimeZones(), TimeProvider.System,
            Options.Create(new VideoImportOptions { MaximumFileSizeBytes = maximumBytes }), NullLogger<VideoImportService>.Instance);
        return new TestContext(camera, cameras, catalog, media, metadata, service);
    }

    private sealed record TestContext(Camera Camera, FakeCameras Cameras, FakeCatalog Catalog,
        FakeMediaStore Media, FakeMetadataReader Metadata, VideoImportService Service);

    private sealed class FakeCameras : ICameraRepository
    {
        public Camera? Camera { get; set; }
        public Task<Camera?> GetAsync(Guid id, CancellationToken cancellationToken) => Task.FromResult(Camera);
        public Task AddAsync(Camera camera, CancellationToken cancellationToken) => Task.CompletedTask;
        public Task<Camera?> GetByCodeAsync(string code, CancellationToken cancellationToken) => Task.FromResult<Camera?>(null);
        public Task<IReadOnlyList<Camera>> ListAsync(CancellationToken cancellationToken) => Task.FromResult<IReadOnlyList<Camera>>([]);
        public Task SaveChangesAsync(CancellationToken cancellationToken) => Task.CompletedTask;
    }

    private sealed class FakeMediaStore : IMediaStore
    {
        public string? WrittenKey { get; private set; }
        public bool Deleted { get; private set; }
        public async Task<MediaWriteResult> WriteAsync(string storageKey, Stream content, CancellationToken cancellationToken)
        { WrittenKey = storageKey; using var sink = new MemoryStream(); await content.CopyToAsync(sink, cancellationToken); return new MediaWriteResult(sink.Length, new string('a', 64)); }
        public Task DeleteAsync(string storageKey, CancellationToken cancellationToken) { Deleted = true; return Task.CompletedTask; }
        public Task<bool> ExistsAsync(string storageKey, CancellationToken cancellationToken) => Task.FromResult(true);
        public Task<Stream> OpenReadAsync(string storageKey, CancellationToken cancellationToken) => Task.FromResult<Stream>(new MemoryStream());
    }

    private sealed class FakeMetadataReader : IVideoMetadataReader
    {
        public VideoMetadata Value { get; set; } = new(1_000, 160, 90, 25, 1, "h264", "mp4", "isom");
        public Exception? Exception { get; set; }
        public Task<VideoMetadata> ReadAsync(string storageKey, CancellationToken cancellationToken) =>
            Exception is null ? Task.FromResult(Value) : Task.FromException<VideoMetadata>(Exception);
    }

    private sealed class TestTimeZones : ITimeZoneService
    {
        public bool IsValidIanaTimeZoneId(string? id) => !string.IsNullOrWhiteSpace(id) && (id == "UTC" || TimeZoneInfo.TryConvertIanaIdToWindowsId(id, out _));
    public TimeZoneInfo GetTimeZone(string id) => TimeZoneInfo.FindSystemTimeZoneById(id);
        public DateTimeOffset ConvertLocalToUtc(DateTime value, string id) => new(TimeZoneInfo.ConvertTimeToUtc(value, GetTimeZone(id)), TimeSpan.Zero);
        public DateTimeOffset ConvertUtcToZone(DateTimeOffset value, string id) => TimeZoneInfo.ConvertTime(value, GetTimeZone(id));
        public bool IsAmbiguous(DateTime value, string id) => GetTimeZone(id).IsAmbiguousTime(value);
        public bool IsInvalid(DateTime value, string id) => GetTimeZone(id).IsInvalidTime(value);
        public TimeSpan GetUtcOffset(DateTime value, string id) => GetTimeZone(id).GetUtcOffset(value);
    }

    private sealed class FakeCatalog : IVideoCatalog
    {
        public bool Added { get; private set; }
        public VideoAsset? Duplicate { get; set; }
        public Exception? SaveException { get; set; }
        public Task<VideoAsset?> GetAsync(Guid id, CancellationToken cancellationToken) => Task.FromResult<VideoAsset?>(null);
        public Task<IReadOnlyList<VideoAsset>> ListAsync(CancellationToken cancellationToken) => Task.FromResult<IReadOnlyList<VideoAsset>>([]);
        public Task<VideoAsset?> FindSourceVideoBySha256Async(string sha256, CancellationToken cancellationToken) => Task.FromResult(Duplicate);
        public Task AddAsync(Artifact artifact, VideoAsset video, CancellationToken cancellationToken) { Added = true; return Task.CompletedTask; }
        public Task SaveChangesAsync(CancellationToken cancellationToken) => SaveException is null ? Task.CompletedTask : Task.FromException(SaveException);
    }
}
