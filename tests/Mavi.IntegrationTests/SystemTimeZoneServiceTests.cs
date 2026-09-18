using Mavi.Application.Abstractions.Time;
using Mavi.Infrastructure.Time;

namespace Mavi.IntegrationTests;

public sealed class SystemTimeZoneServiceTests
{
    private readonly SystemTimeZoneService _service = new();

    // Deterministic conversion matrix
    [Theory]
    [InlineData("Asia/Kolkata", true)]
    [InlineData("America/New_York", true)]
    [InlineData("Europe/London", true)]
    [InlineData("UTC", true)]
    [InlineData("India Standard Time", false)]
    [InlineData("Eastern Standard Time", false)]
    [InlineData("Pacific Standard Time", false)]
    [InlineData("", false)]
    [InlineData("unknown-invalid-zone", false)]
    public void ValidatesOnlyPortableIanaIdentifiers(string id, bool expected) =>
        Assert.Equal(expected, _service.IsValidIanaTimeZoneId(id));

    [Fact]
    public void ConvertsKolkataLocalToUtcAndReturnsActualOffset()
    {
        var local = new DateTime(2026, 9, 9, 14, 0, 0, DateTimeKind.Unspecified);
        Assert.Equal(new DateTimeOffset(2026, 9, 9, 8, 30, 0, TimeSpan.Zero), _service.ConvertLocalToUtc(local, "Asia/Kolkata"));
        Assert.Equal(TimeSpan.FromMinutes(330), _service.GetUtcOffset(local, "Asia/Kolkata"));
    }

    [Fact]
    public void ConvertsUtcToKolkata()
    {
        var converted = _service.ConvertUtcToZone(new DateTimeOffset(2026, 9, 9, 2, 30, 0, TimeSpan.Zero), "Asia/Kolkata");
        Assert.Equal(8, converted.Hour);
        Assert.Equal(0, converted.Minute);
    }

    [Theory]
    [InlineData(2026, 11, 1, 1, 30)]
    [InlineData(2026, 3, 8, 2, 30)]
    public void AmbiguousAndInvalidNewYorkTimesAreRejected(int year, int month, int day, int hour, int minute)
    {
        Assert.Throws<MaviTimeZoneException>(() => _service.ConvertLocalToUtc(
            new DateTime(year, month, day, hour, minute, 0, DateTimeKind.Unspecified), "America/New_York"));
    }

    [Fact]
    public void InvalidTimeZoneHasControlledSemantics() =>
        Assert.Equal("timezone_invalid", Assert.Throws<MaviTimeZoneException>(() => _service.GetTimeZone("Invalid/Mavi")).Code);
}
