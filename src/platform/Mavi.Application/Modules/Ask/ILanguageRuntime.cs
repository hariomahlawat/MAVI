namespace Mavi.Application.Modules.Ask;

/// <summary>Greedy, seeded decoding (ADR-026 §6). The values are recorded with every answer.</summary>
public sealed record LanguageDecoding(double Temperature, int TopK, int Seed, int MaxTokens)
{
    public static LanguageDecoding Deterministic { get; } = new(0, 1, 42, 768);
}

/// <param name="Grammar">A JSON Schema the runtime turns into a decoding grammar: a generation aid, not the authority.</param>
public sealed record LanguageCompletionRequest(string Prompt, string Grammar, LanguageDecoding Decoding);

/// <param name="Truncated">The output stopped at the token limit rather than at its end.</param>
public sealed record LanguageCompletion(string Text, int PromptTokens, int GeneratedTokens, bool Truncated);

/// <summary>
/// The bound language pack and runtime, as configured by the installer and recorded by the launcher. <c>Bound</c> is false
/// when no language role is configured; every other member is then null.
/// </summary>
public sealed record LanguageRuntimeIdentity(
    bool Bound,
    string? ModelPackId,
    string? ModelId,
    string? Quantisation,
    string? RuntimeId,
    string? Device,
    string? DeviceReason)
{
    public static LanguageRuntimeIdentity Unbound { get; } = new(false, null, null, null, null, null, null);
}

/// <summary>
/// The language role (ADR-026 §3): a supervised loopback inference process. It holds no authority; its text is
/// candidate input to the translator.
/// </summary>
public interface ILanguageRuntime
{
    LanguageRuntimeIdentity Identity { get; }

    /// <summary>Whether the role answers now (a short health probe).</summary>
    Task<bool> IsAnsweringAsync(CancellationToken cancellationToken);

    /// <exception cref="LanguageRuntimeUnavailableException">The role is not bound, not answering or timed out.</exception>
    Task<LanguageCompletion> CompleteAsync(LanguageCompletionRequest request, CancellationToken cancellationToken);
}

/// <summary>The language role could not produce a completion; <see cref="Code"/> is the refusal code shown.</summary>
public sealed class LanguageRuntimeUnavailableException(string code, string message, Exception? inner = null)
    : Exception(message, inner)
{
    public string Code { get; } = code;
}

/// <summary>Used when no language role is configured: Ask refuses with <c>language_unavailable</c>.</summary>
public sealed class UnboundLanguageRuntime : ILanguageRuntime
{
    public LanguageRuntimeIdentity Identity => LanguageRuntimeIdentity.Unbound;

    public Task<bool> IsAnsweringAsync(CancellationToken cancellationToken) => Task.FromResult(false);

    public Task<LanguageCompletion> CompleteAsync(LanguageCompletionRequest request, CancellationToken cancellationToken) =>
        throw new LanguageRuntimeUnavailableException(AskCodes.LanguageUnavailable, AskCodes.LanguageUnavailableMessage);
}
