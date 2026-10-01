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
- The User-Agent names the tool and an operator contact passed with `--contact`. The contact is never written to any record.
- 60 s timeout.
- On HTTP 429/503, back off 30 s and then 60 s, then fail closed.
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

## Tests

`tools/qualification/tests/test_source_acquisition.py` runs offline with a fake transport.

## Dependencies

The helper uses only the Python standard library (`urllib`, `hashlib`) plus the in-repo corpus canonicaliser. It adds no library, binary or model prerequisite. It is Development tooling and is not part of the production runtime.
