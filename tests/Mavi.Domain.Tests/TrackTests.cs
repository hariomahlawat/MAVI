using Mavi.Domain.Intelligence;

namespace Mavi.Domain.Tests;

public sealed class TrackTests
{
    [Fact]
    public void CreateDerivesDurationAndUtcTimestamps()
    {
        var recordingStart = new DateTimeOffset(2026, 9, 8, 10, 0, 0, TimeSpan.Zero);
        var track = Track.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), 17, ObjectClass.Person,
            4_120, 21_880, recordingStart, 280, 0.88, 0.96);

        Assert.Equal(17_760, track.DurationMs);
        Assert.Equal(recordingStart.AddMilliseconds(4_120), track.StartTimestampUtc);
        Assert.Equal(recordingStart.AddMilliseconds(21_880), track.EndTimestampUtc);
        Assert.Null(track.EntityId);
    }

    private const string Source = "detector-native:4444444444444444444444444444444444444444444444444444444444444444";

    private static Track Create(ObjectClass objectClass, string? subclass, string? vocabulary, string? source) =>
        Track.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), 1, objectClass,
            0, 1_000, DateTimeOffset.UtcNow, 5, 0.8, 0.9,
            objectSubclass: subclass, objectSubclassVocabulary: vocabulary, objectSubclassSource: source);

    [Theory]
    // Person, or any Track processed before Stage 3: all three null.
    [InlineData(ObjectClass.Person, null, null, null)]
    [InlineData(ObjectClass.Vehicle, null, null, null)]
    // A Stage-3 Vehicle whose vote abstained: vocabulary and source, no value.
    [InlineData(ObjectClass.Vehicle, null, VehicleSubclass.VocabularyV1, Source)]
    // A resolved Stage-3 Vehicle: all three set.
    [InlineData(ObjectClass.Vehicle, "truck", VehicleSubclass.VocabularyV1, Source)]
    [InlineData(ObjectClass.Vehicle, "motorcycle", VehicleSubclass.VocabularyV1, Source)]
    public void TheFourSubclassStatesAreAccepted(ObjectClass objectClass, string? subclass, string? vocabulary, string? source)
    {
        var track = Create(objectClass, subclass, vocabulary, source);

        Assert.Equal(subclass, track.ObjectSubclass);
        Assert.Equal(vocabulary, track.ObjectSubclassVocabulary);
        Assert.Equal(source, track.ObjectSubclassSource);
    }

    [Theory]
    [InlineData(ObjectClass.Person, "car", VehicleSubclass.VocabularyV1, Source)]
    [InlineData(ObjectClass.Person, null, VehicleSubclass.VocabularyV1, Source)]
    [InlineData(ObjectClass.Vehicle, "truck", null, null)]
    [InlineData(ObjectClass.Vehicle, "truck", VehicleSubclass.VocabularyV1, null)]
    [InlineData(ObjectClass.Vehicle, "truck", null, Source)]
    [InlineData(ObjectClass.Vehicle, null, VehicleSubclass.VocabularyV1, null)]
    [InlineData(ObjectClass.Vehicle, null, null, Source)]
    [InlineData(ObjectClass.Vehicle, "bicycle", VehicleSubclass.VocabularyV1, Source)]
    [InlineData(ObjectClass.Vehicle, "suv", VehicleSubclass.VocabularyV1, Source)]
    [InlineData(ObjectClass.Vehicle, "truck", "mavi-vehicle-subclass-v2", Source)]
    [InlineData(ObjectClass.Vehicle, "truck", VehicleSubclass.VocabularyV1, "")]
    [InlineData(ObjectClass.Vehicle, null, VehicleSubclass.VocabularyV1, "classifier:4444444444444444444444444444444444444444444444444444444444444444")]
    [InlineData(ObjectClass.Vehicle, null, VehicleSubclass.VocabularyV1, "detector-native:4444")]
    [InlineData(ObjectClass.Vehicle, "car", VehicleSubclass.VocabularyV1, "detector-native:AAAA444444444444444444444444444444444444444444444444444444444444")]
    public void AnyOtherSubclassCombinationIsRefused(ObjectClass objectClass, string? subclass, string? vocabulary, string? source)
    {
        var error = Assert.Throws<Mavi.Domain.Common.DomainValidationException>(() => Create(objectClass, subclass, vocabulary, source));
        Assert.Equal("track_object_subclass_invalid", error.Code);
    }

    [Fact]
    public void ASourceLongerThanTheColumnIsRefused()
    {
        Assert.Throws<Mavi.Domain.Common.DomainValidationException>(() =>
            Create(ObjectClass.Vehicle, "car", VehicleSubclass.VocabularyV1, new string('a', VehicleSubclass.MaximumSourceLength + 1)));
    }

    [Fact]
    public void CreateRejectsEndBeforeStart()
    {
        Assert.ThrowsAny<Exception>(() => Track.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), 1, ObjectClass.Vehicle,
            10_000, 9_000, DateTimeOffset.UtcNow, 5, 0.8, 0.9));
    }
}
