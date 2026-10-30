using Mavi.Application.Modules.Ask;
using Mavi.Infrastructure.Language;

namespace Mavi.IntegrationTests;

/// <summary>The llama-server request body (ADR-026 §6): greedy and pinned, with prefix reuse on unless switched off (D-S10-7).</summary>
public sealed class LanguageRuntimeBodyTests
{
    private static readonly LanguageCompletionRequest Request = new("prompt", """{"type":"object"}""", LanguageDecoding.Deterministic);

    [Fact]
    public void PrefixReuseIsOnByDefault()
    {
        Assert.True(new LanguageOptions().CachePrompt);
        Assert.True((bool)LlamaServerLanguageRuntime.Body(Request)["cache_prompt"]!);
    }

    [Fact]
    public void PrefixReuseCanBeSwitchedOffWithoutChangingDecoding()
    {
        var on = LlamaServerLanguageRuntime.Body(Request);
        var off = LlamaServerLanguageRuntime.Body(Request, cachePrompt: false);
        Assert.False((bool)off["cache_prompt"]!);
        off.Remove("cache_prompt");
        on.Remove("cache_prompt");
        Assert.Equal(on.ToJsonString(), off.ToJsonString());
    }
}
