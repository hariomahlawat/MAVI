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
/// builds the prompt and grammar, asks the language role once, translates its output, and evaluates the query with the
/// S9 service unchanged. Nothing the model writes is returned; there is no retry.
/// </summary>
public sealed class AskService(
    IAskCatalogueSource catalogueSource,
    ILanguageRuntime runtime,
    StructuredQueryService queries,
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
        var referenceDate = request.ReferenceDate ?? AskSiteTime.Today(zoneId ?? "UTC", timeProvider.GetUtcNow());

        AskResponse Refused(string stage, string code, string path, string message, AskModelResponse? model = null, long translationMs = 0) =>
            new(question, referenceDate, zoneId ?? string.Empty, AskCodes.Refused, null, null,
                new AskRefusalResponse(stage, code, path, message), model ?? Model(null, null), new AskTimingsResponse(translationMs, 0, total.ElapsedMilliseconds),
                QueryContract.Disclosure);

        if (string.IsNullOrWhiteSpace(question) || question.Length > AskCodes.MaximumQuestionLength)
            return Refused(AskCodes.StageRuntime, AskCodes.QuestionInvalid, "/question",
                $"A question is 1 to {AskCodes.MaximumQuestionLength} characters.");
        if (zoneId is null)
            return Refused(AskCodes.StageRuntime, AskCodes.SiteTimeZoneAmbiguous, "",
                "The cameras are in different time zones and no site time zone is configured (Ask:SiteTimeZoneId).");

        var siteTime = new AskSiteTime(zoneId, referenceDate);
        var prompt = AskPrompt.Build(QueryContractVocabulary.Describe(attributeRelease), catalogue, siteTime, question);

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

        var translated = AskTranslator.Translate(completion.Text, siteTime);
        if (translated.Refusal is { } refusal)
            return Refused(refusal.Stage, refusal.Code, refusal.Path, refusal.Message, model, translationMs);

        var evaluation = Stopwatch.StartNew();
        var outcome = await queries.EvaluateAsync(translated.Query!, cancellationToken);
        var evaluationMs = evaluation.ElapsedMilliseconds;
        if (outcome.Refusal is { } serviceRefusal)
        {
            return Refused(AskCodes.StageService, serviceRefusal.Code, serviceRefusal.Path, serviceRefusal.Message, model, translationMs)
                with { Timings = new AskTimingsResponse(translationMs, evaluationMs, total.ElapsedMilliseconds) };
        }

        var envelope = outcome.Envelope!;
        return new AskResponse(
            question,
            referenceDate,
            zoneId,
            AskCodes.Answered,
            new AskInterpretationResponse(envelope.ResolvedQuery, envelope.QueryFingerprint, References(envelope.ResolvedQuery, catalogue)),
            envelope,
            null,
            model,
            new AskTimingsResponse(translationMs, evaluationMs, total.ElapsedMilliseconds),
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
