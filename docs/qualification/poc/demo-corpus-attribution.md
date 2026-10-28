# MAVI PoC demo corpus — attribution and licences

**Status:** DRAFT, **pending owner acceptance** (register row B2). When the owner accepts this file, it ships in the PoC kit next to the demo clips, unchanged.

The MAVI PoC kit contains twelve short video clips, licensed under **CC0 1.0** or a **Creative Commons Attribution (CC BY)** licence. No ShareAlike, NonCommercial or NoDerivatives material is included.
- **Clips 1–8** are derived from videos published on Wikimedia Commons. Each licence was read from the file's own Commons description page, at the exact page revision recorded in `tools/poc/demo-corpus/demo-corpus-v1.json`.
- **Clips 9–12** are derived from the MEVA dataset release, which is licensed as a whole under CC BY 4.0. See the MEVA notice below.

**Changes made to every clip (applies to all twelve).** Each clip was:
- trimmed to the time window stated below;
- scaled down to at most the stated width, keeping the aspect ratio;
- re-encoded as H.264/MP4 with MAVI's pinned FFmpeg command;
- stripped of its audio track and container metadata.

No other edit was made: no overlay, no crop and no colour change. The clips are used unchanged as test input for an offline video-analytics demonstration. None of the authors or licensors endorses MAVI or this use.

**Disclaimer of warranties.** The licensors provide the works "as is". See each licence for its full terms.

| # | Demo clip (kit file) | Source work (Wikimedia Commons) | Author / credit | Licence | Window used |
|---|---|---|---|---|---|
| 1 | `s2-01-dusseldorf-junction.mp4` | [Straßenverkehr in Düsseldorf.ogv](https://commons.wikimedia.org/wiki/File:Stra%C3%9Fenverkehr_in_D%C3%BCsseldorf.ogv) (Worringer Platz, 2014-03-08) | Slick (own work) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | 0–180 s |
| 2 | `s2-02-sofia-junction.mp4` | [Trams and road cars at Macedonia square in Sofia.webm](https://commons.wikimedia.org/wiki/File:Trams_and_road_cars_at_Macedonia_square_in_Sofia.webm) (2012-10) | hctv (originally published on YouTube) | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | 2–90 s |
| 3 | `s2-03-crest-hill-road.mp4` | [Views of Caton Farm Road in Crest Hill, Illinois 04.webm](https://commons.wikimedia.org/wiki/File:Views_of_Caton_Farm_Road_in_Crest_Hill,_Illinois_04.webm) (2026-09-05) | Illinois_Roadbuff (Rogue Jr) (own work) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 1–69 s |
| 4 | `s2-04-night-highway.mp4` | [Cars driving at night.webm](https://commons.wikimedia.org/wiki/File:Cars_driving_at_night.webm) (2011-05-28) | YouTube user "Editor" (https://www.youtube.com/user/Editor), YouTube video `Ina7KMV2OEI` | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | 0–158 s |
| 5 | `s2-05-vrhnika-arch-gate.mp4` | [Road traffic – cobblestone road.webm](https://commons.wikimedia.org/wiki/File:Road_traffic_%E2%80%93_cobblestone_road.webm) (2010s) | Sounds of Changes; video recording: Barbara Rezar Grilc; sound recording: Boštjan Troha; photo: Dušan Oblak (uploaded by barbara.grilc) | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | 0–104 s |
| 6 | `s2-06-beynost-level-crossing.mp4` | [Passage à niveaux Beynost 2016.webm](https://commons.wikimedia.org/wiki/File:Passage_%C3%A0_niveaux_Beynost_2016.webm) (2016) | Benoît Prieur (own work) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | 0–70 s |
| 7 | `s2-07-shibuya-crossing.mp4` | [Shibuya Crossing.ogv](https://commons.wikimedia.org/wiki/File:Shibuya_Crossing.ogv) (2008-10-08) | Emran Kassim from Nagoya, Aichi, Japan (via Flickr, "Shibuya crossroad - Video") | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | 0–88 s |
| 8 | `s2-08-damascus-gate-overhead.mp4` | [Three Minutes of Damascus Gate.webm](https://commons.wikimedia.org/wiki/File:Three_Minutes_of_Damascus_Gate.webm) (2018-07-22) | Marsupium (own work) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | 2–172 s |
| 9 | `s2-09-meva-parking-lot.mp4` | MEVA camera G424 (school parking lot), clip `2018-03-11.16-20-02.16-25-02.school.G424.r13.avi` | "Multiview Extended Video with Activities" (MEVA) dataset by Kitware Inc. and the Intelligence Advanced Research Projects Activity (IARPA) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 0–180 s |
| 10 | `s2-10-meva-cafe-lobby.mp4` | MEVA camera G421 (school cafe), clip `2018-03-11.16-20-00.16-25-00.school.G421.r13.avi` | as clip 9 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 0–180 s |
| 11 | `s2-11-meva-school-hall.mp4` | MEVA camera G423 (school hallway), clip `2018-03-11.16-20-00.16-25-01.school.G423.r13.avi` | as clip 9 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 0–180 s |
| 12 | `s2-12-meva-stairwell.mp4` | MEVA camera G419 (school stairwell), clip `2018-03-11.16-20-01.16-25-01.school.G419.r13.avi` | as clip 9 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 0–180 s |

The CC0 works need no attribution. They are credited anyway.

**MEVA notice (clips 9–12).**
- **Attribution and licence.** "Multiview Extended Video with Activities" (MEVA) dataset by Kitware Inc. and the Intelligence Advanced Research Projects Activity (IARPA), licensed under a Creative Commons Attribution 4.0 International License (https://creativecommons.org/licenses/by/4.0/). Source: https://mevadata.org (public release `mevadata-public-01`, drops-123-r13).
- **Changes.** The changes listed above apply: trimmed to the first 180 s, scaled to at most 1920 px wide, re-encoded and audio removed.
- **The people shown.** The people in these clips are volunteer actors recorded at a training facility under an IRB-approved informed-consent process that covered release of the data under CC BY 4.0. Use these clips only as test input. Do not attempt to identify the actors.

## Notes for redistributors

- **Recording times are not real.** The camera names, camera time zone (Asia/Kolkata) and "recording start" times that the demo shows are demo settings, not the real capture time or place. The real dates are in the table above.
- **Zones and lines are demo configuration.** The demo cameras' zones, lines and restricted areas are MAVI configuration drawn for the demonstration. They are not annotations of the works.
- **Recording times are demo settings, but MEVA's simultaneity is real.** Clips 9–12 come from one real 5-minute slot. Their demo start times keep the real offsets between the four cameras, so a person seen in more than one of them was really there at those relative times.
- **No biometric data ships.** In clips 1–8, persons and vehicles appear incidentally in public places. Clips 9–12 show volunteer actors who consented to the recording and its CC BY release. Access control at the facility minimised non-participants in view (MEVA notice). The kit contains no face crop, embedding, gallery, label or annotation derived from these clips. Biometric derivatives produced by a running demo stay on the demo host, and the uninstall path deletes them (plan D3).
- **Platform-licensed footage is not here.** Pexels/Pixabay-licensed footage and research-licensed datasets (for example BDD100K) are **not** part of this corpus. They may be used only on owner machines for live demos (D3).

## Provenance

The selection, the exact file identities and the hashes are recorded in:
- `docs/qualification/poc/s2-demo-corpus-scope-declaration.md`: the predeclared scopes and rules, with amendments;
- `docs/qualification/poc/s2-demo-corpus-admissibility.md`: the ADR-017 admissibility status for each source;
- `tools/poc/demo-corpus/demo-corpus-v1.json`: the Commons page revision, provider SHA-1, original SHA-256, trim window and derivative SHA-256 for each clip.
