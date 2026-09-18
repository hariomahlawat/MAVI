namespace Mavi.Infrastructure.Storage;

internal interface ILocalMediaPathResolver
{
    string ResolveLocalPath(string storageKey);
}
