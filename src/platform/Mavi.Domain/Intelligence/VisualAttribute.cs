using Mavi.Domain.Common;
using System.Diagnostics.CodeAnalysis;

namespace Mavi.Domain.Intelligence;

[SuppressMessage("Naming", "CA1711:Identifiers should not have incorrect suffix", Justification = "VisualAttribute is the approved domain term.")]
public sealed class VisualAttribute
{
    private VisualAttribute() { }

    // Construction
    public static VisualAttribute Create(Guid trackId, Guid? observationId, string attributeType, string value,
        double confidence, string? modelName = null, string? modelVersion = null)
    {
        if (trackId == Guid.Empty || string.IsNullOrWhiteSpace(attributeType) || attributeType.Length > 64 ||
            string.IsNullOrWhiteSpace(value) || value.Length > 128 || !double.IsFinite(confidence) || confidence is < 0 or > 1 ||
            modelName?.Length > 128 || modelVersion?.Length > 128)
            throw new DomainValidationException("visual_attribute_invalid", "The visual attribute data is invalid.");
        return new VisualAttribute { Id = Guid.CreateVersion7(), TrackId = trackId, ObservationId = observationId,
            AttributeType = attributeType, Value = value, Confidence = confidence, ModelName = modelName,
            ModelVersion = modelVersion, CreatedAtUtc = DateTimeOffset.UtcNow };
    }

    // Properties
    public Guid Id { get; private set; }
    public Guid TrackId { get; private set; }
    public Guid? ObservationId { get; private set; }
    public string AttributeType { get; private set; } = string.Empty;
    public string Value { get; private set; } = string.Empty;
    public double Confidence { get; private set; }
    public string? ModelName { get; private set; }
    public string? ModelVersion { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
}
