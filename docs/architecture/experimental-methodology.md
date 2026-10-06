# Experimental Methodology

**Status:** Standing engineering rule, adopted 2026-10-06. The binding summary is the "Experimental methodology" section of `AGENTS.md`; this document explains it.
**Relation to other rules:** It refines operating principle 8 (review for scientific validity) of `docs/architecture/engineering-operating-principles.md` and works alongside principles 6 and 6a (proportionate evidence), ADR-015 (protected final qualification), ADR-017 and the `AGENTS.md` "Data, benchmarks and annotation" rules (benchmarks, mappings and data). Where those documents set a stricter requirement for a particular claim, that requirement applies.

## 1. Principle

A request states a question to investigate. It is not evidence that the method it proposes answers that question. For consequential evidence-producing work, the agent or engineer executing it is responsible for the scientific validity of the method as well as for running it, and is expected to disagree with a proposed method that cannot answer the question.

## 2. Scope

The rule applies to an experiment, benchmark, qualification activity, parameter study, dataset or taxonomy mapping, diagnostic analysis or architectural intervention whose result could materially influence any of:

- MAVI architecture;
- Production parameters or profiles;
- the interpretation of a benchmark;
- qualification status or an acceptance-register row;
- a capability claim;
- detector, tracker or model selection or tuning;
- dataset or taxonomy decisions.

It does not apply to ordinary engineering: deterministic bug fixes, formatting, mechanical refactors with unchanged semantics, routine test repairs, implementation of an already-approved design, and trivial documentation corrections.

Work moves into scope when it begins to change a benchmark or metric definition, a causal interpretation, a qualification criterion, Production behaviour or a capability claim, even if it started as routine. Apply the rule from that point. When unsure whether work is in scope, treat it as in scope; the challenge costs little when the method is sound.

## 3. Relation to the requester

Preserve the requested objective; challenge the method proposed for reaching it. The rule never licenses ignoring the objective or substituting a different question.

A flaw is material when it could change or invalidate the conclusion the experiment is meant to support. If the challenge finds a material flaw, do not run the experiment merely to complete the task. Stop and report:

1. the questionable assumption;
2. the evidence against it, citing the implementation, pinned dependency, document or result;
3. which proposed conclusion would be invalid or ambiguous;
4. the smallest corrected experiment or investigation that still serves the objective.

If the requester, informed of the flaw, still asks for the original run, it may be executed as a labelled limited or diagnostic run. The limitation then travels with every conclusion drawn from it. A request, however explicit, is never evidence that the method is sound.

## 4. Workflow

**Challenge → freeze → execute → cold review.** The stages describe the work, not approval meetings. They add no approval ceremony beyond what the claim already requires (principle 6a). Owner approval is needed only where an existing rule requires it for that claim, or where the challenge changes the requested method materially.

### 4.1 Challenge

Before running anything:

- State the measurement or causal question.
- List the assumptions the proposed method needs to answer it.
- Verify each assumption against:
  - the actual repository implementation;
  - pinned dependency behaviour, read from the installed version rather than from memory or documentation of another version;
  - existing evidence and its definitions.
- Identify confounders and alternative explanations.
- Check that the metric measures the claimed mechanism, not a proxy for it.
- Check that the intervention changes only the intended variable.
- Ask whether an analysis of existing evidence would answer the question without a new experiment.

Prefer the smallest controlled experiment that discriminates between the plausible explanations.

### 4.2 Freeze

Once the method survives challenge, record and freeze before reading any outcome:

- the question or hypothesis;
- the intervention and its control;
- the metrics;
- the attribution and classification rules;
- the decision or stopping criteria, where a decision depends on the result.

Hash diagnostic tooling before inspecting outcomes where practical. Do not adjust the method after seeing results, except under §6.

### 4.3 Execute

Run exactly the frozen experiment. Do not silently broaden it, add parameter points or add sweeps after seeing intermediate results; a new question goes back to §4.1. Keep authoritative and diagnostic evidence separate, and never modify authoritative artefacts from diagnostic work.

### 4.4 Cold review

Before a consequential conclusion is promoted, it is cold-reviewed. The review checks:

- the method;
- implementation fidelity (the experiment ran what was frozen);
- the evidence;
- the arithmetic;
- alternative explanations;
- the scope of the claim.

The reviewer may reject the result or narrow the claim. How independent the review must be follows the claim (principle 6a; ADR-017 §10):

- **Claims that require independence** (Production configuration or profile changes, Production qualification claims, and claims whose governing rule already requires independent review, such as ADR-015 frozen qualification): the review is done by someone who did not design or run the work, either a human reviewer or a separate agent session working from the recorded evidence. Until then the conclusion is recorded as pending independent review and is not promoted.
- **Development-only claims** (Development benchmark interpretation, Development capability or model-selection evidence, Development acceptance-register outcomes): the review may be a deliberate fresh pass by the author over the recorded evidence. It is recorded with the result but needs no second reviewer and does not block. Development benchmarking does not inherit human-independence controls or approval sequencing (ADR-017 §10).

## 5. Evidence language

Label the status of important statements about experimental results:

- **Observed:** explicitly present in measured or runtime evidence.
- **Derived:** computed deterministically from frozen evidence under declared rules.
- **Inferred:** an interpretation the evidence supports but does not show directly.
- **Hypothesis:** a plausible explanation that still needs discrimination.

A correlation or a proxy is not a cause. State a causal conclusion only on the basis of a controlled intervention, a direct trace of the mechanism, or equivalent evidence. Common traps:

- treating a score threshold as the eligibility rule of a component whose real lifecycle has more states;
- treating a benchmark proxy as Production behaviour;
- attributing an association failure to the detector or tracker without tracing it;
- calling a timing correlation a temporal-causality result;
- calling an unmatched prediction a false positive when the ground truth may be incomplete;
- treating a dataset mapping as exact without support from the dataset's native definitions (`AGENTS.md`, "Data, benchmarks and annotation", item 3).

## 6. Defects found after freezing or running

- Disclose the defect.
- Keep the defective result, labelled as superseded, where retaining it is useful. Never silently overwrite it.
- Fix only the identified defect in the method or tooling.
- Add a regression check for the failure mode that was found.
- Freeze the corrected method again before reading its outcomes.
- Do not mix figures from superseded and current analyses unless the mix is justified and labelled.

## 7. Stopping is a valid outcome

A failed methodology review is a successful engineering outcome. It costs less than an experiment whose conclusion cannot be trusted. Likewise:

- a result showing no useful effect is valid evidence;
- falsifying the hypothesis that started the work is not a failed task;
- finding that another subsystem is the dominant cause redirects the work rather than forcing the original intervention.
