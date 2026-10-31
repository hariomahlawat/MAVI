# MAVI PoC demo recording script (briefing video)

**Purpose.** This script produces the silent video of about two minutes embedded in the one-slide capabilities briefing (`E:\MAVI-Working\briefing\MAVI-Capabilities-Briefing.pptx`). The video follows the plan section 3 demonstration (`docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md`), told as a story:
- an **opening** of up to 12 s: the problem;
- **eleven chapters**, one per capability line on the slide: 6–9 s each, and about 11 s for "Draw zones and lines";
- two **Next phase** chapters (live alerts on your rules; watchlist alerts as candidates), about 15 s together;
- a **payoff** of up to 10 s: the answer found.

Chapters 1–11 are a real capture of the PoC UI; the opening, the two Next phase chapters and the payoff's wall and statements are rendered by the briefing's `build/story_video.py` from corpus footage. **Where it is recorded.** Slice S13 records it on the Development laptop (GTX 1650 Ti) from a rehearsal install, as the rehearsal of register row D1 (`docs/reviews/2026-10-28-poc-acceptance.md`). D1 itself is the same script on the RTX 4090 demonstration host, offline, from the kit (S12); that run re-records the capture. The laptop demonstrates the 1.5B Ask pack only (owner decision D-S10-3).

**Hard rules.**
- Use only demo-corpus clips 1–13 (`tools/poc/demo-corpus/demo-corpus-v1.json`). **Never** show BDD100K H3 plate sequences, Pexels/Pixabay footage or any owner-machine-only media.
- Faces, similarity and cross-camera results are **candidates**: every candidate on screen shows its score and threshold. No result is ever labelled as an identity.
- The captions and the opening and closing statements are the only overlays. There is no narration.

**Capture.** Use a 1920×1080 browser at 100% zoom, dark theme, with no OS notifications. Pre-load each page off-camera. Record each chapter as its own take, then cut the takes together. A scripted capture (a headless Chromium driven over the DevTools protocol, frames from its screencast) is allowed and gives repeatable takes; it shows no OS cursor, so actions must be visible from what they change on screen. The browser must negotiate Windows identity with the PoC at `http://localhost:<port>` (operator actions are refused at `127.0.0.1`).

## Opening (up to 12 s, no bookmark)

| Time | On screen |
|---|---|
| 0–5 s | All 12 corpus cameras in a 4×3 wall (MAVI multi-camera view, or composited from the clips), each showing camera number and clock. Statement: **"12 cameras. Recording all day, every day."** |
| 5–9 s | The wall grows to 48 tiles (the 12 clips at different offsets). Statement: **"A site with 48 cameras records 1,152 hours of video every day."** |
| 9–12 s | The wall dims. Centre: **"Something happened yesterday. Where do you start?"** Small line: "Watching it all at normal speed would take 144 working days." |

The numbers are arithmetic: 48 cameras × 24 h = 1,152 h, and 1,152 h ÷ 8 h a working day = 144 working days. They are not a benchmark.

## Chapters (bookmark = chapter name = the slide's capability line, exactly)

| # | Chapter / bookmark | Caption | Clip(s) | What happens on screen | Must be visible |
|---|---|---|---|---|---|
| 1 | `Track people and vehicles` | Track movement | 1 Worringer Platz junction | Player with track boxes and IDs on people and vehicles; zones and the "Junction exit" line; live people and vehicle counts. | Boxes that follow real objects. |
| 2 | `Read number plates` | Read plates | 6 Beynost level crossing | Type the partial plate text `V661` (a fragment of the pipeline's own read on this clip, register C4.3), see the matches, open one: Track, plate crop, source frame, player seeks. | Read text with its confidence. Never substitute BDD100K. |
| 3 | `Colours, bags, headwear` | Describe appearance | 8 MEVA bus stop (G331) | Select a person: upper and lower clothing colour, bag, headwear. | Observed rows **and** one Unknown row, each with evidence. |
| 4 | `Search by appearance` | Search appearance | 2 Macedonia Square junction | Query "yellow taxi" → ranked Tracks with crops; the matches are boxed in the player. | Query text; a score on every result. |
| 5 | `Find similar (candidates)` | Similar candidates | 1 Worringer Platz junction (query); candidates from 5 Archway gate and 9 parking lot (not clip 3: its camera is hand-held) | From one vehicle, choose "Find similar". | Panel titled **"Similarity candidates"**, the threshold line, and a score on every row. |
| 6 | `Find this face (candidates)` | Face candidates | 12 MEVA stairwell (G419) | Person with a usable face → earlier appearances and the gallery candidate; a second person shown as Unknown. | Score **and** threshold; "a person decides". The gallery is built on the host from MEVA crops only, never shipped. |
| 7 | `Across cameras (candidates)` | Cross-camera candidates | 10 cafe lobby and 13 entrance hall (the same real 5-minute slot) | The Entity candidate with both Tracks' evidence side by side and its factors (appearance score, time plausibility, face as a separate factor), a note, then Confirm. Confirm only a pair the evidence makes plausible: in S7's diagnostic look 2 of the top 10 were plausible; the S13 take confirms the one S7's operator confirmed (appearance 0.954, 2.1 min apart). | "Cross-camera candidate", factor scores, and the confirmation attributed to the operator. |
| 8 | `Draw zones and lines` | Zones and lines | 1 Worringer Platz junction | **Scene editor (about 4 s):** the camera's configured zones and the gate line, with its direction labels. Do not save a change on camera: a save makes a new scene revision and re-derives the camera's analytics. **Then (about 7 s)** the camera's crossing counts per line and direction, from Tracks (the "Junction exit" line over 09:00–09:03). The Archway gate's line has no crossing in the pipeline output, so it cannot show a count. | The geometry is the camera's real configured zone and line. The counts come from Tracks, not from the editor. |
| 9 | `Events on a timeline` | Event timeline | 2 Macedonia Square junction | The events timeline fitted to the recording; the "Crosswalk" crossings and the per-minute counts; one event's evidence. | Rule version on each event. |
| 10 | `Ask in plain language, confirm the query` | Ask, confirm | 1 Worringer Platz junction: "How many vehicles crossed the Junction exit line today?" (the laptop's 1.5B pack interprets it exactly; checked off-camera first; reference date 2026-10-01) | The question is typed → the proposed query under **Interpreted as** → the operator presses **Run** → the answer from Advanced Search's service, with drill-through. | **"Interpreted as"**, readable, and **Run** pressed before any answer appears (Ask proposes, the operator confirms; D-S10-10). |
| 11 | `Audited review and cases` | Audited cases | 5 Archway gate: the vehicle read as LJ384CR | A review decision on a Track (Confirm detection), the Track and an event added to a case, a note typed, then the Audit page with those entries. | Append-only audit entries with the Windows operator identity and time. |

## Next phase (bookmarks = the slide's NEXT lines; lower-third tag "Next phase")

Live camera ingest and real-time alerting are **not in the PoC**. They need their own ADR (live ingest, latency budget, alert model, watchlist governance) and a stream-capacity spike. The S13 capture therefore **cannot** record these two chapters. Keep the rendered chapters from `build/story_video.py` (corpus footage, drawn UI, "Next phase" tag) in the final cut until live alerting exists.

| # | Chapter / bookmark | Caption | Clip(s) | What happens on screen | Must be visible |
|---|---|---|---|---|---|
| 12 | `Live alerts on your rules` | Live alerts | 5 Archway gate 47.5 s + 8 MEVA bus stop 60 s, side by side, LIVE badges | A tracked vehicle crosses "Arch gate" and an alert is raised from that crossing. The dwell timer over the man in "Waiting area" runs 0:55 → 1:01 and fires "stayed over 60 s". | The "Next phase" tag; alerts raised on this computer, no internet. |
| 13 | `Watchlist alerts (candidates)` | Watchlist alerts | 12 MEVA stairwell 1 s, LIVE badge | "Watchlist alert · candidate": the live face against entry W-0127 (no photo), "Score 0.84 · threshold 0.80", "A candidate, not an identity. A person decides." The operator presses Dismiss ("not the same person"), and it is audited. | Score **and** threshold; the human decision. Never show a real person as a confirmed watchlist match. |

## Payoff (up to 10 s; bookmark `Payoff`, which clears the last highlight)

| Time | On screen |
|---|---|
| 0–2.8 s | The 12-camera wall. A scan line sweeps across it: tiles that don't match go grey, and the Archway gate tile lights in accent with "Match · 09:14:22". Statement: **"One question. Every camera checked."** |
| 2.8–4.6 s | Zoom into the matching tile until it fills the frame. |
| 4.6–8.6 s | Evidence view: the Track box on the vehicle, the "Arch gate" line, the evidence card ("Open in player", "Add to case"). **The deployment banner ("Proof of concept · Not Production-qualified") is legible here: the one time it is called out.** |
| 8.6–10 s | Fade to: **"From 1,152 hours to the clip that matters."**, then to dark, so the loop restarts cleanly on the wall. |

## Timing, captions, poster, export

- **Timing.** The opening is 12 s, the chapters 7 s each (6–9 s allowed; zones and lines about 11 s) and the payoff 10 s, and the two Next phase chapters 8 s and 7 s, so the total is about 118 s. Write down the start time of every chapter and of the payoff in milliseconds. `build/finish_deck.ps1` re-points the bookmarks from `startMs` in `chapters.json` (see the briefing README).
- **Captions** use the two words in the Caption column, at the lower left. The number is in accent blue #3B82F6 and the words in #E6EBF2. The font is Segoe UI Semibold, about 64 px, on a translucent #0A0E15 band. The caption runs through the whole chapter and never covers scores, thresholds or the banner.
- **Credits.** Keep each clip's source and licence credit small at the lower right throughout its chapter (`docs/qualification/poc/demo-corpus-attribution.md`). The CC BY clips require this.
- **Poster frame.** A still of the dimmed 12-camera wall with a play button and "Click to play · <length> seconds", saved as a 1920×1080 PNG at `E:\MAVI-Working\briefing\media\MAVI-demo-poster.png`.
- **Export.** MP4, H.264 High, level 4.1, yuv420p, 1920×1080, 25 or 30 fps constant, a keyframe at least every 2 s, `+faststart`. **No audio track** in the capture. The sound bed and UI sounds are added afterwards by the briefing's `build/sound_design.py`, timed from the chapter starts, and the deck embeds that version muted by default. CRF 20–23, **under 150 MB**, saved as `E:\MAVI-Working\briefing\media\MAVI-demo.mp4`. Media never enters Git.
- **Check before handing over.**
  - Opening, eleven chapters in list order, the two Next phase chapters, payoff.
  - No BDD100K frame.
  - Every candidate has a score and threshold.
  - "Similarity candidates" and "Interpreted as" are readable.
  - The banner is legible in the payoff.
  - The total is about two minutes and the file is under 150 MB.
