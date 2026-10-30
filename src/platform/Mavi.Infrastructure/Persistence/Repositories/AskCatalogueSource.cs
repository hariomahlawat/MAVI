using Mavi.Application.Modules.Ask;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The Ask MAVI site catalogue (ADR-026 §4): every camera, with the enabled zones and lines of its active scene revision.
/// Read-only; what an operator could see on the cameras and scene pages, nothing more.
/// </summary>
public sealed class AskCatalogueSource(MaviDbContext db) : IAskCatalogueSource
{
    public async Task<AskSiteCatalogue> ReadAsync(CancellationToken cancellationToken)
    {
        var cameras = await db.Cameras.AsNoTracking()
            .Select(camera => new { camera.Id, camera.Code, camera.Name, camera.TimeZoneId })
            .ToListAsync(cancellationToken);
        var activeRevisionIds = await db.SceneConfigurations.AsNoTracking()
            .Where(configuration => configuration.ActiveRevisionId != null)
            .Select(configuration => new { configuration.CameraId, RevisionId = configuration.ActiveRevisionId!.Value })
            .ToListAsync(cancellationToken);
        var revisionIds = activeRevisionIds.Select(item => item.RevisionId).ToArray();
        var revisions = await db.SceneConfigurationRevisions.AsNoTracking()
            .Where(revision => revisionIds.Contains(revision.Id))
            .Include(revision => revision.Zones)
            .Include(revision => revision.TripLines)
            .AsSplitQuery()
            .ToDictionaryAsync(revision => revision.Id, cancellationToken);
        var revisionByCamera = activeRevisionIds.ToDictionary(item => item.CameraId, item => revisions.GetValueOrDefault(item.RevisionId));

        return AskSiteCatalogue.Ordered(cameras.Select(camera =>
        {
            var revision = revisionByCamera.GetValueOrDefault(camera.Id);
            return new AskCatalogueCamera(
                camera.Id,
                camera.Code,
                camera.Name,
                camera.TimeZoneId,
                revision is null
                    ? []
                    : [.. revision.Zones.Where(zone => zone.Enabled).Select(zone => new AskCatalogueZone(zone.ZoneId, zone.Name, zone.Kind.ToString()))],
                revision is null
                    ? []
                    : [.. revision.TripLines.Where(line => line.Enabled).Select(line => new AskCatalogueLine(line.LineId, line.Name, line.AToBLabel, line.BToALabel))]);
        }));
    }
}
