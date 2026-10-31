using System.Globalization;

namespace Mavi.Application.Modules.Ask;

/// <summary>
/// The site's time for one question (ADR-026 §4): its IANA zone and the reference date that "today" means. The model
/// writes site-local instants with the zone's explicit offset; the translator checks each offset against
/// <see cref="OffsetAt"/> and converts to UTC. The prompt states the offset at the reference date's midnight.
/// </summary>
public sealed record AskSiteTime
{
    private readonly TimeZoneInfo zone;

    public AskSiteTime(string timeZoneId, DateOnly referenceDate)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(timeZoneId);
        zone = TimeZoneInfo.FindSystemTimeZoneById(timeZoneId);
        TimeZoneId = timeZoneId;
        ReferenceDate = referenceDate;
        Offset = zone.GetUtcOffset(referenceDate.ToDateTime(TimeOnly.MinValue, DateTimeKind.Unspecified));
        var noon = new DateTimeOffset(referenceDate.ToDateTime(new TimeOnly(12, 0), DateTimeKind.Utc));
        Offsets = Enumerable.Range(-OffsetDaysBefore, OffsetDaysBefore + OffsetDaysAfter + 1)
            .Select(day => zone.GetUtcOffset(noon.AddDays(day).UtcDateTime))
            .Append(Offset)
            .Distinct()
            .Order()
            .ToList();
    }

    private const int OffsetDaysBefore = 366;
    private const int OffsetDaysAfter = 2;

    public string TimeZoneId { get; }

    public DateOnly ReferenceDate { get; }

    /// <summary>The zone's offset at the reference date's local midnight.</summary>
    public TimeSpan Offset { get; }

    /// <summary>The offset as ISO 8601 writes it: <c>+05:30</c>, <c>-04:00</c>, <c>+00:00</c>.</summary>
    public string OffsetText => FormatOffset(Offset);

    /// <summary>
    /// Every offset the zone uses from 366 days before the reference date to 2 days after it, ascending (prompt v2,
    /// m8): a question may name any day of the past year, and in a zone with daylight saving those days carry two
    /// offsets. The translator still checks each instant's offset against the zone at that instant.
    /// </summary>
    public IReadOnlyList<TimeSpan> Offsets { get; }

    public TimeSpan OffsetAt(DateTimeOffset instant) => zone.GetUtcOffset(instant.UtcDateTime);

    /// <summary>The offset of a site-local wall-clock time (for an ambiguous or skipped local time, the zone's standard offset).</summary>
    public TimeSpan OffsetAtLocal(DateTime local) =>
        zone.IsInvalidTime(local) || zone.IsAmbiguousTime(local) ? zone.BaseUtcOffset : zone.GetUtcOffset(local);

    /// <summary>The site's current date, for a question that names none.</summary>
    public static DateOnly Today(string timeZoneId, DateTimeOffset nowUtc) =>
        DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(nowUtc, TimeZoneInfo.FindSystemTimeZoneById(timeZoneId)).DateTime);

    public static string FormatOffset(TimeSpan offset)
    {
        var sign = offset < TimeSpan.Zero ? "-" : "+";
        var magnitude = offset.Duration();
        return string.Create(CultureInfo.InvariantCulture, $"{sign}{magnitude.Hours:00}:{magnitude.Minutes:00}");
    }
}
