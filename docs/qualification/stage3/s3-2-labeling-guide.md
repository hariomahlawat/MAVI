# S3.2 Vehicle Subclass Labelling Guide

**Guide:** `mavi-vehicle-subclass-labeling-guide-v1`.
**Labels:** `mavi-vehicle-subclass-labels-v1`.
**Used by:** S3.2 pilot (T10) and any S3.2 expansion. The parent plan is `docs/superpowers/plans/2026-10-03-stage3-s3-2-vehicle-subclass-measurement.md`, §5 and §10.

This guide defines the human reference label for one MAVI Vehicle Track. Every pack embeds this exact file, and every frozen label is bound to it by hash. If anything is unclear while you are labelling, do not reinterpret this guide. Use `unknown` with the closest reason, and put the question in the note.

## 1. Your task

Each item is one Track: one vehicle that MAVI followed through a video. You see up to four crops of the Track, plus a context frame for each crop with the Track's box drawn on it. Decide what type of road vehicle the boxed object is, using the four labels below, or choose `unknown`.

**Rules that always apply**
1. **Use only the evidence in the pack:** the crops, the context frames and this guide. Do not use the video's title, the camera, the location, or any other source.
2. **Never use MAVI's opinion.** The pack never shows a predicted type or confidence. If you ever see one, stop labelling and report it before you continue.
3. **Do not guess.** Choose a class only when the visible evidence fits that class's definition without assuming anything you cannot see. Otherwise choose `unknown` with a reason. `unknown` is a correct, useful answer, not a failure.
4. **Do not force one of the four classes.** If an object is a vehicle that none of the four classes describes, choose `unknown`.
5. **Do not classify finer than the four classes.** Make, model, brand, colour, body style names and "SUV versus sedan" are irrelevant. Only the four classes below matter.
6. **Stay independent.** If you are the primary or the overlap reviewer, do not discuss items, labels, difficult cases or counts with the other reviewer, or with anyone else, until both label sets are frozen. Ask process questions (how to use the page, not how to label an item) of the measurement owner only.

## 2. Labels

| Label | Key | Definition |
|---|---|---|
| `car` | 1 | A motor vehicle built mainly to carry a small number of people (up to about 9 seats), with a passenger body: sedans, hatchbacks, coupés, convertibles, estates, SUVs and crossovers, minivans and MPVs, and passenger vans with side windows along the passenger area. This includes taxis and police, security or private cars with a car body. |
| `truck` | 2 | A motor vehicle built mainly to carry goods or do work: pickups (any vehicle with an open cargo bed behind the cab), cargo or panel vans and other light commercial vehicles with a closed cargo area, box trucks, flatbeds, tippers, tankers, refuse trucks, tow trucks, cement mixers, fire engines, van- or box-bodied ambulances, and tractor units with or without a trailer. |
| `bus` | 3 | A motor vehicle built to carry many passengers (more than about 9), with a bus or coach body: city buses, coaches, school buses, articulated and double-deck buses, and minibuses or shuttle buses with a bus body. |
| `motorcycle` | 4 | A motorised two-wheeler that a rider sits on: motorcycles, scooters and mopeds, including a motorcycle with a sidecar. |
| `unknown` | 0 | No class can be given from the evidence. A reason is required (§4). |

## 3. Boundary rules

Apply these rules exactly. They decide the hard cases so that two reviewers reach the same answer.

| Case | Rule |
|---|---|
| Car or truck | Decide by purpose, as the body shows it. A passenger body, with windows and seats along its length, is `car`. An open cargo bed or a closed, mostly windowless cargo area is `truck`. |
| Pickup or utility vehicle | An open cargo bed behind the cab is `truck`, whatever the cab size, and even if the bed is covered with a cap or tonneau. A vehicle with a fully enclosed passenger body is `car`, even if it looks rugged or is called a utility vehicle. |
| Van or minivan | A minivan or MPV is `car`. A van whose rear section has side windows and passenger seating is `car`. A van with a windowless or cargo rear section (panel, delivery or work van) is `truck`. If the side or rear section is hidden in every view, choose `unknown`, `occluded`. If it is visible but still does not show whether the rear carries passengers or cargo, choose `unknown`, `ambiguous-type`. |
| Light commercial vehicle | Classify by its body under the car-or-truck rule. Branding, livery or roof equipment alone never makes a vehicle `truck`. |
| Bus or large van | A bus or coach body is `bus`: a high, box-shaped passenger body built as a bus, usually with several rows of side windows, a passenger door and a route or destination sign. A large passenger van with an ordinary van body is `car`. If the deciding part of the body is hidden, choose `unknown`, `occluded`. If the body is visible but you still cannot tell a van from a minibus, choose `unknown`, `ambiguous-type`. |
| Emergency and service vehicles | Classify by body, not by role. A police car is `car`. A police van follows the van rule. An ambulance with a box or van body is `truck`. A fire engine is `truck`. A school or transit bus is `bus`. |
| Tractor unit and trailer | A tractor unit, with or without a trailer, is `truck`. If the Track follows only a trailer, a caravan or other towed equipment with no towing vehicle visible, choose `unknown`, `other` with the note `trailer only`. A car towing a trailer is `car` when the box is on the car. |
| Motorcycle or other two-wheeler | Any motorised two-wheeler a rider sits on is `motorcycle`: scooters, mopeds, e-motorcycles, and a motorcycle with a sidecar. A bicycle, including one with pedal assist, is not one of the four classes: choose `unknown`, `other` with the note `bicycle`. A stand-up kick scooter takes `unknown`, `other` with the note `kick scooter`. If a two-wheeler is visible but you cannot tell whether it is motorised, choose `unknown`, `ambiguous-type`. If it is hidden or too small to judge, use `occluded` or `too-small`. |
| Three-wheelers and other vehicles | Auto-rickshaws, tuk-tuks, quad bikes, agricultural tractors, construction plant, trams, trains and other vehicles outside the four classes take `unknown`, `other`, with a short type note such as `auto-rickshaw` or `tram`. |
| Partly visible vehicle | If the visible part shows the defining feature of one class, use that class: for example, a bus body, an open cargo bed or a motorcycle. If what would decide the class is hidden, choose `unknown`, `occluded`. That applies whether another object or the frame edge hides it. |
| Severe occlusion | If the vehicle is mostly hidden in every view, and no view shows a defining feature, choose `unknown`, `occluded`. |
| Too small to classify | If the vehicle is too small, blurred, dark or low-resolution in every view for its type to be seen, choose `unknown`, `too-small`. Do this even if you could guess from the size or shape of a blob. |
| Mixed Track (identity switch) | If the views clearly show more than one physical vehicle, choose `unknown`, `mixed-track`, even when the vehicles are of the same type. "Clearly" means different colour, shape or type, or that the box visibly moves to another vehicle. |
| Not a vehicle | If the box marks no road vehicle, choose `unknown`, `not-a-vehicle`. Examples: a person, a sign, a building, a shadow, a reflection or an empty road. |
| Ambiguous type | If a vehicle is clearly visible but fits two class definitions, or none, and no rule above decides it, choose `unknown`, `ambiguous-type`. |

## 4. `unknown` reasons

Choose exactly one reason. If more than one applies, use the first in this order:

1. `not-a-vehicle`: the box marks no road vehicle in any view.
2. `mixed-track`: the views show more than one physical vehicle.
3. `occluded`: the deciding part is hidden, by another object or by the frame edge.
4. `too-small`: the vehicle is visible but too small, blurred or dark for its type to be seen.
5. `ambiguous-type`: the vehicle is clearly visible but the class cannot be decided.
6. `other`: anything else, including vehicles outside the four classes. A note is required (§6).

**Hidden or undecidable.** These two reasons are kept apart everywhere in this guide, including in §3.
- When the part of the vehicle that would decide the class cannot be seen in any view, the reason is `occluded` (hidden by an object or the frame edge) or `too-small` (too small, blurred or dark).
- `ambiguous-type` is only for a vehicle whose deciding part is visible but still does not settle the class.

## 5. When views disagree

All views of an item belong to one Track. Base the label on the object inside the box.

- **The views show the same vehicle but differ in quality:** decide from the clearest view(s). A poor view does not override a clear one.
- **The clear views of the same vehicle support different classes:** apply the boundary rules (§3). If they still do not decide it, choose `unknown`, `ambiguous-type`.
- **The views show different vehicles:** choose `unknown`, `mixed-track`.
- **The crop and its context frame:** use the context frame to understand size, position and what the box covers. The box drawn on the context frame decides which object is meant.

## 6. Notes

A note is at most 200 characters, on one line. It is optional, except with `other`.
- **Required** with `other`: name the type or the situation (for example `bicycle`, `trailer only`, `tram`). The labelling page does not enforce this, so check it yourself before exporting (§8).
- **Optionally** add one when a short remark would help an adjudicator. For example: `cargo bed visible in view 3`, or `box shifts to second car in view 4`.
- Never put MAVI ids, guesses about MAVI's prediction, licence plates, people's names, or other identifying details in a note.

## 7. Worked examples (described, no images)

1. A white SUV, fully visible in three views. → `car`.
2. A double-cab pickup whose open cargo bed is visible in one view. → `truck`.
3. A pickup seen only from the front, with the bed hidden by a parked bus. → `unknown`, `occluded`.
4. A high-roof van with no side windows behind the front doors. → `truck`.
5. A van with three rows of side windows, the same size as an ordinary van. → `car`.
6. A box-shaped minibus with a destination sign and a passenger door in the side. → `bus`.
7. A scooter with a seated rider. → `motorcycle`.
8. A cyclist on a bicycle. → `unknown`, `other`, note `bicycle`.
9. Distant vehicles of a few pixels, whose shape could be a car or a van. → `unknown`, `too-small`.
10. The first two crops show a red car and the last two a grey van. → `unknown`, `mixed-track`.
11. The box sits on a road sign in every view. → `unknown`, `not-a-vehicle`.
12. An articulated truck: a tractor unit with a trailer. → `truck`.

## 8. Before exporting your decisions

- Check that every item has a decision, that every `unknown` has a reason, and that every `other` has a note.
- The measurement owner checks the export before freezing it. If an `other` decision has no note, the export goes back to the same reviewer, who adds the note on the page and exports again. The exported file is never edited by hand, and nothing else about any decision is discussed.
- Use **Export decisions** and send the exported file only to the measurement owner, who freezes it.
- Do not edit the exported file. A correction becomes a new, frozen label set; nothing is edited in place.
