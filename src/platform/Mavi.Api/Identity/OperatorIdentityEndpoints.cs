using Mavi.Api.Deployment;
using Mavi.Application.Deployment;
using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Identity;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Identity;

/// <summary>
/// The two endpoints of S11-min that require the operator policy: who the operator is, and the
/// sample attributable mutation later slices copy (ADR-010 §8).
/// </summary>
public static class OperatorIdentityEndpoints
{
    public static IEndpointRouteBuilder MapOperatorIdentityEndpoints(this IEndpointRouteBuilder endpoints)
    {
        endpoints.MapGet("/api/system/operator", (ICurrentOperator currentOperator) =>
        {
            var actor = currentOperator.Required;
            return Results.Ok(new OperatorResponse(actor.OperatorId, actor.DisplayName, actor.IdentitySource));
        }).RequireAuthorization(OperatorPolicy.Name);

        // The operator acknowledges the deployment disclosure they were shown. The statement must be the
        // one in effect, so an acknowledgement cannot be recorded against text the host never served.
        endpoints.MapPost("/api/system/disclosure-acknowledgements", async (DisclosureAcknowledgementRequest request,
            IOptions<DeploymentOptions> deployment, IOptions<OperatorIdentityOptions> identity, IAuditWriter audit,
            CancellationToken cancellationToken) =>
        {
            var disclosure = DeploymentDisclosureReader.Read(deployment.Value, DeploymentEndpoints.BuildProfile, identity.Value);
            var receipt = await DisclosureAcknowledgement.RecordAsync(audit, disclosure, request.Statement, cancellationToken);
            return receipt is null
                ? Results.Problem(statusCode: StatusCodes.Status409Conflict, title: "disclosure_statement_mismatch",
                    detail: "The acknowledged statement is not the disclosure this host serves.")
                : Results.Json(receipt, statusCode: StatusCodes.Status201Created);
        }).RequireAuthorization(OperatorPolicy.Name);
        return endpoints;
    }

    public sealed record OperatorResponse(string OperatorId, string DisplayName, string IdentitySource);

    public sealed record DisclosureAcknowledgementRequest(string? Statement);
}
