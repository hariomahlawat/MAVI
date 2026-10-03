# S3.2b-2 runbook: real corpus intake and derivation

**Status:** execution runbook, not yet executed. No real corpus, release record, determination, source pool, ingestion map or derivation exists. Executing it requires the gates in §0.

**Scope.** It covers real release intake, rights and R-5 recording, media probing, the source-pool freeze, ingestion-map preparation and T8 derivation. It ends at the S3.2b-3 pre-flight checklist (§18). It does not cover T9 (S3.2b-3) or T10/T11.

**Authority and prerequisites.** The precedence order is `docs/architecture/README.md`, "Documentation precedence".
- **ADR-016 (accepted, 2026-10-02): the Stage-3 subclass-source decision.** `capability-implementation-roadmap.md` records Stage 3's source precondition as satisfied by it. It decides the source (detector-native) and requires **evaluation first** (§7): measurement on MAVI-held development clips before any operator exposure. S3.2 is that measurement.
- **The capability roadmap.** `capability-roadmap.md` records Stage 3 as **In progress (Development measurement; not operator-exposed)**. API, search and UI exposure stays deferred under ADR-016 §7 until this measurement supports it. Nothing in this runbook exposes anything.
- **The register.** `docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md` is Stage 3's only authoritative exit gate and owns every acceptance state this runbook gathers evidence for (rows E1–E21; §18).
- **The plan.** `docs/superpowers/plans/2026-10-03-stage3-s3-2-vehicle-subclass-measurement.md` (T7, T8, T9, §8, §15, §20) states how ADR-016 §7 is carried out.
- **Tooling:** as merged in PR #150 (`main@379b7b22`).
- **Gate before §3.** R-1 records, in the ledger (§17), that ADR-016 is still `Accepted` and not superseded on the `main` used for this event, and that neither roadmap names any other unmet prerequisite for this measurement. If either check fails, **stop**: a superseding decision governs, not this runbook.

Every command below is the implemented CLI. Where no CLI exists, a short snippet calls the merged module function itself; none of them is a new tool.

**Never:**
- commit corpus media, frames or crops to Git;
- write a local absolute path into a canonical artefact;
- edit a canonical artefact to silence a refusal;
- let MAVI tooling accept terms, judge rights or privacy, or choose the pool from MAVI output.

---

## 0. Roles, preconditions and conventions

| Role | Holder (assign before §3) | Decides |
|---|---|---|
| R-1 Accountable execution owner | `<R-1 NAME>` | access request, terms acceptance, the controlled-store designation, the pilot selection (§10) |
| R-5 Licence Review Owner | `<R-5 NAME>` | the rights and privacy determination, the R-5 ruling, and whether member names may enter Git (§11.3) |
| Operator | `<OPERATOR NAME>` | runs the commands, retains the evidence, keeps the ledger (§17) |

**Preconditions.**
- [ ] A Windows x64 Development machine with a clone of `main` that contains PR #150.
- [ ] The repository venv, `$Repo\.venv`, has `tools/requirements.txt` installed, including `tzdata`.
- [ ] A verified FFmpeg dependency pack (§2).
- [ ] R-1 has designated the controlled store (§1).

**PowerShell session variables.** Set these once per session. All later commands run from the repository root.

```powershell
$Repo  = "<REPO_ROOT>"                                   # the Git clone
$Py    = "$Repo\.venv\Scripts\python.exe"
$Store = "E:\MAVI-Controlled\Stage3\S3.2\<EVENT_ID>"     # the designated controlled store (§1)
$Root  = "$Store\release-root"                           # the release root: release files only
$Pack  = "$Store\media-tools\ffmpeg"                     # the verified FFmpeg dependency pack (§2)
$RelJson = "$Store\release\release-record.json"
$MaxImportBytes = <HOST_VideoImport_MaximumFileSizeBytes> # the S3.2b-3 host value; default 3221225472
Set-Location $Repo
```

**Conventions.**
- **Hashes** are lowercase hex. PowerShell's `Get-FileHash` prints upper case, so always use `(Get-FileHash -Algorithm SHA256 <file>).Hash.ToLowerInvariant()`.
- **Hand-written JSON** (the release record, `selection.json`, the map draft) is UTF-8 **without a BOM**. The tools' strict JSON reader refuses a BOM. In Windows PowerShell 5.1, `Set-Content -Encoding utf8` and `Out-File` add one, so write with `[IO.File]::WriteAllText(<path>, <text>, [Text.UTF8Encoding]::new($false))` or with an editor set to "UTF-8" (not "UTF-8 with BOM").
- **Member paths** are release-relative and use forward slashes (`videos/c001/clip.mkv`). They are exactly the `files[].path` of the release record (§4).
- **Write-once outputs.** Every tool refuses an existing output (`output_exists`). A rerun always goes to a new path. A successful output is never deleted or overwritten.
- **Logs.** Tee every command's stdout and stderr into `$Store\logs\` with a sortable name. For example:
  `... 2>&1 | Tee-Object "$Store\logs\<YYYYMMDD-HHMMSS>-<step>.log"`.
  Logs stay in the controlled store, because they contain local paths.

---

## 1. Controlled-store layout

**Purpose.** One local place outside Git for every real byte and every path-bearing log.

**Convention.** This follows the S2c precedent: R-1/R-6 designated an event-specific store outside Git (`real-qualification-execution-record.md` §4.3.9). For S3.2b-2, R-1 designates `$Store`, an E: path by default, and records the designation in the ledger (§17). It must not be inside any Git worktree. `verify_release_files` refuses a root inside one, and `derive_mp4` refuses an `--out` inside one.

```text
<Store>\
  terms\           exact terms/licence/access material as received (also copied into release-root\evidence\)
  release-root\    THE release root: only the files listed in the release record's files[]
    archives\        delivered archives exactly as downloaded (never modified)
    media\           videos extracted from those archives
    evidence\        terms/licence text, readme, version text, source metadata files, exposure statements
  release\         release-record.json, files-inventory.json, authorisation reports
  media-tools\     ffmpeg\ (the verified pack), pack-identity.txt
  probes\          <sourceSha256>.probe.json (one per candidate video)
  selection\       candidate-review.csv (§9), selection.json (§10)
  pool\            source-pool.json (the frozen record)
  ingestion\       ingestion-map.json, convention notes
  derivations\     <memberSlug>__<mode>__run1\ (and __run2\ for determinism repeats)
  evidence\        ledger (§17), extraction re-check, pre-flight (§18) evidence
  logs\            command transcripts (they contain local paths and stay here)
```

**Create the layout first.** Every later step expects these directories. The tools refuse a missing output parent (`output_parent_missing`).

```powershell
"terms","release-root","release","media-tools","probes","selection","pool","ingestion","derivations","evidence","logs" |
  ForEach-Object { New-Item -ItemType Directory -Force "$Store\$_" | Out-Null }
```

**Rules.**
- No real corpus media, frame, crop, archive or log goes into Git.
- Git receives only permitted metadata or digests:
  - the source-pool record or its `.sha256` digest (§11.3);
  - the ingestion map or its digest, and the ingestion convention (§12);
  - later, the hash-only §20 evidence.
- Canonical S3.2 artefacts (probe, pool, map, derivation) never contain a local path; the tools enforce this. Logs and ledgers in the store may.
- The release record (`$RelJson`) stays in the controlled store. Its identity, `releaseRecordSha256`, is recorded in the ledger. T9 reads it at runtime.

---

## 2. Verified media-tool pack

**Purpose.** Pin the exact FFmpeg and ffprobe used for every probe and derivation.

**Why not PATH.** The tools accept binaries only from a MAVI FFmpeg dependency pack (`tools/stage3/media_tools.py`). That means a manifest, the host runtime id, a SHA-256 per executable, and a `-version` output containing the manifest `version`. Artefacts record the pack's `{version, sha256}`. A PATH binary has no pinned identity, so it is never acceptable evidence.

**Inputs.** `config/dependencies/offline-binary-catalog-v1.json` (`ffmpeg-win-x64`, pinned version and archive SHA-256).

**Commands.**
1. Prepare the pack on the connected preparation machine. Use the authoritative script and its documentation (`vendor/ffmpeg/README.md`); do not prepare it ad hoc:
   ```powershell
   & "$Repo\tools\setup\Prepare-MaviFfmpegWindows.ps1"     # stages $Repo\vendor\ffmpeg (gitignored)
   ```
   On a disconnected host, use the `vendor\ffmpeg` of the verified offline binary kit instead.
2. Freeze it for this event: copy it once into the store, then verify it.
   ```powershell
   Copy-Item -Recurse "$Repo\vendor\ffmpeg" $Pack
   @'
   import hashlib, sys; sys.path.insert(0, "tools/stage3")
   from pathlib import Path
   import media_tools
   lines = [f"{tool} {media_tools.load(sys.argv[1], tool).identity}" for tool in ("ffprobe", "ffmpeg")]
   lines.append("manifest.json " + hashlib.sha256((Path(sys.argv[1]) / "manifest.json").read_bytes()).hexdigest())
   Path(sys.argv[2]).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n"); print("\n".join(lines))
   '@ | & $Py - $Pack "$Store\media-tools\pack-identity.txt"
   ```
   Python writes the identity file itself, so it stays UTF-8 in every PowerShell version.

**Expected.** One `{version, sha256}` line each for ffprobe and ffmpeg, then the manifest SHA-256.

**Stop.** Any `media_tools_invalid:*`.

**Retain.** `pack-identity.txt`, the pack's `win-x64\LICENSE.txt`, and the catalog entry it came from.

**Exit.** Use `$Pack` unchanged for every §8, §13 and §14 command. If the pack changes mid-event, all later probes and derivations differ in identity. Avoid that: if it must change, record why and re-probe.

---

## 3. Dataset acquisition boundary (human)

**Purpose.** Obtain the release lawfully and retain proof of what was received. Only humans act here.

| Human / owner actions (R-1) | MAVI tooling never |
|---|---|
| request access through the official source as presented | clicks through, signs or accepts any terms |
| read the terms, and accept them only if acceptable | infers permission because a download succeeded |
| retain the exact terms/licence material received | substitutes general web information for missing legal evidence |
| decide whether the dataset may proceed to R-5 review | decides rights, privacy or the R-5 ruling |

**Retention checklist.** All of these must be complete before any member is used:
- [ ] Official dataset and release name, as presented.
- [ ] Release or version identifier, as presented.
- [ ] The official source reference: the HTTPS URL of the access page.
- [ ] The exact retrieval date or dates.
- [ ] The licence/terms/agreement documents, saved byte-exactly in `terms\` and `release-root\evidence\`.
- [ ] SHA-256 of every terms document.
- [ ] Every delivered archive in `release-root\archives\`, exactly as downloaded, with its size and SHA-256.
- [ ] Release readme, version and changelog text, in `release-root\evidence\`.
- [ ] Any source-provided camera, time, location or scene metadata, saved as delivered in `release-root\evidence\` or inside the archives.
- [ ] Any public statement relevant to known model exposure, as a document or a recorded reference, for `knownExposure`.

**Stop.** Any of these:
- access is not granted;
- the terms are not acceptable to R-1;
- the terms cannot be retained byte-exactly;
- the release identity is ambiguous.

If any applies, record it and do not proceed (plan §8, "If CityFlow is unsuitable").

**Do not assert dataset facts from memory.** Every fact about the dataset comes from the retained material. That includes edition, licence, camera layout, metadata availability and exposure.

---

## 4. Release-root assembly and file inventory

**Purpose.** Place and hash exactly the files the release record will list.

**Steps.**
1. **Archives.** Copy the delivered archives into `release-root\archives\`, unmodified.
2. **Extraction.** Extract the videos into `release-root\media\`, then extract a second time into a scratch directory outside the store, using the same tool and version. Every video's SHA-256 must match between the two extractions. Record the tool, its version and the comparison in `evidence\extraction-check.txt`.
   - MAVI tooling does not prove that an extracted file came from an archive. This repeat extraction is the human evidence that it did.
3. **Evidence files.** Copy them into `release-root\evidence\`.
4. **Path check.** Every path under the root must match the release parser's member-path rule: `/`-separated segments of `A-Z a-z 0-9 . _ -` only, so no spaces and no other characters. If a delivered name does not match, **stop and raise an engineering issue.** Do not rename files silently, because the release record pins paths.
5. **Generate the inventory.** This is mechanical hashing only.
   ```powershell
   @'
   import hashlib, json, re, sys
   from pathlib import Path
   root = Path(sys.argv[1]); rule = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
   files = []
   for p in sorted(root.rglob("*")):
       if p.is_file():
           rel = p.relative_to(root).as_posix()
           if not rule.fullmatch(rel): sys.exit(f"path not representable: {rel}")
           h = hashlib.sha256()
           with open(p, "rb") as s:
               for b in iter(lambda: s.read(1 << 20), b""): h.update(b)
           files.append({"path": rel, "sizeBytes": p.stat().st_size, "sha256": h.hexdigest()})
   files.sort(key=lambda f: f["path"])
   Path(sys.argv[2]).write_text(json.dumps(files, indent=1) + "\n", encoding="utf-8", newline="\n")
   print(len(files), "files")
   '@ | & $Py - $Root "$Store\release\files-inventory.json"
   ```
   Python writes the file itself, because PowerShell 5.1 `>` redirection would write UTF-16.

**Expected.** `files-inventory.json`: a sorted, unique `[{path, sizeBytes, sha256}]` list covering every file under `$Root`.

**Rules.**
- Nothing else may live under `$Root`.
- `verify_release_files` checks every listed file on every T8 run, so an unlisted file would be unverified material.

---

## 5. Release-record authoring (`mavi-attribute-dataset-release-v1`)

**Purpose.** Author the record parsed by `parse_release` (`tools/qualification/attributes/datasets/release.py`). Do not create a real record before §3 and §4 are complete.

**Field-level text rules.**
- The parser refuses a local path anywhere in the record.
- `name`, `version`, exposure `subject`/`evidence` and excluded `reason` are free text checked by `require_free_text` (`canonical.py`). The same rule applies to the pool's `sourceCamera`/`inclusionReason` and the map's camera `name`/`sourceCamera`. It refuses anything path-like or URL-like:
  - a scheme (`://`) or `file:`;
  - a leading `/` segment, a drive letter or `..\`;
  - `%2f` or `%5c`;
  - **media file names** (`x.mp4`, `.mkv`, ...).
- Write these fields as prose. Put URLs only in `officialUrl` and `licence.url`.

| Field | Source of value | Author | Null? | Must never be invented |
|---|---|---|---|---|
| `schemaVersion` | constant `mavi-attribute-dataset-release-v1` | mechanical | no | |
| `releaseId` | stable MAVI token for this release: `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, at most 64 characters | R-1 | no | must not imply a version not shown in the retained material |
| `name` | the official dataset name, as presented | R-1 | no | |
| `version` | the release/edition/track identifier, as presented | R-1 | no | yes: copy it from the retained readme or version text |
| `origin` | constant `public` (v1 records public releases only) | mechanical | no | |
| `officialUrl` | the HTTPS official access page, at most 500 characters | R-1 | no | yes |
| `pinnedSource.kind` | token naming the retrieval channel (for example the provider's portal): `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, at most 64 characters (no trailing or double hyphen) | R-1 | no | |
| `pinnedSource.reference` | the request, approval or download reference as presented (non-empty text) | R-1 | no | yes |
| `pinnedSource.retrievedOn` | `YYYY-MM-DD` of the retrieval | R-1 | no | yes |
| `licence.codes` | sorted, unique, lowercase licence codes (for example `cc-by-4.0`); for bespoke terms, a token naming them | R-5 confirms | no (non-empty) | yes: never guess a standard licence for bespoke terms |
| `licence.url` | HTTPS URL of the licence/terms | R-1 | yes (if there is no URL) | |
| `licence.textSha256` | SHA-256 of the retained licence/terms file | mechanical | no | |
| `files` | `files-inventory.json` (§4), verbatim | mechanical | no (non-empty) | never hand-edit sizes or hashes |
| `excludedMembers` | `[{path, reason}]`, sorted by `path`, for members R-1/R-5 exclude on review | R-1 / R-5 | `[]` allowed | |
| `determination` | **R-5 only** (§6) | R-5 | `null` until R-5 decides | never authored by the operator or by tooling |
| `knownExposure` | `[{subject, evidence}]` sorted, from retained statements | R-1 | `[]` allowed | yes: only documented exposure |

**Excluded members.** These stay listed in `files[]`, so they are still pinned and verified, and also appear in `excludedMembers`. The tools refuse them as pool members (`source_pool_invalid:member_excluded`) and as derivation members (`derivation_member_excluded`).

**Template** (placeholders only; not a record):

```json
{
  "schemaVersion": "mavi-attribute-dataset-release-v1",
  "releaseId": "<RELEASE_ID>",
  "name": "<OFFICIAL_DATASET_NAME>",
  "version": "<RELEASE_VERSION_AS_PRESENTED>",
  "origin": "public",
  "officialUrl": "<OFFICIAL_HTTPS_URL>",
  "pinnedSource": {"kind": "<CHANNEL_TOKEN>", "reference": "<ACCESS_REFERENCE>", "retrievedOn": "<YYYY-MM-DD>"},
  "licence": {"codes": ["<LICENCE_CODE>"], "url": "<LICENCE_HTTPS_URL_OR_null>", "textSha256": "<SHA256>"},
  "files": "<CONTENTS OF files-inventory.json>",
  "excludedMembers": [],
  "determination": null,
  "knownExposure": []
}
```

The record's identity is `release_sha256(release)`: the SHA-256 of its canonical form. Any edit, including R-5 adding the determination, changes it. Record the final value in the ledger only after R-5's determination is in the record.

---

## 6. R-5 decision package

**Purpose.** Give R-5 everything needed to decide. The operator and the tooling decide nothing here.

**Package contents** (assembled by the operator in `release\r5-package\`):
- the release record with `determination: null`, and its current SHA-256;
- the retained terms/licence files and their SHA-256s, plus the retained access correspondence;
- the readme and version text;
- the exposure statements;
- the intended use, as stated in the "What each S3.2b-2 step needs from the inventory" list below;
- the member list or, if R-1 has a candidate shortlist, that list.

**What S3.2b-2 asks R-5 to determine.** R-5 fills `determination`; `parse_determination` defines its shape.

| Member | Content (R-5 authors) | Notes |
|---|---|---|
| `determinationId` | token | |
| `reviewedOn` | `YYYY-MM-DD` | |
| `purposes` | must include `benchmarking` and `development` (sorted list) | public origin can never carry `frozen-qualification` |
| `licenceCodes` | must cover every `licence.codes` entry | |
| `rights.reviewedBy`, `rights.evidence` | text | |
| `rights.determination` | only `PERMITTED_FOR_ENGINEERING_USE` authorises | anything else blocks (`rights-determination-missing`) |
| `rights.inventory` | a status for **all five** operations: `evaluate`, `create-derivatives`, `train`, `run-operationally`, `redistribute-derived-weights` | each status is one of `granted`, `not-granted`, `not-stated`, `pending-r5` |
| `privacy.reviewedBy`, `privacy.basis` | text | |
| `privacy.disposition` | `PERMITTED` or `DENIED` | `DENIED` blocks (`privacy-denied`) |
| `r5Ruling` | `null`, or `{ruledBy, ruling, reference}` | **required**, with `ruling: "PERMITTED"`, when any licence code is share-alike or not a recognised open licence (bespoke terms are) |

**What each S3.2b-2 step needs from the inventory:**
- source-pool use and measurement: `benchmarking` and `development` exercise `evaluate` only, so `evaluate` must be `granted` (`authorise_release_use(..., operations=[], member=m)`);
- **passthrough** needs nothing more: `create-derivatives` is not exercised;
- **remux and transcode** need `create-derivatives` `granted` (`operations=["create-derivatives"]`);
- `train`, `run-operationally` and `redistribute-derived-weights` are not exercised by S3.2b. R-5 still records a status for each.

T8 enforces the determination; it does not make it.

**Expected blocker behaviour** (exact strings from `authorise_release_use` and the tools):

| Situation | Blocker | Tool refusal |
|---|---|---|
| `determination: null` | `determination-missing` | pool: `source_pool_invalid:not_authorised:determination-missing`; T8: `derivation_not_authorised:determination-missing` |
| an operation `not-granted` | `rights-operation-not-granted:<op>` | as above, with that blocker |
| an operation `not-stated` **or** `pending-r5` | `rights-operation-pending-r5:<op>` (the same string for both) | as above |
| purpose or licence not covered | `purpose-not-covered-by-determination` / `licence-not-covered-by-determination` | as above |
| rights or privacy review incomplete or denied | `rights-determination-missing` / `privacy-determination-missing` / `privacy-denied` | as above |
| R-5 ruling required but missing | `r5-ruling-missing` | as above |
| excluded member | (refused before authorisation) | `source_pool_invalid:member_excluded`, `derivation_member_excluded` |

**Exit.** R-5 has written the determination into the record. The operator records the new `releaseRecordSha256` and the per-member authorisation report (§7) in the ledger.

---

## 7. Release verification and authorisation report

**Purpose.** No member proceeds unless the record parses, the store verifies cleanly and authorisation is reported per member.

```powershell
@'
import sys; sys.path.insert(0, "tools/stage3")
import release_bridge as rb
release, sha = rb.read_release(sys.argv[1], "release_invalid")
print("releaseRecordSha256", sha)
problems = rb.release_module.verify_release_files(release, sys.argv[2])   # raises if the root is inside Git
print("problems", len(problems)); [print(" ", p) for p in problems]
excluded = {e["path"] for e in release["excludedMembers"]}
for f in release["files"]:
    m = f["path"]
    if not m.startswith("media/"): continue
    print(m, "EXCLUDED" if m in excluded else "",
          "evaluate:", rb.authorise(release, m, []) or "OK",
          "create-derivatives:", rb.authorise(release, m, ["create-derivatives"]) or "OK")
'@ | & $Py - $RelJson $Root 2>&1 | Tee-Object "$Store\release\authorisation-report.txt"
```

Adjust the `media/` prefix to wherever §4 placed the videos.

**Expected.** `problems 0`, followed by one line per video.

**Stop.** Any of these:
- the record does not parse (`release_invalid:...`);
- `ReleaseError` (the root is inside Git);
- any problem (missing, size differs, sha256 differs, escapes the store).

Investigate and restore the original bytes from `archives\`. Never update hashes to match changed files.

**Retain.** `authorisation-report.txt`, with the `releaseRecordSha256` in the ledger.

---

## 8. Probe every candidate video

**Purpose.** One `vehicle-subclass-media-probe-v1` record per candidate video, named by content.

```powershell
$Member = "<MEMBER>"                                    # e.g. media/<path>/<file>, as in files[]
$Src = Join-Path $Root ($Member -replace '/', '\')
$SrcSha = (Get-FileHash -Algorithm SHA256 $Src).Hash.ToLowerInvariant()
& $Py tools\stage3\probe_media.py --media-tools $Pack --input $Src --out "$Store\probes\$SrcSha.probe.json" 2>&1 |
  Tee-Object "$Store\logs\probe-$SrcSha.log"            # stdout: the probe record's SHA-256
```

**Expected.** `probes\<sourceSha256>.probe.json` (canonical JSON, write-once). The printed line is the probe SHA-256; record it in the ledger. The record holds no file name or path.

**Facts used later.**
- `sourceSha256` and `sourceSizeBytes`;
- `ffprobe{version, sha256}`;
- `videoStreamCount`;
- `video.codec`, `width`, `height`, `durationMs`, `frameRateNumerator`/`frameRateDenominator`;
- `maviImport.containerSupported` and `maviImport.metadataValid`.

**Media facts, not rights facts.** `containerSupported=false` or `metadataValid=false` only selects a derivation mode (§13). It never affects rights.

**Stop.**
- `media_tools_invalid:*`: fix the pack (§2).
- `probe_input_unreadable` or `probe_failed`: the file is unreadable or not media, so the member is not a candidate. Note it in the review sheet.
- `probe_invalid_media`: likewise not a candidate.

---

## 9. Human source-side review sheet

**Purpose.** Support R-1's selection with **source-side facts only**. The sheet is never ground truth. Keep it as `selection\candidate-review.csv`.

```csv
member,sourceSha256,probeSha256,sourceCamera,durationMs,width,height,frameRate,sourceSceneOrLocation,sourceTimeOrWeather,containerSupported,metadataValid,videoStreamCount,codec,likelyMode,note
<MEMBER>,<SHA256>,<SHA256>,<SOURCE_CAMERA_ID>,<MS>,<W>,<H>,<N>/<D>,<FROM RELEASE METADATA OR blank>,<FROM RELEASE METADATA OR blank>,<true|false>,<true|false>,<N>,<CODEC>,<passthrough|remux|transcode>,<NOTE>
```

- **Allowed facts.** Exactly the plan's T7 list:
  - the corpus camera identity;
  - scene or location metadata the release itself supplies;
  - duration and resolution;
  - time of day or weather, only when the release genuinely provides it;
  - probe viability and importability;
  - broad camera and scene diversity.

  Leave a cell blank when the release does not genuinely provide the value; never estimate it.
- **Forbidden content.** The sheet never contains, and selection never uses:
  - the release's native type or class labels, which plan §8 treats as untrusted for this purpose;
  - any count, density or coverage derived from the release's native track/box annotations, which are never ground truth;
  - MAVI subclass or MAVI confidence;
  - Track counts or outcomes;
  - T1 exports;
  - human subclass labels;
  - T6 results.

  None of these exist yet in S3.2b-2, and none may be generated to inform selection.

---

## 10. Pilot source-pool selection (R-1)

**Purpose.** Choose 6–10 members for broad source, camera and scene diversity, using source-side facts only.

**Requirements.** Each one is checked by the freeze tool (§11) or by the operator:
- [ ] 6 ≤ members ≤ 10.
- [ ] Unique member names and unique source SHA-256s.
- [ ] Every member is listed, not excluded, and authorised for `benchmarking` and `development` (§7 shows `evaluate: OK`).
- [ ] Every member has exactly one valid probe in `probes\`.
- [ ] **Every member is derivable.** The pool can never be edited, and T9 needs exactly one derivation per member, so check this before freezing:
  - the probe shows `videoStreamCount` = 1;
  - **and** at least one §13 mode's precondition holds:
    - passthrough-eligible; **or**
    - `create-derivatives: OK` in §7 together with `video.codec` = `h264` (remux) or a valid single-video-stream source (transcode).
- [ ] The intended mode for each member, with its reason, is recorded in the ledger (§17) **before** the freeze.
- [ ] Every member's `sourceCamera` is the camera identifier as the release states it.
- [ ] Every `inclusionReason` names a specific source-side fact.
  - Example: `Adds camera C04, dusk illumination and a long urban approach not otherwise represented`.
  - Never `good diversity`, and never anything implying a MAVI result.
  - Each is one line, at most 200 characters, with no path or URL.

**Selection file.** `selection\selection.json`, in the exact format `freeze_source_pool.py` reads:

```json
{"members": [
  {"member": "<MEMBER_PATH_1>", "sourceCamera": "<SOURCE_CAMERA_ID>", "inclusionReason": "<SPECIFIC SOURCE-SIDE REASON>"},
  {"member": "<MEMBER_PATH_2>", "sourceCamera": "<SOURCE_CAMERA_ID>", "inclusionReason": "<SPECIFIC SOURCE-SIDE REASON>"}
]}
```

Each entry has exactly these three keys. Order does not matter, because the tool sorts.

---

## 11. Freeze the pilot pool

### 11.1 Command

Pass **only the selected members' probes**: a probe for an unselected file is refused (`source_pool_invalid:probe_unmatched`).

```powershell
$ProbeArgs = foreach ($m in (Get-Content "$Store\selection\selection.json" -Raw | ConvertFrom-Json).members) {
  $sha = (Get-FileHash -Algorithm SHA256 (Join-Path $Root ($m.member -replace '/', '\'))).Hash.ToLowerInvariant()
  "--probe"; "$Store\probes\$sha.probe.json" }
& $Py tools\stage3\freeze_source_pool.py --release $RelJson --release-root $Root @ProbeArgs `
  --selection "$Store\selection\selection.json" --out "$Store\pool\source-pool.json" 2>&1 |
  Tee-Object "$Store\logs\freeze-pool.log"              # stdout: the pool record's SHA-256
```

### 11.2 Expected

`pool\source-pool.json`: `vehicle-subclass-source-pool-v1`, canonical, write-once, with:
- `kind: "pilot"`;
- `selectionProcedure.id: "s3-2-source-pool-manual-v1"`;
- `releaseId` and `releaseRecordSha256`;
- `members[]` sorted by member, each with `sha256`, `sizeBytes`, `probeSha256`, `sourceCamera` and `inclusionReason`.

Its identity is the printed SHA-256.

**Stop.** Any `source_pool_invalid:*` (§20). Correct the **input** (the selection or probes) and write a new output path. Never edit the record.

### 11.3 Commitment: Mode A or Mode B

R-5's terms outcome decides the mode; this runbook does not pre-decide it.

- **Mode A: member names may enter Git.**
  1. Copy the record byte-exactly to `docs/qualification/stage3/s3-2-source-pool.json`.
  2. Commit it.
- **Mode B: member names may not enter Git.**
  1. Keep the record in `pool\`.
  2. Commit only `docs/qualification/stage3/s3-2-source-pool.sha256`, containing exactly `<sha256>` followed by one LF: 65 bytes, no BOM, no CR.
  ```powershell
  [IO.File]::WriteAllText("$Repo\docs\qualification\stage3\s3-2-source-pool.sha256", "<POOL_SHA256>`n", [Text.UTF8Encoding]::new($false))
  ```
  - `.gitattributes` pins `docs/qualification/stage3/*.sha256` to LF, so a Windows checkout keeps the exact 65 bytes T9 compares.
  - Check with `(Get-Item <file>).Length` = 65.

**Binding commits come from `main` after the merge, and every later step runs on a checkout of that `main`.** T9 binds files with `git_binding`: the file must be byte-identical at a given commit, and that commit must be an ancestor of the `HEAD` T9 runs on. This repository squash-merges PRs, so a commit made on a feature branch does not survive into `main`'s history.
1. Land the commit on `main`.
2. Take the binding commit from `main`:
   ```powershell
   git fetch origin; $PoolCommit = git rev-parse origin/main
   git show "${PoolCommit}:docs/qualification/stage3/s3-2-source-pool.json" > $null   # or .sha256 in Mode B; must succeed
   ```
3. Record `$PoolCommit` in the ledger.
4. Before any later step that validates a binding (§12.4, §16(b)), move `HEAD` onto the merged `main`. Fetching alone does not move `HEAD`, and every binding commit must be an ancestor of `HEAD`:
   ```powershell
   git switch -c <NEXT_BRANCH> origin/main          # e.g. s3-2-ingestion-map; never reuse the pre-merge branch
   git merge-base --is-ancestor $PoolCommit HEAD; $LASTEXITCODE   # must print 0
   ```

**Frozen.** Once committed on `main`, before any import, the primary pilot pool is frozen. Any later source needs a separate `supplemental` pool; the pilot pool is never widened or edited.

---

## 12. Ingestion map (and convention)

**Purpose.** Prepare T9's only camera, time-zone and recording-start input. Do not create one before the pool is frozen.

### 12.1 Collect

**Per distinct pool `sourceCamera`:**
- `sourceCamera`, copied from the pool;
- `cameraCode` = `S32-` + `sourceCamera` upper-cased, with every character outside `A–Z 0–9 -` replaced by `-`, truncated to 32 characters. Two cameras that normalise to the same code are a refusal;
- `name`: a display name, at most 128 characters, no path;
- `timeZoneId`: an IANA id, valid in the repository's `tzdata` (for example `America/New_York`); Windows ids are refused.

**Per pool member:**
- `member`;
- `cameraCode`: its camera's code;
- `recordingStartLocal`: `YYYY-MM-DDTHH:MM:SS`, with no offset and no `Z`;
- `recordingTime`.

### 12.2 Time source: trusted release metadata versus the Development convention

- **Trusted release metadata.** Use this only if the release genuinely provides a recording time and time zone for the member.
  - `recordingTime = {"source": "release-metadata", "evidence": {"releaseRecordSha256": "<RELEASE_SHA256>", "member": "<EVIDENCE_FILE_PATH>"}}`.
  - The evidence `member` must be a listed, non-excluded file in `files[]`, such as `evidence/<metadata file>`.
- **Development convention.** Use this otherwise. It must be committed **before** the map uses it.
  1. Author `docs/qualification/stage3/s3-2-ingestion-convention.md`. It must:
     - define deterministic Development-only wall-clock times and time zones;
     - say explicitly that **they are not claimed as actual capture times**;
     - choose times that avoid every DST gap or overlap in the zones used. The validator refuses nonexistent and ambiguous local times.
     - In **Mode B** (§11.3) it states its rules per camera or by ordinal and **names no member path**, because the convention enters Git in both modes.
  2. Commit it and land it on `main` before the map is written. The map embeds this commit, and §11.3 explains why a branch commit is lost in a squash merge.
  3. Take its binding from the committed blob on `main`, and continue on a branch created from that `main`:
     ```powershell
     git fetch origin; $ConvCommit = git rev-parse origin/main
     git switch -c <MAP_BRANCH> origin/main           # HEAD must contain $ConvCommit before §12.4 runs
     git merge-base --is-ancestor $ConvCommit HEAD; $LASTEXITCODE   # must print 0
     git show "${ConvCommit}:docs/qualification/stage3/s3-2-ingestion-convention.md" > $null   # must succeed
     @'
     import hashlib, subprocess, sys
     blob = subprocess.run(["git", "show", f"{sys.argv[1]}:docs/qualification/stage3/s3-2-ingestion-convention.md"], capture_output=True, check=True).stdout
     print(hashlib.sha256(blob).hexdigest())
     '@ | & $Py - $ConvCommit
     ```
  4. Use `recordingTime = {"source": "development-convention", "convention": {"sha256": "<SHA256>", "gitCommit": "<40-hex>", "gitPath": "docs/qualification/stage3/s3-2-ingestion-convention.md"}}`.

**Mixing and zones.**
- Members may mix the two sources. Each camera still has **one** `timeZoneId`, which holds for all its members, whichever source they use.
- A release-metadata time that is nonexistent or ambiguous in that zone cannot be imported. Record the conflict, then move that member to the Development convention; the plan allows this. Never shift the time.
- A zone present in `tzdata` that .NET cannot map to Windows is still refused by the MAVI API at S3.2b-3 (`ingestion_map.py` docstring). Prefer canonical IANA region ids.

**Slice placement.** The plan's slice table lists "the committed ingestion map" under S3.2b-3. This runbook prepares, validates and commits the map in S3.2b-2, which is where the Stage-3 register places it (row E14). Committing it before the S3.2b-3 host exists starts nothing: T9 runs only after every register E row is PASS.

### 12.3 Template (placeholders only)

```json
{"schemaVersion": "vehicle-subclass-ingestion-map-v1",
 "sourcePoolSha256": "<POOL_SHA256>",
 "cameras": [{"sourceCamera": "<SOURCE_CAMERA_ID>", "cameraCode": "S32-<NORMALISED>", "name": "<DISPLAY NAME>", "timeZoneId": "<IANA_ZONE>"}],
 "members": [{"member": "<MEMBER_PATH>", "cameraCode": "S32-<NORMALISED>", "recordingStartLocal": "<YYYY-MM-DDTHH:MM:SS>",
              "recordingTime": {"source": "development-convention", "convention": {"sha256": "<SHA256>", "gitCommit": "<COMMIT>", "gitPath": "docs/qualification/stage3/s3-2-ingestion-convention.md"}}}]}
```

### 12.4 Canonicalise, then validate offline

T9 reads only canonical bytes. Write the draft to `ingestion\ingestion-map.draft.json`, then:

```powershell
@'
import json, sys; sys.path.insert(0, "tools/stage3")
import artefacts as a, ingestion_map, release_bridge as rb
draft = a.parse_json(open(sys.argv[1], "rb").read(), "map_unreadable")
pool, _, pool_sha = a.read_artefact(sys.argv[2], "vehicle-subclass-source-pool-v1", "pool_invalid")
release, release_sha = rb.read_release(sys.argv[3], "release_invalid")
ingestion_map.check(draft, pool=pool, pool_sha256=pool_sha, release=release, release_sha256=release_sha, repository=sys.argv[4])
a.write_once(sys.argv[5], a.canonical_json(draft)); print(a.sha256_hex(a.canonical_json(draft)))
'@ | & $Py - "$Store\ingestion\ingestion-map.draft.json" "$Store\pool\source-pool.json" $RelJson $Repo "$Store\ingestion\ingestion-map.json"
```

**Expected.** The canonical `ingestion\ingestion-map.json` and its SHA-256.

**Stop.** Any `ingestion_map_invalid:*` (§20). Fix the draft's **source facts**, never by inventing times.

**Commit mode.** Same as §11.3:
- Mode A: commit `docs/qualification/stage3/s3-2-ingestion-map.json` (canonical bytes).
- Mode B: commit `docs/qualification/stage3/s3-2-ingestion-map.sha256` (`<sha256>` plus LF).

Land the commit on `main` and take `$MapCommit = git rev-parse origin/main` (§11.3). Then run §16's pre-T9 check, which verifies the committed bindings.

---

## 13. Mode decision, member by member

**Purpose.** Choose exactly one mode per frozen member, before any T8 run. There is no automatic fallback: T8 refuses a mode whose precondition fails.

| Mode | Choose when (from the member's probe and §7) | Authorisation |
|---|---|---|
| `passthrough` | `maviImport.containerSupported` and `metadataValid` are true, `videoStreamCount` = 1, and `sourceSizeBytes` ≤ `$MaxImportBytes` | `evaluate` only |
| `remux` | not passthrough-eligible, `videoStreamCount` = 1, `video.codec` is `h264` (the implemented allow-list), and only the container needs converting | `create-derivatives` `granted` |
| `transcode` | a valid single-video-stream source for which neither passthrough nor remux is selected | `create-derivatives` `granted` |

- Each choice and its reason are recorded in the ledger (§17) **before the pool is frozen** (§10), and so before any T8 run.
- A member with `videoStreamCount` ≠ 1 cannot be derived. It should not have been selected; report it.
- If `create-derivatives` is not granted, only passthrough-eligible members can be used.

---

## 14. T8 derivation commands

**Purpose.** One immutable derivation directory per member: `<out>\video.mp4` plus `<out>\derivation-manifest.json`.

Run exactly **one** mode per member: the one recorded in the ledger before the freeze (§10, §13). Never run several modes for one member, and never choose a mode after seeing outputs.

```powershell
$Member = "<MEMBER>"; $Mode = "<MODE FROM LEDGER: passthrough|remux|transcode>"
$Slug = $Member -replace '/', '+'          # '+' never occurs in a member path, so slugs cannot collide
& $Py tools\stage3\derive_mp4.py --media-tools $Pack --release $RelJson --release-root $Root --member $Member `
  --mode $Mode --max-import-bytes $MaxImportBytes --out "$Store\derivations\${Slug}__${Mode}__run1" 2>&1 |
  Tee-Object "$Store\logs\derive-${Slug}-${Mode}-run1.log"
```

**Behaviour.**
- `--member` is the release path with `/`.
- `--out` must not exist and must be outside Git.
- The tool:
  1. verifies the whole release;
  2. copies and hashes the member;
  3. authorises it for the mode;
  4. probes it;
  5. checks the mode precondition;
  6. runs the pinned FFmpeg arguments (remux/transcode);
  7. probes the output and requires it to be importable;
  8. re-hashes the output;
  9. publishes the directory atomically.
- On success it prints the manifest SHA-256. On refusal it leaves no directory.

**Rules.**
- Each member has exactly one successful derivation, `__run1`, and that is the one T9 uses. The only other is the §15 determinism `__run2`, which never reaches T9.
- **A refused mode.** If the recorded mode is refused, record the refusal. A change of mode is a recorded decision (ledger: new mode and reason) made from the refusal and the probe, never from a derived output. The new mode's run is the member's `__run1`.
- Output directories are immutable evidence. Never delete, rename into or overwrite a successful one.
- The manifest is `vehicle-subclass-derivation-v1`, canonical and path-free. §16 validates it.
- The run re-hashes the whole release each time, which is slow for large releases. That cost is accepted.

---

## 15. Real determinism check

**When.** The plan requires two runs for the first real **remux** (if remux is used) and the first real **transcode** (if transcode is used).

**Procedure.**
1. Run §14 for that member and mode into `__run1`, then again into `__run2` (change only the `--out` suffix). Use the same `$Pack`, `$RelJson`, `$Root`, `--member` and `$MaxImportBytes`.
2. Compare:
   ```powershell
   $a = "$Store\derivations\${Slug}__${Mode}__run1"; $b = "$Store\derivations\${Slug}__${Mode}__run2"
   "video.mp4", "derivation-manifest.json" | ForEach-Object {
     $ha = (Get-FileHash -Algorithm SHA256 "$a\$_").Hash.ToLowerInvariant(); $hb = (Get-FileHash -Algorithm SHA256 "$b\$_").Hash.ToLowerInvariant()
     "$_ run1=$ha run2=$hb identical=$($ha -eq $hb)" } | Tee-Object "$Store\evidence\determinism-${Slug}-${Mode}.txt"
   ```
3. The manifests' `ffmpegSha256` and `ffmpegVersion` must be equal; byte-identical manifests imply this.

**Pass.** Both `identical=True`. `__run1` remains the derivation used. `__run2` is retained evidence only and is never given to T9: T9 accepts exactly one derivation per member.

**Fail.**
1. Stop that mode for the whole event.
2. Do not use either output.
3. Retain both directories and the logs.
4. Open an engineering issue before any further corpus processing.

Reproducibility is claimed only for this pinned binary, never across FFmpeg builds.

---

## 16. Pre-T9 consolidated verification

**Purpose.** Run T9's own pre-API input checks offline, in T9's order. This contacts no host.

**(a) Derivations against the frozen pool.** Pass the `__run1` directory of every member, taking the list from the ledger: one per member, and never a `__run2`.

```powershell
@'
import sys; sys.path.insert(0, "tools/stage3")
import artefacts as a, freeze_source_pool, ingest_source_pool as t9
from pathlib import Path
store = Path(sys.argv[1])
pool, _, _ = a.read_artefact(store / "pool/source-pool.json", "vehicle-subclass-source-pool-v1", "pool_invalid")
freeze_source_pool.require_pool_invariants(pool["members"], "pool_invalid")
derivations = t9.load_derivations([Path(p) for p in sys.argv[2:]], pool)   # exactly one valid derivation per pool member
for name, d in sorted(derivations.items()):
    print(name, d["manifestSha256"], d["manifest"]["mode"], d["videoSha256"])
'@ | & $Py - $Store <RUN1_DIR_1> <RUN1_DIR_2> ...
```

**(b) Committed bindings, release and map.** Run this on the checkout S3.2b-3 will use, once the pool and map are on `main`. That checkout is `git switch --detach origin/main` after `git fetch origin`, or a branch created from it; it is never a pre-merge branch. It performs:
- the `bound_artefact` calls T9 makes, each with **its own** commit (`$PoolCommit`, `$MapCommit`);
- the pilot-kind check and the pool invariants;
- the release-to-pool match;
- `ingestion_map.check` on the committed map.

```powershell
@'
import sys; sys.path.insert(0, "tools/stage3")
import freeze_source_pool, ingest_source_pool as t9, ingestion_map, release_bridge as rb
from pathlib import Path
repo, rel, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
pool_commit, pool_file, pool_digest, map_commit, map_file, map_digest = sys.argv[4:10]
if mode == "A":
    pool, pool_sha, pb = t9.bound_artefact(repo, Path(pool_file), "vehicle-subclass-source-pool-v1", "t9_source_pool", t9.POOL_PATHS, pool_commit, None, None)
    doc, map_sha, mb = t9.bound_artefact(repo, Path(map_file), ingestion_map.SCHEMA, ingestion_map.CODE, t9.MAP_PATHS, map_commit, None, None)
else:
    pool, pool_sha, pb = t9.bound_artefact(repo, Path(pool_file), "vehicle-subclass-source-pool-v1", "t9_source_pool", t9.POOL_PATHS, None, Path(pool_digest), pool_commit)
    doc, map_sha, mb = t9.bound_artefact(repo, Path(map_file), ingestion_map.SCHEMA, ingestion_map.CODE, t9.MAP_PATHS, None, Path(map_digest), map_commit)
assert pool["kind"] == "pilot", "t9_source_pool:kind"
freeze_source_pool.require_pool_invariants(pool["members"], "t9_source_pool")
release, release_sha = rb.read_release(rel, "t9_release_invalid")
assert release_sha == pool["releaseRecordSha256"] and release["releaseId"] == pool["releaseId"], "t9_release_mismatch"
ingestion_map.check(doc, pool=pool, pool_sha256=pool_sha, release=release, release_sha256=release_sha, repository=repo)
print("pool", pool_sha, pb); print("map", map_sha, mb); print("release", release_sha)
'@ | & $Py - $Repo $RelJson <A|B> $PoolCommit <POOL_FILE> <POOL_DIGEST_OR_-> $MapCommit <MAP_FILE> <MAP_DIGEST_OR_->
```

Arguments by mode:
- **Mode A:** `<POOL_FILE>` and `<MAP_FILE>` are the committed `docs\qualification\stage3\s3-2-source-pool.json` and `...\s3-2-ingestion-map.json`; pass `-` for both digests.
- **Mode B:** the files are `$Store\pool\source-pool.json` and `$Store\ingestion\ingestion-map.json`; the digests are the committed `...\s3-2-source-pool.sha256` and `...\s3-2-ingestion-map.sha256`.

**(c) One media-tool pack for the whole event.** This checks that every probe and every derivation used the frozen §2 pack: ffprobe identity in every probe and derivation probe, and ffmpeg identity in every remux/transcode manifest.

```powershell
@'
import sys, json; sys.path.insert(0, "tools/stage3")
import media_tools
from pathlib import Path
pack, store = sys.argv[1], Path(sys.argv[2])
probe_id, ffmpeg_id = media_tools.load(pack, "ffprobe").identity, media_tools.load(pack, "ffmpeg").identity
bad = [p.name for p in (store / "probes").glob("*.probe.json") if json.loads(p.read_bytes())["ffprobe"] != probe_id]
for d in sys.argv[3:]:
    m = json.loads((Path(d) / "derivation-manifest.json").read_bytes())
    if m["sourceMedia"]["ffprobe"] != probe_id or m["outputMedia"]["ffprobe"] != probe_id: bad.append(d)
    if m["mode"] != "passthrough" and {"version": m["ffmpegVersion"], "sha256": m["ffmpegSha256"]} != ffmpeg_id: bad.append(d)
print("pack-consistent" if not bad else f"MISMATCH {bad}"); sys.exit(1 if bad else 0)
'@ | & $Py - $Pack $Store <RUN1_DIR_1> <RUN1_DIR_2> ... <RUN2_DIRS>
```

**Stop.** Any refusal, assertion or `MISMATCH`:
- `t9_derivation_*`: a derivation does not match its pool member or release;
- `*:not_committed:*`: a binding commit is wrong (§11.3);
- `ingestion_map_invalid:*`: §12.

---

## 17. Evidence ledger (operational, not a contract)

Keep the ledger as `evidence\s3-2b-2-ledger.md` in the controlled store. It never contains MAVI output.

Event header:
- store path;
- R-1, R-5 and operator names;
- pack identity (§2);
- `releaseRecordSha256` (after R-5);
- commit mode A or B;
- pool SHA-256 and `$PoolCommit`;
- map SHA-256 and `$MapCommit`;
- convention SHA-256 and `$ConvCommit`;
- `$MaxImportBytes`, with the S3.2b-3 host's configured `VideoImport:MaximumFileSizeBytes` it was taken from.

| Member | Source SHA | Probe SHA | Camera | R-5 status (evaluate / create-derivatives) | Mode (+ reason, recorded before the freeze) | Derivation manifest SHA | Output SHA (`video.mp4`) | Determinism repeat |
|---|---|---|---|---|---|---|---|---|
| `<MEMBER>` | `<SHA256>` | `<SHA256>` | `<SOURCE_CAMERA_ID>` | `OK / OK` | `remux: mkv h264` | `<SHA256>` | `<SHA256>` | `run2 identical` / `n/a` |

---

## 18. S3.2b-3 pre-flight checklist (evidence collection, not acceptance)

**The register owns acceptance state.** `docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md` is Stage 3's only authoritative exit gate (`docs/architecture/README.md`, "Documentation precedence" item 4).
- This checklist is a pre-flight and evidence-collection aid. It gathers the evidence each register row needs, and it does not decide any acceptance itself.
- An item ticked here is not a PASS. A row becomes PASS only when its evidence is entered in the register.
- **Scheduling S3.2b-3 requires every register E row to be PASS** (or NOT TRIGGERED, for E17/E18), not merely these items being ticked.
- This runbook does not complete or accept S3.2b-2, S3.2 or Stage 3. Completing the E rows does not complete Stage 3 (register "Scope and completion levels").

| PF | Pre-flight evidence check | Evidence to enter | Register row |
|---|---|---|---|
| PF1 | Official source, release name, version and retrieval date retained | `release-root\evidence\`, the record's `pinnedSource` | E1 |
| PF2 | Exact terms/licence retained; SHA-256 equals `licence.textSha256` | `terms\`, the record | E2 |
| PF3 | R-5 determination in the record (`determination` ≠ null) | the record, `authorisation-report.txt` | E3 |
| PF4 | The release record parses (`release_invalid` not raised) | §7 log | E4 |
| PF5 | `verify_release_files` reports 0 problems against the root outside Git | §7 log | E5 |
| PF6 | No selected member is in `excludedMembers` | pool record vs record | E6 |
| PF7 | Every selected member's `evaluate` authorisation is `OK` | `authorisation-report.txt` | E7 |
| PF8 | Every selected member has exactly one probe whose `sourceSha256` equals its `files[]` sha256 | `probes\`, pool `probeSha256` | E8 |
| PF9 | Every selected member confirmed derivable before the freeze (§10) | ledger, probes, §7 report | E9 |
| PF10 | Intended mode and reason recorded for every member before the freeze (§10, §13) | ledger | E10 |
| PF11 | Pool record has 6 ≤ members ≤ 10 and `kind` = `pilot` | pool record | E11 |
| PF12 | Pool committed on `main` (Mode A JSON or Mode B 65-byte digest); `git merge-base --is-ancestor $PoolCommit HEAD` succeeds on the S3.2b-3 checkout | §16(b) log | E12 |
| PF13 | Convention (if used) committed on `main` before the map; `$ConvCommit` ancestry-valid on that checkout | ledger, §12.2 | E13 |
| PF14 | Map passes §12.4 and §16(b); committed or digest-bound on `main`; `$MapCommit` ancestry-valid | §16(b) log | E14 |
| PF15 | `load_derivations` accepts exactly one `__run1` derivation per pool member (§16(a)) | §16(a) log | E15 |
| PF16 | Every remux/transcode manifest records `operations: ["create-derivatives"]` and `blockers: []` | manifests | E16 |
| PF17 | First remux and first transcode `__run1`/`__run2` comparisons show both files `identical=True` (only for modes used) | `evidence\determinism-*.txt` | E17, E18 |
| PF18 | Every derivation manifest's `importLimitBytes` equals the S3.2b-3 host's configured `VideoImport:MaximumFileSizeBytes` | manifests, host configuration | E19 |
| PF19 | `git ls-files` shows no corpus media, archive, frame, crop or log in the repository | `git ls-files` output | E20 |
| PF20 | `tools/verify_repo.py` passes on each binding commit (pool, convention, map) | log | E12, E13, E14 |
| PF21 | §16(c) shows every probe and derivation bound to the one pack identity in `media-tools\pack-identity.txt` (§2) | §16(c) log, `pack-identity.txt` | E21 |

S3.2b-3's own gates (plan §4 and register F rows) apply after that: a fresh, dedicated Development catalogue created after the pool freeze, the real Model Pack and runtime, and the shipped `1.3.0-candidate` profile. This runbook never starts T9.

---

## 19. Command transcript (placeholders)

```powershell
# --- session and layout (§0, §1)
$Repo="<REPO_ROOT>"; $Py="$Repo\.venv\Scripts\python.exe"; $Store="E:\MAVI-Controlled\Stage3\S3.2\<EVENT_ID>"
$Root="$Store\release-root"; $Pack="$Store\media-tools\ffmpeg"; $RelJson="$Store\release\release-record.json"
$MaxImportBytes=<HOST_VideoImport_MaximumFileSizeBytes>; Set-Location $Repo
"terms","release-root","release","media-tools","probes","selection","pool","ingestion","derivations","evidence","logs" |
  ForEach-Object { New-Item -ItemType Directory -Force "$Store\$_" | Out-Null }

# --- media tools (§2)
& "$Repo\tools\setup\Prepare-MaviFfmpegWindows.ps1"; Copy-Item -Recurse "$Repo\vendor\ffmpeg" $Pack
# then run the §2 verification snippet -> $Store\media-tools\pack-identity.txt

# --- human: §3 acquisition, §4 release-root assembly, §5 record, §6 R-5 determination
# --- §4 inventory snippet -> $Store\release\files-inventory.json ; §7 verification snippet -> authorisation-report.txt

# --- probe each candidate (§8)
$Src = Join-Path $Root ("<MEMBER>" -replace '/', '\'); $SrcSha=(Get-FileHash -Algorithm SHA256 $Src).Hash.ToLowerInvariant()
& $Py tools\stage3\probe_media.py --media-tools $Pack --input $Src --out "$Store\probes\$SrcSha.probe.json"

# --- §9 review sheet, §10 selection and intended modes in the ledger, then freeze the pool (§11)
& $Py tools\stage3\freeze_source_pool.py --release $RelJson --release-root $Root --probe "<PROBE_1>" --probe "<PROBE_2>" `
  --selection "$Store\selection\selection.json" --out "$Store\pool\source-pool.json"
# Mode A: Copy-Item "$Store\pool\source-pool.json" "$Repo\docs\qualification\stage3\s3-2-source-pool.json"
# Mode B: [IO.File]::WriteAllText("$Repo\docs\qualification\stage3\s3-2-source-pool.sha256", "<POOL_SHA256>`n", [Text.UTF8Encoding]::new($false))
git add docs/qualification/stage3; git commit -m "docs(s3): freeze the S3.2 pilot source pool"
# land on main (PR), then: git fetch origin; $PoolCommit = git rev-parse origin/main

# --- ingestion map (§12): land the convention on main first ($ConvCommit from origin/main), run the §12.4 snippet,
#     commit the map (Mode A/B), land it on main, then $MapCommit = git rev-parse origin/main

# --- derive (§14): one command per member, mode from the ledger
& $Py tools\stage3\derive_mp4.py --media-tools $Pack --release $RelJson --release-root $Root --member "<MEMBER>" `
  --mode "<MODE>" --max-import-bytes $MaxImportBytes --out "$Store\derivations\<SLUG>__<MODE>__run1"

# --- determinism (§15): repeat the first remux and the first transcode into __run2, then run the comparison snippet

# --- pre-T9 checks (§16 a/b), then repository validation (set PYTHONPATH only if mavi_vision is not installed in the venv)
$env:PYTHONPATH = "$Repo\src\vision"; & $Py tools\verify_repo.py; git diff --check
```

---

## 20. Failure handling

Every refusal is fail-closed:
- Keep the log and any input.
- Correct the **input** (the selection, the draft map, the store bytes restored from the archives, the pack) or stop.
- Never edit a canonical artefact, a hash or a release `files[]` entry to make a refusal disappear.

| Refusal family | Meaning | Action |
|---|---|---|
| `media_tools_invalid:*` (`manifest`, `schema`, `version`, `runtime`, `artifacts`, `not_listed`, `sha256_invalid`, `missing`, `sha256_mismatch`, `start`, `version_mismatch`, `changed`, `architecture`, `platform`) | the pack is not the verified pack, or a binary changed after verification | stop all probing and derivation; re-verify or re-prepare the pack (§2); outputs made with another pack are a different identity |
| `probe_input_unreadable`, `probe_failed`, `probe_invalid_media` | unreadable, not media, or ffprobe failed | exclude the file from candidacy; note it in the review sheet |
| `probe_invalid:schema:*` | the probe record failed its own schema (a tool defect, not a media property) | retain the input and log; engineering issue |
| `source_pool_invalid:release*` | the record does not parse, the root is in Git, or the store does not verify | §7; restore bytes; never re-hash to match |
| `source_pool_invalid:member_not_listed` / `member_excluded` / `duplicate_member` / `duplicate_content` / `member_count` | the selection breaks the pool rules | R-1 revises the selection; new output path |
| `source_pool_invalid:probe*` | probe missing, extra, non-canonical or not matching | pass exactly one valid probe per selected member |
| `source_pool_invalid:not_authorised:<blockers>` | R-5's determination does not authorise this member | the member cannot be used; do not re-interpret the determination |
| `source_pool_invalid:selection*` / `source_camera` / `inclusion_reason` | malformed selection text | fix the selection text (specific, one line, at most 200 characters, no path or URL) |
| `derivation_release_invalid` / `derivation_release_root_invalid` / `derivation_release_files_mismatch` | the record or store is wrong | §7; restore bytes |
| `derivation_member_not_listed` / `derivation_member_excluded` / `derivation_member_changed` | the member is wrong, excluded, or changed between verification and copy | check `--member` spelling (release path with `/`); a change means the store is unstable, so stop and investigate |
| `derivation_not_authorised:<blockers>` | the mode's operation is not granted | use passthrough only if eligible; otherwise the member cannot be derived |
| `derivation_mode_invalid` / `derivation_import_limit_invalid` | bad argument | correct the argument |
| `derivation_probe_failed[:video_streams]` | the source does not probe, or does not have exactly one video stream | not derivable; it should not have been selected (record it) |
| `derivation_passthrough_not_importable` | the source fails the importer rules or the size limit | choose remux or transcode per §13 (record why); never force passthrough |
| `derivation_remux_codec_unsupported` | the codec is not in the remux allow-list (`h264`) | choose transcode (record why); widening the list is a plan amendment |
| `derivation_ffmpeg_failed[:<rc>]` | FFmpeg exited non-zero | retain the log; do not retry with other arguments; engineering issue |
| `derivation_output_not_importable[:...]` | the output fails the import rules or the size limit | retain the log; engineering issue; do not lower `--max-import-bytes` below the host value or raise it above it |
| `derivation_output_inconsistent[:output\|source_media\|output_media\|passthrough\|unchanged]` | the output changed or does not match its records | stop; storage integrity problem; engineering issue |
| `derivation_output_in_git` | `--out` is inside a Git worktree | use the controlled store |
| `output_exists` | the target exists | use a new path (`__runN`); never delete evidence |
| `output_parent_missing` | the output's parent directory does not exist | create the §1 layout; never write elsewhere |
| `ingestion_map_invalid:schema` / `source_pool` / `missing_member` / `extra_member` / `duplicate_member` | the map does not match the frozen pool | rebuild the draft from the pool; new output path |
| `ingestion_map_invalid:camera_code` / `duplicate_camera_code` / `duplicate_source_camera` / `cameras` / `unknown_camera` / `member_camera` / `camera_name` / `source_camera` | camera rows inconsistent | derive codes with the §12.1 rule; one camera per pool `sourceCamera` |
| `ingestion_map_invalid:time_zone` | not an IANA zone in `tzdata` | use the IANA id; never a Windows id |
| `ingestion_map_invalid:recording_start_malformed` / `_nonexistent` / `_ambiguous` | an impossible or DST-ambiguous local time | release metadata: record the conflict and move that member to the convention (§12.2), never shift the time; convention: amend, re-commit and re-land the convention, then rebuild the map |
| `ingestion_map_invalid:release_evidence` | the evidence names another release or an unlisted file | point it at a listed, non-excluded evidence file in this release |
| `ingestion_map_invalid:convention:*` | the convention is not committed at that commit, its hash differs, or the commit is not an ancestor of `HEAD` | take the hash from the committed blob (§12.2); commit before the map |

---

## 21. Automation boundary

| May be automated | Never automated |
|---|---|
| file hashing and inventories (§4) | terms acceptance or access requests |
| probing (§8) | the R-5 determination, any legal interpretation, the privacy judgement |
| record validation (§7, §12.4, §16) | choosing the pilot pool, and never from MAVI output |
| producing the pool from R-1's selection (§11) | inventing or estimating source timestamps, time zones or metadata |
| derivation (§14) and determinism comparison (§15) | editing canonical artefacts to clear a refusal |
