# Claude Code Instructions for MAVI

Follow `AGENTS.md` as the binding engineering policy. Before a non-trivial change, read the relevant ADRs and specification under `docs/`.

When reviewing or implementing:

- preserve the .NET / React / Python boundaries;
- challenge unnecessary dependencies and premature distributed architecture;
- treat AI output as candidate evidence rather than authoritative operational truth;
- prefer explicit typed contracts over shared implementation details;
- ensure production runtime behavior remains Internet-independent;
- do not add model weights, video datasets or credentials to Git;
- run repository verification and relevant subsystem tests before declaring completion.

For architecture changes, write or update an ADR first and state the trade-off being accepted.
