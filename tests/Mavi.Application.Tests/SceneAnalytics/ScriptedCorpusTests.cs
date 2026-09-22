using System.Text.Json;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Scene;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Application.Tests.SceneAnalytics;

/// <summary>
/// The parent plan's three FFmpeg-scripted videos, on the engine side: the facts
/// written down in <c>scripted-corpus-v1.json</c> are the facts the real engine
/// derives from the scripted motion.
/// </summary>
/// <remarks>
/// <para>
/// The same file drives <c>tools/vision/dev/scripted_corpus.py</c>, which generates
/// the videos and checks every frame's drawn box against the position model, and the
/// fixture worker harness, which reports exactly that box. The worker records one
/// trajectory point per detected frame at the box centre, stamped with the frame's
/// media offset. So the trajectory the real worker seals is the path built below, and
/// this proves the expectations before the Development-machine run uses them.
/// </para>
/// <para>
/// What this does <b>not</b> prove is the worker path itself — decode, detection
/// association, sealing and the analytics host over real files. That is the
/// Development-machine run, and it is recorded separately rather than implied here.
/// </para>
/// </remarks>
public sealed class ScriptedCorpusTests
{
    private static readonly JsonDocument Spec =
        JsonDocument.Parse(File.ReadAllText(TrajectoryDecoderTests.FixturePath("scripted-corpus-v1.json")));

    public static TheoryData<string> Scenarios()
    {
        var data = new TheoryData<string>();
        foreach (var scenario in Spec.RootElement.GetProperty("scenarios").EnumerateArray())
        {
            data.Add(scenario.GetProperty("id").GetString()!);
        }

        return data;
    }

    [Fact]
    public void TheCorpusIsTheThreeScenariosThePlanNames() =>
        Assert.Equal(
            ["line-crossing", "zone-dwell-exit", "stationary-then-depart"],
            Spec.RootElement.GetProperty("scenarios").EnumerateArray().Select(s => s.GetProperty("id").GetString()));

    [Theory]
    [MemberData(nameof(Scenarios))]
    public void TheEngineDerivesTheScriptedFacts(string id)
    {
        var scenario = Spec.RootElement.GetProperty("scenarios").EnumerateArray()
            .Single(candidate => candidate.GetProperty("id").GetString() == id);
        var expected = scenario.GetProperty("expected");
        var revision = Revision(scenario.GetProperty("scene"));
        var zones = revision.Zones.ToDictionary(zone => zone.Name, zone => zone.ZoneId);
        var lines = revision.TripLines.ToDictionary(line => line.Name, line => line.LineId);

        var result = SceneAnalysisEngine.Analyse(
            ScriptedPath(scenario), revision, ObjectClass.Person, SceneAnalyticsParameters.Default);

        Assert.Equal(expected.GetProperty("sampleCount").GetInt32(), result.SampleCount);
        Assert.Equal(0, result.GapCount);

        var expectedVisits = expected.GetProperty("zoneVisits").EnumerateArray().ToList();
        Assert.Equal(expectedVisits.Count, result.ZoneVisits.Count);
        foreach (var (visit, actual) in expectedVisits.Zip(result.ZoneVisits))
        {
            Assert.Equal(zones[visit.GetProperty("zone").GetString()!], actual.ZoneId);
            AssertIn(visit.GetProperty("entryOffsetMs"), actual.EntryOffsetMs);
            AssertIn(visit.GetProperty("exitOffsetMs"), actual.ExitOffsetMs);
            AssertIn(visit.GetProperty("dwellMs"), actual.DwellMs);
            Assert.Equal(visit.GetProperty("beganInside").GetBoolean(), actual.BeganInside);
            Assert.Equal(visit.GetProperty("endedInside").GetBoolean(), actual.EndedInside);
        }

        if (expected.TryGetProperty("loitering", out var loitering))
        {
            foreach (var zone in loitering.EnumerateObject())
            {
                var summary = result.ZoneSummaries.Single(entry => entry.ZoneId == zones[zone.Name]);
                Assert.Equal(zone.Value.GetBoolean(), summary.Loitering);
            }
        }

        var expectedCrossings = expected.GetProperty("lineCrossings").EnumerateArray().ToList();
        Assert.Equal(expectedCrossings.Count, result.LineCrossings.Count);
        foreach (var (crossing, actual) in expectedCrossings.Zip(result.LineCrossings))
        {
            Assert.Equal(lines[crossing.GetProperty("line").GetString()!], actual.LineId);
            Assert.Equal(crossing.GetProperty("direction").GetString(), actual.Direction);
            AssertIn(crossing.GetProperty("offsetMs"), actual.OffsetMs);
        }

        Assert.Equal(expected.GetProperty("heading").GetString(), result.Motion.Heading);

        var expectedStationary = expected.GetProperty("stationaryIntervals").EnumerateArray().ToList();
        Assert.Equal(expectedStationary.Count, result.Motion.StationaryIntervals.Count);
        foreach (var (interval, actual) in expectedStationary.Zip(result.Motion.StationaryIntervals))
        {
            AssertIn(interval.GetProperty("startOffsetMs"), actual.StartOffsetMs);
            AssertIn(interval.GetProperty("endOffsetMs"), actual.EndOffsetMs);
        }
    }

    /// <summary>
    /// The worker's trajectory for a scripted video: the box centre on every detection
    /// frame, in whole pixels rounded half up — the same model the generator draws and
    /// the frame-by-frame verifier checks — stamped at the frame's media offset.
    /// </summary>
    private static List<TrajectorySample> ScriptedPath(JsonElement scenario)
    {
        var video = Spec.RootElement.GetProperty("video");
        var width = video.GetProperty("width").GetDouble();
        var height = video.GetProperty("height").GetDouble();
        var fps = video.GetProperty("fps").GetInt32();
        var keys = scenario.GetProperty("centreKeyframes").EnumerateArray()
            .Select(key => (Frame: key[0].GetInt32(), X: key[1].GetDouble(), Y: key[2].GetDouble()))
            .ToList();

        var samples = new List<TrajectorySample>();
        for (var frame = video.GetProperty("firstDetectionFrame").GetInt32();
             frame <= video.GetProperty("lastDetectionFrame").GetInt32();
             frame++)
        {
            var segment = Enumerable.Range(0, keys.Count - 1).First(i => keys[i].Frame <= frame && frame <= keys[i + 1].Frame);
            var (from, to) = (keys[segment], keys[segment + 1]);
            var share = to.Frame == from.Frame ? 0 : (double)(frame - from.Frame) / (to.Frame - from.Frame);
            var x = Math.Floor(from.X + ((to.X - from.X) * share) + 0.5);
            var y = Math.Floor(from.Y + ((to.Y - from.Y) * share) + 0.5);
            samples.Add(new TrajectorySample(frame * 1000L / fps, NormalizedPoint.FromRounded(x / width, y / height)));
        }

        return samples;
    }

    private static SceneConfigurationRevision Revision(JsonElement scene) =>
        SceneFixture.Revision(
            zones: scene.GetProperty("zones").EnumerateArray().Select(zone => new SceneZoneDraft(
                null,
                zone.GetProperty("name").GetString(),
                null,
                true,
                [.. zone.GetProperty("vertices").EnumerateArray().Select(Point)],
                zone.GetProperty("loiteringThresholdSeconds").GetInt32())),
            lines: scene.GetProperty("tripLines").EnumerateArray().Select(line => new TripLineDraft(
                null,
                line.GetProperty("name").GetString(),
                true,
                Point(line.GetProperty("a")),
                Point(line.GetProperty("b")),
                true,
                line.GetProperty("aToBLabel").GetString(),
                line.GetProperty("bToALabel").GetString())));

    private static ScenePointDraft Point(JsonElement point) => new(point[0].GetDouble(), point[1].GetDouble());

    private static void AssertIn(JsonElement bracket, long actual) =>
        Assert.InRange(actual, bracket[0].GetInt64(), bracket[1].GetInt64());
}
