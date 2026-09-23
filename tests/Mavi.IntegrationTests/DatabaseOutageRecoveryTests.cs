using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// Plan §11, "PostgreSQL restart/reconnect": while the database is unreachable the two
/// analytics routes fail closed — no answer, nothing internal on the wire — and once it
/// is back the same API process answers exactly as it did before, with no restart.
/// </summary>
/// <remarks>
/// The database is taken away by a relay the API connects through, not by stopping the
/// shared test server: the relay drops every live connection, as a server restart does,
/// and then refuses new ones until it is restored. Nothing here waits on time; each
/// transition is complete before the next request is sent.
///
/// The API runs on Kestrel rather than TestServer because TestServer hands an unhandled
/// server exception to the test's client instead of producing the response a browser
/// would receive, and that response is exactly what this test is about.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class DatabaseOutageRecoveryTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    private const string From = "2026-09-21T04:00:00Z";
    private const string To = "2026-09-21T07:00:00Z";

    [Fact]
    public async Task TheAnalyticsRoutesFailClosedWhileTheDatabaseIsDownAndAnswerTheSameOnceItIsBack()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await world.AttachTrajectoryAsync(TrajectoryPayload.Encode(
        [
            (0L, 0.10, 0.10),
            (2_000L, 0.50, 0.50),
        ]));

        var target = new NpgsqlConnectionStringBuilder(fixture.ConnectionString);
        await using var relay = PostgresRelay.Start(target.Host!, target.Port);
        var throughRelay = new NpgsqlConnectionStringBuilder(fixture.ConnectionString)
        {
            Host = "127.0.0.1",
            Port = relay.Port,
        }.ConnectionString;

        await using var factory = new ApiTestFactory
        {
            Clock = world.Clock,
            EnableSceneAnalyticsHost = false,
            MediaRootOverride = world.MediaRoot,
            EvidenceRootOverride = world.EvidenceRoot,
            OverrideServices = services =>
            {
                services.RemoveAll<DbContextOptions<MaviDbContext>>();
                services.AddDbContext<MaviDbContext>(options =>
                    options.UseNpgsql(throughRelay, npgsql => npgsql.UseVector()));
            },
        };
        factory.UseKestrel(0);
        factory.StartServer();
        using var client = factory.CreateClient();

        var aggregates = $"/api/cameras/{world.CameraId}/analytics/aggregates?fromUtc={From}&toUtc={To}&bucketSeconds=900";
        var heatmap = $"/api/cameras/{world.CameraId}/analytics/heatmap?fromUtc={From}&toUtc={To}";

        var aggregatesBefore = await AnswerAsync(client, aggregates);
        var heatmapBefore = await AnswerAsync(client, heatmap);
        Assert.True(relay.ConnectionsRelayed > 0, "The API did not reach the database through the relay.");

        relay.GoDown();

        foreach (var route in new[] { aggregates, heatmap })
        {
            using var response = await client.GetAsync(route);
            var body = await response.Content.ReadAsStringAsync();

            // No answer at all, rather than a partial or zero-valued one.
            Assert.True(
                (int)response.StatusCode >= 500,
                $"{route} answered {(int)response.StatusCode} while the database was unreachable: {body}");

            // Nothing about the database, the connection or the code crosses the wire.
            foreach (var secret in new[]
                     {
                         target.Host!, relay.Port.ToString(System.Globalization.CultureInfo.InvariantCulture),
                         target.Database!, target.Username!, "Npgsql", "Exception", "   at ", "Password",
                     })
            {
                Assert.DoesNotContain(secret, body, StringComparison.OrdinalIgnoreCase);
            }
        }

        relay.ComeBack();

        // The same process, never restarted: the same answer, apart from the snapshot
        // each request allocates for itself.
        Assert.Equal(aggregatesBefore, await AnswerAsync(client, aggregates));
        Assert.Equal(heatmapBefore, await AnswerAsync(client, heatmap));
    }

    /// <summary>The 200 body, with the per-request snapshot sequence removed.</summary>
    private static async Task<string> AnswerAsync(HttpClient client, string route)
    {
        using var response = await client.GetAsync(route);
        var body = await response.Content.ReadAsStringAsync();
        Assert.True(response.StatusCode == HttpStatusCode.OK, $"{route} answered {(int)response.StatusCode}: {body}");

        var answer = JsonNode.Parse(body)!.AsObject();
        Assert.True(answer.Remove("snapshotVisibilitySequence"), "The answer carried no snapshot sequence.");
        return answer.ToJsonString(new JsonSerializerOptions { WriteIndented = false });
    }

    private static async Task CommitFactsAsync(SceneAnalyticsWorld world)
    {
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            null,
            Now.AddDays(-1),
            50,
            default);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        var result = await lifecycle.CommitFactsAsync(claim!, world.Facts(claim!.AnalysisId), default);
        Assert.True(result.IsSuccess);
    }

    /// <summary>
    /// A TCP relay in front of PostgreSQL that can be taken down and brought back. Down
    /// drops every relayed connection and closes each new one on arrival; back restores
    /// relaying. The listening port never changes, so the API's connection string is the
    /// same before, during and after.
    /// </summary>
    private sealed class PostgresRelay : IAsyncDisposable
    {
        private readonly TcpListener _listener;
        private readonly string _targetHost;
        private readonly int _targetPort;
        private readonly CancellationTokenSource _stopping = new();
        private readonly ConcurrentDictionary<TcpClient, byte> _live = new();
        private readonly Task _accepting;
        private volatile bool _down;
        private int _relayed;

        private PostgresRelay(string targetHost, int targetPort)
        {
            _targetHost = targetHost;
            _targetPort = targetPort;
            _listener = new TcpListener(IPAddress.Loopback, 0);
            _listener.Start();
            _accepting = AcceptAsync();
        }

        public static PostgresRelay Start(string targetHost, int targetPort) => new(targetHost, targetPort);

        public int Port => ((IPEndPoint)_listener.LocalEndpoint).Port;

        public int ConnectionsRelayed => Volatile.Read(ref _relayed);

        public void GoDown()
        {
            _down = true;
            foreach (var connection in _live.Keys)
            {
                connection.Close();
            }
        }

        public void ComeBack() => _down = false;

        private async Task AcceptAsync()
        {
            while (!_stopping.IsCancellationRequested)
            {
                TcpClient incoming;
                try
                {
                    incoming = await _listener.AcceptTcpClientAsync(_stopping.Token);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
                catch (ObjectDisposedException)
                {
                    return;
                }

                if (_down)
                {
                    incoming.Close();
                    continue;
                }

                _ = RelayAsync(incoming);
            }
        }

        private async Task RelayAsync(TcpClient incoming)
        {
            using var outgoing = new TcpClient();
            _live.TryAdd(incoming, 0);
            _live.TryAdd(outgoing, 0);
            try
            {
                await outgoing.ConnectAsync(_targetHost, _targetPort, _stopping.Token);
                Interlocked.Increment(ref _relayed);
                var upstream = incoming.GetStream().CopyToAsync(outgoing.GetStream(), _stopping.Token);
                var downstream = outgoing.GetStream().CopyToAsync(incoming.GetStream(), _stopping.Token);
                await Task.WhenAny(upstream, downstream);
            }
            catch (Exception exception) when (exception is IOException or SocketException
                                                  or ObjectDisposedException or OperationCanceledException
                                                  or InvalidOperationException)
            {
                // A dropped connection is the point of the relay, not a failure of it.
            }
            finally
            {
                _live.TryRemove(incoming, out _);
                _live.TryRemove(outgoing, out _);
                incoming.Close();
                outgoing.Close();
            }
        }

        public async ValueTask DisposeAsync()
        {
            await _stopping.CancelAsync();
            _listener.Stop();
            foreach (var connection in _live.Keys)
            {
                connection.Close();
            }

            await _accepting;
            _stopping.Dispose();
        }
    }
}
