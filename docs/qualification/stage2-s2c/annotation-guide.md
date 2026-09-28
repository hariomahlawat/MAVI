# Stage 2 S2c — Attribute Annotation Guide v1

**Status:** Version 1, **candidate**. The guide is fixed now, but its vocabulary is frozen only after the pilot and a recorded owner decision (§10). The frozen guide is identified by its LF-normalised SHA-256, which is recorded in the F1 evidence record (`docs/qualification/stage2-s2c/corpus/f1-evidence-record.json`) and in every assignment. After the pilot, the guide changes only through a new version (§12). It is never edited to fit results.

**Governing:** qualification plan §4 (labelling protocol), §3 (corpus governance), §19 R1 (freeze order), §20 R2 (four partitions); S2c plan §6, §7.1, §10.2–§10.3; ADR-013 §7 and §12 (Unknown/Unavailable semantics).
**Machine-readable vocabulary:** `tools/qualification/attributes/corpus/data/attribute-task-v1-candidate.json`. Where the two disagree, the JSON file governs values and this guide governs how to apply them. A disagreement is a defect to fix before the pilot.
**Tooling:** `tools/qualification/attributes/corpus/README.md`.

---

## 1. Purpose

This guide defines how people produce MAVI's ground truth for learned person and vehicle attributes. Ground truth is what later model selection (S2c.2–S2c.4) and qualification (S5) are measured against. It must therefore be:
- **reproducible**: two careful annotators reach the same label for the same reason;
- **honest about uncertainty**: "cannot tell" is a first-class answer, never a forced guess.

MAVI is a domain-neutral visual-intelligence platform. Nothing in this guide concerns who a person is. No label describes identity, face, age, gender, ethnicity, or any other biometric or demographic property, and annotators must not record any such information anywhere.

## 2. What you label: the annotation unit

MAVI stores accepted evidence as a **Track Evidence Set**: up to four JPEG crops of one tracked person or vehicle, each with a role.

| Role | What it is |
|---|---|
| `representative` | the Track's mandatory summary crop (at most 64 KiB) |
| `near-view` | the crop with the largest/closest view |
| `early-diverse` / `late-diverse` | crops chosen for viewpoint and time diversity |

The corpus identifies each crop by its MAVI Observation UUID and SHA-256, and each Track by its MAVI Track UUID (see `tools/qualification/attributes/corpus/README.md` §3). You label one of two unit kinds, stated in your assignment:
- **Track unit**: you see all crops of one Track together and give one label per attribute for the tracked subject. This is the primary unit: MAVI's operator-facing result is a Track-level result.
- **Crop unit**: you see one crop and label only what that crop shows.

Every unit first gets a `subject-validity` label, then one label per attribute of its object class.

### 2.1 `subject-validity` (every unit)

| Value | Use when |
|---|---|
| `valid` | the unit shows one person (person Track) or one vehicle (vehicle Track) clearly enough to be the tracked subject |
| `non-subject` | no person/vehicle is recognisable, for example background, a pole, a shadow, a reflection or a detector error |
| `wrong-class` | the subject is a vehicle on a person Track, or the reverse |
| `multiple-subjects` | two or more people/vehicles are equally prominent, and you cannot tell which one is tracked |

If `subject-validity` is not `valid`, every attribute of the unit is `unscorable` with reason `non-subject`. The tooling refuses anything else.

## 3. Label outcomes

Each attribute label is exactly one of:
1. **a value** from the attribute's list (§4–§6);
2. **`unscorable`**, with one reason from the closed list below.

| Reason | Meaning |
|---|---|
| `not-visible` | the relevant region (torso, legs, head, vehicle body) is not in view |
| `insufficient-area` | it is in view but too small or too blurred to judge |
| `occluded` | another object or person covers too much of the region |
| `truncated` | the frame edge cuts off too much of the region |
| `achromatic-imagery` | the crop is infrared, greyscale or so colour-cast that true colour cannot be judged (colour attributes only) |
| `ambiguous` | the region is visible but two or more answers are equally defensible under this guide |
| `non-subject` | only when `subject-validity` is not `valid` |

**Never guess.** If you would be choosing between two values by coin toss, the label is `unscorable` with reason `ambiguous`. A forced guess is worse than an honest `unscorable`: it silently corrupts precision measurements.

`unscorable` is not a negative. For presence attributes, `absent` asserts that you can see the relevant area and the object is not there. `unscorable` asserts that you cannot tell. The tooling keeps the two separate end to end.

## 4. Colour attributes

### 4.1 Values

| Attribute | Values | Conditional value |
|---|---|---|
| `person-upper-colour` | `black`, `blue`, `brown`, `green`, `grey`, `orange`, `pink`, `purple`, `red`, `white`, `yellow` | `multicolour` |
| `person-lower-colour` | same as upper | `multicolour` |
| `vehicle-colour` | `beige`, `black`, `blue`, `brown`, `green`, `grey`, `orange`, `red`, `silver`, `white`, `yellow` | `multicolour` |

`multicolour` is **conditional**: it stays in the vocabulary only if the pilot shows it can be labelled consistently (§10). Colour names follow the basic-colour families. Reference swatches for training sessions use synthetic, licence-clean colour patches generated by the Corpus Custodian, never operational imagery. The swatches define the *centre* of each family; the boundary rules below define the edges.

### 4.2 Target region

| Attribute | Region | Excluded |
|---|---|---|
| upper | the outermost visible upper-body garment: torso from shoulders to waist, including sleeves | skin, hair, headwear, scarves hanging below the waist, bags and their straps, anything carried |
| lower | the lower-body garment: legs from waist to ankles (trousers, skirt, shorts, the lower part of a dress) | shoes, socks visible below the garment, skin, carried objects |
| vehicle | the exterior body panels | glass, wheels, tyres, lights, number plates, chrome trim, roof racks, cargo, reflections of the surroundings |

For a one-piece garment (dress, overall), label upper and lower separately from the parts over the torso and legs.

### 4.3 Dominant-colour rule

Label the colour that covers the largest share of the **visible** target region, judged across all crops of a Track unit.
- **One colour covers at least about two-thirds of the visible region:** label that colour.
- **No colour covers that much**, and two or more colours each cover a substantial share: label `multicolour` if it is still in the vocabulary, otherwise `unscorable` / `ambiguous`.
- **Printed logos, small patterns, stripes narrower than the garment, pockets and trim** do not change the dominant colour. A plain garment with a logo takes the garment's colour.
- **An even fine pattern** (small checks, dense print) whose overall impression is one colour takes that colour. If the impression is genuinely two colours, apply the rule above.

### 4.4 Light, shade and imagery

- **Shadow:** judge the lit part of the region. A garment partly in shadow keeps the colour of its lit part. If it is entirely in deep shadow, use `insufficient-area` or `ambiguous`.
- **Reflections and glare** (common on vehicles): ignore specular highlights and mirrored surroundings, and judge the body paint between them. If glare dominates, the label is `unscorable` / `ambiguous`.
- **Strong colour cast** (sodium lamps, coloured signage, a heavy white-balance error): if you can still tell the underlying colour from neutral references in the same crop (road markings, known white objects), label it. Otherwise use `achromatic-imagery`.
- **Infrared or greyscale imagery:** colour attributes are `unscorable` / `achromatic-imagery`, even when the garment looks "white" or "black" in grey levels.
- **Low saturation.** Low saturation is not the same as achromatic imagery; the crop can be in full colour.
  - A washed-out garment with a recognisable hue takes that hue.
  - A truly neutral garment in a colour image is `white`, `grey`, `black` (or, for vehicles, `silver`).

### 4.5 Known ambiguous pairs

These boundaries are the most error-prone. They are the only colour merges the pilot may make (§10.3).

| Pair | Rule |
|---|---|
| `grey` / `white` (person) | `white` only when it reads as white under the scene's light, with no visible grey tone. Otherwise `grey` |
| `brown` / `orange` (person) | `orange` for a saturated, bright hue; `brown` for a dark or muted one |
| `grey` / `silver` (vehicle) | `silver` for metallic paint with visible sheen; `grey` for flat non-metallic paint |
| `beige` / `brown` (vehicle) | `beige` for a light sand/cream tone; `brown` for a darker earth tone |
| `beige` / `white` (vehicle) | `white` unless a warm cream tint is clearly visible |

### 4.6 Visibility

- **Minimum:** the target region must be visible over a meaningful area. As a rule of thumb, at least a quarter of the torso (upper), both thighs or a comparable leg area (lower), or a quarter of the body panels (vehicle), in at least one crop.
- **Partial visibility** that still meets the minimum is labelled normally.
- **Occlusion or truncation** that leaves less than the minimum is `occluded` / `truncated`.
- **Far and small subjects:** if you cannot distinguish the garment from its surroundings, use `insufficient-area`.

## 5. Presence attributes

The values are `present`, `absent` or `unscorable`. At runtime MAVI will only ever show "present" or leave the attribute Unknown; it never claims absence to an operator. `absent` exists in ground truth only so that false detections can be counted.

### 5.1 `person-backpack`

A bag worn on the back, on both shoulders or slung over one shoulder, with its body on the back.

| Case | Label |
|---|---|
| Backpack body visible from behind or the side | `present` |
| Front view: two shoulder straps clearly visible, but no bag body | `present` only if both straps clearly continue over the shoulders to the back. Otherwise `unscorable` / `ambiguous` |
| A single strap across the chest, bag not visible | `unscorable` / `ambiguous` (it could be a shoulder bag) |
| Backpack held in the hand, not worn | `absent` for `person-backpack`: the plan defines this attribute as a backpack *carried on the back or one shoulder* (S2c plan §7.1). It is also `absent` for `person-bag`, which excludes backpacks. This rare case is not captured by v1, and the pilot records its frequency |
| Clear view of the back and shoulders, no backpack | `absent` |
| Front-only view with no straps | `unscorable` / `not-visible` (a backpack could be hidden behind) |
| Back hidden by another person or object | `unscorable` / `occluded` |
| Subject too small to see straps or bag outline | `unscorable` / `insufficient-area` |

### 5.2 `person-bag` (a carried bag other than a backpack)

A handbag, shoulder bag, messenger bag, tote, briefcase, sports bag or shopping bag, held in the hand, on the forearm or on one shoulder.

| Case | Label |
|---|---|
| Handbag, shoulder bag, briefcase, tote, shopping bag, plastic carrier bag | `present`. The plan lists handbag, shoulder bag and briefcase; this guide also includes totes and shopping/carrier bags, because they are carried bags other than backpacks and are not excluded |
| Backpack only | `absent` for `person-bag` (and `present` for `person-backpack`) |
| Rolling luggage / trolley case being pulled | `absent` for `person-bag`: luggage trolleys are excluded (plan §7.1) |
| Small object held (phone, cup, umbrella, folder) | `absent`: not a bag |
| Both hands and both sides visible, no bag | `absent` |
| A hand or side hidden, so a bag could be there | `unscorable` / `occluded` or `not-visible` |
| Cannot tell a bag from clothing or a held object | `unscorable` / `ambiguous` |

### 5.3 `person-headwear` (conditional)

A hat, cap, beanie, hood worn up, or helmet worn on the head. This attribute is **conditional**: it survives only if the pilot shows it can be labelled reliably (§10), and the helmet/hat distinction is not labelled in v1.

| Case | Label |
|---|---|
| Cap, hat, beanie, helmet or raised hood on the head | `present` |
| Headscarf or other head covering worn on the head | `present` |
| Hood down on the shoulders, or a hat held in the hand | `absent` |
| Head clearly visible and uncovered | `absent` |
| Head outside the crop | `unscorable` / `truncated` |
| Head too small, or hair and headwear indistinguishable | `unscorable` / `insufficient-area` or `ambiguous` |

Headwear is described as an object on the head. Nothing about the person's appearance, hair, face or identity is recorded.

### 5.4 Views and orientation

- **Rear view:** a backpack is usually easiest to judge from behind. Headwear is judged from any view where the head is visible.
- **Track units:** combine all crops. A backpack clearly visible in any crop of the Track is `present`. `absent` requires that the crops together show the relevant area clearly and no crop shows the object.

## 6. Vehicle colour

- **Dominant exterior body colour:** apply §4.2–§4.6.
- **Two-tone vehicles** (for example a different roof colour) take the colour of the larger visible body area. If the two areas are comparable, use `multicolour` (if in vocabulary) or `unscorable` / `ambiguous`.
- **Wraps and liveries:** a full wrap of one colour takes that colour. Heavy multi-colour livery follows the dominant-colour rule.
- **Dirt, dust, snow:** judge the visible paint. If the paint cannot be seen, use `unscorable` / `ambiguous`.

## 7. Crop and evidence-role guidance

- Label what the crops show, not what you expect.
- The Representative is a heavily compressed summary crop. Where it disagrees with a sharper supplemental crop of the same Track, the sharper crop is the better evidence for a Track-unit label.
- **A crop that shows a second person or vehicle:** in Track units, label the subject that is consistent across the Track's crops. If that cannot be determined, set `subject-validity` to `multiple-subjects`.
- Do not use information from outside the crops: other Tracks, other cameras, or knowledge of the scene or the people in it.

## 8. Independence, blinding and adjudication

1. **Assignments** list units and allowed values only. They never contain another person's label or any model output.
2. **Double labelling.** On the double-labelled subset, each annotator labels independently and submits before seeing anyone else's labels. The tooling enforces this:
   - no adjudication view is issued while an independent assignment covering its units is unsubmitted;
   - an annotator who has been shown others' labels for a unit cannot submit an independent label for it.
3. **An independent annotator** is independent of model selection and threshold tuning. At least one is required on every double-labelled unit (qualification plan §4). Annotators are registered by corpus-local pseudonym only.
4. **Blind to models.** No model output may be shown during labelling (qualification plan §4).
   - Model- or VLM-proposed labels, if ever used to speed up *single* labelling, are recorded as proposals with the proposer's model family and are never accepted without a human decision.
   - They are never used on the double-labelled subset.
   - They are never produced by a model of the same backbone lineage as a bake-off candidate (S2c plan §10.3).
5. **Adjudication.** When independent labels disagree, an adjudicator (who may be one of the annotators) sees all labels for the unit, decides, and records a rationale.
   - The original labels are kept unchanged beside the decision.
   - An adjudicator may decide `unscorable`. They must not force a value that the evidence does not support.
6. **Conflicts are never resolved silently.** Ground truth cannot be produced while any conflict lacks an adjudication.

## 9. Partitions and what each step may read

Labels exist for four strict partitions: **training**, **tuning**, **selection** and the **frozen qualification test**.
- The **pilot** uses training units only.
- **Main labelling** covers all four partitions, blind.
- After sealing, frozen-test labels are held by the Corpus Custodian outside the evaluation environment. Model-selection tooling reads only the evaluation view, which excludes them by construction.

## 10. Pilot

### 10.1 What the pilot measures

A small double-labelled set from the training partition, stratified by camera, measures:
- label ambiguity: agreement per attribute (full, scorability, value) and confusion per value pair;
- class prevalence per value;
- annotation time;
- whether `multicolour` is labelable;
- whether headwear is viable;
- whether any colour value is unreliable.

### 10.2 Decision thresholds: fixed before the pilot

The thresholds are in the task file's `pilotDecisionRules`:
- minimum Krippendorff's α for value and for scorability agreement, proposed at 0.667;
- a minimum number of double-labelled units per attribute, proposed at 30;
- a merge-confusion share, proposed at 0.25.

The owner confirms them, and may raise but never lower them, **before any pilot label exists**. The tooling refuses pilot assignments until they are confirmed. They are never changed after pilot results are seen.

### 10.3 Permitted outcomes

Only these changes, all pre-declared, may follow the pilot:
- merge one of the §4.5 value pairs, keeping one member's name;
- merge `person-backpack` with `person-bag` into `person-carried-bag`;
- remove the conditional `multicolour` value;
- remove any attribute that does not reach its thresholds.

Nothing may be added. Each change is an owner decision with its rationale (the freeze decision record). If an attribute cannot be labelled reliably, it is removed or merged; the threshold is not lowered.

## 11. Main labelling

After the freeze:
1. main labelling of Track units (and crop units where the protocol requires them) across all partitions, blind;
2. independent double labelling of a representative subset, including every camera where support permits;
3. adjudication of conflicts;
4. ground truth derived by the tooling;
5. the frozen test sealed.

Agreement is reported per attribute:
- statistics: raw agreement, Cohen's κ (two raters) and Krippendorff's α (nominal);
- separately for the full category, scorability and value;
- with support by partition, site and camera.

## 12. Versioning

- The guide and the task file are versioned together.
- **Before the pilot:** clarifications are allowed, with a new SHA-256 recorded in each assignment.
- **After the freeze:** any change is a new guide version. It invalidates agreement results it could affect, and those units are relabelled or the change is recorded as a protocol revision (qualification plan §18).
- The frozen guide's SHA-256 is recorded in the F1 evidence record.

## 13. Privacy and data handling

- Crops are private evidence. They stay in the Corpus Custodian's access-controlled store, **never in Git**, never in a cloud service, never on personal devices outside that store.
- Labelling works offline. No crop is uploaded anywhere.
- Annotators are identified by corpus-local pseudonyms. No personal data about annotators or subjects is recorded.
- Records in Git hold only opaque identifiers (UUIDs, SHA-256s, pseudonyms), labels and reports. The tooling refuses local paths and locators inside records.
- Illustrations for training use synthetic, licence-clean images only.
- Retention of the corpus and labels follows the Corpus Custodian's recorded retention decision (ADR-013 §19).
