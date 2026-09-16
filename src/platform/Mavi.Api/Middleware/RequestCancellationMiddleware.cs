namespace Mavi.Api.Middleware;

/// <summary>
/// Treats client-aborted HTTP requests as normal cancellation rather than application failures.
/// The request cancellation token is intentionally propagated through EF Core/Npgsql and other
/// asynchronous operations; those layers should remain cancellation-aware.
/// </summary>
public static class RequestCancellationMiddleware
{
    public static IApplicationBuilder UseMaviRequestCancellationHandling(this IApplicationBuilder app)
    {
        ArgumentNullException.ThrowIfNull(app);

        return app.Use(async (context, next) =>
        {
            try
            {
                await next();
            }
            catch (OperationCanceledException) when (context.RequestAborted.IsCancellationRequested)
            {
                // The client disconnected, navigated away, or deliberately cancelled the request.
                // There is no useful response left to write. Swallow only request-abort cancellation;
                // all other cancellation and application exceptions continue through normal handling.
            }
        });
    }
}
