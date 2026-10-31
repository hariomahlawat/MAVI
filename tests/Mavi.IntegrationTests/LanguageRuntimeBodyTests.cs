using Mavi.Application.Modules.Ask;
using Mavi.Infrastructure.Language;

namespace Mavi.IntegrationTests;

/// <summary>The llama-server request body (ADR-026 §6): greedy and pinned; prefix reuse only where configured (D-S10-7).</summary>
public sealed class LanguageRuntimeBodyTests
{
    private static readonly LanguageCompletionRequest Request = new("prompt", """{"type":"object"}""", LanguageDecoding.Deterministic);

    [Fact]
    public void PrefixReuseIsOffUnlessConfigured()
    {
        Assert.False(new LanguageOptions().CachePrompt);
        Assert.True((bool)LlamaServerLanguageRuntime.Body(Request, cachePrompt: true)["cache_prompt"]!);
    }

    [Fact]
    public void PrefixReuseCanBeSwitchedOffWithoutChangingDecoding()
    {
        var on = LlamaServerLanguageRuntime.Body(Request, cachePrompt: true);
        var off = LlamaServerLanguageRuntime.Body(Request, cachePrompt: false);
        Assert.False((bool)off["cache_prompt"]!);
        off.Remove("cache_prompt");
        on.Remove("cache_prompt");
        Assert.Equal(on.ToJsonString(), off.ToJsonString());
    }
}
