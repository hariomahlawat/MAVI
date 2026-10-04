# MAVI Engineering Operating Principles

MAVI is **implementation-first**. As a working target, about 80% of engineering effort goes to operational implementation:
- code, tests and integration;
- data and model pipelines;
- benchmarking, profiling and CI;
- qualification, defect resolution and empirical validation.

About 20% goes to the documentation that engineering actually needs. This sets priorities. It is not a measured quota.

These principles apply alongside the binding rules in `AGENTS.md` and the accepted ADRs, which they do not replace.

1. **Implementation first.** Prefer working, tested capability over process artefacts. Research and architecture work should lead to implementation and measured results.
2. **Document only what materially helps engineering.** Keep:
   - the architecture and important ADRs;
   - implementation plans and interfaces/contracts;
   - qualification methods;
   - concise evidence and results.

   Avoid documentation that adds no engineering, reproducibility or audit value: duplicates, ceremonial approvals and repeated decision records. Update the existing authoritative document instead of writing a parallel one.
3. **Prefer executable controls.** Where practical, enforce an important invariant with code, schemas, tests, CI or qualification tooling rather than prose alone. A rule that only a document states should be the exception.
4. **Do not reinvent the wheel.** Before designing a significant algorithm, dataset, benchmark, statistical method, architecture or piece of infrastructure, check:
   - peer-reviewed research and established standards;
   - mature open-source implementations;
   - reputable public datasets and benchmarks;
   - established industry practice.

   Reuse or adapt a proven approach when it meets MAVI's requirements; record the rationale when the departure is consequential or non-obvious.
5. **Use open and public knowledge intelligently.** Public research, open datasets, benchmarks and open-source implementations are strategic engineering resources. Judge each against the role it is meant to serve, not merely because it is public. ADR-015 applies this to S2c source material.
5a. **Benchmark first; label last.** Prefer reuse of established labelled benchmarks and public research assets before creating new labels. Build deterministic adapters, mappings and ground-truth association around strong existing evidence, respecting each dataset's native taxonomy and declaring every mapping as exact, subset or unsupported; never coerce a label the data does not support. Scope capabilities to what the evidence validates: a supported subset may advance while unsupported classes wait. Manual annotation or new data collection requires a demonstrated benchmark gap accepted by the owner, and must not block an otherwise evidence-supported Development capability. The aim is Development speed and reproducibility. ADR-017 is the governing decision.
6. **Use evidence proportionately.** Apply qualification-grade controls where the claim requires them, such as frozen qualification, Production release or authoritative operational evidence. Ordinary development, training and reference work does not carry final-qualification overhead unless it is technically necessary.
6a. **Use the lightest evidence process appropriate to the claim.** Development benchmarking requires reproducibility, provenance, deterministic evaluation and honest limitations. It does not inherit Production qualification ceremony unless the result is being used to make a Production qualification claim. Do not apply frozen-holdout controls, human-independence controls or approval sequencing mechanically to ordinary Development experiments where they add no scientific value; keep them wherever the claim genuinely requires them. Small diagnostic labelling needs a technical rationale, not an approval; a significant annotation campaign needs a demonstrated gap and owner acceptance (ADR-017 §2). Dataset admissibility is recorded once per release unless the terms vary by file (ADR-017 §7). Acceptance rows record evidence outcomes; they are not process stages, and one piece of work may close several.
6b. **Professional documentation is few authoritative documents, clear precedence, exact evidence and minimal duplication.** One authoritative register per stage; exact hashes and provenance; explicit Development versus Production claims; deterministic tooling; honest model and dataset exposure; no unsupported mappings, silent label coercion, hidden access assumptions, dataset bytes in Git, bypassed access controls or redistribution assumptions; immutable historical evidence. It does not mean more approval records than the engineering claim requires.
7. **Keep MAVI modular.** Components, models and algorithms have explicit interfaces, versioned identities and measurable contracts, so each can be upgraded or replaced without redesigning the system.
8. **Review for technical value.** Reviews focus on:
   - correctness and scientific validity;
   - security and performance;
   - maintainability and test strength;
   - data integrity and operational usefulness.

   Do not add process for its own sake.
9. **Anti-drift rule.** Before proposing a documentation-only task, ask whether code, tests, automation, an existing authoritative document, or established research or implementations would meet the objective better. If they would, take that route.
