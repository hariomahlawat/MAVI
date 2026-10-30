using Mavi.Application.Modules.Events;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Contracts.Api.Query;
using Mavi.Contracts.Api.Tracks;

namespace Mavi.Application.Modules.Query;

/// <summary>
/// The machine-readable vocabulary of contract <c>mavi-query-v1</c> (ADR-024 §8): what <c>GET /api/query/contract</c>
/// returns, and what Ask MAVI prompts from (ADR-026 §4). One builder, so the builder UI and the language model are
/// offered the same contract.
/// </summary>
public static class QueryContractVocabulary
{
    public static QueryContractResponse Describe(IVisualAttributeRelease? attributeRelease)
    {
        var definition = attributeRelease?.Resolution.Definition;
        var attributes = definition is null
            ? []
            : definition.Schema.Attributes
                .OrderBy(item => item.AttributeType, StringComparer.Ordinal)
                .Select(item => new QueryAttributeVocabularyResponse(
                    item.AttributeType,
                    item.ObjectClass == "person" ? "Person" : "Vehicle",
                    [.. item.Values]))
                .ToList();

        var units = new[] { QueryUnit.Track, QueryUnit.Event, QueryUnit.Entity }
            .Select(unit => new QueryUnitVocabularyResponse(
                QueryContract.ToWire(unit),
                unit != QueryUnit.Entity,
                unit == QueryUnit.Entity ? StructuredQueryService.EntityUnavailableReason : null,
                QueryContract.Predicates[unit],
                QueryContract.GroupDimensions[unit],
                QueryContract.DistinctFields[unit]))
            .ToList();

        return new QueryContractResponse(
            QueryContract.Version,
            units,
            QueryContract.Operations,
            QueryContract.ObjectClasses,
            VehicleSubclassExposurePolicy.ExposedSubclasses,
            QueryContract.ZoneRelations,
            QueryContract.CrossingDirections,
            TrackSearchContractRules.MotionDirectionValues,
            QueryContract.PlateMatches,
            attributes,
            definition?.Disclosure,
            EventRuleIds.All,
            RuleCatalogue.Current.CatalogueVersion,
            new QueryBoundsResponse(
                QueryContract.MaximumCameraIds,
                QueryContract.DefaultFindLimit,
                QueryContract.MaximumFindLimit,
                QueryContract.MaximumTopK,
                QueryContract.MaximumSimilarK,
                QueryContract.MinimumBucketSeconds,
                QueryContract.MaximumBucketSeconds,
                QueryContract.MaximumBuckets,
                QueryContract.MaximumMatchedRecords),
            QueryRefusalCodes.All,
            QueryContract.Disclosure);
    }
}
