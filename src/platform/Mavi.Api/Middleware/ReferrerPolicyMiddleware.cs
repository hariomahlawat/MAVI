namespace Mavi.Api.Middleware;

/// <summary>
/// <c>Referrer-Policy: no-referrer</c> on every response the platform serves — the API and the SPA shell and
/// assets alike (Stage 4 plan §5.5; ADR-013 item 20, owner decision 2026-10-13).
/// </summary>
/// <remarks>
/// Defence in depth: a search URL can carry plate text and a cursor in its query string, and without this
/// policy a browser would send that URL as the <c>Referer</c> of the next request, where an intermediary or
/// a request log could record it. It changes no API contract: it is a response header only.
/// </remarks>
public static class ReferrerPolicyMiddleware
{
    public const string HeaderName = "Referrer-Policy";
    public const string Policy = "no-referrer";

    public static IApplicationBuilder UseNoReferrerPolicy(this IApplicationBuilder app)
    {
        ArgumentNullException.ThrowIfNull(app);
        return app.Use(async (context, next) =>
        {
            context.Response.OnStarting(static state =>
            {
                var response = (HttpResponse)state;
                response.Headers[HeaderName] = Policy;
                return Task.CompletedTask;
            }, context.Response);
            await next(context);
        });
    }
}
