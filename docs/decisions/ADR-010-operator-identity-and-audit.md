# ADR-010: Operator identity, authorization and audit for attributable mutations

**Status:** **Proposed — owner decision required** (PoC slice S11-min, register row C10.1). Implemented on the S11-min PR so that it can be reviewed against working code; the row stays IN PROGRESS until the owner accepts this ADR. The decision text for the owner is in §9.

**Date:** 2026-10-29

**Related:** ADR-003 (offline Production); ADR-004 (time authority); ADR-008 (Phase-1 topology: Production behind IIS on Windows); ADR-020 (`poc-single-host`); `docs/superpowers/plans/2026-09-20-audited-review-and-cases-plan.md` (Slice 0 is this ADR, Slice 1 and the append-only principle of Slice 2 are implemented with it); `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md` (S11-min); register `docs/reviews/2026-10-28-poc-acceptance.md` row C10.1.

## Context

Until now MAVI has had no operator mutation that needed attribution: the API has no authentication or authorization middleware and every endpoint is anonymous. The PoC adds several: plate reanalysis (S3), gallery enrolment and update (S6), Entity confirm/dismiss (S7), review decisions and cases (S11-full). Each must record **who** acted, **when** (by the server's clock), and **what**, in a record that cannot be rewritten afterwards.

Constraints:

- Production is offline (ADR-003): no remote identity provider, no OIDC endpoint, no cloud directory.
- Production runs on a Windows host behind IIS (ADR-008); the PoC runs Kestrel on loopback on one Windows host (ADR-020), started by the operator, environment name `PoC`.
- The Production profiles P1–P3 are not to change behaviour in this slice: none of them has an operator mutation yet, and their IIS sites do not enable Windows Authentication.
- Development and CI need a way to exercise attributable endpoints without a Windows token (CI runs on Linux).

**Correction to the plan's premise.** The plans call Negotiate "in-box". It is not part of the ASP.NET Core shared framework: Windows authentication under Kestrel needs the Microsoft package `Microsoft.AspNetCore.Authentication.Negotiate` pinned at **10.0.14**, not the 10.0.11 of the other ASP.NET packages, because 10.0.0–10.0.12 are affected by CVE-2026-70179 (GHSA-vrrp-6v32-2p8g, elevation of privilege). It brings one transitive Microsoft package, `System.DirectoryServices.Protocols` 10.0.14 (LDAP for the non-Windows Kerberos path; managed, with per-OS runtime assemblies and no MAVI-shipped native library). Both are application-local: no machine prerequisite, no network at run time (SSPI on Windows). It is recorded in `config/dependencies/offline-dependency-policy-v1.json`; the developer NuGet cache and `dotnet publish` carry it like the other ASP.NET packages, so the binary catalogue does not change. Under IIS, the same handler defers to IIS's own Windows Authentication — and **throws on every request** if IIS has Windows Authentication disabled. That is why the default mode below is `disabled`.

## Decision

### 1. Identity source: the Windows host, one mode per installation

`Identity:Mode` selects exactly one identity mode for the process:

| Mode | Authentication | Who may act | Where allowed |
|---|---|---|---|
| `disabled` (default) | no scheme visible: the operator schemes are registered, but a scheme provider exposes only the one of the mode in effect, so the Negotiate handler is never built; requests authenticate as anonymous | nobody: every attributable endpoint answers 401 | everywhere; it is the default so that P1–P3 and existing hosts are unchanged |
| `windows-negotiate` | Negotiate (Kerberos/NTLM via SSPI) under Kestrel; deferred to IIS Windows Authentication under IIS | a Windows principal that is a member of a configured group (`Identity:Operators:AuthorizedGroups`) or named in the allow-list (`Identity:Operators:AuthorizedUsers`); an empty configuration authorizes nobody | everywhere; under IIS the site must enable Windows **and** Anonymous Authentication (a Production Setup change, not made here) |
| `development-unattributed` | a fixed fallback identity for every request | everyone who can reach the host | only when the environment is `Development`, or the effective deployment profile is `poc-single-host`; never when the environment is `Production`. Any other combination stops the host at start-up. The refusal is keyed on the environment name and the build/declared profile: a P1–P3 build started with `ASPNETCORE_ENVIRONMENT=Development` by mistake would accept the fallback, because ordinary and Production builds are not distinguishable by build metadata (only the PoC build carries a profile). The fallback also needs `Identity:Mode` set explicitly, which no Production configuration does |

Choosing `development-unattributed` is the explicit setting the fallback requires; there is no implicit fallback. A Windows principal that fails the group/allow-list check is refused (403); an unauthenticated request in `windows-negotiate` mode is challenged (401 `WWW-Authenticate: Negotiate`). Existing endpoints stay anonymous: there is no fallback authorization policy. A new attributable endpoint opts in with `.RequireAuthorization(OperatorPolicy.Name)` and takes its actor from `ICurrentOperator`, never from the request body.

### 2. The operator identity

`ICurrentOperator` (`Mavi.Application.Modules.Identity`) yields `OperatorIdentity(OperatorId, DisplayName, IdentitySource)`:

- `windows-negotiate`: `OperatorId` is the account SID (stable across renames) when the principal carries one, else the account name; `DisplayName` is `DOMAIN\user`; `IdentitySource` = `windows-negotiate`.
- `development-unattributed`: `OperatorId` = `development-unattributed`, `DisplayName` = `Development operator (unattributed)`, `IdentitySource` = `development-unattributed`. The label is carried into every audit record it produces, so an unattributed action can never be read as an attributed one.

### 3. Disclosure

The deployment disclosure (`GET /api/system/deployment`, the System page, ADR-020 §3) gains an `identity` block: the mode in effect, whether actions are attributable, whether any operator is configured, and a statement. Under `poc-single-host` the release metadata written by the installer records the identity mode installed (`identityMode`), and the disclosure shows both; when they differ the System page shows a warning. A change of mode after install is disclosed, not refused: the mode in effect is what every audit row records. The PoC installer writes `windows-negotiate` with `BUILTIN\Users` as the operator group: on a dedicated demonstration host with trusted local users (owner decision S1-T1), every interactive local user is an operator, and every action is attributed to that user's Windows account.

**Browsers.** A browser sends Windows credentials without prompting only to hosts it treats as intranet. Observed on the Development laptop (Chromium 152): from `http://127.0.0.1:<port>` the operator request is refused (401, no credentials sent); from `http://localhost:<port>` the same browser negotiates silently and the operator is resolved. Browser-side attributable actions (S3 onwards) therefore need the operator to open MAVI at `http://localhost:<port>`, or an `AuthServerAllowlist` browser policy; the slice that first adds a UI mutation adjusts the PoC launcher URL. Scripts and services use the credentials of their own process (`UseDefaultCredentials`).

**Cross-site requests.** Because browsers send Windows credentials automatically, a state-changing request under the operator policy must be `application/json` (or carry a JSON body bound by the endpoint). A cross-site page cannot send that without a CORS preflight, which MAVI never grants. Form-shaped requests are refused: 415 by the endpoint's JSON contract, or 403 by the policy when there is no body. The PoC machine configuration also sets `AllowedHosts` to `localhost;127.0.0.1`, so a DNS-rebinding page (another host name resolving to loopback) is refused before any endpoint.

### 4. Append-only audit

One table, `audit_entries`, records every attributable mutation: entry id, operator id, display name and identity source, action, subject type and id, server timestamp (`recorded_at_utc`), SHA-256 of the payload's JSON serialisation (System.Text.Json web defaults: deterministic for a payload type and value, not a canonical JSON form), and correlation id (the request's trace identifier: Kestrel connection id plus request number, unique within a process lifetime, not across restarts).

- **Same transaction.** `IAuditWriter.RecordAsync(record, mutation)` resolves the operator, then runs the mutation and inserts the entry in one database transaction on the request's `MaviDbContext` connection, joining a transaction already open; both commit or neither does. The entry is inserted with SQL, not staged on the change tracker, so a mutation that saves several times or clears the tracker (as plate reanalysis does) cannot drop it. A mutation that manages its own transaction calls `AppendInTransactionAsync` inside it; outside a transaction that call is refused. There is no audit write that could commit apart from the state it describes.
- **Append-only in the database.** Row-level `BEFORE UPDATE` / `BEFORE DELETE` and statement-level `BEFORE TRUNCATE` triggers raise an error, whatever the client. A table owner can still drop the triggers; the guard protects against application defects and casual edits, not against the database owner (privilege separation between the migration role and the application role is a Production hardening item outside the PoC).
- **No payload storage.** The audit row carries the payload hash, not the payload: the mutation's own table holds the state. S11-full adds the read surface.

### 5. Server time authority

Every audit timestamp comes from the injected `TimeProvider` (ADR-004, AGENTS.md); no client-supplied time is accepted.

### 6. Trade-off accepted

- **Ties Phase 1 to the Windows host.** Operator identity is whatever Windows says it is; a non-Windows host gets only `disabled` or the labelled fallback. A portable identity provider (an offline OIDC server, local accounts with passwords) is **deferred**; when a Linux host or a non-domain multi-user deployment needs attributable actions, a new ADR replaces §1.
- **Groups resolve at sign-in.** Membership changes take effect on the next Windows logon token, not immediately.
- **The guard is not tamper-proof against the database owner.** It is an integrity control for the application, not a forensic one (no hash chain). A hash-chained or externally anchored audit log is out of scope.
- **The fallback exists.** It is accepted because CI and Development need to exercise attributable endpoints without a Windows token; it is confined by environment and profile, refused under `Production`, labelled in every record and disclosed.

### 7. Production

P1–P3 behaviour does not change: their configuration does not set `Identity:Mode`, so it is `disabled`; the authentication middleware runs but only the anonymous `disabled` scheme is visible (the Negotiate handler is never built, which a test asserts), and no existing endpoint changes. Enabling `windows-negotiate` for a Production profile requires the IIS site to enable Windows and Anonymous Authentication, which is a Setup change and Production evidence for a later slice.

### 8. Consequences for later slices

S3 (`POST /api/plates/reanalysis`), S6 (gallery), S7 (Entity confirm/dismiss) and S11-full (review decisions, cases) each add `.RequireAuthorization(OperatorPolicy.Name)` to their endpoint and run their mutation through `IAuditWriter.RecordAsync` (or call `AppendInTransactionAsync` inside the transaction they own). S11-full adds the audit read surface.

### 9. Owner decision requested

> **ADR-010 — decision requested.** Accept Windows-integrated operator identity for Phase 1 and the PoC: `Identity:Mode` = `disabled` (default; P1–P3 unchanged) | `windows-negotiate` (Negotiate via the Microsoft package `Microsoft.AspNetCore.Authentication.Negotiate` 10.0.14 (with `System.DirectoryServices.Protocols` 10.0.14) under Kestrel, deferring to IIS Windows Authentication under IIS; operators = configured Windows groups or allow-listed accounts) | `development-unattributed` (fixed labelled fallback, allowed only in `Development` or under `poc-single-host`, refused under `Production`, disclosed and labelled in every audit record). The PoC installer configures `windows-negotiate` with `BUILTIN\Users` as the operator group (trusted-host assumption S1-T1). Every attributable mutation writes one row to an append-only `audit_entries` table in the same database transaction as the mutation, with server time from `TimeProvider`; UPDATE, DELETE and TRUNCATE are refused by database triggers. Accepted trade-off: attribution is tied to the Windows host and a portable identity provider is deferred; the audit guard is an application-integrity control, not a forensic one.
