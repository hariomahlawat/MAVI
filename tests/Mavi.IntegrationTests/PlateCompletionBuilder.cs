using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Plates;
using Mavi.Contracts.Worker.Plates;

namespace Mavi.IntegrationTests;

/// <summary>One detector proposal of a crop, with the readings the recogniser returns if it is selected.</summary>
internal sealed record PlateProposal(int X, int Y, int Width, int Height, double Score, (string RawText, double Confidence)[] Readings);

/// <summary>What the (simulated) worker observed on one leased crop.</summary>
internal sealed record PlateCropSpec(string Status, string? Reason, int Width, int Height, PlateProposal[] Proposals)
{
    public static PlateCropSpec Scored(params PlateProposal[] proposals) => new("scored", null, 200, 150, proposals);
    public static PlateCropSpec Unavailable(string reason) => new("unavailable", reason, 0, 0, []);
    public static PlateCropSpec Abstained(string reason) => new("abstained", reason, 0, 0, []);
    public static PlateCropSpec Excluded() => new("excluded", null, 0, 0, []);
}

internal sealed record BuiltPlateCompletion(byte[] Predictions, PlateCompleteRequest Request);

/// <summary>
/// Builds what an honest plates worker would send for a lease under the fixture profile (two proposals,
/// one plate, three readings; floors 0.25 and 0.5): the <c>PlatePredictions</c> artefact and the
/// completion, by the same rules as <c>mavi_vision.plates.pipeline</c>. Tests mutate either to probe a
/// single platform rule.
/// </summary>
internal static class PlateCompletionBuilder
{
    public const double DetectorFloor = 0.25;
    public const double OcrFloor = 0.5;
    public const int MaxPlates = 1;

    public static readonly PlateProposal DefaultProposal = new(40, 100, 60, 15, 0.9, [("KA 01 AB 1234", 0.8), ("KA01AB1284", 0.6)]);

    private static readonly Dictionary<string, string> TrackReason = new(StringComparer.Ordinal)
    {
        ["evidence_integrity_failed"] = "evidence_integrity_failed",
        ["evidence_missing"] = "evidence_missing",
        ["decode_failed"] = "evidence_decode_failed",
        ["detector_error"] = "plate_inference_failed",
        ["ocr_error"] = "plate_inference_failed",
        ["ocr_output_invalid"] = "plate_inference_failed",
    };

    public static BuiltPlateCompletion Build(PlateLeaseContract lease, Func<int, int, PlateCropSpec>? crop = null, string workerId = "plates-01",
        string actualDevice = "cpu")
    {
        crop ??= (_, _) => PlateCropSpec.Scored(DefaultProposal);
        var artefactTracks = new JsonArray();
        var completionTracks = new JsonArray();
        for (var trackIndex = 0; trackIndex < lease.Tracks.Count; trackIndex++)
        {
            var track = lease.Tracks[trackIndex];
            var crops = new JsonArray();
            var observations = new JsonArray();
            var reads = new List<(string Text, double Confidence, int Rank, Guid Source)>();
            var scored = 0;
            var caused = new HashSet<string>(StringComparer.Ordinal);
            for (var cropIndex = 0; cropIndex < track.Observations.Count; cropIndex++)
            {
                var leased = track.Observations[cropIndex];
                var spec = crop(trackIndex, cropIndex);
                if (spec.Reason is { } reason) caused.Add(TrackReason[reason]);
                var detections = new JsonArray();
                var withDimensions = spec.Status == "scored";
                if (spec.Status == "scored")
                {
                    scored++;
                    var ordered = spec.Proposals.OrderByDescending(item => item.Score).ThenBy(item => item.X).ThenBy(item => item.Y).ToList();
                    var selected = 0;
                    foreach (var proposal in ordered)
                    {
                        JsonNode? plate = null;
                        if (selected < MaxPlates && proposal.Score >= DetectorFloor && selected == ordered.IndexOf(proposal))
                        {
                            var readings = proposal.Readings.OrderByDescending(item => item.Confidence).ThenBy(item => item.RawText, StringComparer.Ordinal).ToList();
                            var read = readings.Count > 0 && readings[0].Confidence >= OcrFloor;
                            plate = new JsonObject
                            {
                                ["outcome"] = read ? "read" : "unreadable",
                                ["plateIndex"] = selected,
                                ["readings"] = new JsonArray(readings.Select((item, rank) => (JsonNode)Reading(rank, item.RawText, item.Confidence)).ToArray()),
                            };
                            var kept = read ? readings.Where(item => item.Confidence >= OcrFloor).ToList() : [];
                            observations.Add(new JsonObject
                            {
                                ["sourceObservationId"] = leased.ObservationId,
                                ["plateIndex"] = selected,
                                ["box"] = new JsonObject { ["x"] = proposal.X, ["y"] = proposal.Y, ["width"] = proposal.Width, ["height"] = proposal.Height },
                                ["cropWidth"] = spec.Width,
                                ["cropHeight"] = spec.Height,
                                ["detectorConfidence"] = proposal.Score,
                                ["outcome"] = read ? "read" : "unreadable",
                                ["readings"] = new JsonArray(kept.Select((item, rank) => (JsonNode)new JsonObject
                                {
                                    ["rank"] = rank,
                                    ["rawText"] = item.RawText,
                                    ["rawLineCount"] = 1 + item.RawText.Count(character => character == '\n'),
                                    ["confidence"] = item.Confidence,
                                }).ToArray()),
                            });
                            if (read) reads.Add((readings[0].RawText, readings[0].Confidence, leased.EvidenceRank, leased.ObservationId));
                            selected++;
                        }

                        detections.Add(new JsonObject
                        {
                            ["box"] = new JsonArray(proposal.X, proposal.Y, proposal.Width, proposal.Height),
                            ["plate"] = plate,
                            ["score"] = proposal.Score,
                        });
                    }
                }

                crops.Add(new JsonObject
                {
                    ["cropHeight"] = withDimensions ? spec.Height : null,
                    ["cropWidth"] = withDimensions ? spec.Width : null,
                    ["detections"] = detections,
                    ["evidenceRank"] = leased.EvidenceRank,
                    ["observationId"] = leased.ObservationId,
                    ["reason"] = spec.Reason,
                    ["role"] = leased.Role,
                    ["status"] = spec.Status,
                });
            }

            var outcome = scored > 0 ? "analysed" : "unavailable";
            var trackReason = scored > 0
                ? null
                : PlateContractRules.TrackUnavailableReasonsBySeverity.FirstOrDefault(caused.Contains) ?? "no_accepted_evidence";
            var texts = reads
                .Select(item => (Normalised: PlateNormalisation.Normalise(item.Text).Normalised, item.Confidence, item.Rank, item.Source))
                .Where(item => item.Normalised is not null)
                .GroupBy(item => item.Normalised!, StringComparer.Ordinal)
                .OrderBy(group => group.Key, StringComparer.Ordinal)
                .Select(group =>
                {
                    var best = group.OrderByDescending(item => item.Confidence).ThenBy(item => item.Rank).First();
                    return (best.Source, Support: group.Count(), Max: group.Max(item => item.Confidence));
                })
                .ToList();
            artefactTracks.Add(new JsonObject
            {
                ["crops"] = crops,
                ["outcome"] = outcome,
                ["reason"] = trackReason,
                ["texts"] = new JsonArray(texts.Select(text => (JsonNode)new JsonObject
                {
                    ["bestPlate"] = new JsonObject { ["observationId"] = text.Source, ["plateIndex"] = 0 },
                    ["maxConfidence"] = text.Max,
                    ["supportCount"] = text.Support,
                }).ToArray()),
                ["trackId"] = track.TrackId,
            });
            completionTracks.Add(new JsonObject
            {
                ["trackId"] = track.TrackId,
                ["outcome"] = outcome,
                ["reason"] = trackReason,
                ["plateObservations"] = scored > 0 ? observations : new JsonArray(),
                ["texts"] = new JsonArray(texts.Select(text => (JsonNode)new JsonObject
                {
                    ["bestPlate"] = new JsonObject { ["sourceObservationId"] = text.Source, ["plateIndex"] = 0 },
                    ["supportCount"] = text.Support,
                    ["maxConfidence"] = text.Max,
                }).ToArray()),
            });
        }

        var identity = lease.Identity;
        var artefact = new JsonObject
        {
            ["analysisId"] = lease.AnalysisId,
            ["identityFingerprint"] = identity.Fingerprint,
            ["normalisation"] = new JsonObject { ["id"] = identity.Normalisation.Id, ["sha256"] = identity.Normalisation.Sha256 },
            ["parametersSha256"] = identity.ParametersSha256,
            ["pipeline"] = new JsonObject { ["id"] = identity.PipelineId, ["version"] = identity.PipelineVersion },
            ["schemaVersion"] = PlateContractRules.PredictionsSchemaVersion,
            ["summaryPolicy"] = new JsonObject
            {
                ["id"] = identity.SummaryPolicy.Id,
                ["sha256"] = identity.SummaryPolicy.Sha256,
                ["version"] = identity.SummaryPolicy.Version,
            },
            ["tracks"] = artefactTracks,
        };
        var predictions = Encoding.UTF8.GetBytes(artefact.ToJsonString() + "\n");
        var body = new JsonObject
        {
            ["schemaVersion"] = PlateContractRules.SchemaVersion,
            ["analysisId"] = lease.AnalysisId,
            ["workerId"] = workerId,
            ["attemptCount"] = lease.AttemptCount,
            ["provenance"] = Provenance(identity, actualDevice),
            ["payload"] = new JsonObject
            {
                ["predictionArtifact"] = new JsonObject
                {
                    ["mediaType"] = PlateContractRules.PredictionsMediaType,
                    ["sizeBytes"] = predictions.LongLength,
                    ["sha256"] = Convert.ToHexStringLower(SHA256.HashData(predictions)),
                },
                ["tracks"] = completionTracks,
            },
        };
        var request = JsonSerializer.Deserialize<PlateCompleteRequest>(body.ToJsonString(), JsonSerializerOptions.Web)!;
        return new BuiltPlateCompletion(predictions, request);
    }

    private static JsonObject Reading(int rank, string rawText, double confidence) => new()
    {
        ["confidence"] = confidence,
        ["rank"] = rank,
        ["rawLineCount"] = 1 + rawText.Count(character => character == '\n'),
        ["rawText"] = rawText,
    };

    private static JsonObject Provenance(PlateIdentityContract identity, string actualDevice) => new()
    {
        ["provenanceContract"] = PlateContractRules.ProvenanceContract,
        ["roleId"] = "plates",
        ["capabilities"] = new JsonArray(identity.Capabilities.Select(item => (JsonNode)new JsonObject
        {
            ["capabilityId"] = item.CapabilityId,
            ["modelPackId"] = item.ModelPackId,
            ["modelManifestSha256"] = new string('5', 64),
            ["qualificationId"] = item.CapabilityId + "-fixture",
            ["qualificationSha256"] = new string('a', 64),
            ["verificationStatus"] = "unverified",
        }).ToArray()),
        ["runtimePackFamilyId"] = "mmdetection-phase1-v1",
        ["runtimeProfileSha256"] = new string('7', 64),
        ["runtimeVariant"] = "windows-x86_64-cpu",
        ["runtimePackId"] = null,
        ["runtimePackSource"] = "unpacked-environment",
        ["componentBindingSha256"] = new string('8', 64),
        ["pipelineProfileSha256"] = new string('9', 64),
        ["configuredDevicePolicy"] = "cpu",
        ["actualDevice"] = actualDevice,
        ["maviBuild"] = "0.0.0-dev",
        ["maviCommit"] = new string('9', 40),
    };

    public static string Format(double value) => value.ToString("R", CultureInfo.InvariantCulture);
}
