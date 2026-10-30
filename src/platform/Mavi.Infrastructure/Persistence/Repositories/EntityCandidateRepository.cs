using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Entities;
using Mavi.Application.Modules.Faces;
using Mavi.Domain.Embeddings;
using Mavi.Domain.Faces;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using Pgvector.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// Entity candidates and confirmed Entities (ADR-023). Candidate derivation reads the existing S4 vectors and writes
/// only <c>entity_candidates</c>; <see cref="ConfirmAsync"/> is the one place in the platform that writes
/// <c>Track.EntityId</c> (a source test enforces it).
/// </summary>
public sealed class EntityCandidateRepository(MaviDbContext db) : IEntityCandidateRepository
{
    private const string UniqueViolation = "23505";
    private const string DerivationUniqueIndex = "ux_entity_candidate_derivations_analysis_catalogue";
    private const string DerivationLockKey = "entity-candidates:derivation";

    /// <summary>Scores within this of the floor are re-checked exactly after rounding, so SQL float noise never decides.</summary>
    private const double FloorSlack = 1e-5;

    private static readonly AnalyticsScopeRequest Everything = new(null, null, null, null, null, null, null, null);

    public async Task<IReadOnlyList<Guid>> ListAnalysesAwaitingDerivationAsync(
        string identityFingerprint, EntityCandidateCatalogueDefinition catalogue, int batchSize, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(catalogue);
        var version = catalogue.CatalogueVersion;
        return await db.EmbeddingAnalyses.AsNoTracking()
            .Where(analysis => analysis.IdentityFingerprint == identityFingerprint &&
                               (analysis.Status == EmbeddingAnalysisStatus.Completed || analysis.Status == EmbeddingAnalysisStatus.Superseded) &&
                               analysis.VisibilitySequence != null &&
                               !db.EntityCandidateDerivations.Any(derivation =>
                                   derivation.EmbeddingAnalysisId == analysis.Id && derivation.CatalogueVersion == version))
            .OrderBy(analysis => analysis.VisibilitySequence)
            .ThenBy(analysis => analysis.Id)
            .Select(analysis => analysis.Id)
            .Take(batchSize)
            .ToListAsync(cancellationToken);
    }

    public async Task<(EntityCandidateDerivationOutcome Outcome, int Inserted)> DeriveAsync(
        Guid embeddingAnalysisId, string identityFingerprint, EntityCandidateCatalogueDefinition catalogue, DateTimeOffset nowUtc,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(catalogue);
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        // One lock for every derivation: of two analyses completing together, the later derivation sees both, so each
        // pair is derived by whichever of its two derivations runs second (ADR-023 §2).
        await db.Database.ExecuteSqlInterpolatedAsync(
            $"SELECT pg_advisory_xact_lock(hashtextextended({DerivationLockKey}, 0))", cancellationToken);
        var version = catalogue.CatalogueVersion;
        if (await db.EntityCandidateDerivations.AsNoTracking()
                .AnyAsync(x => x.EmbeddingAnalysisId == embeddingAnalysisId && x.CatalogueVersion == version, cancellationToken))
            return (EntityCandidateDerivationOutcome.AlreadyDerived, 0);

        var analysis = await db.EmbeddingAnalyses.AsNoTracking()
            .Where(x => x.Id == embeddingAnalysisId && x.IdentityFingerprint == identityFingerprint &&
                        (x.Status == EmbeddingAnalysisStatus.Completed || x.Status == EmbeddingAnalysisStatus.Superseded))
            .Select(x => new { x.Id, x.ProcessingRunId })
            .SingleOrDefaultAsync(cancellationToken);
        if (analysis is null) return (EntityCandidateDerivationOutcome.NotFound, 0);

        var embedded = VisibleEmbedded(identityFingerprint);
        var runVisible = await VisibleRunAsync(analysis.ProcessingRunId, cancellationToken);
        if (!runVisible)
        {
            db.EntityCandidateDerivations.Add(EntityCandidateDerivation.Create(analysis.Id, analysis.ProcessingRunId, version, catalogue.Sha256,
                identityFingerprint, EntityCandidateDerivation.OutcomeNotVisible, 0, nowUtc));
            return (await SaveDerivationAsync(transaction, cancellationToken) ? EntityCandidateDerivationOutcome.NotVisible
                : EntityCandidateDerivationOutcome.AlreadyDerived, 0);
        }

        var maximumDistance = 1.0 - catalogue.AppearanceFloor + FloorSlack;
        var scored = await (
                from left in embedded
                where left.ProcessingRunId == analysis.ProcessingRunId
                from right in embedded
                where right.TrackId != left.TrackId && right.ObjectClass == left.ObjectClass &&
                      (!catalogue.CrossCameraOnly || right.CameraId != left.CameraId) &&
                      (!catalogue.RequireSharedSite || (left.SiteCode != null && right.SiteCode == left.SiteCode))
                let distance = left.Embedding!.CosineDistance(right.Embedding!)
                where distance <= maximumDistance
                select new
                {
                    Left = new PlausibilityTrack(left.TrackId, left.CameraId, left.StartUtc, left.EndUtc, left.SiteCode),
                    Right = new PlausibilityTrack(right.TrackId, right.CameraId, right.StartUtc, right.EndUtc, right.SiteCode),
                    left.ObjectClass,
                    Distance = distance,
                })
            .ToListAsync(cancellationToken);

        var pairs = new Dictionary<(Guid Lower, Guid Higher), (PlausibilityVerdict Verdict, ObjectClass ObjectClass, double Score)>();
        foreach (var item in scored)
        {
            var score = Math.Round(1.0 - item.Distance, 6);
            if (score < catalogue.AppearanceFloor) continue;
            var key = item.Left.TrackId.CompareTo(item.Right.TrackId) < 0 ? (item.Left.TrackId, item.Right.TrackId) : (item.Right.TrackId, item.Left.TrackId);
            if (pairs.ContainsKey(key) || !EntityCandidatePlausibility.InScope(item.Left, item.Right, catalogue)) continue;
            var verdict = EntityCandidatePlausibility.Evaluate(item.Left, item.Right, catalogue);
            if (verdict.Plausible) pairs[key] = (verdict, item.ObjectClass, score);
        }

        var involved = pairs.Keys.SelectMany(key => new[] { key.Lower, key.Higher }).Distinct().ToList();
        var existing = (await db.EntityCandidates.AsNoTracking()
                .Where(x => x.CatalogueVersion == version && x.IdentityFingerprint == identityFingerprint &&
                            involved.Contains(x.LowerTrackId) && involved.Contains(x.HigherTrackId))
                .Select(x => new { x.LowerTrackId, x.HigherTrackId })
                .ToListAsync(cancellationToken))
            .Select(x => (x.LowerTrackId, x.HigherTrackId))
            .ToHashSet();

        var derivation = EntityCandidateDerivation.Create(analysis.Id, analysis.ProcessingRunId, version, catalogue.Sha256, identityFingerprint,
            EntityCandidateDerivation.OutcomeDerived, pairs.Keys.Count(key => !existing.Contains(key)), nowUtc);
        db.EntityCandidateDerivations.Add(derivation);
        foreach (var (key, value) in pairs.OrderBy(pair => pair.Key.Lower).ThenBy(pair => pair.Key.Higher))
        {
            if (existing.Contains(key)) continue;
            db.EntityCandidates.Add(EntityCandidate.Create(derivation.Id, version, identityFingerprint, key.Lower, key.Higher, value.ObjectClass,
                value.Score, value.Verdict.SameCamera, value.Verdict.GapMs, nowUtc));
        }

        return await SaveDerivationAsync(transaction, cancellationToken)
            ? (EntityCandidateDerivationOutcome.Derived, derivation.CandidateCount)
            : (EntityCandidateDerivationOutcome.AlreadyDerived, 0);
    }

    public async Task<EntityCandidatePage> ListAsync(EntityCandidateListQuery query, string identityFingerprint, string catalogueVersion,
        string? faceIdentityFingerprint, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        var rows = VisiblePairs(identityFingerprint, catalogueVersion).Where(x => x.Candidate.Status == query.Status);
        if (query.ObjectClass is { } objectClass) rows = rows.Where(x => x.Candidate.ObjectClass == objectClass);
        if (query.TrackId is { } trackId) rows = rows.Where(x => x.Candidate.LowerTrackId == trackId || x.Candidate.HigherTrackId == trackId);
        if (query.CameraId is { } camera && query.OtherCameraId is { } other)
            rows = rows.Where(x => (x.LowerCameraId == camera && x.HigherCameraId == other) || (x.LowerCameraId == other && x.HigherCameraId == camera));
        else if (query.CameraId is { } single)
            rows = rows.Where(x => x.LowerCameraId == single || x.HigherCameraId == single);

        var total = await rows.CountAsync(cancellationToken);
        var page = await rows
            .OrderByDescending(x => x.Candidate.AppearanceScore)
            .ThenBy(x => x.Candidate.LowerTrackId)
            .ThenBy(x => x.Candidate.HigherTrackId)
            .Skip(query.Offset)
            .Take(query.Limit)
            .Select(x => x.Candidate)
            .ToListAsync(cancellationToken);
        return new EntityCandidatePage(total, await ViewsAsync(page, faceIdentityFingerprint, cancellationToken));
    }

    public async Task<EntityCandidateView?> GetAsync(Guid candidateId, string? faceIdentityFingerprint, CancellationToken cancellationToken)
    {
        var candidate = await db.EntityCandidates.AsNoTracking().SingleOrDefaultAsync(x => x.Id == candidateId, cancellationToken);
        return candidate is null ? null : (await ViewsAsync([candidate], faceIdentityFingerprint, cancellationToken)).Single();
    }

    public async Task<EntityCandidateSummary> SummarizeAsync(string? identityFingerprint, string catalogueVersion, CancellationToken cancellationToken)
    {
        if (identityFingerprint is null) return new EntityCandidateSummary(catalogueVersion, null, 0, 0, []);
        var derivations = await db.EntityCandidateDerivations.AsNoTracking()
            .CountAsync(x => x.CatalogueVersion == catalogueVersion && x.IdentityFingerprint == identityFingerprint, cancellationToken);
        var pending = await db.EmbeddingAnalyses.AsNoTracking()
            .CountAsync(analysis => analysis.IdentityFingerprint == identityFingerprint &&
                                    (analysis.Status == EmbeddingAnalysisStatus.Completed || analysis.Status == EmbeddingAnalysisStatus.Superseded) &&
                                    analysis.VisibilitySequence != null &&
                                    !db.EntityCandidateDerivations.Any(derivation =>
                                        derivation.EmbeddingAnalysisId == analysis.Id && derivation.CatalogueVersion == catalogueVersion),
                cancellationToken);
        var counts = await VisiblePairs(identityFingerprint, catalogueVersion)
            .GroupBy(x => new { x.LowerCameraId, x.LowerCameraCode, x.HigherCameraId, x.HigherCameraCode, x.Candidate.ObjectClass, x.Candidate.Status })
            .Select(group => new { group.Key, Count = group.Count() })
            .ToListAsync(cancellationToken);
        var pairs = counts
            .Select(item =>
            {
                // A camera pair is unordered: the lower camera code first.
                var swap = string.CompareOrdinal(item.Key.LowerCameraCode, item.Key.HigherCameraCode) > 0;
                return new
                {
                    CameraId = swap ? item.Key.HigherCameraId : item.Key.LowerCameraId,
                    CameraCode = swap ? item.Key.HigherCameraCode : item.Key.LowerCameraCode,
                    OtherCameraId = swap ? item.Key.LowerCameraId : item.Key.HigherCameraId,
                    OtherCameraCode = swap ? item.Key.LowerCameraCode : item.Key.HigherCameraCode,
                    item.Key.ObjectClass,
                    item.Key.Status,
                    item.Count,
                };
            })
            .GroupBy(item => (item.CameraId, item.CameraCode, item.OtherCameraId, item.OtherCameraCode, item.ObjectClass))
            .Select(group => new EntityCandidatePairCount(group.Key.CameraId, group.Key.CameraCode, group.Key.OtherCameraId, group.Key.OtherCameraCode,
                group.Key.ObjectClass,
                group.Where(x => x.Status == EntityCandidateStatus.Open).Sum(x => x.Count),
                group.Where(x => x.Status == EntityCandidateStatus.Confirmed).Sum(x => x.Count),
                group.Where(x => x.Status == EntityCandidateStatus.Dismissed).Sum(x => x.Count)))
            .OrderBy(x => x.CameraCode, StringComparer.Ordinal).ThenBy(x => x.OtherCameraCode, StringComparer.Ordinal).ThenBy(x => x.ObjectClass)
            .ToList();
        return new EntityCandidateSummary(catalogueVersion, identityFingerprint, derivations, pending, pairs);
    }

    public async Task<EntityView?> GetEntityAsync(Guid entityId, CancellationToken cancellationToken)
    {
        var entity = await db.Entities.AsNoTracking().SingleOrDefaultAsync(x => x.Id == entityId, cancellationToken);
        if (entity is null) return null;
        var memberIds = await db.Tracks.AsNoTracking().Where(x => x.EntityId == entityId).Select(x => x.Id).ToListAsync(cancellationToken);
        var members = (await TrackViewsAsync(memberIds, cancellationToken)).Values
            .OrderBy(x => x.StartTimestampUtc).ThenBy(x => x.TrackId).ToList();
        var confirmations = await db.EntityCandidates.AsNoTracking()
            .Where(x => x.EntityId == entityId && x.Status == EntityCandidateStatus.Confirmed)
            .OrderBy(x => x.DecidedAtUtc).ThenBy(x => x.Id)
            .ToListAsync(cancellationToken);
        return new EntityView(entity.Id, entity.DisplayCode, entity.EntityType, entity.CreatedAtUtc, entity.UpdatedAtUtc, members,
            await ViewsAsync(confirmations, null, cancellationToken));
    }

    public async Task<EntityDecisionResult> ConfirmAsync(Guid candidateId, string? note, EntityCandidateDecider decider,
        Func<CancellationToken, Task<AuditEntryReceipt>> appendAudit, EntityCandidateCatalogueDefinition catalogue, string identityFingerprint,
        DateTimeOffset nowUtc, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(appendAudit);
        ArgumentNullException.ThrowIfNull(catalogue);
        var owned = db.Database.CurrentTransaction is null ? await db.Database.BeginTransactionAsync(cancellationToken) : null;
        try
        {
            var candidate = await LockCandidateAsync(candidateId, cancellationToken);
            if (candidate is null) return new EntityDecisionResult(EntityCandidateFaceFactorService.NotFoundCode, null, null, false);
            if (candidate.Status != EntityCandidateStatus.Open)
                return new EntityDecisionResult(EntityConfirmationRules.AlreadyDecided, await CurrentViewAsync(candidateId, cancellationToken),
                    candidate.EntityId, false);
            if (!IsCurrent(candidate, catalogue, identityFingerprint))
                return new EntityDecisionResult(EntityConfirmationRules.Superseded, null, null, false);

            // Both Tracks, in id order, so two confirmations sharing a Track serialise without a lock cycle. NO KEY UPDATE, not
            // UPDATE: no key changes here, and a plain UPDATE lock would conflict with the KEY SHARE locks that every
            // foreign-key insert on these Tracks takes (candidates, embeddings, faces), inviting a deadlock with them.
            var tracks = await db.Tracks
                .FromSqlInterpolated($"SELECT * FROM tracks WHERE id = {candidate.LowerTrackId} OR id = {candidate.HigherTrackId} ORDER BY id FOR NO KEY UPDATE")
                .ToListAsync(cancellationToken);
            var lower = tracks.Single(x => x.Id == candidate.LowerTrackId);
            var higher = tracks.Single(x => x.Id == candidate.HigherTrackId);
            var plausibility = await PlausibilityTracksAsync([lower.Id, higher.Id], cancellationToken);
            var visible = await VisibleTrackIdsAsync([lower.Id, higher.Id], cancellationToken);
            if (!visible.Contains(lower.Id) || !visible.Contains(higher.Id))
                return new EntityDecisionResult(EntityConfirmationRules.NotVisible, null, null, false);

            Entity? existingEntity = null;
            EntityMembers? members = null;
            if ((lower.EntityId ?? higher.EntityId) is { } entityId && !(lower.EntityId is not null && higher.EntityId is not null))
            {
                existingEntity = await db.Entities
                    .FromSqlInterpolated($"SELECT * FROM entities WHERE id = {entityId} FOR NO KEY UPDATE")
                    .SingleAsync(cancellationToken);
                // Visible members only: a member on an earlier run of its video stays in the Entity (§7) but is the same object
                // as its reprocessed copy, so checking a new Track against it would refuse the copy as "in two places at once".
                var memberIds = await db.Tracks.AsNoTracking().Where(x => x.EntityId == entityId).Select(x => x.Id).ToListAsync(cancellationToken);
                var visibleMembers = await VisibleTrackIdsAsync(memberIds, cancellationToken);
                var memberTracks = await PlausibilityTracksAsync([.. memberIds.Where(visibleMembers.Contains)], cancellationToken);
                members = new EntityMembers(entityId, existingEntity.EntityType, memberTracks.Values.ToList());
            }

            var plan = EntityConfirmationRules.Plan(plausibility[lower.Id], lower.EntityId, plausibility[higher.Id], higher.EntityId, members, catalogue);
            if (plan.Kind == EntityConfirmationKind.Refused)
                return new EntityDecisionResult(plan.RefusalCode, null, plan.EntityId, false, plan.ConflictingTrackId);

            // The audit entry first, inside this transaction: its id is recorded on the candidate, and if it cannot be
            // written nothing below runs (ADR-010 §4).
            var receipt = await appendAudit(cancellationToken);
            Guid resultEntityId;
            var created = false;
            switch (plan.Kind)
            {
                case EntityConfirmationKind.CreateEntity:
                    var entity = Entity.CreateByConfirmation(candidate.ObjectClass == ObjectClass.Person ? EntityType.Person : EntityType.Vehicle, nowUtc);
                    db.Entities.Add(entity);
                    lower.JoinEntityByConfirmation(entity.Id);
                    higher.JoinEntityByConfirmation(entity.Id);
                    resultEntityId = entity.Id;
                    created = true;
                    break;
                case EntityConfirmationKind.ExtendEntity:
                    resultEntityId = plan.EntityId!.Value;
                    (plan.JoiningTrackId == lower.Id ? lower : higher).JoinEntityByConfirmation(resultEntityId);
                    existingEntity!.Extend(nowUtc);
                    break;
                default:
                    resultEntityId = plan.EntityId!.Value;
                    break;
            }

            candidate.Confirm(resultEntityId, decider, note, receipt.AuditEntryId, nowUtc);
            await db.SaveChangesAsync(cancellationToken);
            if (owned is not null) await owned.CommitAsync(cancellationToken);
            db.ChangeTracker.Clear();
            return new EntityDecisionResult(null, await CurrentViewAsync(candidateId, cancellationToken), resultEntityId, created);
        }
        finally
        {
            if (owned is not null) await owned.DisposeAsync();
            db.ChangeTracker.Clear();
        }
    }

    public async Task<EntityDecisionResult> DismissAsync(Guid candidateId, string? note, EntityCandidateDecider decider,
        Func<CancellationToken, Task<AuditEntryReceipt>> appendAudit, EntityCandidateCatalogueDefinition catalogue, string identityFingerprint,
        DateTimeOffset nowUtc, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(appendAudit);
        var owned = db.Database.CurrentTransaction is null ? await db.Database.BeginTransactionAsync(cancellationToken) : null;
        try
        {
            var candidate = await LockCandidateAsync(candidateId, cancellationToken);
            if (candidate is null) return new EntityDecisionResult(EntityCandidateFaceFactorService.NotFoundCode, null, null, false);
            if (candidate.Status != EntityCandidateStatus.Open)
                return new EntityDecisionResult(EntityConfirmationRules.AlreadyDecided, await CurrentViewAsync(candidateId, cancellationToken),
                    candidate.EntityId, false);
            if (!IsCurrent(candidate, catalogue, identityFingerprint))
                return new EntityDecisionResult(EntityConfirmationRules.Superseded, null, null, false);
            var receipt = await appendAudit(cancellationToken);
            candidate.Dismiss(decider, note, receipt.AuditEntryId, nowUtc);
            await db.SaveChangesAsync(cancellationToken);
            if (owned is not null) await owned.CommitAsync(cancellationToken);
            db.ChangeTracker.Clear();
            return new EntityDecisionResult(null, await CurrentViewAsync(candidateId, cancellationToken), null, false);
        }
        finally
        {
            if (owned is not null) await owned.DisposeAsync();
            db.ChangeTracker.Clear();
        }
    }

    public async Task<EntityFacePair?> BestFacePairAsync(Guid lowerTrackId, Guid higherTrackId, string faceIdentityFingerprint,
        CancellationToken cancellationToken)
    {
        var lower = UsableFaces(lowerTrackId, faceIdentityFingerprint);
        var higher = UsableFaces(higherTrackId, faceIdentityFingerprint);
        var best = await (
                from a in lower
                from b in higher
                let distance = a.Embedding.CosineDistance(b.Embedding)
                orderby distance, a.FaceId, b.FaceId
                select new { a.FaceId, a.ObservationId, a.ArtifactId, a.BoxX, a.BoxY, a.BoxWidth, a.BoxHeight,
                    OtherFaceId = b.FaceId, OtherObservationId = b.ObservationId, OtherArtifactId = b.ArtifactId,
                    OtherBoxX = b.BoxX, OtherBoxY = b.BoxY, OtherBoxWidth = b.BoxWidth, OtherBoxHeight = b.BoxHeight, Distance = distance })
            .FirstOrDefaultAsync(cancellationToken);
        return best is null
            ? null
            : new EntityFacePair(best.FaceId, best.ObservationId, best.ArtifactId, new FaceBox(best.BoxX, best.BoxY, best.BoxWidth, best.BoxHeight),
                best.OtherFaceId, best.OtherObservationId, best.OtherArtifactId,
                new FaceBox(best.OtherBoxX, best.OtherBoxY, best.OtherBoxWidth, best.OtherBoxHeight), Math.Round(1.0 - best.Distance, 6));
    }

    // --- Helpers -----------------------------------------------------------------------------------

    private sealed class EmbeddedTrack
    {
        public Guid TrackId { get; init; }
        public Guid ProcessingRunId { get; init; }
        public Guid CameraId { get; init; }
        public string? SiteCode { get; init; }
        public ObjectClass ObjectClass { get; init; }
        public DateTimeOffset StartUtc { get; init; }
        public DateTimeOffset EndUtc { get; init; }
        public Pgvector.Vector? Embedding { get; init; }
    }

    private sealed class VisiblePair
    {
        public EntityCandidate Candidate { get; init; } = null!;
        public Guid LowerCameraId { get; init; }
        public string LowerCameraCode { get; init; } = string.Empty;
        public Guid HigherCameraId { get; init; }
        public string HigherCameraCode { get; init; } = string.Empty;
    }

    private sealed class UsableFace
    {
        public Guid FaceId { get; init; }
        public Guid ObservationId { get; init; }
        public Guid? ArtifactId { get; init; }
        public float BoxX { get; init; }
        public float BoxY { get; init; }
        public float BoxWidth { get; init; }
        public float BoxHeight { get; init; }
        public Pgvector.Vector Embedding { get; init; } = null!;
    }

    /// <summary>
    /// Embedded Person and Vehicle Tracks of the identity, visible now: the latest completed run per video, the one base
    /// candidate set Track search and Find similar use.
    /// </summary>
    private IQueryable<EmbeddedTrack> VisibleEmbedded(string identityFingerprint) =>
        from x in AnalyticsScopeQuery.BaseCandidates(db, Everything, long.MaxValue)
        where x.track.ObjectClass == ObjectClass.Person || x.track.ObjectClass == ObjectClass.Vehicle
        join row in db.TrackEmbeddings.AsNoTracking() on x.track.Id equals row.TrackId
        join analysis in db.EmbeddingAnalyses.AsNoTracking() on row.AnalysisId equals analysis.Id
        where analysis.IdentityFingerprint == identityFingerprint &&
              (analysis.Status == EmbeddingAnalysisStatus.Completed || analysis.Status == EmbeddingAnalysisStatus.Superseded) &&
              analysis.ProcessingRunId == x.track.ProcessingRunId &&
              row.Outcome == "Embedded"
        select new EmbeddedTrack
        {
            TrackId = x.track.Id,
            ProcessingRunId = x.track.ProcessingRunId,
            CameraId = x.camera.Id,
            SiteCode = x.camera.SiteCode,
            ObjectClass = x.track.ObjectClass,
            StartUtc = x.track.StartTimestampUtc,
            EndUtc = x.track.EndTimestampUtc,
            Embedding = row.Embedding,
        };

    private IQueryable<VisiblePair> VisiblePairs(string identityFingerprint, string catalogueVersion)
    {
        var visible = AnalyticsScopeQuery.BaseCandidates(db, Everything, long.MaxValue);
        return from candidate in db.EntityCandidates.AsNoTracking()
               where candidate.CatalogueVersion == catalogueVersion && candidate.IdentityFingerprint == identityFingerprint
               join lower in visible on candidate.LowerTrackId equals lower.track.Id
               join higher in visible on candidate.HigherTrackId equals higher.track.Id
               select new VisiblePair
               {
                   Candidate = candidate,
                   LowerCameraId = lower.camera.Id,
                   LowerCameraCode = lower.camera.Code,
                   HigherCameraId = higher.camera.Id,
                   HigherCameraCode = higher.camera.Code,
               };
    }

    private IQueryable<UsableFace> UsableFaces(Guid trackId, string faceIdentityFingerprint) =>
        from face in db.FaceObservations.AsNoTracking()
        where face.TrackId == trackId && face.Usable
        join analysis in db.FaceAnalyses.AsNoTracking() on face.AnalysisId equals analysis.Id
        join track in db.Tracks.AsNoTracking() on face.TrackId equals track.Id
        where analysis.IdentityFingerprint == faceIdentityFingerprint && analysis.Status == FaceAnalysisStatus.Completed &&
              analysis.ProcessingRunId == track.ProcessingRunId
        join embedding in db.FaceEmbeddings.AsNoTracking() on face.Id equals embedding.FaceObservationId
        join observation in db.Observations.AsNoTracking() on face.ObservationId equals observation.Id
        select new UsableFace
        {
            FaceId = face.Id,
            ObservationId = face.ObservationId,
            ArtifactId = observation.ThumbnailArtifactId,
            BoxX = face.BoxX,
            BoxY = face.BoxY,
            BoxWidth = face.BoxWidth,
            BoxHeight = face.BoxHeight,
            Embedding = embedding.Embedding,
        };

    private async Task<bool> VisibleRunAsync(Guid processingRunId, CancellationToken cancellationToken)
    {
        var run = await db.ProcessingRuns.AsNoTracking()
            .Where(x => x.Id == processingRunId)
            .Select(x => new { x.VideoAssetId, x.Status, x.CompletedAtUtc, x.VisibilitySequence })
            .SingleOrDefaultAsync(cancellationToken);
        if (run is null || run.Status != ProcessingRunStatus.Completed || run.CompletedAtUtc is null || run.VisibilitySequence is not { } sequence)
            return false;
        return !await db.ProcessingRuns.AsNoTracking().AnyAsync(other =>
            other.VideoAssetId == run.VideoAssetId && other.Status == ProcessingRunStatus.Completed && other.CompletedAtUtc != null &&
            other.VisibilitySequence != null && other.VisibilitySequence > sequence, cancellationToken);
    }

    private async Task<HashSet<Guid>> VisibleTrackIdsAsync(IReadOnlyCollection<Guid> trackIds, CancellationToken cancellationToken) =>
        (await AnalyticsScopeQuery.BaseCandidates(db, Everything, long.MaxValue)
            .Where(x => trackIds.Contains(x.track.Id))
            .Select(x => x.track.Id)
            .ToListAsync(cancellationToken)).ToHashSet();

    private async Task<Dictionary<Guid, PlausibilityTrack>> PlausibilityTracksAsync(IReadOnlyCollection<Guid> trackIds, CancellationToken cancellationToken) =>
        (await (from track in db.Tracks.AsNoTracking()
                where trackIds.Contains(track.Id)
                join video in db.VideoAssets.AsNoTracking() on track.VideoAssetId equals video.Id
                select new { track.Id, video.CameraId, track.StartTimestampUtc, track.EndTimestampUtc })
            .ToListAsync(cancellationToken))
        .ToDictionary(x => x.Id, x => new PlausibilityTrack(x.Id, x.CameraId, x.StartTimestampUtc, x.EndTimestampUtc));

    private async Task<Dictionary<Guid, EntityTrackView>> TrackViewsAsync(IReadOnlyCollection<Guid> trackIds, CancellationToken cancellationToken)
    {
        var visible = await VisibleTrackIdsAsync(trackIds, cancellationToken);
        var rows = await (
                from track in db.Tracks.AsNoTracking()
                where trackIds.Contains(track.Id)
                join video in db.VideoAssets.AsNoTracking() on track.VideoAssetId equals video.Id
                join camera in db.Cameras.AsNoTracking() on video.CameraId equals camera.Id
                join observation in db.Observations.AsNoTracking() on track.RepresentativeObservationId equals observation.Id into observations
                from observation in observations.DefaultIfEmpty()
                select new
                {
                    track.Id, track.ProcessingRunId, track.VideoAssetId, CameraId = camera.Id, camera.Code, camera.Name, track.ObjectClass,
                    track.StartTimestampUtc, track.EndTimestampUtc, track.StartOffsetMs, track.EndOffsetMs,
                    Thumbnail = observation == null ? (Guid?)null : observation.ThumbnailArtifactId, track.EntityId,
                })
            .ToListAsync(cancellationToken);
        return rows.ToDictionary(x => x.Id, x => new EntityTrackView(x.Id, x.ProcessingRunId, x.VideoAssetId, x.CameraId, x.Code, x.Name,
            x.ObjectClass, x.StartTimestampUtc, x.EndTimestampUtc, x.StartOffsetMs, x.EndOffsetMs, x.Thumbnail, x.EntityId, visible.Contains(x.Id)));
    }

    private async Task<IReadOnlyList<EntityCandidateView>> ViewsAsync(List<EntityCandidate> candidates, string? faceIdentityFingerprint,
        CancellationToken cancellationToken)
    {
        if (candidates.Count == 0) return [];
        var trackIds = candidates.SelectMany(x => new[] { x.LowerTrackId, x.HigherTrackId }).Distinct().ToList();
        var tracks = await TrackViewsAsync(trackIds, cancellationToken);
        var withFace = new HashSet<Guid>();
        if (faceIdentityFingerprint is not null)
        {
            var persons = candidates.Where(x => x.ObjectClass == ObjectClass.Person)
                .SelectMany(x => new[] { x.LowerTrackId, x.HigherTrackId }).Distinct().ToList();
            if (persons.Count > 0)
                withFace = (await (
                        from face in db.FaceObservations.AsNoTracking()
                        where persons.Contains(face.TrackId) && face.Usable
                        join analysis in db.FaceAnalyses.AsNoTracking() on face.AnalysisId equals analysis.Id
                        join track in db.Tracks.AsNoTracking() on face.TrackId equals track.Id
                        where analysis.IdentityFingerprint == faceIdentityFingerprint && analysis.Status == FaceAnalysisStatus.Completed &&
                              analysis.ProcessingRunId == track.ProcessingRunId &&
                              db.FaceEmbeddings.Any(embedding => embedding.FaceObservationId == face.Id)
                        select face.TrackId)
                    .Distinct()
                    .ToListAsync(cancellationToken)).ToHashSet();
        }

        return candidates.Select(x => new EntityCandidateView(x.Id, x.CatalogueVersion, x.IdentityFingerprint, x.ObjectClass, x.AppearanceScore,
            x.SameCamera, x.GapMs, x.Status,
            x.DecidedAtUtc is { } decidedAt
                ? new EntityCandidateDecisionView(decidedAt, x.DecidedByOperatorId!, x.DecidedByDisplayName!, x.DecidedByIdentitySource!,
                    x.DecisionNote, x.DecisionAuditEntryId)
                : null,
            x.EntityId, tracks[x.LowerTrackId], tracks[x.HigherTrackId],
            x.ObjectClass == ObjectClass.Person && withFace.Contains(x.LowerTrackId) && withFace.Contains(x.HigherTrackId))).ToList();
    }

    /// <summary>Only a candidate of the current catalogue and embedding identity is decided (ADR-023 §2, recompute).</summary>
    private static bool IsCurrent(EntityCandidate candidate, EntityCandidateCatalogueDefinition catalogue, string identityFingerprint) =>
        candidate.CatalogueVersion == catalogue.CatalogueVersion && candidate.IdentityFingerprint == identityFingerprint;

    private Task<EntityCandidate?> LockCandidateAsync(Guid candidateId, CancellationToken cancellationToken) =>
        db.EntityCandidates
            .FromSqlInterpolated($"SELECT * FROM entity_candidates WHERE id = {candidateId} FOR NO KEY UPDATE")
            .SingleOrDefaultAsync(cancellationToken);

    private async Task<EntityCandidateView?> CurrentViewAsync(Guid candidateId, CancellationToken cancellationToken)
    {
        var candidate = await db.EntityCandidates.AsNoTracking().SingleOrDefaultAsync(x => x.Id == candidateId, cancellationToken);
        return candidate is null ? null : (await ViewsAsync([candidate], null, cancellationToken)).Single();
    }

    private async Task<bool> SaveDerivationAsync(Microsoft.EntityFrameworkCore.Storage.IDbContextTransaction transaction, CancellationToken cancellationToken)
    {
        try
        {
            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            return true;
        }
        catch (DbUpdateException exception) when (exception.InnerException is PostgresException
                                                 {
                                                     SqlState: UniqueViolation,
                                                     ConstraintName: DerivationUniqueIndex,
                                                 })
        {
            // Another writer derived the same analysis; its answer is the same pair-local set. Any other unique violation
            // (a candidate pair) is a defect and propagates, so the sweep logs it instead of relisting the analysis silently.
            return false;
        }
        finally
        {
            db.ChangeTracker.Clear();
        }
    }
}
