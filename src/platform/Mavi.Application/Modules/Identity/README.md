# Identity Module

Operator identity for attributable actions (ADR-010). `ICurrentOperator` yields the operator of the
current request (`OperatorId`, `DisplayName`, `IdentitySource`); `OperatorIdentityPolicy` holds the
rules: the identity mode in effect (`Identity:Mode` = `disabled` | `windows-negotiate` |
`development-unattributed`), the start-up refusal of the fallback outside Development or
`poc-single-host` (and always under Production), and which principal is an operator (configured
Windows groups or accounts). The API host wires these to ASP.NET Core authentication and the
`OperatorPolicy` authorization policy; an attributable endpoint opts in with
`.RequireAuthorization(OperatorPolicy.Name)`.
