using System.Text.Json.Serialization;

namespace Mavi.Contracts.Api.Plates;

/// <summary>
/// <c>POST /api/plates/reanalysis</c> (Stage 4 plan §2.2): exactly one of <see cref="ProcessingRunIds"/>
/// or a camera window (<see cref="CameraId"/>, <see cref="FromUtc"/>, <see cref="ToUtc"/>). Queues the
/// preferred plate identity for those historical runs; bounded and idempotent.
/// </summary>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateReanalysisRequestContract(
    IReadOnlyList<Guid>? ProcessingRunIds,
    Guid? CameraId,
    DateTimeOffset? FromUtc,
    DateTimeOffset? ToUtc);

public sealed record PlateReanalysisResponseContract(
    string IdentityFingerprint,
    int RunsMatched,
    int Queued,
    int AlreadyQueued,
    int NotEligible,
    IReadOnlyList<Guid> SelectedRunIds);
