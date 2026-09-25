using System.Security.Cryptography;
using System.Text;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// The measured storage class of the B3 harness host identity (F4 plan §17.2, §18.3): the same
/// rules as <c>tools/qualification/s1_memory.py storage_class</c>, never a typed-in value.
/// </summary>
public sealed class S1StorageClassTests
{
    private static string Tree(string name, string? rotational, string? partition)
    {
        var root = Path.Combine(Path.GetTempPath(), $"mavi-storage-{Guid.NewGuid():N}");
        var disk = Path.Combine(root, "sys", "devices", "virtual", "block", name);
        Directory.CreateDirectory(Path.Combine(disk, "queue"));
        if (rotational is not null) File.WriteAllText(Path.Combine(disk, "queue", "rotational"), rotational + "\n");
        var target = partition is null ? disk : Path.Combine(disk, partition);
        Directory.CreateDirectory(target);
        Directory.CreateDirectory(Path.Combine(root, "sys", "dev", "block"));
        Directory.CreateSymbolicLink(Path.Combine(root, "sys", "dev", "block", "8:1"), target);
        File.WriteAllText(Path.Combine(root, "mountinfo"),
            "22 1 254:0 / / rw,relatime shared:1 - ext4 /dev/vda rw\n40 22 8:1 / /data rw,relatime shared:9 - ext4 /dev/sda1 rw\n");
        return root;
    }

    [LinuxOnlyTheory]
    [InlineData("sda", "0", "sda1", "ssd")]
    [InlineData("sda", "1", "sda1", "hdd")]
    [InlineData("nvme0n1", "0", "nvme0n1p1", "nvme")]
    [InlineData("vdb", "1", null, "virtual")]
    [InlineData("xvdb", "0", null, "virtual")]
    [InlineData("sda", null, "sda1", "unknown")]
    public void TheLinuxClassIsReadFromTheMountsBlockDevice(string name, string? rotational, string? partition, string expected)
    {
        var root = Tree(name, rotational, partition);
        try
        {
            var (storage, evidence) = S1QualificationSupport.LinuxStorageClass("/data/staging", Path.Combine(root, "mountinfo"), Path.Combine(root, "sys"));
            Assert.Equal(expected, storage);
            Assert.Contains("mount /data fstype=ext4", evidence, StringComparison.Ordinal);
            Assert.Contains(name, evidence, StringComparison.Ordinal);
            // An unmatched path under a longer-named sibling is not that mount.
            Assert.Equal("unknown", S1QualificationSupport.LinuxStorageClass("/datastore", Path.Combine(root, "mountinfo"), Path.Combine(root, "sys")).Class);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private const string GetPhysicalDisk = "DeviceId  : 0\nMediaType : SSD\nBusType   : NVMe\n\nDeviceId  : 1\nMediaType : HDD\nBusType   : SATA\n\nDeviceId  : 2\nMediaType : SSD\nBusType   : SATA\n";

    [Theory]
    [InlineData("0", "nvme")]
    [InlineData("1", "hdd")]
    [InlineData("2", "ssd")]
    [InlineData("9", "unknown")]
    public void TheWindowsClassIsReadFromRetainedGetPhysicalDiskOutput(string device, string expected)
    {
        var file = Path.Combine(Path.GetTempPath(), $"mavi-disk-{Guid.NewGuid():N}.txt");
        File.WriteAllText(file, GetPhysicalDisk);
        try
        {
            var (storage, evidence) = S1QualificationSupport.WindowsStorageClass(file, device);
            Assert.Equal(expected, storage);
            Assert.Contains(Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(GetPhysicalDisk))), evidence, StringComparison.Ordinal);
            Assert.Equal("unknown", S1QualificationSupport.WindowsStorageClass(null, device).Class);
            Assert.Equal("unknown", S1QualificationSupport.WindowsStorageClass(file, null).Class);
        }
        finally
        {
            File.Delete(file);
        }
    }
}

/// <summary>A theory that runs only on Linux and is reported skipped elsewhere, never passed.</summary>
public sealed class LinuxOnlyTheoryAttribute : TheoryAttribute
{
    public LinuxOnlyTheoryAttribute()
    {
        if (!OperatingSystem.IsLinux()) Skip = "reads a synthetic Linux sysfs tree";
    }
}
