using Mavi.Application.Modules.Ask;
using Mavi.Contracts.Api.Ask;

namespace Mavi.Api.Endpoints;

/// <summary>
/// Ask MAVI (ADR-026 §7): <c>POST /api/ask</c> translates one question into one structured query or a refusal and returns
/// the S9 envelope unchanged; <c>GET /api/ask/status</c> says whether the language role can answer. Read-only; the
/// question is not stored. A refusal is a normal 200 response with <c>outcome: refused</c>, so the surface shows it as
/// an answer the operator can read, not as an error.
/// </summary>
public static class AskEndpoints
{
    public static IEndpointRouteBuilder MapAskEndpoints(this IEndpointRouteBuilder endpoints)
    {
        endpoints.MapPost("/api/ask", AskAsync);
        endpoints.MapGet("/api/ask/status", StatusAsync);
        return endpoints;
    }

    private static async Task<IResult> AskAsync(AskRequest request, AskService service, CancellationToken cancellationToken) =>
        Results.Ok(await service.AskAsync(request, cancellationToken));

    private static async Task<IResult> StatusAsync(AskService service, CancellationToken cancellationToken) =>
        Results.Ok(await service.StatusAsync(cancellationToken));
}
