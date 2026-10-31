using System.Diagnostics;
using System.Text.Json;
using Mavi.Application.Modules.Query;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Contracts.Api.Ask;
using Mavi.Contracts.Api.Query;
using Microsoft.Extensions.Options;

namespace Mavi.Application.Modules.Ask;

public sealed class AskOptions
{
    public const string SectionName = "Ask";

    /// <summary>The site's IANA time zone; when empty, the one zone every camera shares (refused if they differ).</summary>
    public string? SiteTimeZoneId { get; set; }
}

/// <summary>
/// Ask MAVI (ADR-026): one question becomes one structured query or a refusal. The service reads the site catalogue,
/// builds the prompt and grammar, asks the language role once, and translates its output into the parser's canonical
/// query. Ask proposes and the operator confirms (D-S10-10): this service never evaluates a query and has no access to
/// the query service; the operator runs the interpretation through <c>POST /api/query</c>. Nothing the model writes is
/// returned; there is no retry. Prompt v2 (D-S10-9) first refuses a question that refers to a place the site does not
/// have, without calling the model (<see cref="AskPlaceReferences"/>).
/// </summary>
public sealed class AskService(
    IAskCatalogueSource catalogueSource,
    ILanguageRuntime runtime,
    IOptions<AskOptions> options,
    TimeProvider timeProvider,
    IVisualAttributeRelease? attributeRelease = null)
{
    public static LanguageDecoding Decoding => LanguageDecoding.Deterministic;

    public async Task<AskResponse> AskAsync(AskRequest request, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var total = Stopwatch.StartNew();
        var question = request.Question ?? string.Empty;
        var catalogue = await catalogueSource.ReadAsync(cancellationToken);
        var zoneId = SiteTimeZone(catalogue);
        // The zone is checked before it is used for anything, the default reference date included.
        var zoneKnown = zoneId is not null && TimeZoneInfo.TryFindSystemTimeZoneById(zoneId, out _);
        var referenceDate = request.ReferenceDate ??
            (zoneKnown ? AskSiteTime.Today(zoneId!, timeProvider.GetUtcNow()) : DateOnly.FromDateTime(timeProvider.GetUtcNow().UtcDateTime));

        AskResponse Refused(string stage, string code, string path, string message, AskModelResponse? model = null, long translationMs = 0) =>
            new(question, referenceDate, zoneId ?? string.Empty, AskCodes.Refused, null,
                new AskRefusalResponse(stage, code, path, message), model ?? Model(null, null), new AskTimingsResponse(translationMs, total.ElapsedMilliseconds),
                QueryContract.Disclosure);

        if (string.IsNullOrWhiteSpace(question) || question.Length > AskCodes.MaximumQuestionLength)
            return Refused(AskCodes.StageRuntime, AskCodes.QuestionInvalid, "/question",
                $"A question is 1 to {AskCodes.MaximumQuestionLength} characters.");
        if (zoneId is null)
            return Refused(AskCodes.StageRuntime, AskCodes.SiteTimeZoneAmbiguous, "",
                "The cameras are in different time zones and no site time zone is configured (Ask:SiteTimeZoneId).");

        if (!zoneKnown)
            return Refused(AskCodes.StageRuntime, AskCodes.SiteTimeZoneInvalid, "",
                $"The site time zone '{zoneId}' is not known on this host (Ask:SiteTimeZoneId, or the cameras' zone).");
        var siteTime = new AskSiteTime(zoneId, referenceDate);

        // A place the site does not have is refused, never answered for the whole site.
        if (AskPlaceReferences.Unknown(question, catalogue).Count > 0)
            return Refused(AskCodes.StageQuestion, AskCodes.UnknownReference, "/question", AskCodes.ModelRefusalMessage(AskCodes.UnknownReference));

        var prompt = AskPrompt.Build(QueryContractVocabulary.Describe(attributeRelease), catalogue, siteTime, question);
        if (prompt.Prompt.Length > AskCodes.MaximumPromptCharacters)
            return Refused(AskCodes.StageRuntime, AskCodes.PromptTooLong, "",
                "The site catalogue is too large for the language role's context; Ask MAVI cannot prompt for this site.", Model(prompt, null));

        var translation = Stopwatch.StartNew();
        LanguageCompletion completion;
        try
        {
            completion = await runtime.CompleteAsync(new LanguageCompletionRequest(prompt.Prompt, prompt.Grammar, Decoding), cancellationToken);
        }
        catch (LanguageRuntimeUnavailableException unavailable)
        {
            return Refused(AskCodes.StageRuntime, unavailable.Code, "", unavailable.Message, Model(prompt, null), translation.ElapsedMilliseconds);
        }

        var translationMs = translation.ElapsedMilliseconds;
        var model = Model(prompt, completion);
        if (completion.Truncated)
            return Refused(AskCodes.StageTranslation, AskCodes.ModelOutputTruncated, "",
                "The model's output stopped before the translation document ended.", model, translationMs);

        var translated = AskTranslator.Translate(completion.Text, siteTime, question);
        if (translated.Refusal is { } refusal)
        {
            // A model refusal already carries platform text. A translation or contract refusal is about what the model
            // wrote, so its message is replaced by platform text and its path cut at the first segment the contract
            // does not name: no model-written member name reaches the operator.
            return refusal.Stage == AskCodes.StageModel
                ? Refused(refusal.Stage, refusal.Code, refusal.Path, refusal.Message, model, translationMs)
                : Refused(refusal.Stage, refusal.Code, ContractPath(refusal.Path), AskCodes.StageMessage(refusal.Stage, refusal.Code), model, translationMs);
        }

        // The proposal is the strict parser's canonical query: exactly what POST /api/query receives when the operator
        // runs it. Nothing is evaluated here.
        var canonical = StructuredQueryCanonical.Write(translated.Query!);
        using var resolved = JsonDocument.Parse(canonical);
        var resolvedQuery = resolved.RootElement.Clone();
        return new AskResponse(
            question,
            referenceDate,
            zoneId,
            AskCodes.Interpreted,
            new AskInterpretationResponse(resolvedQuery, StructuredQueryCanonical.Fingerprint(canonical), References(resolvedQuery, catalogue)),
            null,
            model,
            new AskTimingsResponse(translationMs, total.ElapsedMilliseconds),
            QueryContract.Disclosure);
    }

    public async Task<AskStatusResponse> StatusAsync(CancellationToken cancellationToken)
    {
        var identity = runtime.Identity;
        var answering = identity.Bound && await runtime.IsAnsweringAsync(cancellationToken);
        var catalogue = await catalogueSource.ReadAsync(cancellationToken);
        return new AskStatusResponse(
            identity.Bound,
            answering,
            !identity.Bound ? AskCodes.LanguageUnavailable : answering ? null : AskCodes.LanguageUnavailable,
            identity.ModelPackId,
            identity.ModelId,
            identity.Quantisation,
            identity.RuntimeId,
            identity.Device,
            identity.DeviceReason,
            AskPrompt.TemplateVersion,
            SiteTimeZone(catalogue),
            QueryContract.Disclosure);
    }

    private static readonly HashSet<string> ContractSegments = new(StringComparer.Ordinal)
    {
        "answer", "reason", "query", "contractVersion", "unit", "where", "operation", "requireCompleteCoverage",
        "timeWindow", "fromUtc", "toUtc", "cameraIds", "objectClass", "objectSubclass", "minDurationMs", "minConfidence",
        "zone", "zoneId", "relation", "minDwellMs", "loitering", "line", "lineId", "direction", "motion", "minStationaryMs",
        "attributes", "type", "value", "plateText", "text", "match", "similarTo", "trackId", "k", "ruleIds", "catalogueVersion",
        "op", "limit", "order", "field", "by", "bucketSeconds", "baseline",
    };

    /// <summary>A JSON pointer cut at its first segment that is neither a contract member name nor an array index.</summary>
    public static string ContractPath(string path)
    {
        if (string.IsNullOrEmpty(path))
            return path;
        var kept = new List<string>();
        foreach (var segment in path.Split('/').Skip(1))
        {
            if (!ContractSegments.Contains(segment) && !segment.All(char.IsAsciiDigit))
                break;
            kept.Add(segment);
        }

        return kept.Count == 0 ? "" : "/" + string.Join('/', kept);
    }

    /// <summary>The configured site zone, or the single zone all cameras share; null when they differ and none is configured.</summary>
    private string? SiteTimeZone(AskSiteCatalogue catalogue)
    {
        if (!string.IsNullOrWhiteSpace(options.Value.SiteTimeZoneId))
            return options.Value.SiteTimeZoneId;
        var zones = catalogue.Cameras.Select(camera => camera.TimeZoneId).Distinct(StringComparer.Ordinal).ToList();
        return zones.Count switch
        {
            0 => "UTC",
            1 => zones[0],
            _ => null,
        };
    }

    private AskModelResponse Model(AskPromptRequest? prompt, LanguageCompletion? completion)
    {
        var identity = runtime.Identity;
        return new AskModelResponse(
            identity.ModelPackId,
            identity.ModelId,
            identity.Quantisation,
            identity.RuntimeId,
            identity.Device,
            AskPrompt.TemplateVersion,
            prompt?.PromptSha256,
            Decoding.Temperature,
            Decoding.TopK,
            Decoding.Seed,
            completion?.PromptTokens,
            completion?.GeneratedTokens);
    }

    /// <summary>The cameras, zones and lines the canonical query names, with their catalogue names (platform data).</summary>
    public static IReadOnlyList<AskReferenceResponse> References(JsonElement resolvedQuery, AskSiteCatalogue catalogue)
    {
        var references = new List<AskReferenceResponse>();
        if (!resolvedQuery.TryGetProperty("where", out var where))
            return references;

        if (where.TryGetProperty("cameraIds", out var cameraIds))
        {
            foreach (var id in cameraIds.EnumerateArray().Select(item => Guid.Parse(item.GetString()!)))
            {
                if (catalogue.Cameras.FirstOrDefault(camera => camera.CameraId == id) is { } camera)
                    references.Add(new AskReferenceResponse("camera", id, camera.Name, id, camera.Name));
            }
        }

        if (where.TryGetProperty("zone", out var zone) && Guid.TryParse(zone.GetProperty("zoneId").GetString(), out var zoneId))
        {
            foreach (var camera in catalogue.Cameras)
            {
                if (camera.Zones.FirstOrDefault(item => item.ZoneId == zoneId) is { } match)
                    references.Add(new AskReferenceResponse("zone", zoneId, match.Name, camera.CameraId, camera.Name));
            }
        }

        if (where.TryGetProperty("line", out var line) && Guid.TryParse(line.GetProperty("lineId").GetString(), out var lineId))
        {
            foreach (var camera in catalogue.Cameras)
            {
                if (camera.Lines.FirstOrDefault(item => item.LineId == lineId) is { } match)
                    references.Add(new AskReferenceResponse("line", lineId, match.Name, camera.CameraId, camera.Name, match.AToBLabel, match.BToALabel));
            }
        }

        return references;
    }
}
