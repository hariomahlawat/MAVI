using Mavi.Application.Abstractions.Time;

namespace Mavi.Infrastructure.Time;

public sealed class SystemTimeZoneService : ITimeZoneService
{
    // Portable identifier policy
    public bool IsValidIanaTimeZoneId(string? timeZoneId)
    {
        if (string.IsNullOrWhiteSpace(timeZoneId)) return false;
        var normalized = timeZoneId.Trim();
        if (!string.Equals(timeZoneId, normalized, StringComparison.Ordinal)) return false;
        if (string.Equals(normalized, "UTC", StringComparison.Ordinal)) return true;
        if (!TimeZoneInfo.TryConvertIanaIdToWindowsId(normalized, out _)) return false;
        try { _ = TimeZoneInfo.FindSystemTimeZoneById(normalized); return true; }
        catch (Exception exception) when (exception is TimeZoneNotFoundException or InvalidTimeZoneException) { return false; }
    }

    // Zone resolution
    public TimeZoneInfo GetTimeZone(string timeZoneId)
    {
        if (!IsValidIanaTimeZoneId(timeZoneId))
            throw new MaviTimeZoneException("timezone_invalid", "The time zone must be a recognized IANA identifier.");
        try { return TimeZoneInfo.FindSystemTimeZoneById(timeZoneId); }
        catch (Exception exception) when (exception is TimeZoneNotFoundException or InvalidTimeZoneException)
        { throw new MaviTimeZoneException("timezone_invalid", "The time zone is not recognized.", exception); }
    }

    // Explicit conversions
    public DateTimeOffset ConvertLocalToUtc(DateTime localDateTime, string timeZoneId)
    {
        if (localDateTime.Kind != DateTimeKind.Unspecified)
            throw new MaviTimeZoneException("local_time_kind_invalid", "Local wall-clock time must have unspecified kind.");
        var zone = GetTimeZone(timeZoneId);
        if (zone.IsAmbiguousTime(localDateTime) || zone.IsInvalidTime(localDateTime))
            throw new MaviTimeZoneException("local_time_invalid", "Local wall-clock time is invalid or ambiguous.");
        return new DateTimeOffset(TimeZoneInfo.ConvertTimeToUtc(localDateTime, zone), TimeSpan.Zero);
    }

    public DateTimeOffset ConvertUtcToZone(DateTimeOffset utcInstant, string timeZoneId) =>
        TimeZoneInfo.ConvertTime(utcInstant, GetTimeZone(timeZoneId));
    public bool IsAmbiguous(DateTime localDateTime, string timeZoneId) => GetTimeZone(timeZoneId).IsAmbiguousTime(localDateTime);
    public bool IsInvalid(DateTime localDateTime, string timeZoneId) => GetTimeZone(timeZoneId).IsInvalidTime(localDateTime);
    public TimeSpan GetUtcOffset(DateTime localDateTime, string timeZoneId) => GetTimeZone(timeZoneId).GetUtcOffset(localDateTime);
}
