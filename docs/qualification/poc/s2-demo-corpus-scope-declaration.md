# PoC S2 — demo corpus: predeclared discovery scopes and selection rules

**Status:** recorded and committed **before any search or metadata request**. The commit that adds this file is the scope declaration; the discovery run cites its hash. Changing a scope or rule after discovery starts requires an amendment section below with a reason. Nothing may be silently re-scoped.

**Governing:** plan `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md` §4 S2 and D3 (on `poc/s0-decisions`, PR #237); register rows B1–B5 in `docs/reviews/2026-10-28-poc-acceptance.md`; ADR-017; `AGENTS.md` "Data, benchmarks and annotation"; `tools/qualification/source_acquisition/README.md`.

**Operator:** a Claude Code session (PoC S2), on the owner's instruction of 2026-10-28. The owner sources no data; the operator does the discovery and records determinations. The operator is not an independent reviewer; owner acceptance of the attribution file (register B2) is the owner's ratification of the corpus.

## 1. Purpose (ADR-017 step 1)

Demonstration media for the PoC: 8–12 recorded, fixed-camera clips on which the PoC demo exercises import, tracking, Stage-1 scene analytics (zones, trip lines, dwell, restricted bays), plates (best effort), embeddings, zero-shot attributes and face coverage measurement. **This corpus is not a benchmark, not qualification evidence and not training data.** No label, annotation or ground truth is created (B5). Any capability number later measured on these clips is Development-grade demo evidence only.

**Reuse first (ADR-017).** No established labelled benchmark is a substitute: the demo needs *redistributable* clips the kit can ship. BDD100K (research licence) and the H3 plate sequences are already held for owner-machine live demos (D3) and are not re-acquired here. Kit media must be CC0 or CC-BY (D3).

## 2. Provider and tool

- Provider: **Wikimedia Commons only**, via `tools/qualification/source_acquisition` (`discover`, then `acquire --purpose-approvals`). It is the only provider the tool implements; its network policy (HTTPS, allow-listed hosts, provider SHA-1 verification) applies unchanged.
- Pexels / Pixabay: **not used in the first pass.** They are an owner-machine-only fallback (D3) for a scene class that Commons cannot fill, recorded as an amendment with the reason, retained in a separate `owner-machine-only` folder that never enters the kit.
- Controlled store: `E:\MAVI-Controlled\PoC\Corpus\` (outside Git). Layout: `source-store\` (the helper's `--store`), `derivatives\` (trimmed clips), `manifests\` (SHA-256 manifests), `owner-machine-only\` (empty unless the fallback is used).

## 3. Discovery scopes (fixed)

Each scope is one `discover --search` call (the helper prefixes `filetype:video`) with `--limit 40`, run once, in this order. No other search, category or title lookup is made in the first pass.

| Scope | Search text | Scene class sought |
|---|---|---|
| Q1 | `traffic intersection` | road junction |
| Q2 | `traffic junction` | road junction |
| Q3 | `toll plaza` | gate with vehicles / plates |
| Q4 | `vehicles entering gate` | gate with vehicles / plates |
| Q5 | `parking lot` | car park |
| Q6 | `car park` | car park |
| Q7 | `pedestrian crossing` | pedestrian area |
| Q8 | `pedestrians walking street` | pedestrian area |
| Q9 | `lobby people walking` | lobby / close range, faces |
| Q10 | `railway station concourse people` | lobby / close range, faces |
| Q11 | `surveillance camera footage` | any class |
| Q12 | `timelapse traffic` (excluded at selection unless real-time) | road junction |

## 4. Selection rules (applied in this order)

1. **Licence (file's own page, `extmetadata`).** Kit-eligible only: `cc0`, `cc-by-2.0`, `cc-by-2.5`, `cc-by-3.0`, `cc-by-4.0`. Excluded from the kit: CC-BY-SA (all versions), PD marks other than CC0, GFDL, NC, ND, unknown. A PD-marked file is not CC0 and is excluded under D3.
2. **Technical.** Continuous video (helper rule); duration ≥ 60 s; frame size ≥ 640×360; author named.
3. **Viewpoint.** Fixed (static) camera for the usable span. Screened first from title/description; then a diagnostic look at three frames (start, middle, end) — *rationale: confirm the viewpoint is static so polygon/line geometry stays valid; no labels or counts are produced.* Real-time only (no time-lapse, no edits/cuts in the trimmed span).
4. **Faces (B3).** A clip selected for the face demo, or in which faces are recognisable at close range, is admitted only if CC0 or the page states a model release. Distant, incidental, non-recognisable passers-by in a CC-BY street scene do not make a clip face-bearing; the privacy basis is recorded per determination.
5. **Coverage.** Target 10 clips, minimum 8, maximum 12; at least 3 junction/gate, 1 car park, 2 pedestrian, 1 lobby/close-range. Within a class, prefer: longer real-time span, higher resolution, visible plates (gate/junction), more people/vehicles in frame, distinct site. At most 2 clips from one uploader per class.
6. **Trim.** 1–3 minutes per clip from the original, with the repository's pinned FFmpeg and a recorded deterministic command. Originals are retained unchanged.

## 5. What is never done

No label, box, count, identity, ground truth or annotation is created; no model output is read during selection; no bytes, crops or frames enter Git; no biometric derivative is created in S2.

## Amendments

### A1 (2026-10-28, after pass 1, before pass 2): second discovery pass

**Reason.** Pass 1 (Q1–Q12) described 212 unique files. Only 20 meet rules 1–2 (kit licence, ≥ 60 s, ≥ 640×360), and most of those are press conferences, slideshows or drive-arounds. That leaves fewer than 8 plausible fixed-camera candidates and **no lobby/close-range candidate**. Licence mix of pass 1: PD 77, CC-BY-SA 75, CC-BY 43, CC0 17, other 0. Rules §4 are **unchanged**; only the scope list grows. Pass-1 results stay in the record.

**Pass 2 scopes** (same tool and limit; categories use `discover --category`, which lists direct file members only):

| Scope | Kind | Text | Scene class sought |
|---|---|---|---|
| R1 | search | `road traffic cars` | junction |
| R2 | search | `roundabout traffic` | junction |
| R3 | search | `street traffic people` | junction / pedestrian |
| R4 | search | `crowd walking` | pedestrian |
| R5 | search | `people walking` | pedestrian / lobby |
| R6 | search | `shopping mall people` | lobby |
| R7 | search | `airport terminal people` | lobby |
| R8 | search | `metro station people` | lobby |
| R9 | search | `office lobby` | lobby |
| R10 | search | `parking garage` | car park |
| R11 | category | `Category:Videos of road traffic` | junction |
| R12 | category | `Category:Videos of pedestrians` | pedestrian |
| R13 | category | `Category:Videos of crowds` | pedestrian / lobby |
| R14 | category | `Category:Videos of people walking` | pedestrian / lobby |

### A2 (2026-10-28, after pass 2, before pass 3): licence-targeted pass

**Reason.** Pass 2 raised the pool to 501 described files and 80 that pass rules 1–2. The diagnostic three-frame screen (rule 3) found only three fully fixed viewpoints. Most rule-passing files are walking tours, drive-throughs, drone shots, dashcams or press events. There is still no CC0 or model-released close-range face candidate. Rules §4 are **unchanged**. Pass 3 narrows each search by the file's structured-data licence statement (Commons `haswbstatement:P275=<item>`: CC0 = `Q6938433`, CC-BY-4.0 = `Q20007257`, CC-BY-3.0 = `Q14947546`). This is a discovery filter only: the licence used for every decision is still the one in the file page's own `extmetadata` (rule 1).

| Scope | Search text (after the helper's `filetype:video`) | Scene class sought |
|---|---|---|
| T1 | `haswbstatement:P275=Q6938433 people` | lobby / pedestrian, faces |
| T2 | `haswbstatement:P275=Q6938433 street` | pedestrian / junction |
| T3 | `haswbstatement:P275=Q6938433 traffic` | junction |
| T4 | `haswbstatement:P275=Q6938433 station` | lobby |
| T5 | `haswbstatement:P275=Q6938433 parking` | car park |
| T6 | `haswbstatement:P275=Q20007257 traffic` | junction |
| T7 | `haswbstatement:P275=Q20007257 street people` | pedestrian |
| T8 | `haswbstatement:P275=Q20007257 parking` | car park |
| T9 | `haswbstatement:P275=Q14947546 traffic camera` | junction |
| T10 | `haswbstatement:P275=Q6938433 walking` | pedestrian / faces |

A trim window may sit inside a longer clip whose viewpoint changes elsewhere, provided the whole 60–180 s window is one fixed, uncut shot. A finer diagnostic screen (one frame every ~10 s) of the candidate window establishes this, with the same rationale as rule 3.

### A3 (2026-10-28, after pass 3, before pass 4): car park and indoor-hall pass

**Reason.** After passes 1–3 (about 830 described files) and the diagnostic screens, seven clips have a fixed viewpoint for at least 60 s: five junction/gate/road and two pedestrian. There is still **no car park** and **no lobby/indoor** clip. Rules §4 are unchanged. Pass 4 targets those two classes only, with licence-filtered and multilingual terms (`P275`: CC0 `Q6938433`, CC-BY-4.0 `Q20007257`, CC-BY-3.0 `Q14947546`). It is the **last** discovery pass. Whatever it yields, selection then closes, and any unfilled class is recorded as a gap.

| Scope | Search text (after `filetype:video`) | Class |
|---|---|---|
| U1 | `haswbstatement:P275=Q14947546 parking` | car park |
| U2 | `Parkplatz` | car park |
| U3 | `parkeerplaats` | car park |
| U4 | `estacionamiento` | car park |
| U5 | `haswbstatement:P275=Q14947546 hall people` | lobby |
| U6 | `haswbstatement:P275=Q6938433 hall` | lobby |
| U7 | `concourse` | lobby |
| U8 | `atrium people` | lobby |
| U9 | `escalator people` | lobby |
| U10 | `Bahnhofshalle` | lobby |

If pass 4 still yields no CC0 or model-released lobby/close-range clip, the face scene class is recorded as a gap. It is not filled from a CC-BY clip with recognisable faces (rule 4), and it is not filled by default from a platform-licensed source.
