using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Contracts.Worker.Attributes;

namespace Mavi.IntegrationTests;

internal sealed record BuiltCompletion(VisualAttributeCompleteRequest Request, byte[] Predictions, string Sha256);

/// <summary>
/// A valid completion and its prediction artefact for a lease under the fixture schema,
/// shaped exactly as the worker produces them: one decision per applicable attribute, the
/// artefact's decisions equal to the completion's rows.
/// </summary>
internal static class AttributeCompletionBuilder
{
    public static readonly IReadOnlyDictionary<string, string[]> TypesByClass = new Dictionary<string, string[]>
    {
        ["person"] = ["fixture-person-lower", "fixture-person-upper"],
        ["vehicle"] = ["fixture-vehicle-body"],
    };

    private static readonly string[] Values = ["dark", "light", "mid"];

    /// <param name="unavailable">A Track to report Unavailable, and why.</param>
    /// <param name="unknown">Attribute types to report Unknown on every analysed Track.</param>
    /// <param name="value">The Observed value (a different value is a different completion).</param>
    public static BuiltCompletion Build(
        LeasedUnit unit,
        Func<Guid, string?>? unavailable = null,
        IReadOnlySet<string>? unknown = null,
        string value = "dark",
        string actualDevice = "cpu",
        long? declaredSizeBytes = null,
        string? declaredSha256 = null)
    {
        var lease = unit.Lease;
        var tracks = new List<VisualAttributeTrackResultContract>();
        var predicted = new JsonArray();
        foreach (var track in lease.Tracks)
        {
            var types = TypesByClass[track.ObjectClass];
            var reason = track.Observations.Count == 0 ? "no_accepted_evidence" : unavailable?.Invoke(track.TrackId);
            var observations = new JsonArray();
            var decisions = new JsonArray();
            if (reason is not null)
            {
                foreach (var observation in track.Observations)
                    observations.Add(new JsonObject
                    {
                        ["observationId"] = observation.ObservationId, ["reason"] = reason, ["scores"] = null, ["status"] = "unavailable",
                    });
                tracks.Add(new VisualAttributeTrackResultContract(track.TrackId, VisualAttributeContractRules.OutcomeUnavailable, reason, []));
            }
            else
            {
                var supporting = track.Observations[0].ObservationId;
                foreach (var observation in track.Observations)
                {
                    var scores = new JsonObject();
                    foreach (var type in types)
                        scores[type] = new JsonObject { ["dark"] = value == "dark" ? 0.7 : 0.1, ["light"] = value == "light" ? 0.7 : 0.1, ["mid"] = value == "mid" ? 0.7 : 0.2 };
                    observations.Add(new JsonObject
                    {
                        ["observationId"] = observation.ObservationId, ["reason"] = null, ["scores"] = scores, ["status"] = "scored",
                    });
                }

                var rows = new List<VisualAttributeRowContract>();
                foreach (var type in types)
                {
                    var isUnknown = unknown?.Contains(type) ?? false;
                    rows.Add(isUnknown
                        ? new VisualAttributeRowContract(type, VisualAttributeContractRules.OutcomeUnknown, null, null, null)
                        : new VisualAttributeRowContract(type, VisualAttributeContractRules.OutcomeObserved, value, 0.7, supporting));
                    decisions.Add(new JsonObject
                    {
                        ["attributeType"] = type,
                        ["confidence"] = isUnknown ? null : 0.7,
                        ["outcome"] = isUnknown ? VisualAttributeContractRules.OutcomeUnknown : VisualAttributeContractRules.OutcomeObserved,
                        ["supportingObservationId"] = isUnknown ? null : supporting,
                        ["value"] = isUnknown ? null : value,
                    });
                }

                tracks.Add(new VisualAttributeTrackResultContract(track.TrackId, VisualAttributeContractRules.OutcomeAnalysed, null, rows));
            }

            predicted.Add(new JsonObject
            {
                ["decisions"] = decisions,
                ["observations"] = observations,
                ["outcome"] = reason is null ? VisualAttributeContractRules.OutcomeAnalysed : VisualAttributeContractRules.OutcomeUnavailable,
                ["reason"] = reason,
                ["trackId"] = track.TrackId,
            });
        }

        var identity = lease.Identity;
        var document = new JsonObject
        {
            ["aggregationPolicy"] = new JsonObject
            {
                ["id"] = identity.AggregationPolicyId, ["sha256"] = identity.AggregationPolicySha256, ["version"] = identity.AggregationPolicyVersion,
            },
            ["analysisId"] = lease.AnalysisId,
            ["attributeSchema"] = new JsonObject
            {
                ["id"] = identity.AttributeSchemaId, ["sha256"] = identity.AttributeSchemaSha256, ["version"] = identity.AttributeSchemaVersion,
            },
            ["identityFingerprint"] = identity.Fingerprint,
            ["schemaVersion"] = VisualAttributeContractRules.PredictionsSchemaVersion,
            ["tracks"] = predicted,
        };
        var bytes = Encoding.UTF8.GetBytes(document.ToJsonString() + "\n");
        var sha256 = Convert.ToHexStringLower(SHA256.HashData(bytes));

        var request = new VisualAttributeCompleteRequest(
            VisualAttributeContractRules.SchemaVersion,
            lease.AnalysisId,
            unit.WorkerId,
            lease.AttemptCount,
            Provenance(identity, actualDevice),
            new VisualAttributeCompletionPayloadContract(
                new VisualAttributeArtifactDescriptorContract(VisualAttributeContractRules.PredictionsMediaType, declaredSizeBytes ?? bytes.Length,
                    declaredSha256 ?? sha256),
                tracks));
        return new BuiltCompletion(request, bytes, sha256);
    }

    public static VisualAttributeProvenanceContract Provenance(VisualAttributeIdentityContract identity, string actualDevice = "cpu") => new(
        VisualAttributeContractRules.ProvenanceContract,
        "attributes",
        identity.Capabilities.Select(capability => new VisualAttributeCapabilityProvenanceContract(
            capability.CapabilityId, capability.ModelPackId, new string('e', 64), capability.CapabilityId + "-fixture", new string('f', 64),
            "unverified")).ToList(),
        "mmdetection-phase1-v1",
        new string('1', 64),
        "linux-x86_64-cpu",
        null,
        "unpacked-environment",
        new string('2', 64),
        new string('3', 64),
        "cpu",
        actualDevice,
        null,
        null);

    public static string Serialize(VisualAttributeCompleteRequest request) => JsonSerializer.Serialize(request, JsonSerializerOptions.Web);
}
