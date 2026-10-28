using System.Text.Json;

namespace Mavi.Application.Deployment;

/// <summary>
/// The deployment profile an installation declares (ADR-008, ADR-020) and where its
/// release metadata and device-resolution record live. Written by the installer into the
/// machine configuration; nothing here can hide the disclosure of a profile that requires
/// one.
/// </summary>
public sealed class DeploymentOptions
{
    public const string SectionName = "Deployment";

    /// <summary>The declared profile; empty for an unprofiled host (Development, tests).</summary>
    public string? Profile { get; set; }

    /// <summary>Release metadata written by the installer (<c>mavi-poc-release-metadata-v1</c>).</summary>
    public string? ReleaseMetadataPath { get; set; }

    /// <summary>The launcher's device-resolution record (<c>mavi-device-resolution-v1</c>).</summary>
    public string? DeviceResolutionPath { get; set; }
}

public static class DeploymentProfiles
{
    /// <summary>ADR-020: one Windows host, Development evidence, never Production-qualified.</summary>
    public const string PocSingleHost = "poc-single-host";

    /// <summary>No profile declared. Not a profile an installer writes.</summary>
    public const string Unspecified = "unspecified";
}

/// <summary>
/// The fixed disclosure of the PoC profile (ADR-020 §3). These are constants of the code:
/// the release metadata is checked against them and the response is built from them, so
/// no configuration value or metadata edit can change or remove them.
/// </summary>
public static class PocDisclosure
{
    public const bool ProductionQualified = false;
    public const string EvidenceClass = "Development";
    public const string Statement =
        "Proof-of-concept installation (profile poc-single-host). Not Production-qualified. Evidence class: Development.";
    public const string ReleaseMetadataSchema = "mavi-poc-release-metadata-v1";
    public const string DeviceResolutionSchema = "mavi-device-resolution-v1";
}

public sealed record DeploymentDevice(
    string RequestedPolicy,
    string ResolvedPolicy,
    string Reason,
    string? RuntimePackId,
    string? RuntimeVariant,
    string? ResolvedAtUtc,
    bool VerifyOnly);

public sealed record DeploymentPack(
    string Kind,
    string Role,
    string? CapabilityId,
    string PackId,
    string? Variant,
    string VerificationStatus,
    string? Note);

public sealed record DeploymentDisclosure(
    string SchemaVersion,
    string Profile,
    bool ProductionQualified,
    string? EvidenceClass,
    string? Statement,
    string MetadataStatus,
    string? ApplicationRevision,
    string? InstalledAtUtc,
    string DeviceStatus,
    DeploymentDevice? Device,
    IReadOnlyList<DeploymentPack> Packs);

public sealed class DeploymentDisclosureException(string message) : Exception(message);

public static class DeploymentDisclosureReader
{
    public const string SchemaVersion = "mavi-deployment-disclosure-v1";

    /// <summary>
    /// Fails closed at start-up: an unknown profile, or PoC release metadata that is missing
    /// or claims anything other than the fixed disclosure, stops the host.
    /// </summary>
    public static void Verify(DeploymentOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var profile = NormalizeProfile(options.Profile);
        if (profile != DeploymentProfiles.PocSingleHost)
            return;
        if (string.IsNullOrWhiteSpace(options.ReleaseMetadataPath))
            throw new DeploymentDisclosureException(
                $"{DeploymentOptions.SectionName}:ReleaseMetadataPath is required under profile {DeploymentProfiles.PocSingleHost}.");
        ReadReleaseMetadata(options.ReleaseMetadataPath);
    }

    /// <summary>
    /// The disclosure as served. Under the PoC profile the disclosure fields are the
    /// constants above whatever the files say; an unreadable file is reported as
    /// unavailable, never as an absence of the disclosure.
    /// </summary>
    public static DeploymentDisclosure Read(DeploymentOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var profile = NormalizeProfile(options.Profile);
        var (deviceStatus, device) = ReadDevice(options.DeviceResolutionPath);
        if (profile != DeploymentProfiles.PocSingleHost)
        {
            return new DeploymentDisclosure(SchemaVersion, profile, ProductionQualified: false, null, null,
                "not-configured", null, null, deviceStatus, device, []);
        }

        string metadataStatus;
        ReleaseMetadata? metadata = null;
        try
        {
            metadata = string.IsNullOrWhiteSpace(options.ReleaseMetadataPath)
                ? null
                : ReadReleaseMetadata(options.ReleaseMetadataPath);
            metadataStatus = metadata is null ? "unavailable" : "verified";
        }
        catch (DeploymentDisclosureException)
        {
            metadataStatus = "unavailable";
        }

        return new DeploymentDisclosure(
            SchemaVersion,
            DeploymentProfiles.PocSingleHost,
            PocDisclosure.ProductionQualified,
            PocDisclosure.EvidenceClass,
            PocDisclosure.Statement,
            metadataStatus,
            metadata?.ApplicationRevision,
            metadata?.InstalledAtUtc,
            deviceStatus,
            device,
            metadata?.Packs ?? []);
    }

    private static string NormalizeProfile(string? configured)
    {
        if (string.IsNullOrWhiteSpace(configured))
            return DeploymentProfiles.Unspecified;
        var value = configured.Trim();
        if (string.Equals(value, DeploymentProfiles.PocSingleHost, StringComparison.Ordinal))
            return DeploymentProfiles.PocSingleHost;
        // P1/P2/P3 are declared by their qualified release record, not by this key (ADR-008);
        // any other value is a configuration error, never a silent "unprofiled".
        throw new DeploymentDisclosureException(
            $"{DeploymentOptions.SectionName}:Profile '{value}' is not a profile this host can declare; the only accepted value is {DeploymentProfiles.PocSingleHost}.");
    }

    private sealed record ReleaseMetadata(string? ApplicationRevision, string? InstalledAtUtc, IReadOnlyList<DeploymentPack> Packs);

    private static ReleaseMetadata ReadReleaseMetadata(string path)
    {
        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(File.ReadAllBytes(path));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or JsonException)
        {
            throw new DeploymentDisclosureException($"PoC release metadata '{path}' is unreadable: {exception.Message}");
        }

        using (document)
        {
            var root = document.RootElement;
            Require(root.ValueKind == JsonValueKind.Object, path, "is not a JSON object");
            Require(Text(root, "schemaVersion") == PocDisclosure.ReleaseMetadataSchema, path, $"schemaVersion is not {PocDisclosure.ReleaseMetadataSchema}");
            Require(Text(root, "profile") == DeploymentProfiles.PocSingleHost, path, $"profile is not {DeploymentProfiles.PocSingleHost}");
            Require(root.TryGetProperty("productionQualified", out var qualified) && qualified.ValueKind == JsonValueKind.False,
                path, "productionQualified must be false");
            Require(Text(root, "evidenceClass") == PocDisclosure.EvidenceClass, path, $"evidenceClass must be {PocDisclosure.EvidenceClass}");

            string? revision = null;
            if (root.TryGetProperty("application", out var application) && application.ValueKind == JsonValueKind.Object)
                revision = Text(application, "revision");

            var packs = new List<DeploymentPack>();
            if (root.TryGetProperty("packs", out var packArray))
            {
                Require(packArray.ValueKind == JsonValueKind.Array, path, "packs is not an array");
                foreach (var pack in packArray.EnumerateArray())
                {
                    var kind = Text(pack, "kind");
                    var role = Text(pack, "role");
                    var packId = Text(pack, "packId");
                    var status = Text(pack, "verificationStatus");
                    Require(!string.IsNullOrWhiteSpace(kind) && !string.IsNullOrWhiteSpace(role) &&
                            !string.IsNullOrWhiteSpace(packId) && !string.IsNullOrWhiteSpace(status),
                        path, "every pack needs kind, role, packId and verificationStatus");
                    packs.Add(new DeploymentPack(kind!, role!, Text(pack, "capabilityId"), packId!,
                        Text(pack, "variant"), status!, Text(pack, "note")));
                }
            }

            return new ReleaseMetadata(revision, Text(root, "installedAtUtc"), packs);
        }
    }

    private static (string Status, DeploymentDevice? Device) ReadDevice(string? path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            return ("not-reported", null);
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllBytes(path));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object || Text(root, "schemaVersion") != PocDisclosure.DeviceResolutionSchema)
                return ("unavailable", null);
            var requested = Text(root, "requestedDevicePolicy");
            var resolved = Text(root, "resolvedDevicePolicy");
            var reason = Text(root, "deviceResolutionReason");
            if (string.IsNullOrWhiteSpace(requested) || string.IsNullOrWhiteSpace(resolved) || string.IsNullOrWhiteSpace(reason))
                return ("unavailable", null);
            var verifyOnly = root.TryGetProperty("verifyOnly", out var verify) && verify.ValueKind == JsonValueKind.True;
            return ("reported", new DeploymentDevice(requested!, resolved!, reason!, Text(root, "runtimePackId"),
                Text(root, "runtimeVariant"), Text(root, "resolvedAtUtc"), verifyOnly));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or JsonException)
        {
            return ("unavailable", null);
        }
    }

    private static string? Text(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static void Require(bool condition, string path, string reason)
    {
        if (!condition)
            throw new DeploymentDisclosureException($"PoC release metadata '{path}' is invalid: {reason}.");
    }
}
