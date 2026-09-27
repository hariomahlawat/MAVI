using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using static Mavi.Application.Tests.Completion32Fixture;

namespace Mavi.Application.Tests;

/// <summary>
/// Completion 3.2 provenance rules (S2a plan §4.5, §10): required members, closed
/// vocabularies, derived-identity grammar and the Runtime Pack pairing. Every failure is a
/// stable reason code, never a parser exception.
/// </summary>
public sealed class VisionResultValidatorV32Tests
{
    public static TheoryData<string, string> EarlierVersionsAndFields()
    {
        var data = new TheoryData<string, string>();
        foreach (var version in new[] { "3.0", "3.1" })
            foreach (var field in ComponentIdentityFields)
                data.Add(version, field);
        return data;
    }

    [Theory]
    [MemberData(nameof(EarlierVersionsAndFields))]
    public void AnyOneComponentIdentityMemberIsRefusedInAnEarlierEvidenceSetBody(string version, string field)
    {
        var source = Provenance(Node(InstalledExample));
        var body = WithoutComponentIdentity(Node(InstalledExample), version);
        Provenance(body)[field] = source[field]!.DeepClone();

        Assert.Equal("provenance_v32_field_in_v3_body", Rejection(body));
    }

    [Theory]
    [InlineData("capabilityId", "\"detector\"")]
    [InlineData("modelPackId", "\"mavi-model-v2-7777777777777777777777777777777777777777777777777777777777777777\"")]
    [InlineData("runtimePackId", "\"mavi-runtime-v2-8888888888888888888888888888888888888888888888888888888888888888\"")]
    [InlineData("runtimePackSource", "\"unpacked-environment\"")]
    [InlineData("componentBindingSha256", "\"9999999999999999999999999999999999999999999999999999999999999999\"")]
    public void AnyOneComponentIdentityMemberIsRefusedInA20Body(string field, string value)
    {
        var body = Node("contracts/examples/vision-job-complete-v2.example.json");
        Provenance(body)[field] = JsonNode.Parse(value);

        Assert.Equal("provenance_v32_field_in_v3_body", Rejection(body));
    }

    [Theory]
    [InlineData("capabilityId", "provenance_capability_invalid")]
    [InlineData("modelPackId", "provenance_model_pack_invalid")]
    [InlineData("runtimePackSource", "provenance_runtime_pack_source_invalid")]
    [InlineData("componentBindingSha256", "provenance_component_binding_invalid")]
    public void EachRequiredMemberIsRequiredIn32(string field, string code)
    {
        var absent = Node(InstalledExample);
        Provenance(absent).Remove(field);
        Assert.Equal(code, Rejection(absent));

        var explicitNull = Node(InstalledExample);
        Provenance(explicitNull)[field] = null;
        Assert.Equal(code, Rejection(explicitNull));
    }

    [Theory]
    // Closed registry: case, whitespace, unregistered and model-name ids are all refused.
    [InlineData("capabilityId", "\"Detector\"", "provenance_capability_invalid")]
    [InlineData("capabilityId", "\"detector \"", "provenance_capability_invalid")]
    [InlineData("capabilityId", "\"face-recognition\"", "provenance_capability_invalid")]
    [InlineData("capabilityId", "\"rtmdet-m-coco-phase1\"", "provenance_capability_invalid")]
    [InlineData("capabilityId", "\"\"", "provenance_capability_invalid")]
    // Derived identities: exact prefix, exactly 64 lower-case hex, nothing trailing.
    [InlineData("modelPackId", "\"mavi-model-v2-777777777777777777777777777777777777777777777777777777777777777\"", "provenance_model_pack_invalid")]
    [InlineData("modelPackId", "\"mavi-model-v2-77777777777777777777777777777777777777777777777777777777777777777\"", "provenance_model_pack_invalid")]
    [InlineData("modelPackId", "\"mavi-model-v2-777777777777777777777777777777777777777777777777777777777777777A\"", "provenance_model_pack_invalid")]
    [InlineData("modelPackId", "\"mavi-model-v1-7777777777777777777777777777777777777777777777777777777777777777\"", "provenance_model_pack_invalid")]
    [InlineData("modelPackId", "\"MAVI-model-v2-7777777777777777777777777777777777777777777777777777777777777777\"", "provenance_model_pack_invalid")]
    [InlineData("modelPackId", "\"mavi-model-v2-777777777777777777777777777777777777777777777777777777777777777\\n\"", "provenance_model_pack_invalid")]
    [InlineData("modelPackId", "\"7777777777777777777777777777777777777777777777777777777777777777\"", "provenance_model_pack_invalid")]
    [InlineData("runtimePackId", "\"mavi-runtime-v2-888888888888888888888888888888888888888888888888888888888888888g\"", "provenance_runtime_pack_invalid")]
    [InlineData("runtimePackId", "\"mavi-runtime-v1-8888888888888888888888888888888888888888888888888888888888888888\"", "provenance_runtime_pack_invalid")]
    [InlineData("runtimePackId", "\" mavi-runtime-v2-8888888888888888888888888888888888888888888888888888888888888888\"", "provenance_runtime_pack_invalid")]
    [InlineData("runtimePackId", "\"\"", "provenance_runtime_pack_invalid")]
    [InlineData("componentBindingSha256", "\"999999999999999999999999999999999999999999999999999999999999999\"", "provenance_component_binding_invalid")]
    [InlineData("componentBindingSha256", "\"999999999999999999999999999999999999999999999999999999999999999F\"", "provenance_component_binding_invalid")]
    [InlineData("runtimePackSource", "\"installed\"", "provenance_runtime_pack_source_invalid")]
    [InlineData("runtimePackSource", "\"Installed-Pack\"", "provenance_runtime_pack_source_invalid")]
    [InlineData("runtimePackSource", "\"unpacked\"", "provenance_runtime_pack_source_invalid")]
    public void MalformedButPlausibleMembersAreRefusedWithTheirCode(string field, string value, string code)
    {
        var body = Node(InstalledExample);
        Provenance(body)[field] = JsonNode.Parse(value);

        Assert.Equal(code, Rejection(body));
    }

    [Fact]
    public void AnInstalledPackMustNameItsRuntimePack()
    {
        var absent = Node(InstalledExample);
        Provenance(absent).Remove("runtimePackId");
        Assert.Equal("provenance_runtime_pack_required", Rejection(absent));

        var explicitNull = Node(InstalledExample);
        Provenance(explicitNull)["runtimePackId"] = null;
        Assert.Equal("provenance_runtime_pack_required", Rejection(explicitNull));
    }

    [Fact]
    public void AnUnpackedEnvironmentNamesNoRuntimePack()
    {
        // Unpacked execution is not equivalent to an installed Runtime Pack: it may not
        // borrow a pack identity.
        var body = Node(UnpackedExample);
        Provenance(body)["runtimePackId"] = "mavi-runtime-v2-" + new string('8', 64);

        Assert.Equal("provenance_runtime_pack_required", Rejection(body));
    }

    [Fact]
    public void AnUnpackedEnvironmentIsNeverVerified()
    {
        var body = Node(UnpackedExample);
        var provenance = Provenance(body);
        provenance["verificationStatus"] = "verified";
        provenance["qualificationId"] = "rtmdet-m-coco-phase1-qualification";
        provenance["qualificationSha256"] = new string('a', 64);

        Assert.Equal("provenance_runtime_pack_required", Rejection(body));

        // The same verified claim is well-formed with an installed pack.
        var installed = Node(InstalledExample);
        Provenance(installed)["verificationStatus"] = "verified";
        Provenance(installed)["qualificationId"] = "rtmdet-m-coco-phase1-qualification";
        Provenance(installed)["qualificationSha256"] = new string('a', 64);
        Assert.Equal(CompletionSchema.V32, Validate(installed).Schema);
    }

    [Theory]
    [InlineData("capabilityId", "1")]
    [InlineData("modelPackId", "true")]
    [InlineData("runtimePackId", "{}")]
    [InlineData("runtimePackSource", "[\"installed-pack\"]")]
    public void AWronglyTypedMemberIsRefusedAtBinding(string field, string value)
    {
        var body = Node(InstalledExample);
        Provenance(body)[field] = JsonNode.Parse(value);

        Assert.Throws<JsonException>(() => body.Deserialize<VisionJobCompleteRequest>(Json));
    }

    [Fact]
    public void AnUnknownProvenanceMemberIsStillRefusedIn32()
    {
        var body = Node(InstalledExample);
        Provenance(body)["runtimePackFamilyId"] = "mmdetection-phase1-v1";

        Assert.Throws<JsonException>(() => body.Deserialize<VisionJobCompleteRequest>(Json));
    }

    [Fact]
    public void EvidenceSetRulesStillApplyTo32()
    {
        // 3.2 is an Evidence Set body: missing accounting is refused exactly as in 3.0/3.1.
        var body = Node(InstalledExample);
        body.Remove("evidenceAccounting");
        Assert.Equal("evidence_accounting_missing", Rejection(body));

        var result = Validate(Node(InstalledExample));
        Assert.True(result.Schema.IsEvidenceSet());
        Assert.NotNull(result.EvidenceAccounting);
    }

    [Fact]
    public void EvidenceSetClassificationCoversEverySchema()
    {
        Assert.False(CompletionSchema.V2.IsEvidenceSet());
        Assert.True(CompletionSchema.V3.IsEvidenceSet());
        Assert.True(CompletionSchema.V32.IsEvidenceSet());
        Assert.Throws<ArgumentOutOfRangeException>(() => ((CompletionSchema)99).IsEvidenceSet());
        Assert.Equal(3, Enum.GetValues<CompletionSchema>().Length);
    }

    [Fact]
    public void ThePersistedProvenanceReaderAppliesThe32RulesToA32Row()
    {
        var parser = new VisionRuntimeProvenanceParser();
        var stored = Validate(Node(InstalledExample)).RuntimeProvenanceJson;
        var parsed = parser.ParsePersisted(stored);
        Assert.Equal("detector", parsed.Contract.CapabilityId);
        Assert.Equal("installed-pack", parsed.Contract.RuntimePackSource);

        // A stored row that carries only part of the component identity is refused, never
        // read under the laxer earlier rules.
        var partial = JsonNode.Parse(stored)!.AsObject();
        partial.Remove("componentBindingSha256");
        Assert.Equal("provenance_component_binding_invalid",
            Assert.Throws<VisionResultValidationException>(() => parser.ParsePersisted(partial.ToJsonString())).ReasonCode);

        var unpaired = JsonNode.Parse(stored)!.AsObject();
        unpaired.Remove("runtimePackId");
        Assert.Equal("provenance_runtime_pack_required",
            Assert.Throws<VisionResultValidationException>(() => parser.ParsePersisted(unpaired.ToJsonString())).ReasonCode);

        // A row from an earlier version carries none and still reads.
        var earlier = parser.ParsePersisted(Validate(Node("contracts/examples/vision-job-complete-v3.1.example.json")).RuntimeProvenanceJson);
        Assert.Null(earlier.Contract.CapabilityId);
    }

    [Fact]
    public void ProvenanceParsingRequiresADefinedSchema()
    {
        var provenance = Request(InstalledExample).Provenance!;
        Assert.Throws<ArgumentOutOfRangeException>(() => VisionRuntimeProvenanceParser.Parse(provenance, (CompletionSchema)99));
    }
}
