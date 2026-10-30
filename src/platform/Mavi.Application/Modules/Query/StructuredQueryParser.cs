using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using Mavi.Application.Modules.Events;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Analytics;
using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Query;

/// <summary>The outcome of parsing: a query, or the first refusal met in document order.</summary>
public sealed record StructuredQueryParseResult(StructuredQuery? Query, QueryRefusal? Refusal)
{
    public bool IsValid => Query is not null;
}

/// <summary>
/// The strict parser of contract <c>mavi-query-v1</c> (ADR-024 §1, §7). Closed: an unknown or duplicated member, a
/// value outside its enumeration or bound, a predicate the unit does not allow and an operation parameter the
/// operation does not take are each refused with a typed code and a JSON pointer. Nothing here reads the database;
/// whether a referenced camera, zone, line or Track exists is the service's question.
/// </summary>
public static class StructuredQueryParser
{
    private static readonly string[] RootMembers = ["contractVersion", "unit", "where", "operation", "requireCompleteCoverage"];
    private static readonly string[] WhereMembers =
    [
        "timeWindow", "cameraIds", "objectClass", "objectSubclass", "minDurationMs", "minConfidence", "zone", "line",
        "motion", "attributes", "plateText", "similarTo", "ruleIds", "catalogueVersion",
    ];
    private static readonly Regex InstantPattern = new(
        @"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?(Z|\+00:00)$", RegexOptions.CultureInvariant);

    private static readonly Regex LowerCaseUuid = new(
        "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", RegexOptions.CultureInvariant);

    private static readonly string[] OperationParameters = ["limit", "order", "field", "by", "bucketSeconds", "k", "baseline"];

    public static StructuredQueryParseResult Parse(string json)
    {
        ArgumentNullException.ThrowIfNull(json);
        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(json, new JsonDocumentOptions { MaxDepth = 16 });
        }
        catch (JsonException)
        {
            return Refuse(QueryRefusalCodes.MalformedJson, "", "The body is not a JSON document.");
        }

        using (document)
        {
            return Parse(document.RootElement);
        }
    }

    public static StructuredQueryParseResult Parse(JsonElement root)
    {
        try
        {
            return new StructuredQueryParseResult(ParseRoot(root), null);
        }
        catch (RefusalException refusal)
        {
            return new StructuredQueryParseResult(null, refusal.Refusal);
        }
    }

    // --- Root ----------------------------------------------------------------

    private static StructuredQuery ParseRoot(JsonElement root)
    {
        var members = Members(root, "", RootMembers);

        var version = RequiredString(members, "contractVersion", "");
        if (!string.Equals(version, QueryContract.Version, StringComparison.Ordinal))
            throw Refusal(QueryRefusalCodes.UnsupportedVersion, "/contractVersion", $"Only contract version {QueryContract.Version} is supported.");

        var unitText = RequiredString(members, "unit", "");
        QueryUnit unit = unitText switch
        {
            "track" => QueryUnit.Track,
            "event" => QueryUnit.Event,
            "entity" => QueryUnit.Entity,
            _ => throw Refusal(QueryRefusalCodes.UnsupportedUnit, "/unit", "unit must be one of track, event, entity."),
        };

        if (!members.TryGetValue("where", out var where))
            throw Refusal(QueryRefusalCodes.MissingRequired, "/where", "where is required.");
        if (!members.TryGetValue("operation", out var operationElement))
            throw Refusal(QueryRefusalCodes.MissingRequired, "/operation", "operation is required.");

        var predicates = ParseWhere(where, unit);
        var operation = ParseOperation(operationElement, unit, predicates.Window);

        var requireComplete = false;
        if (members.TryGetValue("requireCompleteCoverage", out var flag))
        {
            if (flag.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
                throw Refusal(QueryRefusalCodes.InvalidValue, "/requireCompleteCoverage", "requireCompleteCoverage must be a boolean.");
            requireComplete = flag.GetBoolean();
        }

        CheckCombinations(unit, predicates, operation);
        return new StructuredQuery(unit, predicates, operation, requireComplete);
    }

    // --- Predicates ----------------------------------------------------------

    private static QueryPredicates ParseWhere(JsonElement where, QueryUnit unit)
    {
        var members = Members(where, "/where", WhereMembers);
        var allowed = QueryContract.Predicates[unit];
        foreach (var name in members.Keys)
        {
            if (!allowed.Contains(name, StringComparer.Ordinal))
                throw Refusal(QueryRefusalCodes.PredicateNotAllowedForUnit, $"/where/{name}",
                    $"{name} is not a predicate of the {QueryContract.ToWire(unit)} unit.");
        }

        if (!members.TryGetValue("timeWindow", out var windowElement))
            throw Refusal(QueryRefusalCodes.MissingRequired, "/where/timeWindow", "timeWindow is required.");
        var window = ParseWindow(windowElement, "/where/timeWindow");

        IReadOnlyList<Guid> cameraIds = [];
        if (members.TryGetValue("cameraIds", out var cameras))
            cameraIds = ParseGuidSet(cameras, "/where/cameraIds", 1, QueryContract.MaximumCameraIds);

        ObjectClass? objectClass = null;
        if (members.TryGetValue("objectClass", out var classElement))
        {
            objectClass = String(classElement, "/where/objectClass") switch
            {
                "Person" => ObjectClass.Person,
                "Vehicle" => ObjectClass.Vehicle,
                _ => throw Refusal(QueryRefusalCodes.InvalidValue, "/where/objectClass", "objectClass must be Person or Vehicle."),
            };
        }

        string? subclass = null;
        if (members.TryGetValue("objectSubclass", out var subclassElement))
        {
            subclass = String(subclassElement, "/where/objectSubclass");
            if (!VehicleSubclassExposurePolicy.IsExposable(subclass))
                throw Refusal(QueryRefusalCodes.InvalidValue, "/where/objectSubclass", "objectSubclass is not an exposed vehicle subclass.");
            if (objectClass == ObjectClass.Person)
                throw Refusal(QueryRefusalCodes.InvalidValue, "/where/objectSubclass", "A vehicle subclass cannot be combined with objectClass Person.");
        }

        long? minDurationMs = members.TryGetValue("minDurationMs", out var duration)
            ? Integer(duration, "/where/minDurationMs", 0, long.MaxValue)
            : null;

        double? minConfidence = null;
        if (members.TryGetValue("minConfidence", out var confidence))
        {
            if (confidence.ValueKind != JsonValueKind.Number || !confidence.TryGetDouble(out var value) ||
                double.IsNaN(value) || value < 0 || value > 1)
                throw Refusal(QueryRefusalCodes.InvalidValue, "/where/minConfidence", "minConfidence must be a number from 0 to 1.");
            minConfidence = value;
        }

        var zone = members.TryGetValue("zone", out var zoneElement) ? ParseZone(zoneElement, unit) : null;
        var line = members.TryGetValue("line", out var lineElement) ? ParseLine(lineElement) : null;
        var motion = members.TryGetValue("motion", out var motionElement) ? ParseMotion(motionElement) : null;
        var attributes = members.TryGetValue("attributes", out var attributeElement) ? ParseAttributes(attributeElement) : null;
        var plate = members.TryGetValue("plateText", out var plateElement) ? ParsePlate(plateElement) : null;
        var similar = members.TryGetValue("similarTo", out var similarElement) ? ParseSimilar(similarElement) : null;

        IReadOnlyList<string> ruleIds = [];
        if (members.TryGetValue("ruleIds", out var rules))
        {
            if (rules.ValueKind != JsonValueKind.Array || rules.GetArrayLength() is 0 || rules.GetArrayLength() > EventRuleIds.All.Count)
                throw Refusal(QueryRefusalCodes.InvalidValue, "/where/ruleIds", $"ruleIds must be an array of 1 to {EventRuleIds.All.Count} rule ids.");
            var set = new SortedSet<string>(StringComparer.Ordinal);
            var index = 0;
            foreach (var item in rules.EnumerateArray())
            {
                var id = String(item, $"/where/ruleIds/{index}");
                if (!EventRuleIds.All.Contains(id, StringComparer.Ordinal))
                    throw Refusal(QueryRefusalCodes.InvalidValue, $"/where/ruleIds/{index}", "Not a rule of the event catalogue.");
                if (!set.Add(id))
                    throw Refusal(QueryRefusalCodes.InvalidValue, $"/where/ruleIds/{index}", "A rule id may appear once.");
                index++;
            }

            ruleIds = [.. set];
        }

        string? catalogueVersion = null;
        if (members.TryGetValue("catalogueVersion", out var catalogue))
        {
            catalogueVersion = String(catalogue, "/where/catalogueVersion");
            if (!string.Equals(catalogueVersion, RuleCatalogue.Current.CatalogueVersion, StringComparison.Ordinal))
                throw Refusal(QueryRefusalCodes.InvalidValue, "/where/catalogueVersion",
                    $"Only the current event catalogue {RuleCatalogue.Current.CatalogueVersion} can be queried.");
        }

        // A subclass or a plate predicate implies Vehicle, as on Track search: stated, so equal queries are one.
        if (unit == QueryUnit.Track && (subclass is not null || plate is not null))
        {
            if (objectClass == ObjectClass.Person)
                throw Refusal(QueryRefusalCodes.InvalidValue, "/where/objectClass", "A plate predicate cannot be combined with objectClass Person.");
            objectClass = ObjectClass.Vehicle;
        }

        // The catalogue version is pinned for an Event query whether or not it was written.
        if (unit == QueryUnit.Event)
            catalogueVersion ??= RuleCatalogue.Current.CatalogueVersion;

        return new QueryPredicates(
            window, cameraIds, objectClass, subclass, minDurationMs, minConfidence, zone, line, motion, attributes, plate,
            similar, ruleIds, catalogueVersion);
    }

    private static QueryZonePredicate ParseZone(JsonElement element, QueryUnit unit)
    {
        var members = Members(element, "/where/zone", ["zoneId", "relation", "minDwellMs", "loitering"]);
        if (unit == QueryUnit.Event)
        {
            foreach (var name in members.Keys.Where(name => name != "zoneId"))
                throw Refusal(QueryRefusalCodes.PredicateNotAllowedForUnit, $"/where/zone/{name}",
                    "An Event zone predicate names the zone only.");
        }

        var zoneId = RequiredGuid(members, "zoneId", "/where/zone");
        TrackZoneRelation? relation = null;
        if (members.TryGetValue("relation", out var relationElement))
        {
            if (!TrackAnalyticsQueryRules.TryParseZoneRelation(String(relationElement, "/where/zone/relation"), out var parsed))
                throw Refusal(QueryRefusalCodes.InvalidValue, "/where/zone/relation", "relation must be entered, exited or dwelled.");
            relation = parsed;
        }

        long? minDwellMs = members.TryGetValue("minDwellMs", out var dwell)
            ? Integer(dwell, "/where/zone/minDwellMs", 0, long.MaxValue)
            : null;

        var loitering = false;
        if (members.TryGetValue("loitering", out var loiteringElement))
        {
            if (loiteringElement.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
                throw Refusal(QueryRefusalCodes.InvalidValue, "/where/zone/loitering", "loitering must be a boolean.");
            loitering = loiteringElement.GetBoolean();
        }

        // The canonical form of Track search: an omitted relation is "dwelled".
        if (unit == QueryUnit.Track)
            relation ??= TrackZoneRelation.Dwelled;
        return new QueryZonePredicate(zoneId, relation, minDwellMs, loitering);
    }

    private static QueryLinePredicate ParseLine(JsonElement element)
    {
        var members = Members(element, "/where/line", ["lineId", "direction"]);
        var lineId = RequiredGuid(members, "lineId", "/where/line");
        TrackCrossingDirection? direction = null;
        if (members.TryGetValue("direction", out var directionElement))
        {
            if (!TrackAnalyticsQueryRules.TryParseCrossingDirection(String(directionElement, "/where/line/direction"), out var parsed))
                throw Refusal(QueryRefusalCodes.InvalidValue, "/where/line/direction", "direction must be aToB or bToA.");
            direction = parsed;
        }

        return new QueryLinePredicate(lineId, direction);
    }

    private static QueryMotionPredicate ParseMotion(JsonElement element)
    {
        var members = Members(element, "/where/motion", ["direction", "minStationaryMs"]);
        if (members.Count == 0)
            throw Refusal(QueryRefusalCodes.MissingRequired, "/where/motion", "motion needs direction or minStationaryMs.");
        string? direction = null;
        if (members.TryGetValue("direction", out var directionElement))
        {
            direction = String(directionElement, "/where/motion/direction");
            if (!TrackSearchContractRules.IsMotionDirection(direction))
                throw Refusal(QueryRefusalCodes.InvalidValue, "/where/motion/direction", "direction must be a compass heading N, NE, E, SE, S, SW, W or NW.");
        }

        long? minStationaryMs = members.TryGetValue("minStationaryMs", out var stationary)
            ? Integer(stationary, "/where/motion/minStationaryMs", 0, long.MaxValue)
            : null;
        return new QueryMotionPredicate(direction, minStationaryMs);
    }

    private static TrackAttributeQuery ParseAttributes(JsonElement element)
    {
        if (element.ValueKind != JsonValueKind.Array ||
            element.GetArrayLength() is 0 ||
            element.GetArrayLength() > TrackSearchContractRules.MaximumAttributePredicates)
            throw Refusal(QueryRefusalCodes.InvalidValue, "/where/attributes",
                $"attributes must be an array of 1 to {TrackSearchContractRules.MaximumAttributePredicates} predicates.");

        var raw = new List<string?>();
        var index = 0;
        foreach (var item in element.EnumerateArray())
        {
            var path = $"/where/attributes/{index}";
            var members = Members(item, path, ["type", "value"]);
            var type = RequiredString(members, "type", path);
            var value = RequiredString(members, "value", path);
            if (!TrackSearchContractRules.IsAttributeToken(type) || !TrackSearchContractRules.IsAttributeToken(value))
                throw Refusal(QueryRefusalCodes.InvalidValue, path, "An attribute type and value are vocabulary tokens.");
            raw.Add(type + ":" + value);
            index++;
        }

        if (!TrackAttributeQueryRules.TryParse(raw, out var query) || query is null)
            throw Refusal(QueryRefusalCodes.InvalidValue, "/where/attributes", "Each attribute type may appear once.");
        return query;
    }

    private static TrackPlateQuery ParsePlate(JsonElement element)
    {
        var members = Members(element, "/where/plateText", ["text", "match"]);
        var text = RequiredString(members, "text", "/where/plateText");
        string? match = members.TryGetValue("match", out var matchElement) ? String(matchElement, "/where/plateText/match") : null;
        if (match is not null && !TrackPlateQueryRules.TryParseMatch(match, out _))
            throw Refusal(QueryRefusalCodes.InvalidValue, "/where/plateText/match", "match must be contains, prefix or exact.");
        if (!TrackPlateQueryRules.TryParse(text, match, out var plate) || plate is null)
            throw Refusal(QueryRefusalCodes.InvalidValue, "/where/plateText/text",
                $"The plate text must normalise to {TrackSearchContractRules.MinimumPlateTextLength}–{TrackSearchContractRules.MaximumPlateTextLength} letters or digits.");
        return plate;
    }

    private static QuerySimilarity ParseSimilar(JsonElement element)
    {
        var members = Members(element, "/where/similarTo", ["trackId", "k"]);
        var trackId = RequiredGuid(members, "trackId", "/where/similarTo");
        var k = members.TryGetValue("k", out var kElement)
            ? (int)Integer(kElement, "/where/similarTo/k", 1, QueryContract.MaximumSimilarK)
            : QueryContract.DefaultSimilarK;
        return new QuerySimilarity(trackId, k);
    }

    // --- Operation -----------------------------------------------------------

    private static QueryOperation ParseOperation(JsonElement element, QueryUnit unit, QueryWindow window)
    {
        var members = Members(element, "/operation", ["op", .. OperationParameters]);
        var op = RequiredString(members, "op", "/operation");
        QueryOperationKind kind = op switch
        {
            "find" => QueryOperationKind.Find,
            "count" => QueryOperationKind.Count,
            "countDistinct" => QueryOperationKind.CountDistinct,
            "groupBy" => QueryOperationKind.GroupBy,
            "timeBucket" => QueryOperationKind.TimeBucket,
            "first" => QueryOperationKind.First,
            "last" => QueryOperationKind.Last,
            "top" => QueryOperationKind.Top,
            "compare" => QueryOperationKind.Compare,
            _ => throw Refusal(QueryRefusalCodes.UnsupportedOperation, "/operation/op",
                "op must be one of find, count, countDistinct, groupBy, timeBucket, first, last, top, compare."),
        };

        string[] takes = kind switch
        {
            QueryOperationKind.Find => ["limit", "order"],
            QueryOperationKind.CountDistinct => ["field"],
            QueryOperationKind.GroupBy => ["by"],
            QueryOperationKind.TimeBucket => ["bucketSeconds"],
            QueryOperationKind.Top => ["by", "k"],
            QueryOperationKind.Compare => ["baseline"],
            _ => [],
        };
        foreach (var name in members.Keys.Where(name => name != "op"))
        {
            if (!takes.Contains(name, StringComparer.Ordinal))
                throw Refusal(QueryRefusalCodes.ParameterNotAllowed, $"/operation/{name}", $"{op} does not take {name}.");
        }

        switch (kind)
        {
            case QueryOperationKind.Find:
            {
                var limit = members.TryGetValue("limit", out var limitElement)
                    ? (int)Integer(limitElement, "/operation/limit", 1, QueryContract.MaximumFindLimit)
                    : QueryContract.DefaultFindLimit;
                var order = QueryOrder.Newest;
                if (members.TryGetValue("order", out var orderElement))
                {
                    order = String(orderElement, "/operation/order") switch
                    {
                        "newest" => QueryOrder.Newest,
                        "oldest" => QueryOrder.Oldest,
                        _ => throw Refusal(QueryRefusalCodes.InvalidValue, "/operation/order", "order must be newest or oldest."),
                    };
                }

                return new QueryOperation(kind, Limit: limit, Order: order);
            }

            case QueryOperationKind.CountDistinct:
            {
                var field = RequiredString(members, "field", "/operation");
                if (!QueryContract.DistinctFields[unit].Contains(field, StringComparer.Ordinal))
                    throw Refusal(QueryRefusalCodes.DimensionNotAllowed, "/operation/field",
                        $"field must be one of {string.Join(", ", QueryContract.DistinctFields[unit])} for this unit.");
                return new QueryOperation(kind, Field: field);
            }

            case QueryOperationKind.GroupBy:
            case QueryOperationKind.Top:
            {
                var by = RequiredString(members, "by", "/operation");
                if (!QueryContract.GroupDimensions[unit].Contains(by, StringComparer.Ordinal))
                    throw Refusal(QueryRefusalCodes.DimensionNotAllowed, "/operation/by",
                        $"by must be one of {string.Join(", ", QueryContract.GroupDimensions[unit])} for this unit.");
                if (kind == QueryOperationKind.GroupBy)
                    return new QueryOperation(kind, By: by);
                var k = members.TryGetValue("k", out var kElement)
                    ? (int)Integer(kElement, "/operation/k", 1, QueryContract.MaximumTopK)
                    : 5;
                return new QueryOperation(kind, By: by, K: k);
            }

            case QueryOperationKind.TimeBucket:
            {
                if (!members.TryGetValue("bucketSeconds", out var bucketElement))
                    throw Refusal(QueryRefusalCodes.MissingRequired, "/operation/bucketSeconds", "bucketSeconds is required.");
                var seconds = (int)Integer(bucketElement, "/operation/bucketSeconds", QueryContract.MinimumBucketSeconds, QueryContract.MaximumBucketSeconds);
                if (AnalyticsQueryRules.BucketCount(window.FromUtc, window.ToUtc, seconds) > QueryContract.MaximumBuckets)
                    throw Refusal(QueryRefusalCodes.TooManyBuckets, "/operation/bucketSeconds",
                        $"The window and bucket size would produce more than {QueryContract.MaximumBuckets} buckets.");
                return new QueryOperation(kind, BucketSeconds: seconds);
            }

            case QueryOperationKind.Compare:
            {
                if (!members.TryGetValue("baseline", out var baseline))
                    throw Refusal(QueryRefusalCodes.MissingRequired, "/operation/baseline", "compare needs a baseline window.");
                return new QueryOperation(kind, Baseline: ParseWindow(baseline, "/operation/baseline"));
            }

            default:
                return new QueryOperation(kind);
        }
    }

    // --- Cross-member rules ----------------------------------------------------

    private static void CheckCombinations(QueryUnit unit, QueryPredicates where, QueryOperation operation)
    {
        if (unit != QueryUnit.Track)
            return;

        // As on Track search, a plate predicate is never combined with attributes: no existing surface answers the
        // combination, so neither does the contract.
        if (where.Attributes is not null && where.Plate is not null)
            throw Refusal(QueryRefusalCodes.AttributeCombinationInvalid, "/where/plateText",
                "Attributes and a plate text cannot be combined, as on Track search.");

        if (where.SimilarTo is not null)
        {
            if (operation.Kind != QueryOperationKind.Find)
                throw Refusal(QueryRefusalCodes.OperationNotAllowed, "/operation/op",
                    "similarTo is a ranking of candidates: only find is allowed with it.");
            if (where.Zone is not null || where.Line is not null || where.Motion is not null || where.Attributes is not null ||
                where.Plate is not null || where.ObjectSubclass is not null || where.MinDurationMs is not null ||
                where.MinConfidence is not null || where.CameraIds.Count > 1)
                throw Refusal(QueryRefusalCodes.SimilarityCombinationUnsupported, "/where/similarTo",
                    "similarTo combines only with timeWindow, one camera and objectClass.");
            if (operation.Order == QueryOrder.Oldest)
                throw Refusal(QueryRefusalCodes.InvalidValue, "/operation/order", "Similarity candidates are ordered by score.");
        }

        if (where.IsGeometric && where.CameraIds.Count != 1)
            throw Refusal(QueryRefusalCodes.GeometryRequiresSingleCamera, "/where/cameraIds",
                "A zone, line or motion predicate belongs to one camera's scene: name exactly one camera.");
    }

    // --- Primitives --------------------------------------------------------------

    private static QueryWindow ParseWindow(JsonElement element, string path)
    {
        var members = Members(element, path, ["fromUtc", "toUtc"]);
        var from = Utc(members, "fromUtc", path);
        var to = Utc(members, "toUtc", path);
        if (from >= to)
            throw Refusal(QueryRefusalCodes.InvalidValue, path, "fromUtc must be earlier than toUtc.");
        return new QueryWindow(from, to);
    }

    private static DateTimeOffset Utc(Dictionary<string, JsonElement> members, string name, string path)
    {
        var text = RequiredString(members, name, path);
        // Explicit UTC only, as on the Stage-3 and events routes, in the schema's grammar: seconds required, at most
        // millisecond precision (the canonical form's), Z or +00:00. Anything else is refused, never reinterpreted.
        if (!InstantPattern.IsMatch(text) ||
            !DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed) ||
            parsed.Offset != TimeSpan.Zero)
            throw Refusal(QueryRefusalCodes.InvalidValue, $"{path}/{name}", $"{name} must be an explicit UTC instant.");
        return parsed;
    }

    private static IReadOnlyList<Guid> ParseGuidSet(JsonElement element, string path, int minimum, int maximum)
    {
        if (element.ValueKind != JsonValueKind.Array || element.GetArrayLength() < minimum || element.GetArrayLength() > maximum)
            throw Refusal(QueryRefusalCodes.InvalidValue, path, $"Must be an array of {minimum} to {maximum} ids.");
        var set = new SortedSet<Guid>();
        var index = 0;
        foreach (var item in element.EnumerateArray())
        {
            if (!set.Add(Guid(item, $"{path}/{index}")))
                throw Refusal(QueryRefusalCodes.InvalidValue, $"{path}/{index}", "An id may appear once.");
            index++;
        }

        return [.. set];
    }

    private static Guid RequiredGuid(Dictionary<string, JsonElement> members, string name, string path)
    {
        if (!members.TryGetValue(name, out var element))
            throw Refusal(QueryRefusalCodes.MissingRequired, $"{path}/{name}", $"{name} is required.");
        return Guid(element, $"{path}/{name}");
    }

    private static Guid Guid(JsonElement element, string path)
    {
        // Lower case only, as the canonical form writes it, so two spellings of one id can never both be accepted.
        if (element.ValueKind != JsonValueKind.String ||
            element.GetString() is not { } text ||
            !LowerCaseUuid.IsMatch(text) ||
            !System.Guid.TryParseExact(text, "D", out var value) ||
            value == System.Guid.Empty)
            throw Refusal(QueryRefusalCodes.InvalidValue, path, "Must be a non-empty lower-case UUID.");
        return value;
    }

    private static long Integer(JsonElement element, string path, long minimum, long maximum)
    {
        var message = maximum == long.MaxValue
            ? $"Must be an integer of at least {minimum}."
            : $"Must be an integer from {minimum} to {maximum}.";
        if (element.ValueKind != JsonValueKind.Number)
            throw Refusal(QueryRefusalCodes.InvalidValue, path, message);

        // JSON Schema's "integer" includes an integral number written with a fraction (10.0); the parser agrees.
        if (!element.TryGetInt64(out var value))
        {
            if (!element.TryGetDouble(out var number) || Math.Floor(number) != number || Math.Abs(number) >= 9e15)
                throw Refusal(QueryRefusalCodes.InvalidValue, path, message);
            value = (long)number;
        }

        if (value < minimum || value > maximum)
            throw Refusal(QueryRefusalCodes.InvalidValue, path, message);
        return value;
    }

    private static string RequiredString(Dictionary<string, JsonElement> members, string name, string path)
    {
        if (!members.TryGetValue(name, out var element))
            throw Refusal(QueryRefusalCodes.MissingRequired, $"{path}/{name}", $"{name} is required.");
        return String(element, $"{path}/{name}");
    }

    private static string String(JsonElement element, string path)
    {
        if (element.ValueKind != JsonValueKind.String)
            throw Refusal(QueryRefusalCodes.InvalidValue, path, "Must be a string.");
        return element.GetString()!;
    }

    /// <summary>An object's members, refusing a non-object, an unknown member and a repeated one.</summary>
    private static Dictionary<string, JsonElement> Members(JsonElement element, string path, IReadOnlyCollection<string> known)
    {
        if (element.ValueKind != JsonValueKind.Object)
            throw Refusal(QueryRefusalCodes.InvalidValue, path, "Must be an object.");
        var members = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
        foreach (var property in element.EnumerateObject())
        {
            var memberPath = $"{path}/{Escape(property.Name)}";
            if (!known.Contains(property.Name, StringComparer.Ordinal))
                throw Refusal(QueryRefusalCodes.UnknownMember, memberPath, $"{property.Name} is not a member of the contract.");
            if (!members.TryAdd(property.Name, property.Value))
                throw Refusal(QueryRefusalCodes.DuplicateMember, memberPath, $"{property.Name} appears more than once.");
        }

        return members;
    }

    /// <summary>One JSON Pointer reference token (RFC 6901): "~" and "/" escaped.</summary>
    private static string Escape(string name) => name.Replace("~", "~0", StringComparison.Ordinal).Replace("/", "~1", StringComparison.Ordinal);

    private static StructuredQueryParseResult Refuse(string code, string path, string message) =>
        new(null, new QueryRefusal(code, path, message));

    private static RefusalException Refusal(string code, string path, string message) =>
        new(new QueryRefusal(code, path, message));

    private sealed class RefusalException(QueryRefusal refusal) : Exception(refusal.Message)
    {
        public QueryRefusal Refusal { get; } = refusal;
    }
}
