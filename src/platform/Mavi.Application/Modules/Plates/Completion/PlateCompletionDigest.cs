using System.Buffers.Binary;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Common;

namespace Mavi.Application.Modules.Plates.Completion;

/// <summary>
/// The plate completion digest (ADR-013 §9 idempotent completion-digest verification; vector
/// <c>contracts/test-vectors/plate-completion-v1-digest.json</c>): length-prefixed fields under its own
/// domain tag, over a completion whose shape has already been validated. The worker id and the
/// capability are never inputs; provenance is, so a replay from another device or build is a
/// different completion. Members are taken in body order, which the validator pins to lease order.
/// </summary>
public static class PlateCompletionDigest
{
    public const string DigestDomain = "mavi:plate-completion-digest:v1";

    /// <exception cref="ArgumentException">A member the digest needs is missing (the body was not shape-validated).</exception>
    public static string Compute(Guid analysisId, int attemptCount, string identityFingerprint, PlateCompleteRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        var provenance = request.Provenance ?? throw Missing();
        var payload = request.Payload ?? throw Missing();
        var artifact = payload.PredictionArtifact ?? throw Missing();
        var tracks = payload.Tracks ?? throw Missing();
        var capabilities = provenance.Capabilities ?? throw Missing();

        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        void Field(string? value)
        {
            if (value is null)
            {
                hash.AppendData([0xFF]);
                return;
            }

            var bytes = Encoding.UTF8.GetBytes(value);
            Span<byte> length = stackalloc byte[4];
            BinaryPrimitives.WriteInt32BigEndian(length, bytes.Length);
            hash.AppendData([0x01]);
            hash.AppendData(length);
            hash.AppendData(bytes);
        }

        void Number(long? value) => Field(value?.ToString(CultureInfo.InvariantCulture));
        void Real(double? value) => Field(value?.ToString("R", CultureInfo.InvariantCulture));
        void Id(Guid? value) => Field(value?.ToString("D"));

        Field(DigestDomain);
        Id(analysisId);
        Number(attemptCount);
        Field(identityFingerprint);
        Field(provenance.ProvenanceContract);
        Field(provenance.RoleId);
        Number(capabilities.Count);
        foreach (var capability in capabilities)
        {
            Field(capability.CapabilityId);
            Field(capability.ModelPackId);
            Field(capability.ModelManifestSha256);
            Field(capability.QualificationId);
            Field(capability.QualificationSha256);
            Field(capability.VerificationStatus);
        }

        Field(provenance.RuntimePackFamilyId);
        Field(provenance.RuntimeProfileSha256);
        Field(provenance.RuntimeVariant);
        Field(provenance.RuntimePackId);
        Field(provenance.RuntimePackSource);
        Field(provenance.ComponentBindingSha256);
        Field(provenance.PipelineProfileSha256);
        Field(provenance.ConfiguredDevicePolicy);
        Field(provenance.ActualDevice);
        Field(provenance.MaviBuild);
        Field(provenance.MaviCommit);
        Field(artifact.MediaType);
        Number(artifact.SizeBytes);
        Field(artifact.Sha256);
        Number(tracks.Count);
        foreach (var track in tracks)
        {
            var observations = track.PlateObservations ?? throw Missing();
            var texts = track.Texts ?? throw Missing();
            Id(track.TrackId);
            Field(track.Outcome);
            Field(track.Reason);
            Number(observations.Count);
            foreach (var observation in observations)
            {
                var box = observation.Box ?? throw Missing();
                var readings = observation.Readings ?? throw Missing();
                Id(observation.SourceObservationId);
                Number(observation.PlateIndex);
                Number(box.X);
                Number(box.Y);
                Number(box.Width);
                Number(box.Height);
                Number(observation.CropWidth);
                Number(observation.CropHeight);
                Real(observation.DetectorConfidence);
                Field(observation.Outcome);
                Number(readings.Count);
                foreach (var reading in readings)
                {
                    Number(reading.Rank);
                    Field(reading.RawText);
                    Number(reading.RawLineCount);
                    Real(reading.Confidence);
                }
            }

            Number(texts.Count);
            foreach (var text in texts)
            {
                var best = text.BestPlate ?? throw Missing();
                Id(best.SourceObservationId);
                Number(best.PlateIndex);
                Number(text.SupportCount);
                Real(text.MaxConfidence);
            }
        }

        return CanonicalSha256.ToHex(hash.GetHashAndReset());
    }

    private static ArgumentException Missing() => new("plate_completion_digest_input_incomplete");
}
