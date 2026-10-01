# S2c B0 source acquisition helper (Development only)

A small helper that discovers, admits and retains **individual public video files** for the S2c B0 source-acquisition pilot. The only provider it implements is Wikimedia Commons. Design and pilot plan: `docs/qualification/stage2-s2c/s2c-b0-source-acquisition-record.md`.

It is **not**:
- a corpus builder;
- a partitioner;
- an annotation tool;
- a generic downloader;
- a registry;
- a provenance service.

It never:
- creates VideoAssets, Tracks, Observations, ground truth, labels or F1 evidence;
- reads candidate output;
- runs a model.

Acquired files are **candidate source material**. Before any of it can become qualification corpus material, it must pass through the real MAVI ingestion → detector → tracker → Evidence Set path, followed by the S2c corpus tooling in `tools/qualification/attributes/corpus/`. This package imports nothing from that path except `canonical_json`/`sha256_hex` and the pseudonym check. A test also asserts that the corpus package has no network imports.

## States

The states come from the B0 brief. There is no new state machine: the effective state is recomputed from evidence every time a receipt is built.

| State | Set by | Meaning |
|---|---|---|
| `DISCOVERED` | automatic | Exact file revision described. The licence code is open, an author is named and a capture date is declared. It is still **not admitted**. |
| `RIGHTS_PENDING` | automatic | File licence unknown, author unknown, or the named rights/privacy review is missing. |
| `PROVENANCE_PENDING` | automatic | Capture date undeclared or unevidenced, freshness not established, reviewed revision differs, or pseudonymous site/viewpoint missing. |
| `ADMITTED_FOR_PILOT` | human request, honoured only when every rule holds | Bytes may be acquired into the controlled store. |
| `REFERENCE_ONLY` | human | Kept as a development reference and never an operational candidate. Requires a reason and role `development-reference`. |
| `REJECTED` | automatic (not video; NC/ND licence) or human (a reason is required) | Not acquired. |

`ADMITTED_FOR_PILOT` requires all of the following. If any is missing, the item falls back to the pending state that names the gap, and the gap is listed in `blockers`:
- The decision binds the exact `pageRevisionId` and provider `fileSha1` that were re-fetched at acquisition time.
- A rights review: `reviewedBy`, determination `PERMITTED_FOR_PILOT_ACQUISITION`, and evidence.
- A privacy review: `reviewedBy` and a basis. Copyright clearance does not settle privacy.
- A named `reviewedBy`.
- A capture interval (`start`, `end`) with evidence kinds from `embedded-container-metadata`, `uploader-statement`, `visible-in-frame` and `corroborating-source`. The upload timestamp is never capture evidence.
- Capture confidence `high` or `medium`.
- A role of `training-only` or `operational-candidate`. For `operational-candidate`, the freshness result must also be `CAPTURE_AFTER_REFERENCE`.
- Pseudonymous `siteId` / `viewpointId`, such as `site-a1` or `viewpoint-a1-1`. These are never place names or subject identities.

Rules that apply to every item:
- The licence is taken from the **file's own** description page (`extmetadata`). It is never taken from the site's text licence or from a category.
- The licence class (`OPEN`/`RESTRICTED`/`UNKNOWN`) is a machine pre-classification. It is not a legal determination.
- Continuous video needs Commons `mediatype` `VIDEO` **and** either a video MIME (`video/webm`, `video/ogg`, `video/mpeg`, `video/mp4`) or the Ogg container MIME `application/ogg` on a `.ogv`/`.ogg` file (any letter case) with a positive integer width and height. Commons labels every Ogg container `application/ogg`, whether it holds Theora video or only Vorbis/Opus audio, so that MIME alone proves nothing either way. No other `application/*` MIME is accepted.

## Time fields are separate

| Receipt field | Meaning |
|---|---|
| `publishedAtUtc` | Upload timestamp of the current file version. |
| `declaredCaptureDate` | Free text from the page (`DateTimeOriginal`), unreviewed. |
| `capture{start,end,confidence,evidenceKinds,evidence}` | The human-reviewed capture interval. |
| `acquisition.acquiredAtUtc` | When MAVI retained the bytes. |

A recent upload is not a fresh capture.

**Freshness rule.** `CAPTURE_AFTER_REFERENCE` is set only when the **whole** capture interval starts after `freshnessReferenceDate`. That date is the latest public release date of any candidate checkpoint in the evaluated set, supplied by the reviewer. An interval that straddles the reference date is `UNDETERMINED`. Freshness is necessary for an operational candidate, but it is **not** proof of independence from candidate training data.

## Network policy

- HTTPS only.
- Allow-listed hosts: `commons.wikimedia.org` and `upload.wikimedia.org`, on the default port.
- Every redirect hop is re-validated, with at most 5 redirects.
- No credentials, cookies or `Authorization` header. The only headers are `User-Agent` and `Accept`.
- The User-Agent names the tool and an operator contact passed with `--contact`. The contact is never written to a receipt, discovery report or evidence record. The recorded-discovery wrapper (below) writes the actual User-Agent into its own run configuration, which is controlled run evidence.
- 60 s timeout per socket operation (connect or read). This is not a total deadline for a request.
- On HTTP 429/503, back off 30 s and then 60 s, then fail closed. `Retry-After` is not read. Network errors (resets, TLS failures, timeouts) are not retried, and the plain `discover` command does not catch them.
- Downloads stream to `<name>.partial` and are verified against the declared size and provider SHA-1. SHA-256 is recorded. Promotion uses a hard link, which never overwrites.
- A failed transfer removes only its own partial file.
- Reruns are idempotent. A verified existing file is `ALREADY_PRESENT_VERIFIED`, and a differing one is refused and left untouched.
- Tests use an injected fake transport and never touch the network.

## Controlled store (outside Git)

The helper refuses any store inside a Git worktree.

```
<store>/discovery/<sha256>.json                        discovery report (content-addressed)
<store>/discovery/decisions-template-<sha16>.json      human decisions template (null review fields)
<store>/evidence/<sha256>.json                         canonical provider metadata responses
<store>/receipts/<sha256>.json                         canonical admission receipts
<store>/media/commons/<pageId>/<sha1>/<safe name>      original files (admitted only)
<store>/source-acquisition-summary.json                last acquire run
```

Records are canonical JSON: sorted keys, ASCII, LF, and no NaN. Receipts contain public URLs but never local paths, credentials or subject identities.

## Usage

```
python tools/qualification/source_acquisition_cli.py discover --store <store> --contact <email-or-url> --search "traffic India 2026" --limit 60
python tools/qualification/source_acquisition_cli.py discover --store <store> --contact <email-or-url> --category "Category:Videos of streets in India"
#   -> reviewers complete discovery/decisions-template-*.json (only for files they have actually reviewed)
python tools/qualification/source_acquisition_cli.py acquire  --store <store> --contact <email-or-url> --decisions <completed decisions>
python tools/qualification/source_acquisition_cli.py verify   --store <store>
```

A category or search is only a **discovery scope**. Every decision names one exact `File:` title, and wildcards and categories are refused as titles. Exit codes: `0` success, `1` one or more item failures or verify problems, `2` refusal (bad store, bad decisions file).

## Recorded discovery (metadata only)

`source_acquisition/recorded_discovery.py` (entry point `tools/qualification/source_discovery_recorded_cli.py`) runs the predeclared retry scopes with durable capture. It does not change the helper. It injects a recording `fetch` and `sleep` into the helper's own `Transport` and calls `discover` unchanged, so the allow-listed hosts, redirect re-validation, credential refusal, metadata hashing, admission rules and store containment stay as above.

**What it adds:**
- **Discovery only.** Every network attempt must be an HTTPS GET of `commons.wikimedia.org/w/api.php` with exactly one `action=query`. Duplicate, encoded or array-style parameter keys are refused. Media and every other URL are refused before a socket opens, and the wrapper's transport refuses `download` outright.
- **Global stop latch.** The run latches on the first of these:
  - a refused URL, or a refusal raised inside the helper's `Transport` (a redirect to a host that is not allow-listed, a non-HTTPS hop, a malformed URL or redirect location, a redirect without a location, too many redirects, an over-limit body);
  - a non-200, non-redirect status, including 429 and 503;
  - an API `error` body;
  - a network or read failure, or a local capture failure (writing or renaming a body);
  - an incomplete or over-limit body;
  - an exhausted attempt budget;
  - the soft deadline;
  - an interruption;
  - a metadata response that the helper's own parser would reject (missing page, wrong shape, unparseable body), before the next title is requested;
  - any other per-file error that the helper records; the run stops after that scope. This is a fallback, since transport and parse errors already latch immediately.

  Once it has latched, no network attempt starts, including redirect hops and the helper's own back-off retries. Local finalisation continues.
- **Limits.** The attempt budget counts every fetch, including each redirect hop. Attempt starts are paced, and scopes are separated by a gap. The soft deadline is checked before every attempt, read chunk and wait. Each attempt has a read-time limit. A hard deadline tries to record an event on a separate thread for at most 5 s, then always ends the process with exit code 124, even if logging fails or blocks. Bodies and per-item evidence already written survive; the in-flight scope's discovery report does not, and `finalize` reconstructs the status.
- **Durable capture.** An `attempt-start` event is fsynced before each attempt, and an `attempt-end` event after it. Bodies stream to `capture/bodies/attempt-NNNNNN.part` and become `.body` only when read completely. Selected response headers are recorded (`retry-after`, `date`, `content-type`, `content-length`, `age`, `server`, `x-cache*`, `location`, `x-ratelimit-*`, `ratelimit*`). Cookies and request headers other than those in the run configuration are never logged.
- **Scopes.** The seven original scopes, P1–P5 then S1–S2, at 20 results each. S1–S2 run only if P1–P5 describe fewer than 40 unique files without error. The candidate cap of 60 unique files is enforced inside each scope: titles already described are not requested again, and only the remaining allowance is requested. Direct-category queries exclude subcategory members, so an empty result does not establish that a category contains no relevant footage.

**Run directory.** Each run creates a new directory, `<run-root>/commons-discovery-retry-<UTC stamp>/` (or `commons-discovery-completion-<UTC stamp>/` for the completion pass), and never reuses one:

```
config/run-config.json, run-config.sha256   written and fsynced before the first request
capture/events.jsonl, scopes.jsonl          append-only, fsynced per event
capture/bodies/attempt-NNNNNN.body|.part    raw responses; .part = incomplete
store/                                      the helper's --store root (discovery/, evidence/)
run-status.json                             derived locally; never overwritten
```

**Commands.**

```
python tools/qualification/source_discovery_recorded_cli.py run      --run-root <Acquisition dir> --contact <url>
python tools/qualification/source_discovery_recorded_cli.py finalize --run-dir <run dir>        # after a hard stop; local only
python tools/qualification/source_discovery_recorded_cli.py bundle   --run-dir <run dir> --evidence-root <Evidence dir> --name <new name>
python tools/qualification/source_discovery_recorded_cli.py verify-bundle --evidence-dir <Evidence dir>/<name> --name <name>
```

**P2 completion pass (predeclared; needs a fresh R-3 approval before any run).** `run-completion` runs exactly `P2_COMPLETION_SCOPES`, which is the P2 search `street India 2026` at the frozen offsets 0, 20, 40 and 60 with a page size of 20, under `P2_COMPLETION_LIMITS`:
- at most 20 **new** unique files;
- 30 actual attempts, against a worst case of 25 logical requests;
- 5 s pacing and 15 s between pages;
- 10/12-minute soft and hard deadlines.

Before the first request, it verifies the prior run's bundle and writes that run's described file identities (page id, title, revision, SHA-1) into `priorRuns` in the configuration. Those files are never re-described and never consume the budget. `run-completion` accepts only the pinned prior bundle (`P2_COMPLETION_PRIOR`: the recorded retry, by bundle name and archive, manifest and configuration SHA-256). Any other bundle, even one that verifies, is refused before a run directory or any request exists. All pages come from one run, so the ranking is a single snapshot. A title that appears again on a later page is described once. Paging stops at the first page without a continuation, or when the new-file cap is reached. Category continuation and subcategories are not supported. The run directory is `commons-discovery-completion-<UTC stamp>`.

**The prior run's automatic states are superseded.** The retry ran on the helper before the Ogg fix, so its discovery report marks 16 `.ogv` VIDEO files `REJECTED` (`not-continuous-video`). The completion pass excludes those files by identity and does not re-describe them. At review time, recompute their states locally from the retained metadata in the prior bundle with the current `admission.build_receipt`. Do not rely on the historical report's states. The historical bundle itself is never rewritten.

```
python tools/qualification/source_discovery_recorded_cli.py run-completion --run-root <Acquisition dir> --contact <url> --prior-evidence-dir <Evidence dir>/<prior name> --prior-name <prior name>
```

`bundle` writes `MANIFEST.json` (path, bytes, SHA-256, role and modification time per file), a `.tar.gz` and its SHA-256 into a new directory, and re-verifies every member. `verify-bundle` repeats that check later. The run configuration, its hash, `run-status.json` and the bundle files are created atomically and never overwritten. The event logs are append-only, and the helper's own store records are written as the helper writes them.

**Exit codes.** `run` exits `0` complete, `1` stopped, `130` interrupted and `124` at the hard deadline. Any command exits `2` on a refusal.

## Review inventory (metadata-only triage)

`source_acquisition/review_inventory.py` (entry point `tools/qualification/source_review_inventory_cli.py`) builds one B0 review inventory from explicitly supplied recorded-discovery bundles. It is local only: no network, no media, no writes inside a bundle.

**Inputs.**
- Each bundle is given as directory, name and the archive SHA-256 it must have.
- The bundle's bytes are read once and verified against its checksum file, that pin and every manifest member before anything is used.
- The provisional freshness reference is recorded as `PROVISIONAL, NOT DECIDED`.
- An optional title-judgements file (`mavi-s2c-b0-title-judgements-v1`) holds corpus-specific title rules. Each rule is a regex with a code from a closed vocabulary and a reason. The file's SHA-256 and its rules are recorded in the output.

**Each candidate (one per Commons page id) records:**
- provenance back to the bundle, archive hash, run, run-configuration hash, scope or page, metadata member and member hash; a page described in several bundles keeps every provenance;
- the **historical** automatic state exactly as that bundle recorded it, next to the state **re-derived** with the current helper;
- triage flags and a primary class, from metadata and titles only.

**Status fields:** `DESCRIBED`, `REVIEWED`, `ADMISSIBLE` and `FROZEN_QUALIFICATION` are kept separate. Only `DESCRIBED` is set here.

**Rules.**
- Title rules describe what a title says. They never establish a visual property, a place or a capture date.
- `NO_INDIA_HINT_IN_TITLE` is descriptive only.
- Freshness exclusion is objective: a file uploaded on or before a reference date cannot have been captured after it.
- `freshnessBoundValidForReferenceOnOrAfter` is the latest upload among the excluded files. The fresh-possible upper bound holds for every reference date from there up to the provisional one.

**Outputs** go to a new directory outside Git and are never overwritten:
- `inventory.json` (canonical) and `inventory.csv`;
- an unreviewed `decisions-template.json`;
- `proposed-metadata-decisions.json`: stage-1 proposals, `PROPOSED_UNCONFIRMED` with `reviewedBy` null, for a named reviewer to confirm or change;
- `visual-review-worksheet.csv` for the candidates that need a person to look;
- `SHA256SUMS`.

The output is deterministic: identical bundles, inputs and code give identical bytes.

```
python tools/qualification/source_review_inventory_cli.py --bundle <evidence dir> <name> <archive sha256> [--bundle ...] --provisional-reference YYYY-MM-DD [--title-judgements <file>] --out <new dir>
```
## Tests

`tools/qualification/tests/test_source_acquisition.py`, `test_recorded_discovery.py` and `test_review_inventory.py` run offline, with fake transports and a fake clock.

## Dependencies

The helper uses only the Python standard library (`urllib`, `hashlib`) plus the in-repo corpus canonicaliser. It adds no library, binary or model prerequisite. It is Development tooling and is not part of the production runtime.
