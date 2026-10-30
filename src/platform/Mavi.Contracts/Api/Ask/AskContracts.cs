using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Contracts.Api.Query;

namespace Mavi.Contracts.Api.Ask;

// Ask MAVI (ADR-026). A question is translated by the bound language model into one structured query of contract
// mavi-query-v1, or refused; the query is evaluated by the S9 service unchanged. Nothing in a response is model text:
// the interpretation is the server's canonical query, the answer is the S9 envelope and every message is platform text.

/// <param name="ReferenceDate">The site-local date that "today" means; absent means today in the site time zone.</param>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record AskRequest(string Question, DateOnly? ReferenceDate = null);

/// <summary>
/// The outcome of one question: <paramref name="Outcome"/> is <c>answered</c> (the query ran; <paramref name="Envelope"/>
/// is the S9 envelope, which may itself be withheld or empty) or <c>refused</c> (<paramref name="Refusal"/> says at
/// which stage and why). A refusal has no interpretation and no envelope.
/// </summary>
public sealed record AskResponse(
    string Question,
    DateOnly ReferenceDate,
    string SiteTimeZoneId,
    string Outcome,
    AskInterpretationResponse? Interpretation,
    QueryEnvelopeResponse? Envelope,
    AskRefusalResponse? Refusal,
    AskModelResponse Model,
    AskTimingsResponse Timings,
    string Disclosure);

/// <summary>
/// What the question was taken to mean: the canonical query the S9 parser produced from the model's output, with its
/// fingerprint, and the names of every camera, zone and line it references, read from the site catalogue.
/// </summary>
public sealed record AskInterpretationResponse(
    JsonElement ResolvedQuery,
    string QueryFingerprint,
    IReadOnlyList<AskReferenceResponse> References);

/// <param name="Kind"><c>camera</c>, <c>zone</c> or <c>line</c>.</param>
public sealed record AskReferenceResponse(
    string Kind,
    Guid Id,
    string Name,
    Guid CameraId,
    string CameraName,
    string? AToBLabel = null,
    string? BToALabel = null);

/// <param name="Stage">
/// <c>runtime</c> (the language role is not available), <c>question</c> (the platform refused the question before the
/// model: it names a place the site does not have), <c>model</c> (the model refused), <c>translation</c> (the
/// model's output is not a translation document), <c>contract</c> (the S9 parser refused the query) or <c>service</c>
/// (the S9 service refused it).
/// </param>
/// <param name="Path">A JSON pointer into the model's translation document or the query, when there is one.</param>
public sealed record AskRefusalResponse(string Stage, string Code, string Path, string Message);

public sealed record AskModelResponse(
    string? ModelPackId,
    string? ModelId,
    string? Quantisation,
    string? RuntimeId,
    string? Device,
    string PromptTemplateVersion,
    string? PromptSha256,
    double Temperature,
    int TopK,
    int Seed,
    int? PromptTokens = null,
    int? GeneratedTokens = null);

public sealed record AskTimingsResponse(long TranslationMs, long EvaluationMs, long TotalMs);

/// <summary><c>GET /api/ask/status</c>: whether Ask MAVI can answer now, and with which packs.</summary>
public sealed record AskStatusResponse(
    bool Bound,
    bool Answering,
    string? Reason,
    string? ModelPackId,
    string? ModelId,
    string? Quantisation,
    string? RuntimeId,
    string? Device,
    string? DeviceReason,
    string PromptTemplateVersion,
    string? SiteTimeZoneId,
    string Disclosure);
