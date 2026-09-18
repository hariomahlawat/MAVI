using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Contracts.Worker;

namespace Mavi.IntegrationTests;

public sealed class WorkerTimestampPrecisionTests
{
    [Theory]
    [InlineData("2026-09-09T03:00:00.1234567Z")]
    [InlineData("2026-09-09T03:00:00.11111111111111111Z")]
    public void WorkerTimestampRejectsMoreThanSixFractionalDigits(string timestampUtc)
    {
        var json = $$"""{"schemaVersion":"2.0","workerId":"gpu-sdd-01","status":"ready","timestampUtc":"{{timestampUtc}}"}""";
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<WorkerHealthContract>(json, JsonOptions()));
    }

    [Fact]
    public void WorkerTimestampAcceptsSixFractionalDigits()
    {
        const string json = """{"schemaVersion":"2.0","workerId":"gpu-sdd-01","status":"ready","timestampUtc":"2026-09-09T03:00:00.123456Z"}""";
        var contract = JsonSerializer.Deserialize<WorkerHealthContract>(json, JsonOptions());

        Assert.NotNull(contract);
        Assert.Equal(TimeSpan.Zero, contract.TimestampUtc.Offset);
    }

    [Fact]
    public void WorkerTimestampSerializerEmitsAtMostMicrosecondPrecision()
    {
        var timestamp = new DateTimeOffset(2026, 9, 9, 3, 0, 0, TimeSpan.Zero).AddTicks(1_234_567);
        var contract = new WorkerHealthContract("2.0", "gpu-sdd-01", "ready", timestamp);

        var json = JsonSerializer.Serialize(contract, JsonOptions());

        Assert.Contains("\"timestampUtc\":\"2026-09-09T03:00:00.123456Z\"", json);
        Assert.DoesNotContain(".1234567Z", json);
    }

    private static JsonSerializerOptions JsonOptions() => new(JsonSerializerDefaults.Web)
    {
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
    };
}
