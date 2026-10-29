using System.Text.Json;
using Mavi.Application.Modules.Faces;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Faces;
using Mavi.Domain.Intelligence;
using Microsoft.EntityFrameworkCore;
using Pgvector;
using Pgvector.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The operator side of ADR-022 against PostgreSQL. Searches are exact and deterministic (no ANN index, as ADR-021
/// §4): candidates are the shared base Track candidates of a snapshot, joined to the pinned identity's published face
/// analysis of each run, and each Track ranks by its best face. Mutations save on the request's context and never open
/// their own transaction, so the caller's audit transaction covers them.
/// </summary>
public sealed class FaceRepository(MaviDbContext db, TimeProvider timeProvider) : IFaceRepository
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    public async Task<int?> SetCameraFaceAnalysisAsync(Guid cameraId, bool enabled, CancellationToken cancellationToken)
    {
        var camera = await db.Cameras.SingleOrDefaultAsync(x => x.Id == cameraId, cancellationToken);
        if (camera is null) return null;
        camera.SetFaceAnalysis(enabled, timeProvider.GetUtcNow());
        await db.SaveChangesAsync(cancellationToken);
        if (enabled) return 0;
        // Opting out deletes the camera's face analyses; their outcomes, faces and vectors cascade (ADR-022 §3, §5).
        return await db.FaceAnalyses.Where(x => x.CameraId == cameraId).ExecuteDeleteAsync(cancellationToken);
    }

    public async Task<TrackFacesView?> GetTrackFacesAsync(Guid trackId, string identityFingerprint, CancellationToken cancellationToken)
    {
        var track = await (
                from item in db.Tracks.AsNoTracking()
                where item.Id == trackId
                join video in db.VideoAssets.AsNoTracking() on item.VideoAssetId equals video.Id
                join camera in db.Cameras.AsNoTracking() on video.CameraId equals camera.Id
                select new { item.Id, item.ObjectClass, item.ProcessingRunId, camera.FaceAnalysisEnabled })
            .SingleOrDefaultAsync(cancellationToken);
        if (track is null) return null;
        if (track.ObjectClass != ObjectClass.Person) return new TrackFacesView(FaceStates.NotPerson, null, []);
        if (!track.FaceAnalysisEnabled) return new TrackFacesView(FaceStates.NotEnabled, null, []);

        var unit = await db.FaceAnalyses.AsNoTracking()
            .Where(x => x.ProcessingRunId == track.ProcessingRunId && x.IdentityFingerprint == identityFingerprint)
            .Select(x => new { x.Id, x.Status, x.FailureCode })
            .SingleOrDefaultAsync(cancellationToken);
        if (unit is null) return new TrackFacesView(FaceStates.NotAnalysed, null, []);
        if (unit.Status == FaceAnalysisStatus.Failed) return new TrackFacesView(FaceStates.Failed, unit.FailureCode, []);
        if (unit.Status != FaceAnalysisStatus.Completed) return new TrackFacesView(FaceStates.Pending, null, []);

        var outcome = await db.FaceTrackOutcomes.AsNoTracking()
            .SingleOrDefaultAsync(x => x.AnalysisId == unit.Id && x.TrackId == trackId, cancellationToken);
        var faces = await (
                from face in db.FaceObservations.AsNoTracking()
                where face.AnalysisId == unit.Id && face.TrackId == trackId
                join observation in db.Observations.AsNoTracking() on face.ObservationId equals observation.Id
                orderby observation.EvidenceRank, face.Score descending, face.Id
                select new { face, observation.ThumbnailArtifactId })
            .ToListAsync(cancellationToken);
        var views = faces.Select(item => new TrackFace(item.face.Id, item.face.ObservationId, item.ThumbnailArtifactId,
            new FaceBox(item.face.BoxX, item.face.BoxY, item.face.BoxWidth, item.face.BoxHeight), item.face.Landmarks,
            Math.Round(item.face.Score, 4), item.face.Usable)).ToList();
        return outcome?.Outcome == FaceLifecycle.OutcomeObserved
            ? new TrackFacesView(FaceStates.Observed, null, views)
            : new TrackFacesView(FaceStates.Unknown, outcome?.Reason ?? "no_evidence", views);
    }

    public async Task<FaceQuery> CreateQueryAsync(
        string identityFingerprint, byte[] image, string mimeType, int maximumPending, CancellationToken cancellationToken)
    {
        var waiting = await db.FaceQueries.AsNoTracking()
            .CountAsync(x => x.Image != null && (x.Status == FaceQueryStatus.Pending || x.Status == FaceQueryStatus.Running), cancellationToken);
        if (waiting >= maximumPending) throw new FaceQueryQueueFullException();
        var query = FaceQuery.Create(identityFingerprint, image, mimeType, timeProvider.GetUtcNow());
        db.FaceQueries.Add(query);
        await db.SaveChangesAsync(cancellationToken);
        return query;
    }

    public async Task<FaceQueryView?> GetQueryAsync(Guid queryId, CancellationToken cancellationToken)
    {
        var query = await db.FaceQueries.AsNoTracking()
            .Where(x => x.Id == queryId)
            .Select(x => new { x.Id, x.Status, x.FailureCode, x.FacesJson, x.CreatedAtUtc, x.PurgeAfterUtc })
            .SingleOrDefaultAsync(cancellationToken);
        if (query is null) return null;
        var faces = query.FacesJson is null ? [] : JsonSerializer.Deserialize<List<FaceQueryFace>>(query.FacesJson, Json) ?? [];
        var thumbnails = await db.FaceQueryEmbeddings.AsNoTracking()
            .Where(x => x.QueryId == queryId)
            .Select(x => new { x.FaceIndex, x.Thumbnail })
            .ToDictionaryAsync(x => x.FaceIndex, x => x.Thumbnail, cancellationToken);
        return new FaceQueryView(query.Id, query.Status, query.FailureCode, faces, thumbnails, query.CreatedAtUtc, query.PurgeAfterUtc);
    }

    public async Task<FaceSourceResolution> ResolveAsync(FaceSource source, string identityFingerprint, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(source);
        if (source.FaceId is { } faceId)
        {
            var face = await (
                    from item in db.FaceObservations.AsNoTracking()
                    where item.Id == faceId
                    join analysis in db.FaceAnalyses.AsNoTracking() on item.AnalysisId equals analysis.Id
                    join embedding in db.FaceEmbeddings.AsNoTracking() on item.Id equals embedding.FaceObservationId into embeddings
                    from embedding in embeddings.DefaultIfEmpty()
                    select new { analysis.IdentityFingerprint, analysis.Status, Embedding = embedding == null ? null : embedding.Embedding })
                .SingleOrDefaultAsync(cancellationToken);
            if (face is null) return new(null, FaceSourceCodes.NotFound);
            if (face.Embedding is null || face.IdentityFingerprint != identityFingerprint || face.Status != FaceAnalysisStatus.Completed)
                return new(null, FaceSourceCodes.NotUsable);
            return new(new ResolvedFace(face.Embedding.ToArray(), faceId, null), null);
        }

        var query = await db.FaceQueries.AsNoTracking()
            .Where(x => x.Id == source.QueryId)
            .Select(x => new { x.IdentityFingerprint, x.Status, x.FacesJson })
            .SingleOrDefaultAsync(cancellationToken);
        if (query is null) return new(null, FaceSourceCodes.NotFound);
        if (query.Status != FaceQueryStatus.Completed) return new(null, FaceSourceCodes.QueryNotReady);
        if (query.IdentityFingerprint != identityFingerprint) return new(null, FaceSourceCodes.NotUsable);
        var row = await db.FaceQueryEmbeddings.AsNoTracking()
            .SingleOrDefaultAsync(x => x.QueryId == source.QueryId && x.FaceIndex == source.FaceIndex, cancellationToken);
        if (row is not null) return new(new ResolvedFace(row.Embedding.ToArray(), null, row.Thumbnail), null);
        var count = query.FacesJson is null ? 0 : JsonSerializer.Deserialize<List<FaceQueryFace>>(query.FacesJson, Json)?.Count ?? 0;
        return new(null, source.FaceIndex < count ? FaceSourceCodes.NotUsable : FaceSourceCodes.NotFound);
    }

    public async Task<FaceRankResult> RankAsync(float[] vector, string identityFingerprint, Guid? excludeFaceId, int take,
        long? snapshotVisibilitySequence, DateTimeOffset? snapshotUtc, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(vector);
        // A search is audited (ADR-022 §6): it joins the audit's transaction when one is open, else runs in its own.
        var owned = db.Database.CurrentTransaction is null ? await db.Database.BeginTransactionAsync(cancellationToken) : null;
        try
        {
            long sequence;
            DateTimeOffset at;
            if (snapshotVisibilitySequence is { } pinned && snapshotUtc is { } pinnedAt)
            {
                sequence = pinned;
                at = pinnedAt;
            }
            else
            {
                await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
                sequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
                at = timeProvider.GetUtcNow().ToUniversalTime();
            }

            var query = new Vector(vector);
            var scope = new TrackSearchQuery(null, null, null, ObjectClass.Person, null, null, null, null, null, take);
            var candidates = AnalyticsScopeQuery.BaseCandidates(db, AnalyticsScopeRequest.From(scope), sequence);
            var ranked =
                from x in candidates
                where x.track.ObjectClass == ObjectClass.Person
                join face in db.FaceObservations.AsNoTracking() on x.track.Id equals face.TrackId
                join analysis in db.FaceAnalyses.AsNoTracking() on face.AnalysisId equals analysis.Id
                join embedding in db.FaceEmbeddings.AsNoTracking() on face.Id equals embedding.FaceObservationId
                join observation in db.Observations.AsNoTracking() on face.ObservationId equals observation.Id
                where analysis.IdentityFingerprint == identityFingerprint &&
                      analysis.Status == FaceAnalysisStatus.Completed &&
                      analysis.VisibilitySequence <= sequence &&
                      analysis.ProcessingRunId == x.track.ProcessingRunId &&
                      (excludeFaceId == null || face.Id != excludeFaceId)
                let distance = embedding.Embedding.CosineDistance(query)
                orderby distance, x.track.Id, face.Id
                select new
                {
                    TrackId = x.track.Id,
                    x.track.ProcessingRunId,
                    CameraId = x.camera.Id,
                    CameraName = x.camera.Name,
                    x.track.StartTimestampUtc,
                    Distance = distance,
                    FaceId = face.Id,
                    face.ObservationId,
                    observation.ThumbnailArtifactId,
                    face.BoxX,
                    face.BoxY,
                    face.BoxWidth,
                    face.BoxHeight,
                };
            // Every usable face of the candidates is ranked, then each Track keeps its best face. Usable faces are rare
            // in CCTV (register C5A.2), so the exact scan stays small; the ANN trigger is ADR-021 §4's.
            var rows = await ranked.ToListAsync(cancellationToken);
            if (owned is not null) await owned.CommitAsync(cancellationToken);
            var best = rows
                .GroupBy(item => item.TrackId)
                .Select(group => group.First())
                .Select(item => new FaceCandidateRow(item.TrackId, item.ProcessingRunId, item.CameraId, item.CameraName, item.StartTimestampUtc,
                    Math.Round(1.0 - item.Distance, 6), item.FaceId, item.ObservationId, item.ThumbnailArtifactId,
                    new FaceBox(item.BoxX, item.BoxY, item.BoxWidth, item.BoxHeight)))
                .OrderByDescending(item => item.Score).ThenBy(item => item.TrackId)
                .Take(take)
                .ToList();
            return new FaceRankResult(best, sequence, at);
        }
        finally
        {
            if (owned is not null) await owned.DisposeAsync();
        }
    }

    public async Task<IReadOnlyList<GalleryCandidate>> CompareGalleryAsync(
        float[] vector, string identityFingerprint, double threshold, int take, CancellationToken cancellationToken)
    {
        // The gallery is small and operator-curated: an exact in-process cosine over the identity's templates.
        var templates = await (
                from template in db.EnrolledPersonFaces.AsNoTracking()
                where template.IdentityFingerprint == identityFingerprint
                join person in db.EnrolledPersons.AsNoTracking() on template.EnrolledPersonId equals person.Id
                select new { person.Id, person.Label, template.Embedding })
            .ToListAsync(cancellationToken);
        return templates
            .Where(item => item.Embedding.Length == vector.Length)
            .GroupBy(item => item.Id)
            .Select(group => new GalleryCandidate(group.Key, group.First().Label,
                Math.Round(group.Max(item => Cosine(item.Embedding, vector)), 6)))
            .Where(item => item.Score >= threshold)
            .OrderByDescending(item => item.Score).ThenBy(item => item.EnrolledPersonId)
            .Take(take)
            .ToList();
    }

    private static double Cosine(float[] left, float[] right)
    {
        double dot = 0, a = 0, b = 0;
        for (var index = 0; index < left.Length; index++)
        {
            dot += (double)left[index] * right[index];
            a += (double)left[index] * left[index];
            b += (double)right[index] * right[index];
        }

        return a == 0 || b == 0 ? 0 : dot / Math.Sqrt(a * b);
    }

    public async Task<IReadOnlyList<GalleryEntryView>> ListGalleryAsync(CancellationToken cancellationToken)
    {
        var persons = await db.EnrolledPersons.AsNoTracking().OrderBy(x => x.Label).ThenBy(x => x.Id).ToListAsync(cancellationToken);
        var templates = await TemplatesAsync(persons.Select(x => x.Id).ToList(), cancellationToken);
        return persons.Select(person => View(person, templates[person.Id])).ToList();
    }

    public async Task<GalleryEntryView?> GetGalleryEntryAsync(Guid enrolledPersonId, CancellationToken cancellationToken)
    {
        var person = await db.EnrolledPersons.AsNoTracking().SingleOrDefaultAsync(x => x.Id == enrolledPersonId, cancellationToken);
        if (person is null) return null;
        var templates = await TemplatesAsync([person.Id], cancellationToken);
        return View(person, templates[person.Id]);
    }

    public async Task<Guid> EnrolAsync(string? label, string? note, ResolvedFace face, string identityFingerprint, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(face);
        var now = timeProvider.GetUtcNow();
        var person = EnrolledPerson.Create(label, note, now);
        db.EnrolledPersons.Add(person);
        db.EnrolledPersonFaces.Add(Template(person.Id, face, identityFingerprint, now));
        await db.SaveChangesAsync(cancellationToken);
        return person.Id;
    }

    public async Task<bool> UpdateGalleryEntryAsync(Guid enrolledPersonId, string? label, string? note, bool noteGiven, CancellationToken cancellationToken)
    {
        var person = await db.EnrolledPersons.SingleOrDefaultAsync(x => x.Id == enrolledPersonId, cancellationToken);
        if (person is null) return false;
        person.Update(label, note, noteGiven, timeProvider.GetUtcNow());
        await db.SaveChangesAsync(cancellationToken);
        return true;
    }

    public async Task<Guid?> AddTemplateAsync(Guid enrolledPersonId, ResolvedFace face, string identityFingerprint, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(face);
        var person = await db.EnrolledPersons.SingleOrDefaultAsync(x => x.Id == enrolledPersonId, cancellationToken);
        if (person is null) return null;
        var now = timeProvider.GetUtcNow();
        var template = Template(person.Id, face, identityFingerprint, now);
        db.EnrolledPersonFaces.Add(template);
        person.Update(null, null, noteGiven: false, now);
        await db.SaveChangesAsync(cancellationToken);
        return template.Id;
    }

    public async Task<bool> DeleteTemplateAsync(Guid enrolledPersonId, Guid templateId, CancellationToken cancellationToken) =>
        await db.EnrolledPersonFaces.Where(x => x.Id == templateId && x.EnrolledPersonId == enrolledPersonId)
            .ExecuteDeleteAsync(cancellationToken) == 1;

    public async Task<bool> DeleteGalleryEntryAsync(Guid enrolledPersonId, CancellationToken cancellationToken) =>
        await db.EnrolledPersons.Where(x => x.Id == enrolledPersonId).ExecuteDeleteAsync(cancellationToken) == 1;

    private static EnrolledPersonFace Template(Guid personId, ResolvedFace face, string identityFingerprint, DateTimeOffset now) =>
        face.FaceObservationId is { } observation
            ? EnrolledPersonFace.Create(personId, identityFingerprint, face.Vector, EnrolledFaceSource.Evidence, observation, null, now)
            : EnrolledPersonFace.Create(personId, identityFingerprint, face.Vector, EnrolledFaceSource.Query, null, face.Thumbnail, now);

    private async Task<ILookup<Guid, GalleryTemplateView>> TemplatesAsync(IReadOnlyList<Guid> personIds, CancellationToken cancellationToken)
    {
        var rows = await db.EnrolledPersonFaces.AsNoTracking()
            .Where(x => personIds.Contains(x.EnrolledPersonId))
            .OrderBy(x => x.CreatedAtUtc).ThenBy(x => x.Id)
            .Select(x => new { x.Id, x.EnrolledPersonId, x.SourceKind, x.SourceFaceObservationId, x.Thumbnail, x.CreatedAtUtc })
            .ToListAsync(cancellationToken);
        var faceIds = rows.Where(x => x.SourceFaceObservationId is not null).Select(x => x.SourceFaceObservationId!.Value).ToList();
        var faces = await (
                from face in db.FaceObservations.AsNoTracking()
                where faceIds.Contains(face.Id)
                join observation in db.Observations.AsNoTracking() on face.ObservationId equals observation.Id
                select new { face.Id, face.ObservationId, observation.ThumbnailArtifactId, face.BoxX, face.BoxY, face.BoxWidth, face.BoxHeight })
            .ToDictionaryAsync(x => x.Id, cancellationToken);
        return rows.ToLookup(x => x.EnrolledPersonId, x =>
        {
            // An evidence template whose run was deleted keeps its vector and loses its picture (ADR-022 §4).
            var source = x.SourceFaceObservationId is { } id && faces.TryGetValue(id, out var face) ? face : null;
            return new GalleryTemplateView(x.Id, x.SourceKind, x.SourceFaceObservationId, source?.ObservationId, source?.ThumbnailArtifactId,
                source is null ? null : new FaceBox(source.BoxX, source.BoxY, source.BoxWidth, source.BoxHeight), x.Thumbnail, x.CreatedAtUtc);
        });
    }

    private static GalleryEntryView View(EnrolledPerson person, IEnumerable<GalleryTemplateView> templates) =>
        new(person.Id, person.Label, person.Note, person.CreatedAtUtc, person.UpdatedAtUtc, templates.ToList());
}
