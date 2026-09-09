namespace Mavi.Application.Abstractions.Time;

public interface ITimeZoneService
{
    bool IsValidIanaTimeZoneId(string? timeZoneId);
    TimeZoneInfo GetTimeZone(string timeZoneId);
    DateTimeOffset ConvertLocalToUtc(DateTime localDateTime, string timeZoneId);
    DateTimeOffset ConvertUtcToZone(DateTimeOffset utcInstant, string timeZoneId);
    bool IsAmbiguous(DateTime localDateTime, string timeZoneId);
    bool IsInvalid(DateTime localDateTime, string timeZoneId);
    TimeSpan GetUtcOffset(DateTime localDateTime, string timeZoneId);
}

public sealed class MaviTimeZoneException(string code, string message, Exception? innerException = null)
    : Exception(message, innerException)
{
    public string Code { get; } = code;
}
