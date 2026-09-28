using Mavi.Domain.VisualAttributes;

namespace Mavi.IntegrationTests;

internal static class VisualAttributeTestIdentity
{
    public static VisualAttributeIdentityFields Fields(char fill = 'a') => new(
        Fingerprint: new string(fill, 64),
        AttributeSchemaId: "visual-attributes-fixture",
        AttributeSchemaVersion: "1.0.0",
        AttributeSchemaSha256: new string('b', 64),
        PipelineId: "visual-attributes-fixture",
        PipelineVersion: "1.0.0",
        AggregationPolicyId: "mean-score-argmax",
        AggregationPolicyVersion: "1.0.0",
        AggregationPolicySha256: new string('c', 64),
        CapabilitiesCanonical: "[]",
        ParametersSha256: new string('d', 64));
}
