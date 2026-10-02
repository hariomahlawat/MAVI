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

   Reuse or adapt a proven approach when it meets MAVI's requirements, and record why when it does not.
5. **Use open and public knowledge intelligently.** Public research, open datasets, benchmarks and open-source implementations are strategic engineering resources. Judge each against the role it is meant to serve, not merely because it is public. ADR-015 applies this to S2c source material.
6. **Use evidence proportionately.** Apply qualification-grade controls where the claim requires them, such as frozen qualification, Production release or authoritative operational evidence. Ordinary development, training and reference work does not carry final-qualification overhead unless it is technically necessary.
7. **Keep MAVI modular.** Components, models and algorithms have explicit interfaces, versioned identities and measurable contracts, so each can be upgraded or replaced without redesigning the system.
8. **Review for technical value.** Reviews focus on:
   - correctness and scientific validity;
   - security and performance;
   - maintainability and test strength;
   - data integrity and operational usefulness.

   Do not add process for its own sake.
9. **Anti-drift rule.** Before proposing a documentation-only task, ask whether code, tests, automation, an existing authoritative document, or established research or implementations would meet the objective better. If they would, take that route.
