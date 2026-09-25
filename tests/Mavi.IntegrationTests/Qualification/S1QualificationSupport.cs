using Mavi.Domain.Cameras;
using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.AspNetCore.Hosting;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Npgsql;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// Shared machinery of the S1.4 B3 F4 harnesses (F4 plan §8, §9, §11): the worst-shape request
/// with every object really staged, nearest-rank statistics, the measured host identity (storage
/// class included, §17.2) and the finalizer configuration the host actually runs with.
/// Test code only: nothing here changes what the product does.
/// </summary>
internal static class S1QualificationSupport
{
    public const int WorstTracks = WorkerContractRules.MaximumCompletionTracks;
    public const int ObjectsPerTrack = 5;
    public static readonly string[] Roles = ["representative", "near-view", "early-diverse", "late-diverse"];
    public static readonly JsonSerializerOptions Web = new(JsonSerializerDefaults.Web);
    public static readonly JsonSerializerOptions Indented = new() { WriteIndented = true };

    public static int Setting(string name, int fallback) =>
        int.TryParse(Environment.GetEnvironmentVariable(name), NumberStyles.None, CultureInfo.InvariantCulture, out var value) && value > 0
            ? value
            : fallback;

    // -- the worst shape ----------------------------------------------------------------------

    public sealed record StagedShape(int Tracks, int Observations, int StagedObjects, long StagedBytes);

    /// <summary>
    /// Stages <paramref name="trackCount"/> Tracks for a job's first attempt before it is leased,
    /// so the (real, system-clock) lease cannot expire while 50,000 objects are written: four
    /// crops and one trajectory per Track, each small and distinct. Returns the staged
    /// descriptors to build the request from once the lease is taken.
    /// </summary>
    public static async Task<(IReadOnlyList<StagedTrack> Tracks, StagedShape Shape)> StageAsync(IMediaStore store, Guid jobId, int attemptCount, int trackCount)
    {
        var prefix = $"staging/{jobId:D}/attempt-{attemptCount:0000}";
        var tracks = new List<StagedTrack>(trackCount);
        long bytes = 0;
        for (var index = 0; index < trackCount; index++)
        {
            // The longest canonical Track id (the WorkerContractV3Tests worst document shape).
            var trackId = new string('a', 58) + index.ToString("D6", CultureInfo.InvariantCulture);
            var crops = new List<VisionArtifactDescriptorContract>(Roles.Length);
            foreach (var role in Roles)
            {
                var key = $"{prefix}/evidence/{trackId}-{role}.jpg";
                var stored = await store.WriteAsync(key, new MemoryStream(Encoding.UTF8.GetBytes($"jpeg-{trackId}-{role}")), CancellationToken.None);
                bytes += stored.SizeBytes;
                crops.Add(new VisionArtifactDescriptorContract(key, "image/jpeg", stored.SizeBytes, stored.Sha256));
            }

            var trajectoryKey = $"{prefix}/trajectories/{trackId}.msgpack";
            var trajectory = await store.WriteAsync(trajectoryKey, new MemoryStream(Encoding.UTF8.GetBytes($"trajectory-{trackId}")), CancellationToken.None);
            bytes += trajectory.SizeBytes;
            tracks.Add(new StagedTrack(trackId, crops, new VisionArtifactDescriptorContract(trajectoryKey, "application/msgpack", trajectory.SizeBytes, trajectory.Sha256)));
        }

        return (tracks, new StagedShape(trackCount, trackCount * Roles.Length, trackCount * ObjectsPerTrack, bytes));
    }

    public sealed record StagedTrack(string TrackId, IReadOnlyList<VisionArtifactDescriptorContract> Crops, VisionArtifactDescriptorContract Trajectory);

    /// <summary>The completion body for a lease over staged Tracks, at the longest canonical numbers.</summary>
    public static VisionJobCompleteRequest Request(VisionJobLeaseContract lease, IReadOnlyList<StagedTrack> staged, string schemaVersion)
    {
        const double longDouble = 0.12345678901234568;
        var tracks = staged.Select(track => new VisionTrackResultContract(
            track.TrackId, "vehicle", 0, 1000, 4, longDouble, longDouble, null, track.Trajectory,
            [.. Roles.Select((role, rank) => new VisionTrackObservationContract(
                role, rank, 250 + rank * 250, rank, longDouble, longDouble, longDouble,
                new VisionBoundingBoxContract(longDouble, longDouble, longDouble, longDouble),
                track.Crops[rank]))])).ToArray();
        VisionEvidenceRoleAccountingContract Role(int rank)
        {
            var total = staged.Sum(track => track.Crops[rank].SizeBytes ?? 0);
            return new(staged.Count, staged.Count, 0, total, total);
        }

        return new VisionJobCompleteRequest(
            schemaVersion, lease.JobId, lease.WorkerId, lease.LeaseToken, lease.AttemptCount,
            4, 1250, VisionResultCompletionApiTests.Provenance(), tracks,
            new VisionEvidenceAccountingContract(Role(0), Role(1), Role(2), Role(3)));
    }

    /// <summary>Seeds a video and queues it; returns the video, its run and its (not yet leased) job.</summary>
    public static async Task<(Guid VideoId, Guid JobId, Guid CameraId)> QueueAsync(ApiTestFactory factory, HttpClient client)
    {
        var videoId = await SeedVideoAsync(factory);
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var video = await db.VideoAssets.AsNoTracking().SingleAsync(x => x.Id == videoId);
        var run = await db.ProcessingRuns.AsNoTracking().SingleAsync(x => x.VideoAssetId == videoId);
        var job = await db.VisionJobs.AsNoTracking().SingleAsync(x => x.ProcessingRunId == run.Id);
        return (videoId, job.Id, video.CameraId);
    }

    /// <summary>
    /// A seeded video, as <c>VisionResultCompletionApiTests.SeedVideoAsync</c>, with its own camera
    /// code and source hash so that several jobs can be queued in one schema (the release proof,
    /// the concurrency check).
    /// </summary>
    public static async Task<Guid> SeedVideoAsync(ApiTestFactory factory)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var now = DateTimeOffset.UtcNow;
        var unique = Guid.CreateVersion7();
        var camera = Camera.Create($"CAM-{unique:N}"[..24].ToUpperInvariant(), "Qualification", "UTC", now);
        var source = Artifact.Create(ArtifactType.SourceVideo, $"source/{unique}.mp4", "video/mp4", 100,
            Convert.ToHexStringLower(SHA256.HashData(unique.ToByteArray())), createdAtUtc: now);
        var video = VideoAsset.Create(camera.Id, source.Id, "source.mp4", now, 60_000, 25, 1, 1920, 1080, "h264", TimestampSource.Manual, 1, importedAtUtc: now);
        db.AddRange(camera, source, video);
        await db.SaveChangesAsync();
        return video.Id;
    }

    /// <summary>A fresh schema, migrated by a host with every background loop off.</summary>
    public static async Task ResetDatabaseAsync(string? mediaRoot = null, string? evidenceRoot = null)
    {
        using var reset = new ApiTestFactory { MediaRootOverride = mediaRoot, EvidenceRootOverride = evidenceRoot };
        await reset.ResetAndMigrateAsync();
    }

    public static async Task<long> CountAsync(ApiTestFactory factory, string sql, params object[] parameters)
    {
        await using var connection = new NpgsqlConnection(factory.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        foreach (var parameter in parameters)
            command.Parameters.AddWithValue(parameter);
        return Convert.ToInt64(await command.ExecuteScalarAsync(), CultureInfo.InvariantCulture);
    }

    /// <summary>Tracks, Observations and the published crop/trajectory Artifact rows: zero until publication.</summary>
    public static Task<long> PublishedRowsAsync(ApiTestFactory factory) => CountAsync(
        factory,
        "SELECT (SELECT count(*) FROM tracks) + (SELECT count(*) FROM observations) + " +
        "(SELECT count(*) FROM artifacts WHERE artifact_type IN ('EvidenceCrop', 'TrackTrajectory', 'Thumbnail'))");

    public static int FileCount(string root) =>
        Directory.Exists(root) ? Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Count() : 0;

    // -- statistics ---------------------------------------------------------------------------

    /// <summary>Nearest-rank percentile, the rule the evidence checker recomputes.</summary>
    public static double Percentile(IEnumerable<double> values, double fraction)
    {
        var ordered = values.Order().ToArray();
        if (ordered.Length == 0) throw new InvalidOperationException("percentile_of_empty_series");
        var rank = (int)Math.Ceiling(fraction * ordered.Length);
        return ordered[Math.Clamp(rank, 1, ordered.Length) - 1];
    }

    public static object Stats(IReadOnlyCollection<double> values) => values.Count == 0
        ? new { n = 0 }
        : new { n = values.Count, min = values.Min(), p50 = Percentile(values, 0.50), p95 = Percentile(values, 0.95), max = values.Max() };

    public static double TicksMs(long start, long end) => (end - start) * 1000.0 / Stopwatch.Frequency;

    // -- host identity (§7.2, §17.2) ----------------------------------------------------------

    /// <summary>The qualified CPU variant of this host, or <c>unqualified-*</c>.</summary>
    public static string RuntimeVariant()
    {
        var architecture = System.Runtime.InteropServices.RuntimeInformation.OSArchitecture;
        if (architecture != System.Runtime.InteropServices.Architecture.X64)
            return $"unqualified-{architecture}".ToLowerInvariant();
        if (OperatingSystem.IsWindows()) return "windows-x86_64-cpu";
        if (OperatingSystem.IsLinux()) return "linux-x86_64-cpu";
        return "unqualified-os";
    }

    public static string? CpuModel()
    {
        try
        {
            if (OperatingSystem.IsLinux())
            {
                var line = File.ReadLines("/proc/cpuinfo").FirstOrDefault(x => x.StartsWith("model name", StringComparison.Ordinal));
                return line?.Split(':', 2)[1].Trim();
            }

            if (OperatingSystem.IsWindows())
            {
                using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"HARDWARE\DESCRIPTION\System\CentralProcessor\0");
                return (key?.GetValue("ProcessorNameString") as string)?.Trim();
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }

        return null;
    }

    public static string FilesystemOf(string path)
    {
        var full = Path.GetFullPath(path);
        var drive = DriveInfo.GetDrives()
            .Where(x => full.StartsWith(x.RootDirectory.FullName, OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal))
            .MaxBy(x => x.RootDirectory.FullName.Length);
        return drive is null ? "unknown" : drive.DriveFormat;
    }

    public const string WindowsDiskEvidenceVariable = "MAVI_QUALIFICATION_WINDOWS_DISK_EVIDENCE";
    public const string WindowsDiskIdVariable = "MAVI_QUALIFICATION_WINDOWS_DISK_ID";

    /// <summary>
    /// The storage class of the device under <paramref name="path"/>, and the raw reading it was
    /// derived from, never a typed-in value (F4 plan §17.2, §18.3). A GitHub-hosted runner is
    /// reported as such; a paravirtual device as <c>virtual</c>; anything unclassifiable as
    /// <c>unknown</c>, with the reason.
    /// </summary>
    public static (string Class, string Evidence) StorageClassOf(string path)
    {
        if (string.Equals(Environment.GetEnvironmentVariable("GITHUB_ACTIONS"), "true", StringComparison.Ordinal))
            return ("hosted-runner", $"GITHUB_ACTIONS=true RUNNER_NAME={Environment.GetEnvironmentVariable("RUNNER_NAME")}");
        if (OperatingSystem.IsLinux())
            return LinuxStorageClass(Path.GetFullPath(path), "/proc/self/mountinfo", "/sys");
        if (OperatingSystem.IsWindows())
            return WindowsStorageClass(Environment.GetEnvironmentVariable(WindowsDiskEvidenceVariable), Environment.GetEnvironmentVariable(WindowsDiskIdVariable));
        return ("unknown", "unsupported operating system");
    }

    private static readonly string[] NetworkFilesystems = ["nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "9p", "ceph", "glusterfs"];

    /// <summary>Linux: the mount's major:minor → <c>/sys/dev/block</c> → the whole disk's <c>queue/rotational</c>.</summary>
    internal static (string Class, string Evidence) LinuxStorageClass(string path, string mountInfoPath, string sysRoot)
    {
        string? mountPoint = null, device = null, filesystem = null;
        try
        {
            foreach (var line in File.ReadLines(mountInfoPath))
            {
                // id parent major:minor root mount-point options ... - fstype source super-options
                var halves = line.Split(" - ", 2);
                var fields = halves[0].Split(' ');
                if (fields.Length < 5 || halves.Length < 2) continue;
                var point = fields[4].Replace("\\040", " ", StringComparison.Ordinal);
                var inside = path == point || path.StartsWith(point.TrimEnd('/') + "/", StringComparison.Ordinal) || point == "/";
                if (inside && (mountPoint is null || point.Length > mountPoint.Length))
                {
                    mountPoint = point;
                    device = fields[2];
                    filesystem = halves[1].Split(' ')[0];
                }
            }
        }
        catch (IOException exception)
        {
            return ("unknown", $"{mountInfoPath} unreadable: {exception.GetType().Name}");
        }

        if (mountPoint is null || device is null)
            return ("unknown", $"no mount found for {path}");
        if (NetworkFilesystems.Contains(filesystem, StringComparer.Ordinal))
            return ("network", $"mount {mountPoint} fstype={filesystem}");
        var devLink = Path.Combine(sysRoot, "dev", "block", device);
        string? resolved;
        try
        {
            resolved = new DirectoryInfo(devLink).ResolveLinkTarget(returnFinalTarget: true)?.FullName;
        }
        catch (IOException)
        {
            resolved = null;
        }

        if (resolved is null)
            return ("unknown", $"mount {mountPoint} fstype={filesystem} device {device}: {devLink} is not a block device link");
        var disk = File.Exists(Path.Combine(resolved, "queue", "rotational")) ? resolved : Path.GetDirectoryName(resolved)!;
        var name = Path.GetFileName(disk);
        var rotationalPath = Path.Combine(disk, "queue", "rotational");
        string? rotational = null;
        try
        {
            rotational = File.ReadAllText(rotationalPath).Trim();
        }
        catch (IOException)
        {
        }

        var evidence = $"mount {mountPoint} fstype={filesystem} device {device} -> {name}; {rotationalPath}={rotational ?? "unreadable"}";
        if (name.StartsWith("nvme", StringComparison.Ordinal)) return ("nvme", evidence);
        if (name.StartsWith("vd", StringComparison.Ordinal) || name.StartsWith("xvd", StringComparison.Ordinal)) return ("virtual", evidence);
        return rotational switch
        {
            "0" => ("ssd", evidence),
            "1" => ("hdd", evidence),
            _ => ("unknown", evidence),
        };
    }

    /// <summary>
    /// Windows: the operator retains <c>Get-PhysicalDisk | Format-List DeviceId,MediaType,BusType</c>
    /// output and names the disk behind the evidence volume; the class is read from that output
    /// and the evidence carries its SHA-256. No WMI dependency is added (F4 plan §18.3).
    /// </summary>
    internal static (string Class, string Evidence) WindowsStorageClass(string? evidenceFile, string? deviceId)
    {
        if (string.IsNullOrWhiteSpace(evidenceFile) || !File.Exists(evidenceFile) || string.IsNullOrWhiteSpace(deviceId))
            return ("unknown", $"set {WindowsDiskEvidenceVariable} to retained Get-PhysicalDisk output and {WindowsDiskIdVariable} to the evidence volume's disk");
        var text = File.ReadAllText(evidenceFile);
        var digest = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
        foreach (var block in text.Replace("\r\n", "\n", StringComparison.Ordinal).Split("\n\n", StringSplitOptions.RemoveEmptyEntries))
        {
            var fields = block.Split('\n')
                .Select(line => line.Split(':', 2))
                .Where(parts => parts.Length == 2)
                .ToDictionary(parts => parts[0].Trim(), parts => parts[1].Trim(), StringComparer.OrdinalIgnoreCase);
            if (!fields.TryGetValue("DeviceId", out var id) || !string.Equals(id, deviceId.Trim(), StringComparison.Ordinal)) continue;
            fields.TryGetValue("MediaType", out var media);
            fields.TryGetValue("BusType", out var bus);
            var evidence = $"Get-PhysicalDisk sha256:{digest} DeviceId={id} MediaType={media} BusType={bus}";
            if (string.Equals(bus, "NVMe", StringComparison.OrdinalIgnoreCase)) return ("nvme", evidence);
            return media?.ToUpperInvariant() switch
            {
                "SSD" => ("ssd", evidence),
                "HDD" => ("hdd", evidence),
                _ => ("unknown", evidence),
            };
        }

        return ("unknown", $"Get-PhysicalDisk sha256:{digest} has no DeviceId {deviceId}");
    }

    /// <summary>The host block every B3 output carries, bound by the checker to the record's host.</summary>
    public static Dictionary<string, object?> Host(string evidenceRoot)
    {
        var (storageClass, evidence) = StorageClassOf(evidenceRoot);
        return new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["cpuModel"] = CpuModel(),
            ["logicalCores"] = Environment.ProcessorCount,
            ["acceptedEvidenceFilesystem"] = FilesystemOf(evidenceRoot),
            ["storageClass"] = storageClass,
            ["storageClassEvidence"] = evidence,
        };
    }

    // -- configuration (§9.1, §10) -------------------------------------------------------------

    public static readonly string[] FrozenKeys =
    [
        "MaxConcurrentFinalizations", "PollIntervalSeconds", "ClaimSeconds", "ClaimExtensionSeconds",
        "MaximumFinalizationAttempts", "MaximumFinalizationDurationSeconds", "SealingBatchSize", "PayloadCleanupGraceSeconds",
    ];

    /// <summary>The options the host is really running with, as the checker compares them.</summary>
    public static Dictionary<string, object> EffectiveConfiguration(IServiceProvider services)
    {
        var options = services.GetRequiredService<IOptions<VisionFinalizationOptions>>().Value;
        return new Dictionary<string, object>(StringComparer.Ordinal)
        {
            ["Enabled"] = options.Enabled,
            ["MaxConcurrentFinalizations"] = options.MaxConcurrentFinalizations,
            ["PollIntervalSeconds"] = options.PollIntervalSeconds,
            ["ClaimSeconds"] = options.ClaimSeconds,
            ["ClaimExtensionSeconds"] = options.ClaimExtensionSeconds,
            ["MaximumFinalizationAttempts"] = options.MaximumFinalizationAttempts,
            ["MaximumFinalizationDurationSeconds"] = options.MaximumFinalizationDurationSeconds,
            ["SealingBatchSize"] = options.SealingBatchSize,
            ["PayloadCleanupGraceSeconds"] = options.PayloadCleanupGraceSeconds,
        };
    }

    /// <summary>The <c>VisionFinalization</c> section of the appsettings.json the host loaded.</summary>
    public static JsonElement CommittedConfiguration(IServiceProvider services)
    {
        var root = services.GetRequiredService<IWebHostEnvironment>().ContentRootPath;
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "appsettings.json")));
        return document.RootElement.GetProperty("VisionFinalization").Clone();
    }

    /// <summary>"appsettings.json" when every frozen value the host runs with is the committed one.</summary>
    public static string OptionsSource(IServiceProvider services)
    {
        var effective = EffectiveConfiguration(services);
        var committed = CommittedConfiguration(services);
        return FrozenKeys.All(key => committed.TryGetProperty(key, out var value) && value.GetInt32() == (int)effective[key])
            ? "appsettings.json"
            : "overridden";
    }

    /// <summary>The Npgsql command timeout the runtime DbContext uses (the connection string's, else Npgsql's default).</summary>
    public static int EffectiveCommandTimeoutSeconds(IServiceProvider services)
    {
        using var scope = services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        return db.Database.GetCommandTimeout() ?? new NpgsqlConnectionStringBuilder(db.Database.GetConnectionString()).CommandTimeout;
    }

    /// <summary>Reasons shared by every heavy B3 harness why a run cannot be evidence.</summary>
    public static List<string> CommonNonAuthoritativeReasons(IReadOnlyDictionary<string, string> environment, string storageClass)
    {
        var reasons = new List<string>();
        if (!QualificationGate.IsQualificationGrade(environment)) reasons.Add("not a qualification-grade PostgreSQL");
        if (RuntimeVariant().StartsWith("unqualified", StringComparison.Ordinal)) reasons.Add($"host is {RuntimeVariant()}");
        if (storageClass == "hosted-runner") reasons.Add("a hosted runner cannot qualify B3 timing");
        foreach (var key in new[] { QualificationGate.GitWorkingTreeCleanKey, QualificationGate.GitCommitObjectPresentKey })
        {
            if (!environment.TryGetValue(key, out var value) || value != "true")
                reasons.Add($"{key} is not true");
        }

        return reasons;
    }

    public static string WriteOutput(string name, object output)
    {
        var path = Path.Combine(QualificationGate.OutputDirectory, name);
        File.WriteAllText(path, JsonSerializer.Serialize(output, Indented));
        return path;
    }
}

/// <summary>
/// A fact that runs only when the heavy qualification pass is asked for. Otherwise it is
/// reported as <b>skipped</b>, never as a pass. A malformed <c>MAVI_QUALIFICATION</c> value
/// throws, exactly as <see cref="QualificationGate.Enabled"/> does.
/// </summary>
public sealed class S1QualificationFactAttribute : FactAttribute
{
    public S1QualificationFactAttribute()
    {
        if (!QualificationGate.Enabled)
            Skip = $"heavy S1.4 qualification harness; set {QualificationGate.EnabledVariable}=1 to run it";
    }
}
