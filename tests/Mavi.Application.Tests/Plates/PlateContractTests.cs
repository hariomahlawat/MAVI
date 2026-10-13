using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Application.Modules.Plates;
using Mavi.Application.Modules.Plates.Completion;
using Mavi.Contracts.Worker.Plates;

namespace Mavi.Application.Tests.Plates;

/// <summary>
/// The plate control-plane contract artefacts (Stage 4 plan §5.3; ADR-013 implementation amendment
/// 2026-10-13, items 11–13): the checked-in examples bind into the DTOs, agree with each other and with
/// the identity, digest and bound vectors, and the bounds the contract states are honest.
/// </summary>
public sealed class PlateContractTests
{
    private static readonly JsonSerializerOptions Web = new(JsonSerializerDefaults.Web);

    private static string Root => CompletionDigestGoldenTests.FindRepositoryRoot();

    private static byte[] Bytes(string relative) => File.ReadAllBytes(Path.Combine(Root, relative));

    private static string Sha256(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));

    [Fact]
    public void TheNormalisationShaIsTheVectorFileSha()
    {
        Assert.Equal(PlateContractRules.NormalisationSha256, Sha256(Bytes("contracts/test-vectors/plate-normalisation-v1.json")));
        Assert.Equal(PlateContractRules.NormalisationId, PlateNormalisation.NormalisationId);
    }

    [Fact]
    public void TheIdentityVectorIsDerivedFromTheFixtureProfile()
    {
        using var vectors = JsonDocument.Parse(Bytes("contracts/test-vectors/plate-identity-v1.json"));
        foreach (var vector in vectors.RootElement.GetProperty("vectors").EnumerateArray())
        {
            var profilePath = vector.GetProperty("pipelineProfile").GetString()!;
            var directory = Path.GetDirectoryName(profilePath)!;
            using var profile = JsonDocument.Parse(Bytes(profilePath));
            var root = profile.RootElement;
            Assert.Equal("mavi-plate-pipeline-v1", root.GetProperty("schemaVersion").GetString());
            Assert.Equal(PlateContractRules.PredictionsSchemaVersion, root.GetProperty("predictionsSchemaVersion").GetString());
            Assert.Equal(PlateContractRules.NormalisationId, root.GetProperty("normalisation").GetProperty("id").GetString());
            Assert.Equal(PlateContractRules.NormalisationSha256, root.GetProperty("normalisation").GetProperty("sha256").GetString());

            var summaryBytes = Bytes(Path.Combine(directory, root.GetProperty("summaryPolicy").GetProperty("file").GetString()!));
            var parameterBytes = Bytes(Path.Combine(directory, root.GetProperty("parameters").GetProperty("file").GetString()!));
            Assert.Equal(root.GetProperty("summaryPolicy").GetProperty("sha256").GetString(), Sha256(summaryBytes));
            Assert.Equal(root.GetProperty("parameters").GetProperty("sha256").GetString(), Sha256(parameterBytes));
            using var summary = JsonDocument.Parse(summaryBytes);
            var capabilities = vector.GetProperty("capabilities");

            var identity = PlateIdentity.Create(
                root.GetProperty("pipelineId").GetString()!,
                root.GetProperty("pipelineVersion").GetString()!,
                summary.RootElement.GetProperty("summaryPolicyId").GetString()!,
                summary.RootElement.GetProperty("summaryPolicyVersion").GetString()!,
                Sha256(summaryBytes),
                [
                    new PlateCapabilityIdentity(PlateContractRules.CapabilityOcr, capabilities.GetProperty("ocr").GetString()!),
                    new PlateCapabilityIdentity(PlateContractRules.CapabilityPlateDetector, capabilities.GetProperty("plate-detector").GetString()!),
                ],
                Sha256(parameterBytes));

            Assert.Equal(vector.GetProperty("canonicalIdentity").GetString(), identity.Canonical);
            Assert.Equal(vector.GetProperty("fingerprint").GetString(), identity.Fingerprint);
        }
    }

    [Fact]
    public void TheIdentityRefusesCapabilitiesOutOfCanonicalOrder()
    {
        var pack = "mavi-model-v2-" + new string('1', 64);
        Assert.Throws<ArgumentException>(() => PlateIdentity.Create("plates-fixture", "1.0.0", "plate-track-text-rank0", "1.0.0",
            new string('a', 64),
            [new PlateCapabilityIdentity("plate-detector", pack), new PlateCapabilityIdentity("ocr", pack)], new string('b', 64)));
        Assert.Throws<ArgumentException>(() => PlateIdentity.Create("plates-fixture", "1.0.0", "plate-track-text-rank0", "1.0.0",
            new string('a', 64), [new PlateCapabilityIdentity("ocr", pack)], new string('b', 64)));
    }

    [Fact]
    public void AReanalysisRequestIsBoundedByThePlansHundredRuns()
    {
        Assert.Equal(100, Mavi.Application.Modules.Plates.PlateOptions.MaximumReanalysisRunsCeiling);
        Assert.Empty(new Mavi.Application.Modules.Plates.PlateOptions { MaximumRunsPerReanalysisRequest = 100 }.Validate());
        Assert.Contains(new Mavi.Application.Modules.Plates.PlateOptions { MaximumRunsPerReanalysisRequest = 101 }.Validate(),
            problem => problem.Contains("MaximumRunsPerReanalysisRequest", StringComparison.Ordinal));
    }

    [Fact]
    public void ReadingsRankInTheCrossLanguageOrder()
    {
        using var document = JsonDocument.Parse(Bytes("contracts/test-vectors/plate-reading-order-v1.json"));
        foreach (var vector in document.RootElement.GetProperty("vectors").EnumerateArray())
        {
            var readings = vector.GetProperty("readings").EnumerateArray()
                .Select(item => (Text: item.GetProperty("rawText").GetString()!, Confidence: item.GetProperty("confidence").GetDouble()))
                .ToList();
            if (vector.GetProperty("refused").GetBoolean())
            {
                // No strict order exists: some two readings rank after each other in neither direction.
                Assert.Equal(JsonValueKind.Null, vector.GetProperty("rankedIndices").ValueKind);
                Assert.Contains(
                    from i in Enumerable.Range(0, readings.Count)
                    from j in Enumerable.Range(0, readings.Count)
                    where i < j
                    select (readings[i], readings[j]),
                    pair => !PlateContractRules.RanksAfter(pair.Item1.Confidence, pair.Item1.Text, pair.Item2.Confidence, pair.Item2.Text) &&
                            !PlateContractRules.RanksAfter(pair.Item2.Confidence, pair.Item2.Text, pair.Item1.Confidence, pair.Item1.Text));
                continue;
            }

            var ranked = vector.GetProperty("rankedIndices").EnumerateArray().Select(item => readings[item.GetInt32()]).ToList();
            for (var index = 1; index < ranked.Count; index++)
            {
                var (prior, current) = (ranked[index - 1], ranked[index]);
                Assert.True(PlateContractRules.RanksAfter(prior.Confidence, prior.Text, current.Confidence, current.Text), vector.GetProperty("name").GetString());
                Assert.False(PlateContractRules.RanksAfter(current.Confidence, current.Text, prior.Confidence, prior.Text), vector.GetProperty("name").GetString());
            }
        }

        // Strict: an equal reading never ranks after itself.
        Assert.False(PlateContractRules.RanksAfter(0.9, "KA01", 0.9, "KA01"));
    }

    [Fact]
    public void TheBoundVectorsMatchTheContractArithmetic()
    {
        using var document = JsonDocument.Parse(Bytes("contracts/test-vectors/plate-artifact-bound-v1.json"));
        Assert.Equal(PlateContractRules.MaximumPredictionArtifactBytes, document.RootElement.GetProperty("maximumBytes").GetInt64());
        var vectors = document.RootElement.GetProperty("vectors").EnumerateArray().ToList();
        // Every profile inside the bounded v1 limits fits the cap; the largest one is the worst case.
        Assert.All(vectors, item => Assert.True(item.GetProperty("accepted").GetBoolean()));
        Assert.Contains(vectors, item =>
            item.GetProperty("maxDetectionsPerCrop").GetInt32() == PlateContractRules.MaximumDetectionsPerCrop &&
            item.GetProperty("maxPlatesPerCrop").GetInt32() == PlateContractRules.MaximumPlatesPerCrop &&
            item.GetProperty("maxReadingsPerPlate").GetInt32() == PlateContractRules.MaximumReadingsPerPlate);
        Assert.True(PlateContractRules.WorstCasePredictionArtifactBytes(PlateContractRules.MaximumDetectionsPerCrop,
            PlateContractRules.MaximumPlatesPerCrop, PlateContractRules.MaximumReadingsPerPlate) <= PlateContractRules.MaximumPredictionArtifactBytes);
        foreach (var vector in vectors)
        {
            var detections = vector.GetProperty("maxDetectionsPerCrop").GetInt32();
            var plates = vector.GetProperty("maxPlatesPerCrop").GetInt32();
            var readings = vector.GetProperty("maxReadingsPerPlate").GetInt32();
            Assert.Equal(vector.GetProperty("worstCaseArtifactBytes").GetInt64(),
                PlateContractRules.WorstCasePredictionArtifactBytes(detections, plates, readings));
            Assert.Equal(vector.GetProperty("worstCaseCompletionBytes").GetInt64(),
                PlateContractRules.WorstCaseCompletionBodyBytes(detections, plates, readings));
            Assert.Equal(vector.GetProperty("accepted").GetBoolean(),
                PlateContractRules.IsAdmissibleProfileShape(detections, plates, readings));
        }
    }

    [Fact]
    public void TheFixtureProfileShapeIsAdmissible()
    {
        using var parameters = JsonDocument.Parse(Bytes("tests/fixtures/plates/fixture-parameters-v1.json"));
        var root = parameters.RootElement;
        Assert.True(PlateContractRules.IsAdmissibleProfileShape(
            root.GetProperty("maxDetectionsPerCrop").GetInt32(),
            root.GetProperty("maxPlatesPerCrop").GetInt32(),
            root.GetProperty("maxReadingsPerPlate").GetInt32()));
    }

    [Theory]
    [InlineData(0, 1, 1)]
    [InlineData(3, 1, 3)]
    [InlineData(2, 2, 1)]
    [InlineData(1, 2, 1)]
    [InlineData(2, 0, 1)]
    [InlineData(2, 1, 0)]
    [InlineData(2, 1, 4)]
    public void AProfileShapeOutOfRangeIsRefused(int detections, int plates, int readings)
    {
        Assert.False(PlateContractRules.IsAdmissibleProfileShape(detections, plates, readings));
        Assert.Throws<ArgumentOutOfRangeException>(() => PlateContractRules.WorstCasePredictionArtifactBytes(detections, plates, readings));
    }

    [Fact]
    public void TheLeaseExampleBindsAndNamesTheVectorIdentity()
    {
        var lease = JsonSerializer.Deserialize<PlateLeaseContract>(Bytes("contracts/examples/plate-lease-v1.example.json"), Web)!;
        Assert.Equal(PlateContractRules.SchemaVersion, lease.SchemaVersion);
        Assert.Equal(VectorFingerprint(), lease.Identity.Fingerprint);
        Assert.Equal(PlateContractRules.Capabilities, lease.Identity.Capabilities.Select(item => item.CapabilityId));
        Assert.All(lease.Tracks, track =>
        {
            Assert.Equal(PlateContractRules.ObjectClassVehicle, track.ObjectClass);
            Assert.All(track.Observations, observation => Assert.True(PlateContractRules.IsEvidenceRole(observation.Role)));
        });
    }

    [Fact]
    public void TheCompletionExampleBindsStrictlyAndPinsThePredictionsExample()
    {
        var predictions = Bytes("contracts/examples/plate-predictions-v1.example.json");
        var request = JsonSerializer.Deserialize<PlateCompleteRequest>(Bytes("contracts/examples/plate-complete-v1.example.json"), Web)!;

        Assert.Equal(PlateContractRules.SchemaVersion, request.SchemaVersion);
        Assert.Equal(PlateContractRules.ProvenanceContract, request.Provenance!.ProvenanceContract);
        Assert.Equal(predictions.LongLength, request.Payload!.PredictionArtifact!.SizeBytes);
        Assert.Equal(Sha256(predictions), request.Payload.PredictionArtifact.Sha256);
        foreach (var reading in request.Payload.Tracks!.SelectMany(track => track.PlateObservations!).SelectMany(item => item.Readings!))
        {
            Assert.True(PlateContractRules.IsRawText(reading.RawText));
            Assert.Equal(PlateContractRules.RawLineCount(reading.RawText!), reading.RawLineCount);
        }
    }

    [Fact]
    public void TheCompletionRefusesAnUnknownMemberAndTheCapability()
    {
        var text = Encoding.UTF8.GetString(Bytes("contracts/examples/plate-complete-v1.example.json"));
        var withToken = text.Replace("\"workerId\": \"plates-01\",", "\"workerId\": \"plates-01\", \"leaseToken\": \"x\",", StringComparison.Ordinal);
        Assert.NotEqual(text, withToken);
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<PlateCompleteRequest>(withToken, Web));
        var withNormalised = text.Replace("\"rawLineCount\": 1,", "\"rawLineCount\": 1, \"normalisedText\": \"X\",", StringComparison.Ordinal);
        Assert.NotEqual(text, withNormalised);
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<PlateCompleteRequest>(withNormalised, Web));
    }

    [Fact]
    public void ThePredictionsExampleIsCanonicalAndNamesTheVectorIdentity()
    {
        var bytes = Bytes("contracts/examples/plate-predictions-v1.example.json");
        Assert.Equal((byte)'\n', bytes[^1]);
        Assert.DoesNotContain((byte)'\n', bytes[..^1]);
        Assert.DoesNotContain(bytes, value => value > 0x7F);
        using var document = JsonDocument.Parse(bytes);
        Assert.Equal(PlateContractRules.PredictionsSchemaVersion, document.RootElement.GetProperty("schemaVersion").GetString());
        Assert.Equal(VectorFingerprint(), document.RootElement.GetProperty("identityFingerprint").GetString());
        Assert.Equal(PlateContractRules.NormalisationSha256,
            document.RootElement.GetProperty("normalisation").GetProperty("sha256").GetString());
    }

    [Fact]
    public void TheCompletionDigestVectorPinsTheExample()
    {
        using var vector = JsonDocument.Parse(Bytes("contracts/test-vectors/plate-completion-v1-digest.json"));
        var root = vector.RootElement;
        Assert.Equal(PlateCompletionDigest.DigestDomain, root.GetProperty("digestDomain").GetString());
        var exampleBytes = Bytes(root.GetProperty("example").GetString()!);
        Assert.Equal(root.GetProperty("exampleSha256").GetString(), Sha256(exampleBytes));
        var request = JsonSerializer.Deserialize<PlateCompleteRequest>(exampleBytes, Web)!;

        var digest = PlateCompletionDigest.Compute(request.AnalysisId!.Value, request.AttemptCount!.Value, VectorFingerprint(), request);

        Assert.Equal(root.GetProperty("digest").GetString(), digest);
    }

    [Fact]
    public void TheCompletionDigestChangesWithProvenanceAndReadings()
    {
        var bytes = Bytes("contracts/examples/plate-complete-v1.example.json");
        var request = JsonSerializer.Deserialize<PlateCompleteRequest>(bytes, Web)!;
        var baseline = PlateCompletionDigest.Compute(request.AnalysisId!.Value, 1, VectorFingerprint(), request);

        var otherDevice = request with { Provenance = request.Provenance! with { ActualDevice = "cuda:0" } };
        Assert.NotEqual(baseline, PlateCompletionDigest.Compute(request.AnalysisId.Value, 1, VectorFingerprint(), otherDevice));
        Assert.NotEqual(baseline, PlateCompletionDigest.Compute(request.AnalysisId.Value, 2, VectorFingerprint(), request));

        var tracks = request.Payload!.Tracks!.ToList();
        var first = tracks[0];
        var observations = first.PlateObservations!.ToList();
        var readings = observations[0].Readings!.ToList();
        readings[0] = readings[0] with { RawText = "KA 01 AB 1235" };
        observations[0] = observations[0] with { Readings = readings };
        tracks[0] = first with { PlateObservations = observations };
        var otherReading = request with { Payload = request.Payload with { Tracks = tracks } };
        Assert.NotEqual(baseline, PlateCompletionDigest.Compute(request.AnalysisId.Value, 1, VectorFingerprint(), otherReading));
    }

    [Theory]
    [InlineData("KA01AB1234", true)]
    [InlineData("KA 01 AB 1234", true)]
    [InlineData("MH12\nDE 4321", true)]
    [InlineData("\u0915\u093e01", true)]
    [InlineData("\ud83d\ude97A1", true)]
    [InlineData("", false)]
    [InlineData("\nKA01", false)]
    [InlineData("KA01\n", false)]
    [InlineData("KA\n01\nAB", false)]
    [InlineData("KA\t01", false)]
    [InlineData("KA\r\n01", false)]
    [InlineData("KA\u007f01", false)]
    [InlineData("KA\u000001", false)]
    [InlineData("KA\ufffe01", true)]   // kept verbatim; normalisation rejects it (v1 vectors)
    [InlineData("KA\uffff01", true)]
    [InlineData("123456789012345678901234567890123", false)]
    [InlineData("12345678901234567890123456789012", true)]
    public void RawTextFollowsTheWireRule(string value, bool expected)
    {
        Assert.Equal(expected, PlateContractRules.IsRawText(value));
    }

    [Fact]
    public void RawTextRefusesLoneSurrogates()
    {
        // Built in code: an attribute argument cannot carry ill-formed UTF-16.
        Assert.False(PlateContractRules.IsRawText(new string(['\ud83d', 'A'])));
        Assert.False(PlateContractRules.IsRawText(new string(['A', '\ude97'])));
        Assert.False(PlateContractRules.IsRawText(new string(['A', '\ud83d'])));
        Assert.True(PlateContractRules.IsRawText(new string(['\ud83d', '\ude97'])));
    }

    /// <summary>
    /// ADR-013 item 13: one UTF-16 code unit of raw text normalises to at most four characters, so a
    /// 32-unit raw text never yields more than <see cref="PlateContractRules.MaximumNormalisedTextLength"/>.
    /// </summary>
    [Fact]
    public void NormalisationExpandsAtMostFourCharactersPerCodeUnit()
    {
        var worst = 0;
        for (var codePoint = 0; codePoint <= 0x10FFFF; codePoint++)
        {
            if (codePoint is >= 0xD800 and <= 0xDFFF) continue;
            var text = char.ConvertFromUtf32(codePoint);
            if (!PlateContractRules.IsRawText(text)) continue;
            var result = PlateNormalisation.Normalise(text);
            if (result.Normalised is null) continue;
            Assert.True(result.Normalised.Length <= PlateContractRules.MaximumNormalisationExpansion * text.Length, $"U+{codePoint:X4}");
            worst = Math.Max(worst, result.Normalised.Length);
        }

        // The bound is tight: some code unit (for example U+2167 ROMAN NUMERAL EIGHT) reaches it.
        Assert.Equal(PlateContractRules.MaximumNormalisationExpansion, worst);
    }

    private static string VectorFingerprint()
    {
        using var document = JsonDocument.Parse(Bytes("contracts/test-vectors/plate-identity-v1.json"));
        return document.RootElement.GetProperty("vectors")[0].GetProperty("fingerprint").GetString()!;
    }
}
