using System.Text.Json;
using System.Text.Json.Serialization;

namespace Mavi.Contracts.Worker.Attributes;

// The attribute control plane (S2b plan §9). Every request body is the reusable envelope of
// ADR-013 §9 as amended: schemaVersion, analysisId, workerId, attemptCount, provenance and a
// typed payload. The lease capability is never a member of any of these records.

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisualAttributeLeaseRequest(
    string? SchemaVersion,
    string? WorkerId,
    string? IdentityFingerprint);

public sealed record VisualAttributeCapabilityIdentityContract(string CapabilityId, string ModelPackId);

/// <summary>The analysis identity of ADR-013 §11 without the run, and its fingerprint (§16).</summary>
public sealed record VisualAttributeIdentityContract(
    string Fingerprint,
    string AttributeSchemaId,
    string AttributeSchemaVersion,
    string AttributeSchemaSha256,
    string PipelineId,
    string PipelineVersion,
    string AggregationPolicyId,
    string AggregationPolicyVersion,
    string AggregationPolicySha256,
    IReadOnlyList<VisualAttributeCapabilityIdentityContract> Capabilities,
    string ParametersSha256);

/// <summary>One accepted EvidenceCrop the leased attempt may read, with its recorded facts.</summary>
public sealed record VisualAttributeLeaseObservationContract(
    Guid ObservationId,
    string Role,
    int EvidenceRank,
    long SizeBytes,
    string Sha256);

public sealed record VisualAttributeLeaseTrackContract(
    Guid TrackId,
    string ObjectClass,
    IReadOnlyList<VisualAttributeLeaseObservationContract> Observations);

/// <summary>
/// The lease response. The capability itself is in the <c>X-Mavi-Lease-Capability</c>
/// response header, never here.
/// </summary>
public sealed record VisualAttributeLeaseContract(
    string SchemaVersion,
    Guid AnalysisId,
    Guid ProcessingRunId,
    string WorkerId,
    int AttemptCount,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset LeaseExpiresAtUtc,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset DeadlineAtUtc,
    VisualAttributeIdentityContract Identity,
    IReadOnlyList<VisualAttributeLeaseTrackContract> Tracks);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisualAttributeHeartbeatRequest(
    string? SchemaVersion,
    Guid? AnalysisId,
    string? WorkerId,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? AttemptCount);

public sealed record VisualAttributeHeartbeatResponse(
    string SchemaVersion,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset LeaseExpiresAtUtc);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisualAttributeFailRequest(
    string? SchemaVersion,
    Guid? AnalysisId,
    string? WorkerId,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? AttemptCount,
    string? FailureCode,
    string? FailureMessage);

/// <summary><c>requeued</c> (a retryable failure with attempts and time left) or <c>failed</c>.</summary>
public sealed record VisualAttributeFailResponse(string SchemaVersion, string Outcome);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisualAttributeCapabilityProvenanceContract(
    string? CapabilityId,
    string? ModelPackId,
    string? ModelManifestSha256,
    string? QualificationId,
    string? QualificationSha256,
    string? VerificationStatus);

/// <summary>
/// Producer provenance (ADR-014 §8). Not identity: it enters the completion digest, so a replay
/// from another device or build is a conflict, but it never creates a new analysis.
/// </summary>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisualAttributeProvenanceContract(
    string? ProvenanceContract,
    string? RoleId,
    [property: JsonConverter(typeof(BoundedCapabilityProvenanceListJsonConverter))]
    IReadOnlyList<VisualAttributeCapabilityProvenanceContract>? Capabilities,
    string? RuntimePackFamilyId,
    string? RuntimeProfileSha256,
    string? RuntimeVariant,
    string? RuntimePackId,
    string? RuntimePackSource,
    string? ComponentBindingSha256,
    string? PipelineProfileSha256,
    string? ConfiguredDevicePolicy,
    string? ActualDevice,
    string? MaviBuild,
    string? MaviCommit);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisualAttributeArtifactDescriptorContract(
    string? MediaType,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? SizeBytes,
    string? Sha256);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisualAttributeRowContract(
    string? AttributeType,
    string? Outcome,
    string? Value,
    double? Confidence,
    Guid? SupportingObservationId);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisualAttributeTrackResultContract(
    Guid? TrackId,
    string? Outcome,
    string? Reason,
    [property: JsonConverter(typeof(BoundedAttributeRowListJsonConverter))]
    IReadOnlyList<VisualAttributeRowContract>? Attributes);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisualAttributeCompletionPayloadContract(
    VisualAttributeArtifactDescriptorContract? PredictionArtifact,
    [property: JsonConverter(typeof(BoundedAttributeTrackListJsonConverter))]
    IReadOnlyList<VisualAttributeTrackResultContract>? Tracks);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisualAttributeCompleteRequest(
    string? SchemaVersion,
    Guid? AnalysisId,
    string? WorkerId,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? AttemptCount,
    VisualAttributeProvenanceContract? Provenance,
    VisualAttributeCompletionPayloadContract? Payload);

/// <summary><c>completed</c> (the run's default) or <c>superseded</c> (an obsolete identity, published as history).</summary>
public sealed record VisualAttributeCompleteResponse(
    string SchemaVersion,
    Guid AnalysisId,
    Guid ProcessingRunId,
    string Status,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset CompletedAtUtc,
    int TracksAnalysed,
    int TracksUnavailable);

// --- Bounded collections: a hostile body cannot allocate past the contract bound. ---------

public abstract class BoundedListJsonConverter<T> : JsonConverter<IReadOnlyList<T>?>
    where T : class
{
    protected abstract int Maximum { get; }
    protected abstract string Name { get; }

    public override bool HandleNull => true;

    public override IReadOnlyList<T>? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.Null) return null;
        if (reader.TokenType != JsonTokenType.StartArray)
            throw new JsonException($"Expected a {Name} array.");

        var items = new List<T>();
        while (reader.Read())
        {
            if (reader.TokenType == JsonTokenType.EndArray)
                return items;
            if (items.Count >= Maximum)
                throw new JsonException($"The {Name} limit is exceeded.");
            var item = JsonSerializer.Deserialize<T>(ref reader, options)
                ?? throw new JsonException($"A {Name} array cannot contain null.");
            items.Add(item);
        }

        throw new JsonException($"Incomplete {Name} array.");
    }

    public override void Write(Utf8JsonWriter writer, IReadOnlyList<T>? value, JsonSerializerOptions options)
    {
        ArgumentNullException.ThrowIfNull(writer);
        if (value is null)
        {
            writer.WriteNullValue();
            return;
        }
        if (value.Count > Maximum)
            throw new JsonException($"The {Name} limit is exceeded.");
        writer.WriteStartArray();
        foreach (var item in value)
            JsonSerializer.Serialize(writer, item, options);
        writer.WriteEndArray();
    }
}

public sealed class BoundedAttributeTrackListJsonConverter : BoundedListJsonConverter<VisualAttributeTrackResultContract>
{
    protected override int Maximum => VisualAttributeContractRules.MaximumAnalysisTracks;
    protected override string Name => "track";
}

public sealed class BoundedAttributeRowListJsonConverter : BoundedListJsonConverter<VisualAttributeRowContract>
{
    protected override int Maximum => VisualAttributeContractRules.MaximumAttributeTypesPerObjectClass;
    protected override string Name => "attribute";
}

public sealed class BoundedCapabilityProvenanceListJsonConverter : BoundedListJsonConverter<VisualAttributeCapabilityProvenanceContract>
{
    // One entry per attribute capability id.
    protected override int Maximum => 2;
    protected override string Name => "capability provenance";
}
