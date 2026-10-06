# Tracker-profile qualification principles

**Status:** Recorded 2026-10-06. Qualification principles; no profile, model or code change.
**Prompted by:** the Stage-3 H3 tracker-gate diagnosis (acceptance register `docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md`, *H3 diagnostic interpretation*), which showed that `trackActivationThreshold = 0.7` restricts association on the BDD100K 5 Hz benchmark domain.

## Principles

1. **Origin of the current values.** `highConfidenceThreshold = 0.6` and `trackActivationThreshold = 0.7` in pipeline profile `phase1-detection-tracking-v1` are the Trackers 2.6.0 defaults, adopted as a neutral starting point awaiting representative tuning (`docs/superpowers/specs/2026-09-11-task-10-rtmdet-bytetrack-design.md`, tracker parameter section: "candidate behavioural parameters, not an accuracy claim"). They were never shown to be MAVI optima.
2. **No single-benchmark settings.** Stage-3 diagnostic benchmarks may identify candidate analytical parameters. No parameter becomes a Production profile setting on the evidence of H3, or of any single benchmark, alone.
3. **One general profile is preferred** where the evidence supports it.
4. **Operating envelope.** Production qualification covers the declared operating envelope, at minimum:
   - several frame rates: low-rate, normal CCTV rates and variable frame rate where available;
   - fixed CCTV viewpoints;
   - high and low camera angles;
   - daylight, dim and night or artificial illumination;
   - near, medium and small or distant objects;
   - sparse and dense scenes;
   - compression and resolution variation;
   - occlusion;
   - Person and Vehicle tracking;
   - the relevant Person and Vehicle subtypes.
5. **More than one profile** is introduced only if measured evidence shows that one profile cannot robustly cover the operating envelope.
6. **No operator tuning.** Operators are not given arbitrary tracker-threshold controls.
7. **Frame-count parameters are frame-rate dependent.** `minimumConsecutiveFrames` (and any other parameter counted in frames) means a different real time at different source frame rates: 2 frames is 400 ms at 5 Hz and about 67 ms at 30 Hz. Production qualification must take this into account. This is recorded as an open qualification and design question; the parameter is not redesigned here.

## What H3 does and does not show

H3 is a valid Development measurement on a 5 Hz tracking domain. It shows that the activation gate restricts association there, and that lowering activation alone also increases Track count and fragmentation. It does not establish a Production tracker profile, and it does not show that any particular value is better outside its domain.
