# Audit Module

Append-only audit of attributable mutations (ADR-010 §4). `IAuditWriter.RecordAsync` runs the
mutation and inserts one `audit_entries` row in the same database transaction (joining the caller's
open transaction if there is one), so the row commits or rolls back with the mutation it records;
`AppendInTransactionAsync` adds a row inside a transaction the caller already holds. The operator
comes from `ICurrentOperator`, the time from `TimeProvider`, the correlation id from
`IAuditCorrelation`. The database refuses UPDATE, DELETE and TRUNCATE on the table.
