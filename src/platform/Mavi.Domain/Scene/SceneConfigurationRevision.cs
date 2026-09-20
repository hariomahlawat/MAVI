using Mavi.Domain.Common;

namespace Mavi.Domain.Scene;

/// <summary>
/// One immutable snapshot of a camera's whole scene: every zone and trip line as
/// they stood when the operator saved. Never edited; a change produces the next
/// revision and leaves this one exactly as it was.
/// </summary>
public sealed class SceneConfigurationRevision
{
    private readonly List<SceneZone> _zones = [];
    private readonly List<TripLine> _tripLines = [];

    private SceneConfigurationRevision() { }

    internal static SceneConfigurationRevision Create(
        Guid sceneConfigurationId,
        int revisionNumber,
        string createdBy,
        SceneRevisionDraft draft,
        SceneIdentitySet knownIdentities,
        DateTimeOffset createdAtUtc)
    {
        ArgumentNullException.ThrowIfNull(draft);
        ArgumentNullException.ThrowIfNull(knownIdentities);

        if (sceneConfigurationId == Guid.Empty || revisionNumber < 1)
        {
            throw new DomainValidationException(
                SceneErrorCodes.RevisionInvalid,
                "A revision requires a configuration and a positive revision number.");
        }

        if (string.IsNullOrWhiteSpace(createdBy) || createdBy.Length > SceneRules.MaximumCreatedByLength)
        {
            throw new DomainValidationException(
                SceneErrorCodes.RevisionInvalid,
                "A revision requires a server-controlled actor.");
        }

        var note = NormalizeNote(draft.Note);
        var (referenceVideoAssetId, referenceOffsetMs) =
            NormalizeReferenceFrame(draft.ReferenceFrameVideoAssetId, draft.ReferenceFrameOffsetMs);

        var zones = draft.Zones ?? [];
        var lines = draft.TripLines ?? [];
        if (zones.Count > SceneRules.MaximumZonesPerRevision || lines.Count > SceneRules.MaximumTripLinesPerRevision)
        {
            throw new DomainValidationException(
                SceneErrorCodes.GeometryCount,
                $"A revision may carry at most {SceneRules.MaximumZonesPerRevision} zones and " +
                $"{SceneRules.MaximumTripLinesPerRevision} trip lines.");
        }

        var revision = new SceneConfigurationRevision
        {
            Id = Guid.CreateVersion7(),
            SceneConfigurationId = sceneConfigurationId,
            RevisionNumber = revisionNumber,
            CreatedBy = createdBy,
            Note = note,
            ReferenceFrameVideoAssetId = referenceVideoAssetId,
            ReferenceFrameOffsetMs = referenceOffsetMs,
            CreatedAtUtc = createdAtUtc.ToUniversalTime(),
        };

        var usedIdentities = new HashSet<Guid>();
        var zoneNames = new HashSet<string>(SceneRules.NameComparer);
        foreach (var zoneDraft in zones)
        {
            var zoneId = ResolveIdentity(zoneDraft.ZoneId, knownIdentities.ZoneIds, usedIdentities);
            var zone = SceneZone.Create(
                revision.Id,
                zoneId,
                zoneDraft.Name,
                ParseZoneKind(zoneDraft.Kind),
                zoneDraft.Enabled,
                zoneDraft.Vertices,
                zoneDraft.LoiteringThresholdSeconds);
            if (!zoneNames.Add(zone.Name))
            {
                throw new DomainValidationException(
                    SceneErrorCodes.ZoneNameDuplicate,
                    $"Zone name '{zone.Name}' is used more than once in this revision.");
            }

            revision._zones.Add(zone);
        }

        var lineNames = new HashSet<string>(SceneRules.NameComparer);
        foreach (var lineDraft in lines)
        {
            var lineId = ResolveIdentity(lineDraft.LineId, knownIdentities.LineIds, usedIdentities);
            var line = TripLine.Create(
                revision.Id,
                lineId,
                lineDraft.Name,
                lineDraft.Enabled,
                lineDraft.A,
                lineDraft.B,
                lineDraft.Directed,
                lineDraft.AToBLabel,
                lineDraft.BToALabel);
            if (!lineNames.Add(line.Name))
            {
                throw new DomainValidationException(
                    SceneErrorCodes.LineNameDuplicate,
                    $"Trip line name '{line.Name}' is used more than once in this revision.");
            }

            revision._tripLines.Add(line);
        }

        return revision;
    }

    public Guid Id { get; private set; }

    public Guid SceneConfigurationId { get; private set; }

    /// <summary>1 for the first save, incrementing by one per save.</summary>
    public int RevisionNumber { get; private set; }

    public DateTimeOffset CreatedAtUtc { get; private set; }

    /// <summary>Server-controlled; see <see cref="SceneRules.UnattributedDevelopmentActor"/>.</summary>
    public string CreatedBy { get; private set; } = string.Empty;

    public string? Note { get; private set; }

    public Guid? ReferenceFrameVideoAssetId { get; private set; }

    /// <summary>Media-relative offset of the still the operator drew on.</summary>
    public long? ReferenceFrameOffsetMs { get; private set; }

    public IReadOnlyList<SceneZone> Zones => _zones;

    public IReadOnlyList<TripLine> TripLines => _tripLines;

    /// <summary>
    /// False exactly when nothing in the revision is enabled, which is how an
    /// operator deliberately switches analytics off for the camera (ADR-011).
    /// Derived from the geometry rather than stored, so the two cannot disagree.
    /// </summary>
    public bool AnalyticsEnabled =>
        _zones.Exists(zone => zone.Enabled) || _tripLines.Exists(line => line.Enabled);

    private static Guid ResolveIdentity(Guid? supplied, IReadOnlySet<Guid> known, HashSet<Guid> used)
    {
        if (supplied is not { } identity)
        {
            // A new object always receives a server-issued identity; a caller can
            // never mint one, which is what keeps the stable-identity set honest.
            var issued = Guid.CreateVersion7();
            used.Add(issued);
            return issued;
        }

        if (identity == Guid.Empty || !known.Contains(identity))
        {
            throw new DomainValidationException(
                SceneErrorCodes.IdentityUnknown,
                "A supplied zone or trip line identity does not belong to the active revision.");
        }

        if (!used.Add(identity))
        {
            throw new DomainValidationException(
                SceneErrorCodes.IdentityDuplicate,
                "A zone or trip line identity was supplied more than once in this revision.");
        }

        return identity;
    }

    private static SceneZoneKind ParseZoneKind(string? kind)
    {
        if (string.IsNullOrWhiteSpace(kind))
        {
            return SceneZoneKind.General;
        }

        // Ordinal, case-sensitive: the wire vocabulary is closed and exact.
        return Enum.TryParse<SceneZoneKind>(kind.Trim(), ignoreCase: false, out var parsed) && Enum.IsDefined(parsed)
            ? parsed
            : throw new DomainValidationException(SceneErrorCodes.ZoneKindInvalid, "Unknown zone kind.");
    }

    private static string? NormalizeNote(string? note)
    {
        if (string.IsNullOrWhiteSpace(note))
        {
            return null;
        }

        var trimmed = note.Trim();
        if (trimmed.Length > SceneRules.MaximumNoteLength)
        {
            throw new DomainValidationException(
                SceneErrorCodes.NoteTooLong,
                $"A revision note must not exceed {SceneRules.MaximumNoteLength} characters.");
        }

        return trimmed;
    }

    private static (Guid? VideoAssetId, long? OffsetMs) NormalizeReferenceFrame(Guid? videoAssetId, long? offsetMs)
    {
        // A reference frame is a video and an instant within it. Half of one identifies
        // nothing, so the pair is accepted only whole or not at all.
        if (videoAssetId is null && offsetMs is null)
        {
            return (null, null);
        }

        if (videoAssetId is null || offsetMs is null || videoAssetId == Guid.Empty)
        {
            throw new DomainValidationException(
                SceneErrorCodes.ReferenceFrameIncomplete,
                "A reference frame needs both a video asset and an offset, or neither.");
        }

        if (offsetMs < 0)
        {
            throw new DomainValidationException(
                SceneErrorCodes.ReferenceFrameOffsetInvalid,
                "A reference frame offset must not be negative.");
        }

        return (videoAssetId, offsetMs);
    }
}
