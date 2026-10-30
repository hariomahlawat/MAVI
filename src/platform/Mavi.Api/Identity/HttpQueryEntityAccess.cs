using Mavi.Application.Modules.Query;
using Microsoft.AspNetCore.Authorization;

namespace Mavi.Api.Identity;

/// <summary>
/// Whether the current request may read the structured query's Entity unit: only an operator under
/// <see cref="OperatorPolicy"/> (ADR-023 §6, §9), whichever route evaluates the query (<c>/api/query</c> or Ask MAVI).
/// Outside a request, nobody may.
/// </summary>
public sealed class HttpQueryEntityAccess(IHttpContextAccessor accessor, IAuthorizationService authorization) : IQueryEntityAccess
{
    public async Task<bool> MayReadEntitiesAsync(CancellationToken cancellationToken)
    {
        if (accessor.HttpContext is not { } context) return false;
        return (await authorization.AuthorizeAsync(context.User, context, OperatorPolicy.Name)).Succeeded;
    }
}
