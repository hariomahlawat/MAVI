using Mavi.Contracts.Worker;

namespace Mavi.Application.Tests;

/// <summary>The unverified CPU provenance shared by the completion validator tests.</summary>
internal static class VisionResultValidatorTestProvenance
{
    public static VisionRuntimeProvenanceContract Create() =>
        new(
            "rtmdet-m",
            "1",
            new string('1', 64),
            new string('2', 64),
            new string('3', 64),
            "phase1",
            "1",
            new string('4', 64),
            null,
            null,
            "unverified",
            "runtime-v1",
            new string('5', 64),
            "linux-x86_64-cpu",
            new string('6', 64),
            "mmdetection",
            new Dictionary<string, string> { ["python"] = "3.12.14", ["trackers"] = "2.6.0" },
            null,
            new VisionPlatformIdentityContract(
                "Linux", "6.8", "qualified", "x86_64", "x86_64",
                "3.12.14", "CPython", ["main", "Sep 2026"], "GCC"),
            "cpu",
            0,
            "cpu",
            null,
            "build-a",
            new string('a', 40),
            "every-frame",
            new VisionTrackerParametersContract(30, .25, .1, .2, 2, 1),
            "RGB");
}
