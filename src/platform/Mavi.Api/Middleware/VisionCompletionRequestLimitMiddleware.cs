using Mavi.Contracts.Worker;
using Microsoft.AspNetCore.Http.Features;

namespace Mavi.Api.Middleware;

public static class VisionCompletionRequestLimitMiddleware
{
    public static IApplicationBuilder UseVisionCompletionRequestLimits(this IApplicationBuilder app)
    {
        ArgumentNullException.ThrowIfNull(app);
        return app.Use(async (context, next) =>
        {
            if (IsCompletionPath(context.Request.Path))
            {
                var feature = context.Features.Get<IHttpMaxRequestBodySizeFeature>();
                if (feature is { IsReadOnly: false })
                    feature.MaxRequestBodySize = WorkerContractRules.MaximumCompletionRequestBodyBytes;

                if (context.Request.ContentLength is > WorkerContractRules.MaximumCompletionRequestBodyBytes)
                {
                    context.Response.StatusCode = StatusCodes.Status413PayloadTooLarge;
                    return;
                }
            }

            await next();
        });
    }

    private static bool IsCompletionPath(PathString path)
    {
        var value = path.Value;
        return value is not null &&
               value.StartsWith("/api/vision/jobs/", StringComparison.OrdinalIgnoreCase) &&
               value.EndsWith("/complete", StringComparison.OrdinalIgnoreCase);
    }
}
