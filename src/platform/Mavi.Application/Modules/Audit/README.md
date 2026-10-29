# Audit Module

Append-only audit of attributable mutations (ADR-010 §4). `IAuditWriter.Append` stages one
`audit_entries` row on the request's unit of work, so it commits or rolls back with the mutation it
records; `AppendAndCommitAsync` is for actions whose only state is the audit row. The operator comes
from `ICurrentOperator`, the time from `TimeProvider`, the correlation id from `IAuditCorrelation`.
The database refuses UPDATE, DELETE and TRUNCATE on the table.
