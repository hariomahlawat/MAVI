using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Entities;
using Mavi.Domain.Intelligence;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The audited Entity corrections of ADR-027 §4: unlink, merge and reopen. Each runs in one transaction, takes its row locks
/// <c>FOR NO KEY UPDATE</c> in the order confirmation uses (candidate, then Tracks in id order, then Entities in id order),
/// re-checks under the locks, appends the audit entry before any state changes, records the change in the append-only
/// history and updates the projections. A refusal writes nothing. None of them asserts identity.
/// </summary>
public sealed partial class EntityCandidateRepository
{
    public async Task<EntityCorrectionResult> UnlinkAsync(Guid entityId, Guid trackId, string? note, EntityCandidateDecider decider,
        Func<CancellationToken, Task<AuditEntryReceipt>> appendAudit, DateTimeOffset nowUtc, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(appendAudit);
        var cleanNote = EntityNotes.Normalise(note);
        var owned = db.Database.CurrentTransaction is null ? await db.Database.BeginTransactionAsync(cancellationToken) : null;
        try
        {
            var track = await db.Tracks.FromSqlInterpolated($"SELECT * FROM tracks WHERE id = {trackId} FOR NO KEY UPDATE")
                .SingleOrDefaultAsync(cancellationToken);
            var entity = await LockEntitiesAsync([entityId], cancellationToken);
            if (!entity.TryGetValue(entityId, out var found)) return new EntityCorrectionResult(EntityCorrectionRules.EntityNotFound);
            if (found.State != EntityMergeState.Active) return new EntityCorrectionResult(EntityCorrectionRules.EntityNotActive);
            if (track is null || track.EntityId != entityId) return new EntityCorrectionResult(EntityCorrectionRules.TrackNotMember);

            var receipt = await appendAudit(cancellationToken);
            track.LeaveEntityByUnlink(entityId);
            found.Touch(nowUtc);
            db.EntityMembershipChanges.Add(EntityMembershipChange.Record(track.Id, entityId, EntityMembershipChangeKind.Left,
                EntityMembershipCause.Unlinked, null, cleanNote, Actor(decider, nowUtc, receipt)));
            await db.SaveChangesAsync(cancellationToken);
            if (owned is not null) await owned.CommitAsync(cancellationToken);
            db.ChangeTracker.Clear();
            return new EntityCorrectionResult(null, await GetEntityAsync(entityId, cancellationToken));
        }
        finally
        {
            if (owned is not null) await owned.DisposeAsync();
            db.ChangeTracker.Clear();
        }
    }

    public async Task<EntityCorrectionResult> MergeAsync(Guid sourceEntityId, Guid targetEntityId, string? note, EntityCandidateDecider decider,
        Func<CancellationToken, Task<AuditEntryReceipt>> appendAudit, EntityCandidateCatalogueDefinition catalogue, DateTimeOffset nowUtc,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(appendAudit);
        ArgumentNullException.ThrowIfNull(catalogue);
        var cleanNote = EntityNotes.Normalise(note);
        if (sourceEntityId == targetEntityId) return new EntityCorrectionResult(EntityCorrectionRules.MergeInvalid);
        var owned = db.Database.CurrentTransaction is null ? await db.Database.BeginTransactionAsync(cancellationToken) : null;
        try
        {
            // Members are read first, then locked in id order before the Entities (the order confirmation uses), then read
            // again: a membership that changed in between is refused rather than merged half-way.
            var seen = await MemberIdsAsync([sourceEntityId, targetEntityId], cancellationToken);
            var ordered = seen.Order().ToArray();
            if (ordered.Length > 0)
                await db.Tracks.FromSqlInterpolated($"SELECT * FROM tracks WHERE id = ANY({ordered}) ORDER BY id FOR NO KEY UPDATE")
                    .ToListAsync(cancellationToken);
            var entities = await LockEntitiesAsync([sourceEntityId, targetEntityId], cancellationToken);
            if (!entities.TryGetValue(sourceEntityId, out var source) || !entities.TryGetValue(targetEntityId, out var target))
                return new EntityCorrectionResult(EntityCorrectionRules.EntityNotFound);
            if (source.State != EntityMergeState.Active || target.State != EntityMergeState.Active)
                return new EntityCorrectionResult(EntityCorrectionRules.EntityNotActive);
            if (source.EntityType != target.EntityType) return new EntityCorrectionResult(EntityCorrectionRules.MergeInvalid);
            if (!(await MemberIdsAsync([sourceEntityId, targetEntityId], cancellationToken)).SetEquals(seen))
                return new EntityCorrectionResult(EntityCorrectionRules.ChangedConcurrently);

            var tracks = await db.Tracks.Where(x => x.EntityId == sourceEntityId || x.EntityId == targetEntityId).ToListAsync(cancellationToken);
            var sourceMembers = tracks.Where(x => x.EntityId == sourceEntityId).ToList();
            var targetMembers = tracks.Where(x => x.EntityId == targetEntityId).ToList();
            // Every cross pair must be physically possible (ADR-023 §4), every member counted, earlier runs included (fail-closed,
            // as extension is). Scope (site) is a candidate-generation rule and is not applied to an operator's merge.
            var plausibility = await PlausibilityTracksAsync(tracks.Select(x => x.Id).ToList(), cancellationToken);
            foreach (var left in sourceMembers.OrderBy(x => x.Id))
            foreach (var right in targetMembers.OrderBy(x => x.Id))
                if (!EntityCandidatePlausibility.Evaluate(plausibility[left.Id], plausibility[right.Id], catalogue).Plausible)
                    return new EntityCorrectionResult(EntityCorrectionRules.MergeImplausible, ConflictingTrackId: left.Id,
                        OtherConflictingTrackId: right.Id);

            var receipt = await appendAudit(cancellationToken);
            var actor = Actor(decider, nowUtc, receipt);
            // The leaves are saved before the joins: the sequence, not the insert order EF chooses, makes each join the Track's latest change.
            foreach (var track in sourceMembers.OrderBy(x => x.Id))
            {
                track.MoveEntityByMerge(sourceEntityId, targetEntityId);
                db.EntityMembershipChanges.Add(EntityMembershipChange.Record(track.Id, sourceEntityId, EntityMembershipChangeKind.Left,
                    EntityMembershipCause.Merged, null, cleanNote, actor));
            }

            await db.SaveChangesAsync(cancellationToken);
            foreach (var track in sourceMembers.OrderBy(x => x.Id))
                db.EntityMembershipChanges.Add(EntityMembershipChange.Record(track.Id, targetEntityId, EntityMembershipChangeKind.Joined,
                    EntityMembershipCause.Merged, null, cleanNote, actor));
            source.MergeInto(target, nowUtc);
            await db.SaveChangesAsync(cancellationToken);
            if (owned is not null) await owned.CommitAsync(cancellationToken);
            db.ChangeTracker.Clear();
            return new EntityCorrectionResult(null, await GetEntityAsync(targetEntityId, cancellationToken));
        }
        finally
        {
            if (owned is not null) await owned.DisposeAsync();
            db.ChangeTracker.Clear();
        }
    }

    public async Task<EntityDecisionResult> ReopenAsync(Guid candidateId, string? note, EntityCandidateDecider decider,
        Func<CancellationToken, Task<AuditEntryReceipt>> appendAudit, EntityCandidateCatalogueDefinition catalogue, string identityFingerprint,
        DateTimeOffset nowUtc, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(appendAudit);
        ArgumentNullException.ThrowIfNull(catalogue);
        var cleanNote = EntityNotes.Normalise(note);
        var owned = db.Database.CurrentTransaction is null ? await db.Database.BeginTransactionAsync(cancellationToken) : null;
        try
        {
            var candidate = await LockCandidateAsync(candidateId, cancellationToken);
            if (candidate is null) return new EntityDecisionResult(EntityCandidateFaceFactorService.NotFoundCode, null, null, false);
            if (candidate.Status == EntityCandidateStatus.Open)
                return new EntityDecisionResult(EntityCorrectionRules.CandidateNotDecided, await CurrentViewAsync(candidateId, cancellationToken), null,
                    false);
            if (!IsCurrent(candidate, catalogue, identityFingerprint))
                return new EntityDecisionResult(EntityConfirmationRules.Superseded, null, null, false);
            if (candidate.Status == EntityCandidateStatus.Confirmed)
            {
                // Locked like confirmation, so a concurrent confirm, unlink or merge on these Tracks is serialised with this check.
                var tracks = await db.Tracks
                    .FromSqlInterpolated(
                        $"SELECT * FROM tracks WHERE id = {candidate.LowerTrackId} OR id = {candidate.HigherTrackId} ORDER BY id FOR NO KEY UPDATE")
                    .AsNoTracking().ToListAsync(cancellationToken);
                if (tracks.Count == 2 && tracks[0].EntityId is { } together && tracks[1].EntityId == together)
                    return new EntityDecisionResult(EntityCorrectionRules.CandidateStillLinked, await CurrentViewAsync(candidateId, cancellationToken),
                        together, false);
            }

            var receipt = await appendAudit(cancellationToken);
            candidate.Reopen();
            db.EntityCandidateDecisions.Add(EntityCandidateDecisionRecord.Record(candidate.Id, EntityCandidateDecisionKind.Reopened, null, cleanNote,
                Actor(decider, nowUtc, receipt)));
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

    public async Task<IReadOnlyList<EntityCandidateDecisionHistoryView>?> GetCandidateHistoryAsync(Guid candidateId,
        CancellationToken cancellationToken)
    {
        if (!await db.EntityCandidates.AnyAsync(x => x.Id == candidateId, cancellationToken)) return null;
        var rows = await db.EntityCandidateDecisions.AsNoTracking().Where(x => x.CandidateId == candidateId).OrderBy(x => x.Sequence)
            .ToListAsync(cancellationToken);
        return rows.Select(x => new EntityCandidateDecisionHistoryView(x.Sequence, x.Decision, x.EntityId, x.Note, x.OperatorId,
            x.OperatorDisplayName, x.IdentitySource, x.AtUtc, x.AuditEntryId)).ToList();
    }

    // --- Helpers ---------------------------------------------------------------------------------

    private static EntityDecisionActor Actor(EntityCandidateDecider decider, DateTimeOffset nowUtc, AuditEntryReceipt receipt) =>
        new(decider.OperatorId, decider.DisplayName, decider.IdentitySource, nowUtc.ToUniversalTime(), receipt.AuditEntryId);

    private async Task<Dictionary<Guid, Entity>> LockEntitiesAsync(Guid[] entityIds, CancellationToken cancellationToken)
    {
        var ordered = entityIds.Distinct().Order().ToArray();
        var locked = await db.Entities.FromSqlInterpolated($"SELECT * FROM entities WHERE id = ANY({ordered}) ORDER BY id FOR NO KEY UPDATE")
            .ToListAsync(cancellationToken);
        return locked.ToDictionary(x => x.Id);
    }

    private async Task<HashSet<Guid>> MemberIdsAsync(Guid[] entityIds, CancellationToken cancellationToken) =>
        (await db.Tracks.AsNoTracking().Where(x => x.EntityId != null && entityIds.Contains(x.EntityId.Value)).Select(x => x.Id)
            .ToListAsync(cancellationToken)).ToHashSet();

    /// <summary>The Entity and every Entity merged into it, directly or through another merge.</summary>
    private async Task<List<Guid>> MergedLineageAsync(Guid entityId, CancellationToken cancellationToken)
    {
        var lineage = new List<Guid> { entityId };
        var frontier = new List<Guid> { entityId };
        while (frontier.Count > 0)
        {
            var current = frontier;
            frontier = await db.Entities.AsNoTracking()
                .Where(x => x.MergedIntoEntityId != null && current.Contains(x.MergedIntoEntityId.Value) && !lineage.Contains(x.Id))
                .Select(x => x.Id).ToListAsync(cancellationToken);
            lineage.AddRange(frontier);
        }

        return lineage;
    }

    private static EntityMembershipChangeView ChangeView(EntityMembershipChange row) => new(row.Sequence, row.TrackId, row.EntityId, row.Change,
        row.Cause, row.CandidateId, row.Note, row.OperatorId, row.OperatorDisplayName, row.IdentitySource, row.AtUtc, row.AuditEntryId);
}
