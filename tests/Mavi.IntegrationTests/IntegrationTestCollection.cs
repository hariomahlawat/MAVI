namespace Mavi.IntegrationTests;

// Database test serialization
[CollectionDefinition(Name, DisableParallelization = true)]
public sealed class DatabaseIntegrationGroup : ICollectionFixture<PostgresFixture>
{
    public const string Name = "PostgreSQL integration";
}
