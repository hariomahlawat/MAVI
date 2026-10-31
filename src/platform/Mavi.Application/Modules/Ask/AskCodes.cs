namespace Mavi.Application.Modules.Ask;

/// <summary>The closed vocabulary of Ask MAVI outcomes, refusal stages and codes (ADR-026 §4). Every message is platform text.</summary>
public static class AskCodes
{
    /// <summary>The version of the translation document the model emits.</summary>
    public const string TranslationVersion = "mavi-ask-translation-v1";

    /// <summary>The question was translated into a proposed query; nothing has run (D-S10-10).</summary>
    public const string Interpreted = "interpreted";
    public const string Refused = "refused";

    public const string StageRuntime = "runtime";

    /// <summary>Prompt v2: the platform refused the question before the model was called (an unknown place).</summary>
    public const string StageQuestion = "question";
    public const string StageModel = "model";
    public const string StageTranslation = "translation";
    public const string StageContract = "contract";

    // Model refusals: the only reasons a model may give, with no free text.
    public const string OutsideContract = "outside_contract";
    public const string UnknownReference = "unknown_reference";
    public static readonly IReadOnlyList<string> ModelRefusalReasons = [OutsideContract, UnknownReference];

    // Translation refusals: the model's output is not a usable translation document.
    public const string ModelOutputInvalid = "model_output_invalid";
    public const string ModelOutputTruncated = "model_output_truncated";
    public const string TimeOffsetMismatch = "time_offset_mismatch";

    /// <summary>Prompt v2 (m2): the plate text the model wrote does not occur in the question.</summary>
    public const string PlateTextUngrounded = "plate_text_ungrounded";

    // Runtime and request refusals.
    public const string LanguageUnavailable = "language_unavailable";
    public const string LanguageTimeout = "language_timeout";
    public const string QuestionInvalid = "question_invalid";
    public const string SiteTimeZoneAmbiguous = "site_time_zone_ambiguous";
    public const string SiteTimeZoneInvalid = "site_time_zone_invalid";
    public const string PromptTooLong = "prompt_too_long";

    /// <summary>
    /// The largest prompt sent, in characters: about 6,400 tokens for the demo site's 12 cameras is about 25,000
    /// characters; the role's context is 8,192 tokens of which 768 are kept for the answer. A larger site is refused
    /// rather than truncated (ADR-026 §4; known limits).
    /// </summary>
    public const int MaximumPromptCharacters = 28_000;

    /// <summary>Platform text for a refusal at the translation or contract stage; never text the model wrote.</summary>
    public static string StageMessage(string stage, string code) => (stage, code) switch
    {
        (StageTranslation, TimeOffsetMismatch) => "An instant in the interpreted query does not carry the site time zone's offset.",
        (StageTranslation, PlateTextUngrounded) => "The plate text in the interpreted query is not one the question contains.",
        (StageTranslation, ModelOutputTruncated) => "The model's output stopped before the query was complete.",
        (StageTranslation, _) => "The model's output was not a usable query or refusal.",
        (StageContract, _) => $"The interpreted query is outside the query contract ({code}).",
        _ => throw new ArgumentOutOfRangeException(nameof(stage)),
    };

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
