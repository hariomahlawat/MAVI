namespace Mavi.Application.Modules.Ask;

/// <summary>The closed vocabulary of Ask MAVI outcomes, refusal stages and codes (ADR-026 §4). Every message is platform text.</summary>
public static class AskCodes
{
    /// <summary>The version of the translation document the model emits.</summary>
    public const string TranslationVersion = "mavi-ask-translation-v1";

    public const string Answered = "answered";
    public const string Refused = "refused";

    public const string StageRuntime = "runtime";
    public const string StageModel = "model";
    public const string StageTranslation = "translation";
    public const string StageContract = "contract";
    public const string StageService = "service";

    // Model refusals: the only reasons a model may give, with no free text.
    public const string OutsideContract = "outside_contract";
    public const string UnknownReference = "unknown_reference";
    public static readonly IReadOnlyList<string> ModelRefusalReasons = [OutsideContract, UnknownReference];

    // Translation refusals: the model's output is not a usable translation document.
    public const string ModelOutputInvalid = "model_output_invalid";
    public const string ModelOutputTruncated = "model_output_truncated";
    public const string TimeOffsetMismatch = "time_offset_mismatch";

    // Runtime and request refusals.
    public const string LanguageUnavailable = "language_unavailable";
    public const string LanguageTimeout = "language_timeout";
    public const string QuestionInvalid = "question_invalid";
    public const string SiteTimeZoneAmbiguous = "site_time_zone_ambiguous";

    public const int MaximumQuestionLength = 500;

    public const string LanguageUnavailableMessage =
        "Ask MAVI is not available: no language model is bound on this installation, or it is not answering.";

    public static string ModelRefusalMessage(string reason) => reason switch
    {
        OutsideContract =>
            "Ask MAVI answers only what a structured query can express: counts, lists, groups, time buckets, " +
            "rankings and comparisons of Tracks and Events, by time, camera, class, zone, line, attributes and plate text.",
        UnknownReference =>
            "The question names a camera, zone or line that is not configured on this site.",
        _ => throw new ArgumentOutOfRangeException(nameof(reason)),
    };
}
