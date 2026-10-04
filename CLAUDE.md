# Claude Code Instructions for MAVI

Follow `AGENTS.md` as the binding engineering policy, and work implementation-first per `docs/architecture/engineering-operating-principles.md`. Before a non-trivial change, read the relevant ADRs and specification under `docs/`.

When reviewing or implementing:

- preserve the .NET / React / Python boundaries;
- challenge unnecessary dependencies and premature distributed architecture;
- treat AI output as candidate evidence rather than authoritative operational truth;
- prefer explicit typed contracts over shared implementation details;
- ensure production runtime behavior remains Internet-independent;
- treat every new/changed library, SDK, native binary, runtime or model prerequisite as part of the feature: update `config/dependencies/offline-dependency-policy-v1.json`, offline packaging/setup, verification, licences and runbooks in the same change;
- do not add model weights, video datasets or credentials to Git;
- before proposing a significant annotation campaign, a bespoke dataset or new Development capture, follow ADR-017 and the `AGENTS.md` "Data, benchmarks and annotation" rules: search for and reuse established labelled benchmarks first, and treat such a campaign as a justified fallback (small diagnostic labelling needs only a technical rationale);
- run repository verification and relevant subsystem tests before declaring completion.

For architecture changes, write or update an ADR first and state the trade-off being accepted.
