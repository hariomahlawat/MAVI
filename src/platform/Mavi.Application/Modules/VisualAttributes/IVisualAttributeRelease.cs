using Mavi.Application.Modules.VisualAttributes.Release;
using Mavi.Domain.VisualAttributes;

namespace Mavi.Application.Modules.VisualAttributes;

/// <summary>
/// The attribute definition the running release declares, resolved once at startup
/// (ADR-013 implementation amendment 2026-09-28, item 1). The currently preferred identity is
/// this definition's identity; nothing else decides it.
/// </summary>
public interface IVisualAttributeRelease
{
    VisualAttributeReleaseResolution Resolution { get; }
}

public static class VisualAttributeReleaseExtensions
{
    public static VisualAttributeIdentityFields ToFields(this VisualAttributeIdentity identity)
    {
        ArgumentNullException.ThrowIfNull(identity);
        return new VisualAttributeIdentityFields(
            identity.Fingerprint,
            identity.AttributeSchemaId,
            identity.AttributeSchemaVersion,
            identity.AttributeSchemaSha256,
            identity.PipelineId,
            identity.PipelineVersion,
            identity.AggregationPolicyId,
            identity.AggregationPolicyVersion,
            identity.AggregationPolicySha256,
            identity.CapabilitiesCanonical,
            identity.ParametersSha256);
    }

    /// <summary>The object classes any attribute of the schema applies to.</summary>
    public static IReadOnlyList<string> ApplicableObjectClasses(this AttributeSchemaDefinition schema)
    {
        ArgumentNullException.ThrowIfNull(schema);
        return schema.Attributes.Select(item => item.ObjectClass).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList();
    }
}
