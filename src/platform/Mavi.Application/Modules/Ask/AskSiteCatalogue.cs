namespace Mavi.Application.Modules.Ask;

/// <summary>
/// What the language model may refer to (ADR-026 §4): every camera, and the enabled zones and lines of its active scene
/// revision, by id and operator-given name. Ordered by camera code, then name, so the prompt built from it is stable.
/// Platform data, read in the request; the model only chooses among these ids.
/// </summary>
public sealed record AskSiteCatalogue(IReadOnlyList<AskCatalogueCamera> Cameras)
{
    public static AskSiteCatalogue Ordered(IEnumerable<AskCatalogueCamera> cameras) => new(
        cameras
            .Select(camera => camera with
            {
                Zones = [.. camera.Zones.OrderBy(zone => zone.Name, StringComparer.Ordinal).ThenBy(zone => zone.ZoneId)],
                Lines = [.. camera.Lines.OrderBy(line => line.Name, StringComparer.Ordinal).ThenBy(line => line.LineId)],
            })
            .OrderBy(camera => camera.Code, StringComparer.Ordinal)
            .ThenBy(camera => camera.CameraId)
            .ToList());
}

public sealed record AskCatalogueCamera(
    Guid CameraId,
    string Code,
    string Name,
    string TimeZoneId,
    IReadOnlyList<AskCatalogueZone> Zones,
    IReadOnlyList<AskCatalogueLine> Lines);

public sealed record AskCatalogueZone(Guid ZoneId, string Name, string Kind);

public sealed record AskCatalogueLine(Guid LineId, string Name, string AToBLabel, string BToALabel);

/// <summary>Reads the site catalogue: cameras and the enabled geometry of their active scene revisions.</summary>
public interface IAskCatalogueSource
{
    Task<AskSiteCatalogue> ReadAsync(CancellationToken cancellationToken);
}
