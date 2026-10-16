"""MSR revision M3: group authority (the authority redesign of PR #220; owner decisions O1-O8).

Normative text: ``proposals/m3-benchmark-only-baseline.md`` §3 rules 4a and 9 and its authority section, and
``candidate-credibility.md`` §7 and §8. Three assumptions of the earlier design are replaced here, each once:

* **The author no longer lists the composition set.** The ordinary composition set U is derived from the frozen
  ``compositionUniverse`` and the committed component rankings (``m3_universe``), sealed before protected D
  (``baseline_seal``), and a decision's composition set must equal it (``check_composition_decision``).
* **The current tree no longer decides the audit.** The audit domain comes from one reachable-history walk
  (``m3_git.model_selection_history``) and is sticky: an M3 event stays auditable after every current declaration or
  file has gone (``model_selection_domain``, ``check_event_history``: invariants A1-A4).
* **Local Git is no longer the clock.** Protected D opens only through ``open_protected_d``: the group must be valid
  under the same predicate repository verification runs (``check_group_authority``), every seal RESOLVED, the default
  branch verifiably protected (owner decision O2), and the seal published on the canonical repository's default branch
  (live anchor, D2). Every D manifest and decision records ``anchorCommit``, re-verified in repository mode (D3).

Standard library only. Network access (the canonical GitHub repository and its API) is used only by
``open_protected_d``, a Development-time qualification step; absence or uncertainty refuses (owner decision O8).
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .baseline_seal import (
    ARTEFACT_INFIXES,
    D_MANIFEST_INFIX,
    D_MANIFEST_SCHEMA,
    LEGACY_LAYER_A_INFIX,
    RANKING_INFIX,
    RANKING_SUFFIX,
    RESOLVED,
    SEAL_INFIX,
    STOPPED,
    SealBinding,
    bob_payload_hashes,
    candidate_file_hashes,
    capability_of,
    check_partner_universe,
    derive_group_inputs,
    event_folder,
    frozen_compositions,
    read_canonical,
    record_seal_citations,
    verify_baseline_seal,
)
from .credibility import (
    BENCHMARK_BASELINE,
    DECISION_SUFFIX,
    EVENT_ID_RE,
    FROZEN_SUFFIX,
    IMMUTABLE_REVISION_RE,
    LOCAL_ID_RE,
    MODEL_SELECTION_DIR,
    PROTOCOL_SUFFIX,
    SHA256_RE,
    SHORTLISTED,
    CredibilityError,
    _fail,
    _instant,
    _keys,
    _list,
    _match,
    _number,
    _text,
    canonical_json,
    document_sha256,
    lf_normalised_sha256,
    read_json,
    validate_evolution,
    validate_ledger,
)
from .m3_git import (
    GitCommandError,
    History,
    _git,
    _run,
    first_add_commit,
    is_ancestor,
    model_selection_history,
    read_blobs,
    ref_commit_or_none,
    strictly_before,
    worktree_status,
)
from .m3_universe import (
    BASELINE_GATE,
    FAILED,
    PASSED,
    SUPERSEDES_FIELD,
    UNIVERSE_FIELD,
    check_component_ranking,
    component_event,
    derive_top_k,
    group_id,
    ordinary_compositions_sha256,
)

CANONICAL_REPOSITORY = "hariomahlawat/MAVI"
CANONICAL_ORIGIN = f"https://github.com/{CANONICAL_REPOSITORY}.git"
DEFAULT_BRANCH = "main"
DEFAULT_BRANCH_REF = f"refs/heads/{DEFAULT_BRANCH}"
RECORDED_ANCHOR_REF = f"refs/remotes/origin/{DEFAULT_BRANCH}"
AUTHORITY_FIELD = "compositionAuthority"
ABANDON_REASONS = ("baseline-d-unavailable",)

# A4: the structured record lines of a domain event are append-only across every historical version of the record.
STRUCTURED_LINE_RE = re.compile(
    r"^(?:(?:Protocol|Component ranking \S+|Baseline seal \S+|Decision|Decision snapshot|Snapshot) SHA-256: "
    r"[0-9a-f]{64}|Superseded by \S+|Abandoned: \S+ evidence SHA-256: [0-9a-f]{64}) *$")
RANKING_CITATION_RE = re.compile(r"^Component ranking (?P<id>\S+) SHA-256: (?P<sha>[0-9a-f]{64}) *$", re.MULTILINE)
SUPERSEDED_RE = re.compile(r"^Superseded by (?P<id>\S+) *$", re.MULTILINE)
ABANDONED_RE = re.compile(r"^Abandoned: (?P<reason>\S+) evidence SHA-256: (?P<sha>[0-9a-f]{64}) *$", re.MULTILINE)
M3_RECORD_RE = re.compile(r"^(?:Baseline seal \S+ SHA-256: |Component ranking \S+ SHA-256: |Superseded by |Abandoned: )",
                          re.MULTILINE)
RECORD_NAME_RE = re.compile(r"^msr-[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?-\d{4}-\d{2}\.md$")
DECISION_KEYS = ("groupId", "anchorCommit", "baselineSeals", "dExecutionStartedAt", "incumbent", "baseline", "topK",
                 "componentFinalists", "compositionCandidates", "rankedCompositions", "frontier",
                 "strongestEvaluatedComposition", "implementationComposition")
_ROW_KEYS = ("compositionId", "components", "gates", "dScore", "technicalGates", "comparativeScore", "dResultSha256",
             "baselineSealSha256s")
D_MANIFEST_KEYS = ("schema", "eventId", "manifestId", "groupId", "resultSha256", "anchorCommit",
                   "ordinaryCompositionsSha256", "baselineSeals")


# ------------------------------------------------------------------ record lines


def ranking_citation(event_id: str, digest: str) -> str:
    return f"Component ranking {event_id} SHA-256: {digest}"


def superseded_line(new_event_id: str) -> str:
    return f"Superseded by {new_event_id}"


def abandonment_line(reason: str, evidence_sha256: str) -> str:
    """Owner decision O4: the record line that moves a group event to the existing ``ABANDONED`` state (README §3.2)
    when the baseline D result cannot be evaluated after protected D was opened. The evidence is the ``resultSha256``
    of a committed D manifest of the group. No technical decision and no M1 outcome follows."""
    if reason not in ABANDON_REASONS:
        raise _fail("abandonment_reason_not_allowed", reason)
    _match(evidence_sha256, SHA256_RE, "abandonment.evidence")
    return f"Abandoned: {reason} evidence SHA-256: {evidence_sha256}"


def structured_lines(text: str) -> set[str]:
    return {line.rstrip() for line in text.replace("\r\n", "\n").split("\n") if STRUCTURED_LINE_RE.match(line)}


def _cited(regex: re.Pattern, text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for match in regex.finditer(text.replace("\r\n", "\n")):
        found.setdefault(match["id"], []).append(match["sha"])
    return found


# ------------------------------------------------------------------ paths


def _rel(path: Path, repo: Path) -> str:
    return Path(path).relative_to(repo).as_posix()


def event_paths(event_id: str) -> dict[str, str]:
    folder = (MODEL_SELECTION_DIR / capability_of(event_id)).as_posix()
    return {"folder": folder, "frozen": f"{folder}/{event_id}{FROZEN_SUFFIX}",
            "protocol": f"{folder}/{event_id}{PROTOCOL_SUFFIX}", "record": f"{folder}/{event_id}.md",
            "ranking": f"{folder}/{event_id}{RANKING_SUFFIX}", "decision": f"{folder}/{event_id}{DECISION_SUFFIX}"}


def artefact_event(path: str) -> str | None:
    """The event an M3 artefact path belongs to, or None when the name is no M3 artefact."""
    name = Path(path).name
    if not (name.startswith("msr-") and name.endswith(".json")):
        return None
    for infix in ARTEFACT_INFIXES:
        if infix in name:
            return name.split(infix)[0]
    return None


def _is_m3_ledger(document: object) -> bool:
    return isinstance(document, dict) and (
        document.get("methodRevision") == "msr-v1-m3" or UNIVERSE_FIELD in document
        or any(isinstance(e, dict) and isinstance(e.get("disposition"), dict)
               and e["disposition"].get("status") == BENCHMARK_BASELINE for e in document.get("candidates") or ()))


# ------------------------------------------------------------------ A1: the sticky audit domain


@dataclass
class Domain:
    events: dict[str, set[str]] = field(default_factory=dict)  # eventId -> reasons
    never_committed: set[str] = field(default_factory=set)  # members known only from a universe

    def add(self, event_id: str, reason: str) -> None:
        self.events.setdefault(event_id, set()).add(reason)


def model_selection_domain(repo: Path, history: History) -> Domain:
    """A1: every event with a reachable M3 artefact add, a reachable M3 frozen-ledger blob, a reachable record blob with
    an M3 structured line, or membership in (or supersession by) any historical ``compositionUniverse``. Computed from
    the walk only (plus blobs read by id), so it is sticky: deleting or rewriting the current files never removes an
    event from it."""
    domain = Domain()
    wanted: dict[str, set[str]] = {}
    for path in sorted(history.paths()):
        name = Path(path).name
        event = artefact_event(path)
        if event is not None:
            if not EVENT_ID_RE.match(event):
                raise _fail("m3_artefact_name_invalid", path)
            domain.add(event, f"artefact:{name}")
        elif name.startswith("msr-") and name.endswith(FROZEN_SUFFIX):
            wanted[path] = history.blobs.get(path, set())
        elif RECORD_NAME_RE.match(name):
            wanted[path] = history.blobs.get(path, set())
    blobs = read_blobs(repo, {b for ids in wanted.values() for b in ids})
    for path, ids in sorted(wanted.items()):
        name = Path(path).name
        for blob in sorted(ids):
            text = blobs[blob].decode("utf-8", "replace")
            if name.endswith(FROZEN_SUFFIX):
                try:
                    document = json.loads(text)
                except ValueError:
                    continue  # an unparseable version declares nothing; A2 refuses any rewrite of a domain ledger
                if _is_m3_ledger(document):
                    event = name[: -len(FROZEN_SUFFIX)]
                    domain.add(event, "frozen-ledger")
                    universe = document.get(UNIVERSE_FIELD)
                    if isinstance(universe, dict):
                        for item in universe.get("componentEvents") or ():
                            if isinstance(item, dict) and isinstance(item.get("eventId"), str) \
                                    and EVENT_ID_RE.match(item["eventId"]):
                                domain.add(item["eventId"], f"member-of:{event}")
                    supersedes = document.get(SUPERSEDES_FIELD)
                    if isinstance(supersedes, dict) and isinstance(supersedes.get("eventId"), str) \
                            and EVENT_ID_RE.match(supersedes["eventId"]):
                        domain.add(supersedes["eventId"], f"superseded-by:{event}")
            elif M3_RECORD_RE.search(text.replace("\r\n", "\n")):
                domain.add(name[: -len(".md")], "record")
    for event in domain.events:
        if event_paths(event)["frozen"] not in history.paths():
            domain.never_committed.add(event)
    return domain


# ------------------------------------------------------------------ A2-A4: per-event history


def check_event_history(repo: Path, history: History, event_id: str, record_text: str | None) -> None:
    """A2-A4 for one domain event over the whole reachable history.

    A2: HEAD holds the frozen ledger, the protocol and the record (``m3_event_erased``); the frozen ledger and the
    protocol keep exactly one blob and are never modified, retyped or deleted on any parent edge, nor modified in the
    work tree (``m3_frozen_file_rewritten``). A3: M3 artefacts are add-only, one blob each, present in HEAD and
    unmodified in the work tree. A4: every structured line of every historical record version is still in the record
    (``m3_record_line_removed``)."""
    paths = event_paths(event_id)
    if paths["frozen"] not in history.paths():
        raise _fail("m3_group_member_missing", event_id)
    for kind in ("frozen", "protocol", "record"):
        if paths[kind] not in history.head_tree:
            raise _fail("m3_event_erased", f"{event_id}:{kind}")
    status = worktree_status(repo, [paths["frozen"], paths["protocol"]])
    for kind in ("frozen", "protocol"):
        path = paths[kind]
        if history.rewrites.get(path) or history.deletes.get(path) or len(history.blobs.get(path, ())) != 1 \
                or status.get(path, "  ").strip():
            raise _fail("m3_frozen_file_rewritten", f"{event_id}:{kind}")
    folder = paths["folder"]
    artefacts = sorted(p for p in history.paths() | set(history.head_tree)
                       if p.startswith(folder + "/") and artefact_event(p) == event_id)
    status = worktree_status(repo, artefacts)
    for path in artefacts:
        if LEGACY_LAYER_A_INFIX in Path(path).name:
            raise _fail("legacy_layer_a_artefact", path)
        if history.deletes.get(path):
            raise _fail("baseline_artefact_deleted_in_history", f"{path}@{sorted(history.deletes[path])[0][:12]}")
        if history.rewrites.get(path) or len(history.blobs.get(path, ())) != 1:
            raise _fail("baseline_artefact_rewritten_in_history", path)
        if history.head_tree.get(path) not in history.blobs[path]:
            raise _fail("baseline_artefact_deleted_in_history", path)
        if status.get(path, "  ")[1:].strip() or status.get(path, "  ")[0] in "MDRT":
            raise _fail("baseline_artefact_rewritten_in_history", path)
    current = structured_lines(record_text or "")
    record_blobs = history.blobs.get(paths["record"], set())
    texts = read_blobs(repo, record_blobs)
    for blob in sorted(record_blobs):
        missing = structured_lines(texts[blob].decode("utf-8", "replace")) - current
        if missing:
            raise _fail("m3_record_line_removed", f"{event_id}:{sorted(missing)[0]}")


# ------------------------------------------------------------------ the pure group state (shared by every mode)


@dataclass
class GroupState:
    """Everything the frozen rule derives for one composition group from its committed documents."""
    group_id: str
    universe: dict
    frozen_by_event: dict[str, dict]
    protocol_by_event: dict[str, str]
    bob_event: str
    partner_event: str
    composition_id: str
    bob_ids: set[str]
    rankings: dict[str, dict | None]
    seal: dict | None
    seal_sha256: str | None
    seal_status: str | None
    s0: str | None = None
    ordinary: list | None = None
    top_k: dict[str, list[str]] | None = None
    checked_rankings: dict | None = None

    @property
    def resolved(self) -> bool:
        return self.seal_status == RESOLVED and self.ordinary is not None


def derive_group_state(frozen_by_event: Mapping[str, Mapping], protocol_by_event: Mapping[str, str],
                       rankings: Mapping[str, Mapping | None], seal: Mapping | None, *, s0: str | None = None) -> GroupState:
    """The pure part of the group predicate (no Git): identical universe in every member, exactly one benchmark-only
    baseline with one gate-only composition whose partner is the other member, the partner universe, R1 (no ordinary
    candidate pins a BOB payload file), the component rankings, the seal re-derived field for field, and U."""
    events = sorted(frozen_by_event)
    universes = {document_sha256(frozen_by_event[e].get(UNIVERSE_FIELD)) for e in events}
    first = frozen_by_event[events[0]]
    universe = first.get(UNIVERSE_FIELD)
    if universe is None or len(universes) != 1:
        raise _fail("composition_universe_differs_between_events", ",".join(events))
    members = [item["eventId"] for item in universe["componentEvents"]]
    if sorted(members) != events:
        raise _fail("m3_group_member_missing", ",".join(sorted(set(members) ^ set(events))))
    bobs = [(e, c, entry, rule) for e in events for c, (entry, rule) in frozen_compositions(frozen_by_event[e]).items()]
    if len(bobs) != 1:
        raise _fail("composition_universe_requires_one_baseline", group_id(universe)[:12])
    bob_event, composition, bob_entry, rule = bobs[0]
    partner_event = rule["partnerEventId"]
    if partner_event == bob_event or partner_event not in members:
        raise _fail("baseline_partner_event_not_in_group", partner_event)
    check_partner_universe(rule, frozen_by_event[partner_event], f"group.{composition}", bob_entry)
    forbidden = bob_payload_hashes(bob_entry)
    for e in events:
        for entry in frozen_by_event[e]["candidates"]:
            if entry["disposition"]["status"] == SHORTLISTED and candidate_file_hashes(entry) & forbidden:
                raise _fail("benchmark_baseline_bytes_in_ordinary_candidate", f"{e}.{entry['candidateId']}")
    state = GroupState(group_id(universe), dict(universe), dict(frozen_by_event), dict(protocol_by_event), bob_event,
                       partner_event, composition, {bob_entry["candidateId"]}, dict(rankings), None, None, None, s0)
    if seal is None:
        for e in events:  # a ranking committed before the seal is checked at once
            if rankings.get(e) is not None:
                check_component_ranking(rankings[e], frozen_by_event[e])
        return state
    if not isinstance(seal, dict) or seal.get("compositionId") != composition:
        raise _fail("baseline_seal_composition_mismatch", composition)
    bob_frozen = frozen_by_event[bob_event]
    state.seal = dict(seal)
    state.seal_sha256 = verify_baseline_seal(seal, frozen=bob_frozen, protocol_sha256=protocol_by_event[bob_event],
                                             partner_ledger=frozen_by_event[partner_event], rankings=rankings)
    state.seal_status = seal["status"]
    if seal["status"] == RESOLVED:
        derived = derive_group_inputs(bob_frozen, composition, frozen_by_event[partner_event], rankings)
        state.ordinary = derived.ordinary
        state.checked_rankings = derived.rankings
        state.top_k = {item["eventId"]: derive_top_k(derived.rankings[item["eventId"]], item["k"])
                       for item in universe["componentEvents"]}
    return state


# ------------------------------------------------------------------ repository context


@dataclass
class Context:
    repo: Path
    history: History
    domain: Domain
    frozen: dict[str, dict]  # eventId -> current frozen ledger (validated by the file checks)
    authorities: dict[str, "GroupAuthority"] = field(default_factory=dict)


@dataclass
class GroupAuthority:
    state: GroupState
    members: list[str]
    d_manifests: dict[str, dict] = field(default_factory=dict)  # repo-relative path -> manifest
    decisions: dict[str, dict] = field(default_factory=dict)  # eventId -> decision
    abandoned: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    checked: list[str] = field(default_factory=list)

    @property
    def d_authorising(self) -> bool:
        return self.state.resolved and not self.abandoned and self.superseded_by is None


def _commit_of(ctx: Context, path: str) -> str | None:
    adds = ctx.history.adds.get(path)
    return first_add_commit(ctx.repo, adds, path) if adds else None


def _before(ctx: Context, earlier: str | None, later: str | None, where: str) -> None:
    """Chronology helper: ``earlier`` strictly before ``later``. An uncommitted later artefact will be committed on
    top of HEAD, which already holds every committed one; two uncommitted ones prove nothing."""
    if later is None:
        if earlier is None:
            raise _fail("m3_chronology_unproven", where)
        return
    if earlier is None or not strictly_before(ctx.repo, earlier, later):
        raise _fail("m3_chronology_violated", where)


def _record_text(repo: Path, event_id: str) -> str:
    path = Path(repo) / event_paths(event_id)["record"]
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def check_event_files(repo: Path, event_id: str) -> tuple[dict, str]:
    """The per-event file checks repository verification runs for every frozen event (and the pre-D gate for the
    group): the frozen ledger evolves into the working ledger append-only (shortlist, BOB set and universe fixed); the
    protocol cites the frozen hash and ``frozenOn``; the record carries the protocol's LF hash. Returns the frozen
    ledger and the protocol hash."""
    paths = {k: Path(repo) / v for k, v in event_paths(event_id).items()}
    working = paths["frozen"].with_name(f"{event_id}-evidence-ledger.json")
    if not paths["frozen"].is_file():
        raise _fail("m3_group_member_missing", event_id)
    if not working.is_file():
        raise _fail("frozen_ledger_without_ledger", _rel(paths["frozen"], repo))
    frozen = read_json(paths["frozen"])
    validate_evolution(frozen, read_json(working))
    text = paths["protocol"].read_text(encoding="utf-8") if paths["protocol"].is_file() else ""
    if document_sha256(frozen) not in text or frozen.get("frozenOn", "") not in text:
        raise _fail("frozen_ledger_not_cited_by_protocol", _rel(paths["frozen"], repo))
    if not paths["record"].is_file() or lf_normalised_sha256(paths["protocol"]) not in \
            paths["record"].read_text(encoding="utf-8"):
        raise _fail("protocol_hash_not_recorded_in_record", _rel(paths["protocol"], repo))
    return frozen, lf_normalised_sha256(paths["protocol"])


def _load_rankings(ctx: Context, members: list[str]) -> dict[str, dict | None]:
    rankings: dict[str, dict | None] = {}
    for e in members:
        path = Path(ctx.repo) / event_paths(e)["ranking"]
        document = read_canonical(path, "component_ranking_not_canonical") if path.is_file() else None
        cited = _cited(RANKING_CITATION_RE, _record_text(ctx.repo, e))
        if document is not None:
            hashes = cited.get(e, [])
            if len(hashes) > 1:
                raise _fail("component_ranking_cited_twice", path.name)
            if hashes != [document_sha256(document)]:
                raise _fail("component_ranking_not_recorded", path.name)
        for other in sorted(set(cited) - ({e} if document is not None else set())):
            raise _fail("component_ranking_cited_without_file", f"{e}:{other}")
        rankings[e] = document
    return rankings


def _load_seal(ctx: Context, bob_event: str, composition: str) -> dict | None:
    folder = Path(ctx.repo) / event_paths(bob_event)["folder"]
    seals = {p.name[len(f"{bob_event}{SEAL_INFIX}"):-len(".json")]: p
             for p in folder.glob(f"{bob_event}{SEAL_INFIX}*.json")}
    cited = record_seal_citations(_record_text(ctx.repo, bob_event))
    for composition_id, path in sorted(seals.items()):
        if composition_id != composition:
            raise _fail("baseline_artefact_without_frozen_composition", _rel(path, ctx.repo))
    for composition_id in sorted(set(cited) - set(seals)):
        raise _fail("baseline_seal_cited_without_file", f"{bob_event}:{composition_id}")
    if composition not in seals:
        return None
    path = seals[composition]
    seal = read_canonical(path, "baseline_seal_not_canonical")
    hashes = cited.get(composition, [])
    if len(hashes) > 1:
        raise _fail("baseline_seal_cited_twice", path.name)
    if hashes != [document_sha256(seal)]:
        raise _fail("baseline_seal_not_recorded", path.name)
    return seal


def check_group_authority(ctx: Context, gid: str, *, mode: str, remote_url: str | None = None,
                          github_api: Callable[[str], object] | None = None) -> GroupAuthority:
    """THE authority predicate of a composition group. Repository verification (``mode="repository"``) and the only
    pre-D entry point ``open_protected_d`` (``mode="pre_d"``) both call it, so D can never open on a state the
    repository check refuses. In order: full history (the context holds the walk); the member files; the identical
    universe, the one BOB and its partner, R1, the cited component rankings and the cited seal re-derived field for
    field (``derive_group_state``); A2-A4 for every member; chronology F ≺ R ≺ S0; D manifests, decisions,
    supersession and abandonment; and, in ``pre_d`` mode only, clean RESOLVED state, the protected default branch (O2)
    and the live anchor (D2)."""
    if mode not in ("repository", "pre_d"):
        raise _fail("authority_mode_invalid", mode)
    cached = ctx.authorities.get(gid)
    if cached is not None and mode == "repository":
        return cached
    universes = {e: f.get(UNIVERSE_FIELD) for e, f in ctx.frozen.items() if f.get(UNIVERSE_FIELD) is not None}
    by_group = sorted(e for e, u in universes.items() if group_id(u) == gid)
    if not by_group:
        raise _fail("composition_group_unknown", gid[:12])
    universe = universes[by_group[0]]
    members = sorted(item["eventId"] for item in universe["componentEvents"])
    frozen_by_event, protocol_by_event = {}, {}
    for e in members:
        if e not in ctx.frozen:
            raise _fail("m3_group_member_missing", e)
        frozen_by_event[e], protocol_by_event[e] = check_event_files(ctx.repo, e)
    rankings = _load_rankings(ctx, members)
    bob_event = next((e for e in members if frozen_compositions(frozen_by_event[e])), None)
    if bob_event is None:
        raise _fail("composition_universe_requires_one_baseline", gid[:12])
    composition = sorted(frozen_compositions(frozen_by_event[bob_event]))[0]
    seal = _load_seal(ctx, bob_event, composition)
    state = derive_group_state(frozen_by_event, protocol_by_event, rankings, seal)
    authority = GroupAuthority(state, members)
    for e in members:
        check_event_history(ctx.repo, ctx.history, e, _record_text(ctx.repo, e))
    # D1: F ≺ R ≺ S0 (strict)
    seal_rel = event_paths(bob_event)["folder"] + f"/{bob_event}{SEAL_INFIX}{composition}.json"
    s0 = _commit_of(ctx, seal_rel) if seal is not None else None
    if seal is not None and s0 is None and mode == "pre_d":
        raise _fail("baseline_seal_not_committed", seal_rel)
    state.s0 = s0
    for e in members:
        f = _commit_of(ctx, event_paths(e)["frozen"])
        if rankings[e] is not None:
            r = _commit_of(ctx, event_paths(e)["ranking"])
            _before(ctx, f, r, f"{e}:freeze<ranking")
            if seal is not None:
                _before(ctx, r, s0, f"{e}:ranking<seal")
        elif seal is not None:
            raise _fail("m3_chronology_violated", f"{e}:seal-without-ranking")
    _check_member_artefacts(ctx, authority)
    _check_d_artefacts(ctx, authority)
    _check_abandonment(ctx, authority)
    _check_decision_blocks(ctx, authority)
    _read_superseded_by(ctx, authority)
    ctx.authorities[gid] = authority  # cached before the cross-group checks, which may look back at this group
    _check_supersedes(ctx, authority)
    _check_stop_blocks_later_events(ctx, authority)
    if mode == "pre_d":
        _check_pre_d(ctx, authority, remote_url, github_api)
    return authority


def _check_d_artefacts(ctx: Context, authority: GroupAuthority) -> None:
    state = authority.state
    for e in authority.members:
        folder = Path(ctx.repo) / event_paths(e)["folder"]
        for path in sorted(folder.glob(f"{e}{D_MANIFEST_INFIX}*.json")):
            if e != state.bob_event:
                raise _fail("d_manifest_location_mismatch", _rel(path, ctx.repo))
            manifest = read_canonical(path, "d_manifest_not_canonical")
            rel = _rel(path, ctx.repo)
            _check_manifest_shape(manifest, state, path.name)
            if not state.resolved:
                raise _fail("baseline_stopped_no_d_result", rel)
            _check_binding_rows(manifest, state, rel)
            check_recorded_anchor(ctx.repo, manifest["anchorCommit"], state.s0, ctx.history.adds.get(rel, set()), rel)
            authority.d_manifests[rel] = manifest
            authority.checked.append(rel)


def _check_manifest_shape(manifest: Mapping, state: GroupState, name: str) -> None:
    _keys(manifest, D_MANIFEST_KEYS, name)
    if manifest["schema"] != D_MANIFEST_SCHEMA:
        raise _fail("schema_unsupported", f"{name}.schema")
    manifest_id = _match(manifest["manifestId"], LOCAL_ID_RE, f"{name}.manifestId")
    if manifest["eventId"] != state.bob_event or name != f"{state.bob_event}{D_MANIFEST_INFIX}{manifest_id}.json":
        raise _fail("d_manifest_location_mismatch", name)
    _match(manifest["resultSha256"], SHA256_RE, f"{name}.resultSha256")
    _match(manifest["anchorCommit"], IMMUTABLE_REVISION_RE, f"{name}.anchorCommit")


def _check_binding_rows(document: Mapping, state: GroupState, where: str, *, with_status: bool = False) -> None:
    """A D manifest or decision is bound to the group, the sealed U and the one seal by hash and S0."""
    if document["groupId"] != state.group_id:
        raise _fail("d_artefact_group_mismatch", where)
    if "ordinaryCompositionsSha256" in document and \
            document["ordinaryCompositionsSha256"] != state.seal["ordinaryCompositionsSha256"]:
        raise _fail("d_artefact_universe_mismatch", where)
    expected = {"compositionId": state.composition_id, "sealSha256": state.seal_sha256, "sealCommit": state.s0}
    if with_status:
        expected["status"] = state.seal_status
    rows = _list(document["baselineSeals"], f"{where}.baselineSeals")
    if rows != [expected]:
        raise _fail("d_manifest_baseline_seal_mismatch", f"{where}.baselineSeals")


def check_recorded_anchor(repo: Path, anchor: str, s0: str | None, adds: Iterable[str], where: str) -> None:
    """D3 for a committed (or about to be committed) protected-D artefact: S0 ≼ A; A ≺ the artefact's first add (or
    A ≼ HEAD before it is committed); A ≼ HEAD; and A ≼ ``refs/remotes/origin/main`` (fetched from GitHub by
    ``actions/checkout`` with full history). A missing or stale ref refuses (``anchor_unverifiable``)."""
    _match(anchor, IMMUTABLE_REVISION_RE, f"{where}.anchorCommit")
    if s0 is None:
        raise _fail("baseline_seal_not_committed", where)
    if ref_commit_or_none(repo, anchor) != anchor:
        raise _fail("anchor_not_in_head", f"{where}:{anchor[:12]}")
    if not is_ancestor(repo, s0, anchor):
        raise _fail("anchor_precedes_seal", where)
    if not is_ancestor(repo, anchor, "HEAD"):
        raise _fail("anchor_not_in_head", where)
    adds = set(adds)
    if adds and not strictly_before(repo, anchor, first_add_commit(repo, adds, where)):
        raise _fail("d_artefact_not_after_anchor", where)
    published = ref_commit_or_none(repo, RECORDED_ANCHOR_REF)
    if published is None or not is_ancestor(repo, anchor, published):
        raise _fail("anchor_unverifiable", f"{where}:{RECORDED_ANCHOR_REF}")


def _check_abandonment(ctx: Context, authority: GroupAuthority) -> None:
    lines = {e: sorted(m.group(0).rstrip() for m in ABANDONED_RE.finditer(_record_text(ctx.repo, e).replace("\r\n", "\n")))
             for e in authority.members}
    if not any(lines.values()):
        return
    first = lines[authority.members[0]]
    if any(v != first for v in lines.values()):
        raise _fail("group_abandonment_incomplete", authority.state.group_id[:12])
    results = {m["resultSha256"] for m in authority.d_manifests.values()}
    for line in first:
        match = ABANDONED_RE.match(line)
        if match["reason"] not in ABANDON_REASONS:
            raise _fail("abandonment_reason_not_allowed", match["reason"])
        if match["sha"] not in results:
            raise _fail("abandonment_without_protected_d", line)
    authority.abandoned = first


def _check_decision_blocks(ctx: Context, authority: GroupAuthority) -> None:
    state = authority.state
    blocks = {}
    for e in authority.members:
        path = Path(ctx.repo) / event_paths(e)["decision"]
        if not path.is_file():
            continue
        decision = read_json(path)
        rel = _rel(path, ctx.repo)
        if authority.abandoned:
            raise _fail("event_abandoned_decision_refused", rel)
        if not state.resolved:
            raise _fail("baseline_stopped_decision_refused", rel)
        block = _keys(decision.get(AUTHORITY_FIELD), DECISION_KEYS, f"{rel}.{AUTHORITY_FIELD}")
        _check_binding_rows(block, state, rel, with_status=True)
        check_recorded_anchor(ctx.repo, block["anchorCommit"], state.s0, ctx.history.adds.get(rel, set()), rel)
        blocks[e] = document_sha256(block)
        authority.decisions[e] = decision
    if len(set(blocks.values())) > 1:
        raise _fail("composition_authority_differs_between_group_events", state.group_id[:12])


def _group_of_event(ctx: Context, event_id: str) -> str | None:
    frozen = ctx.frozen.get(event_id)
    return None if frozen is None or frozen.get(UNIVERSE_FIELD) is None else group_id(frozen[UNIVERSE_FIELD])


def _check_member_artefacts(ctx: Context, authority: GroupAuthority) -> None:
    """Every M3 artefact in a member folder is a known one: the member's component ranking, the group's one seal or a
    D manifest of the BOB event (checked below). Anything else is refused."""
    state = authority.state
    for e in authority.members:
        folder = Path(ctx.repo) / event_paths(e)["folder"]
        for path in sorted(folder.glob(f"{e}-*.json")):
            if artefact_event(path.name) != e:
                continue
            name = path.name
            if name == f"{e}{RANKING_SUFFIX}":
                continue
            if e == state.bob_event and (name == f"{e}{SEAL_INFIX}{state.composition_id}.json"
                                         or (D_MANIFEST_INFIX in name and RANKING_INFIX not in name
                                             and SEAL_INFIX not in name and LEGACY_LAYER_A_INFIX not in name)):
                continue
            if LEGACY_LAYER_A_INFIX in name:
                raise _fail("legacy_layer_a_artefact", _rel(path, ctx.repo))
            if D_MANIFEST_INFIX in name:
                raise _fail("d_manifest_location_mismatch", _rel(path, ctx.repo))
            raise _fail("baseline_artefact_without_frozen_composition", _rel(path, ctx.repo))


def _read_superseded_by(ctx: Context, authority: GroupAuthority) -> None:
    """``Superseded by <id>`` record lines: the named event exists and supersedes this member; one successor only."""
    for e in authority.members:
        for line in sorted(m["id"] for m in SUPERSEDED_RE.finditer(_record_text(ctx.repo, e).replace("\r\n", "\n"))):
            successor = ctx.frozen.get(line)
            if successor is None or (successor.get(SUPERSEDES_FIELD) or {}).get("eventId") != e:
                raise _fail("superseded_line_without_superseding_event", f"{e}:{line}")
            if authority.superseded_by not in (None, line):
                raise _fail("event_superseded_twice", e)
            authority.superseded_by = line
    if authority.superseded_by is not None and authority.state.seal_status != STOPPED:
        raise _fail("supersedes_target_not_stopped", ",".join(authority.members))


def _check_supersedes(ctx: Context, authority: GroupAuthority) -> None:
    """Owner decisions O1/O6 (E1/E2): a member declaring ``supersedes`` names a domain event whose frozen ledger hash
    matches, whose group seal is STOPPED with exactly the cited seal hashes, which holds no D artefact and no decision,
    whose record carries ``Superseded by <member>``, and whose stop (S0) strictly precedes the member's freeze. The
    member itself is M3 with a gate-only composition (its universe requires the ``baseline`` gate)."""
    state = authority.state
    for e in authority.members:
        block = state.frozen_by_event[e].get(SUPERSEDES_FIELD)
        if block is None:
            continue
        target = block["eventId"]
        if target not in ctx.frozen or target not in ctx.domain.events:
            raise _fail("supersedes_target_missing", f"{e}->{target}")
        if document_sha256(ctx.frozen[target]) != block["frozenLedgerSha256"]:
            raise _fail("supersedes_frozen_ledger_mismatch", f"{e}->{target}")
        target_gid = _group_of_event(ctx, target)
        if target_gid is None or target_gid == state.group_id:
            raise _fail("supersedes_target_missing", f"{e}->{target}")
        target_auth = check_group_authority(ctx, target_gid, mode="repository")
        tstate = target_auth.state
        if tstate.seal_status != STOPPED or [tstate.seal_sha256] != block["stoppedSealSha256s"]:
            raise _fail("supersedes_target_not_stopped", f"{e}->{target}")
        if target_auth.d_manifests or target_auth.decisions:
            raise _fail("supersedes_target_has_d_or_decision", f"{e}->{target}")
        if superseded_line(e) not in structured_lines(_record_text(ctx.repo, target)):
            raise _fail("superseded_record_line_missing", f"{target}:{e}")
        _before(ctx, tstate.s0, _commit_of(ctx, event_paths(e)["frozen"]), f"{target}:stop<{e}:freeze")


def _check_stop_blocks_later_events(ctx: Context, authority: GroupAuthority) -> None:
    """E3: while a member of a STOPPED group is not superseded, every other frozen event of its capability (M1, M2 or
    M3) must have been frozen before the stop; a later one must supersede it (and so be M3 with a gate, O6)."""
    state = authority.state
    if state.seal_status != STOPPED or authority.superseded_by is not None:
        return
    for e in authority.members:
        capability = capability_of(e)
        for other in sorted(ctx.frozen):
            if other in authority.members or capability_of(other) != capability:
                continue
            f_other = _commit_of(ctx, event_paths(other)["frozen"])
            if f_other is not None and state.s0 is not None and is_ancestor(ctx.repo, f_other, state.s0):
                continue  # frozen before the stop
            raise _fail("stopped_event_not_superseded", f"{e}:{other}")


# ------------------------------------------------------------------ repository mode


def build_context(repo: Path, frozen: Mapping[str, Mapping]) -> Context:
    history = model_selection_history(Path(repo))
    return Context(Path(repo), history, model_selection_domain(Path(repo), history), dict(frozen))


def validate_repository_m3(repo: Path, frozen_by_path: Mapping[Path, Mapping]) -> tuple[list[str], Context]:
    """Repository mode. Builds the history walk unconditionally (full history is required for every repository), runs
    A2-A4 for every domain event, and ``check_group_authority`` for every composition group. Returns the M3 files
    checked (nothing extra when the domain is empty) and the context."""
    frozen = {path.name: document for path, document in frozen_by_path.items()}
    ctx = build_context(repo, frozen)
    checked: list[str] = []
    for event_id in sorted(ctx.domain.events):
        if event_id in ctx.domain.never_committed:
            raise _fail("m3_group_member_missing", event_id)
        if ctx.frozen.get(event_id, {}).get(UNIVERSE_FIELD) is None:
            # an M3 event must stay an M3 group event; a vanished or non-M3 current ledger is refused by A2 first
            check_event_history(ctx.repo, ctx.history, event_id, _record_text(repo, event_id))
            raise _fail("m3_artefact_without_group", event_id)
        check_event_history(ctx.repo, ctx.history, event_id, _record_text(repo, event_id))
    gids = sorted({group_id(f[UNIVERSE_FIELD]) for f in ctx.frozen.values() if f.get(UNIVERSE_FIELD) is not None})
    for gid in gids:
        authority = check_group_authority(ctx, gid, mode="repository")
        state = authority.state
        for e in authority.members:
            paths = event_paths(e)
            if state.rankings.get(e) is not None:
                checked.append(paths["ranking"])
        if state.seal is not None:
            checked.append(event_paths(state.bob_event)["folder"] +
                           f"/{state.bob_event}{SEAL_INFIX}{state.composition_id}.json")
        checked += authority.checked
    # stray M3 artefacts in a folder whose event is no group member
    root = Path(repo) / MODEL_SELECTION_DIR
    for path in sorted(root.glob("*/msr-*.json")):
        event = artefact_event(path.name)
        if event is not None and _group_of_event(ctx, event) is None:
            raise _fail("baseline_artefact_without_frozen_composition", _rel(path, repo))
    if ctx.domain.events:
        checked.append("git-history:full")
    return checked, ctx


def repository_group_authority(repo: Path, gid: str) -> GroupAuthority:
    """The group authority of ``gid`` exactly as repository verification computes it (used by the decision CLI)."""
    from .credibility import _validate_repository
    _checked, ctx = _validate_repository(Path(repo))
    if gid not in ctx.authorities:
        raise _fail("composition_group_unknown", gid[:12])
    return ctx.authorities[gid]


# ------------------------------------------------------------------ O2: protected default branch


def gh_api(path: str) -> object:
    """``gh api <path>`` (read-only). Any failure raises ``protected_default_branch_unverifiable``."""
    completed = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github+json", path],
                               capture_output=True, check=False, env={**__import__("os").environ,
                                                                       "GH_PROMPT_DISABLED": "1"})
    if completed.returncode != 0:
        raise _fail("protected_default_branch_unverifiable",
                    f"gh api {path}: rc={completed.returncode}: {completed.stderr.decode('utf-8', 'replace')[-500:]}")
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except ValueError as exc:
        raise _fail("protected_default_branch_unverifiable", f"gh api {path}: not JSON") from exc


_DEFAULT_BRANCH_PATTERNS = ("~DEFAULT_BRANCH", "~ALL", DEFAULT_BRANCH_REF)


def verify_default_branch_protection(github_api: Callable[[str], object],
                                     repository: str = CANONICAL_REPOSITORY) -> int:
    """Owner decision O2: an ACTIVE branch ruleset covers the default branch with ``deletion`` and ``non_fast_forward``
    and NO bypass actors, and GitHub reports both rules as applying to ``main``. Returns the ruleset id. Anything that
    cannot be verified refuses (``protected_default_branch_unverifiable``); a verified absence refuses
    (``protected_default_branch_unverified``)."""
    try:
        rulesets = github_api(f"repos/{repository}/rulesets?includes_parents=true")
        applied = github_api(f"repos/{repository}/rules/branches/{DEFAULT_BRANCH}")
        if not isinstance(rulesets, list) or not isinstance(applied, list):
            raise _fail("protected_default_branch_unverifiable", "unexpected API shape")
        applied_rules = {(r.get("type"), r.get("ruleset_id")) for r in applied if isinstance(r, dict)}
        for summary in rulesets:
            if not isinstance(summary, dict) or summary.get("enforcement") != "active" \
                    or summary.get("target", "branch") != "branch" or not isinstance(summary.get("id"), int):
                continue
            detail = github_api(f"repos/{repository}/rulesets/{summary['id']}")
            if not isinstance(detail, dict) or detail.get("enforcement") != "active":
                continue
            ref_name = ((detail.get("conditions") or {}).get("ref_name") or {})
            include, exclude = ref_name.get("include") or [], ref_name.get("exclude") or []
            covers = any(p in _DEFAULT_BRANCH_PATTERNS for p in include) and \
                not any(p in _DEFAULT_BRANCH_PATTERNS for p in exclude)
            types = {r.get("type") for r in detail.get("rules") or () if isinstance(r, dict)}
            if covers and {"deletion", "non_fast_forward"} <= types and detail.get("bypass_actors") == [] and \
                    {("deletion", summary["id"]), ("non_fast_forward", summary["id"])} <= applied_rules:
                return summary["id"]
    except CredibilityError:
        raise
    except Exception as exc:  # noqa: BLE001 - any API failure is unverifiable, never a pass
        raise _fail("protected_default_branch_unverifiable", f"{type(exc).__name__}: {exc}") from exc
    raise _fail("protected_default_branch_unverified", f"{repository}:{DEFAULT_BRANCH}")


# ------------------------------------------------------------------ D2: the live anchor


def check_live_anchor(repo: Path, s0s: Iterable[str], remote_url: str, paths: Iterable[str]) -> str:
    """D2. ``git ls-remote --exit-code <canonical> refs/heads/main`` must return exactly one line, T; T is fetched and
    must be a commit; every seal's S0 must be an ancestor of T (published); T must be an ancestor of HEAD; the group
    paths must be identical at T and HEAD and clean in the work tree. Never reads ``origin`` or its remote-tracking
    refs. No network, a failed fetch or an unexpected answer refuses (``anchor_unavailable``)."""
    repo = Path(repo)
    args = ("ls-remote", "--exit-code", remote_url, DEFAULT_BRANCH_REF)
    completed = _run(repo, args)
    if completed.returncode != 0:
        raise _fail("anchor_unavailable", f"ls-remote rc={completed.returncode}: "
                    f"{completed.stderr.decode('utf-8', 'replace').strip()[-500:]}")
    lines = [line for line in completed.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    if len(lines) != 1:
        raise _fail("anchor_unavailable", f"ls-remote returned {len(lines)} lines")
    tip, _, ref = lines[0].partition("\t")
    if ref.strip() != DEFAULT_BRANCH_REF or not IMMUTABLE_REVISION_RE.match(tip.strip()):
        raise _fail("anchor_unavailable", "unexpected ls-remote answer")
    tip = tip.strip()
    fetched = _run(repo, ("fetch", "--no-tags", "--quiet", remote_url, DEFAULT_BRANCH_REF))
    if fetched.returncode != 0:
        raise _fail("anchor_unavailable", f"fetch rc={fetched.returncode}: "
                    f"{fetched.stderr.decode('utf-8', 'replace').strip()[-500:]}")
    _git(repo, "cat-file", "-e", f"{tip}^{{commit}}")
    for s0 in s0s:
        if not is_ancestor(repo, s0, tip):
            raise _fail("seal_not_published", s0[:12])
    if not is_ancestor(repo, tip, "HEAD"):
        raise _fail("anchor_not_in_head", tip[:12])
    paths = sorted(set(paths))
    diff = _run(repo, ("diff", "--quiet", tip, "HEAD", "--", *paths))
    if diff.returncode == 1:
        raise _fail("group_state_differs_from_anchor", tip[:12])
    if diff.returncode != 0:
        raise GitCommandError("git_command_failed", ("diff", "--quiet"), diff.returncode,
                              diff.stderr.decode("utf-8", "replace"))
    if worktree_status(repo, paths):
        raise _fail("group_state_not_clean", ",".join(paths))
    return tip


# ------------------------------------------------------------------ the only pre-D entry point


@dataclass(frozen=True)
class DAuthorization:
    group_id: str
    anchor_commit: str
    seals: tuple[SealBinding, ...]
    ordinary_compositions_sha256: str
    bob_event: str


def _check_pre_d(ctx: Context, authority: GroupAuthority, remote_url: str | None,
                 github_api: Callable[[str], object] | None) -> None:
    state = authority.state
    if state.seal is None:
        raise _fail("d_not_authorised", "baseline-seal-missing")
    if state.seal_status != RESOLVED:
        raise _fail("d_not_authorised", f"baseline-seal-{state.seal_status}:{state.seal['stopReason']}")
    if any(state.rankings.get(e) is None for e in authority.members) or state.ordinary is None:
        raise _fail("d_not_authorised", "composition-universe-indeterminate")
    if authority.abandoned:
        raise _fail("d_not_authorised", "group-abandoned")
    if authority.superseded_by is not None:
        raise _fail("d_not_authorised", f"superseded-by:{authority.superseded_by}")
    if state.s0 is None:
        raise _fail("d_not_authorised", "baseline-seal-not-committed")
    if remote_url is None or github_api is None:
        raise _fail("d_not_authorised", "anchor-not-configured")


def open_protected_d(repo: Path, group: str, *, remote_url: str = CANONICAL_ORIGIN,
                     github_api: Callable[[str], object] = gh_api) -> DAuthorization:
    """THE pre-D gate. Call before reading any protected D data; record the returned anchor, seal hash, seal commit
    (S0) and U hash in every D manifest (``d_manifest_document``).

    ``group`` is the group id or the id of any member event. The whole repository must verify (the same predicate as
    ``validate_repository``, including every other group, supersession and the sticky audit), then for this group:
    every member file clean and committed, the one seal RESOLVED, U determinate, not abandoned or superseded; the
    default branch protected by an active ruleset without bypass (O2); and the live anchor T on the canonical
    repository (D2). Offline, or any doubt, refuses."""
    from .credibility import _validate_repository
    repo = Path(repo)
    _checked, ctx = _validate_repository(repo)
    gid = group if SHA256_RE.match(group) else _group_of_event(ctx, group)
    if gid is None or gid not in ctx.authorities:
        raise _fail("composition_group_unknown", str(group)[:24])
    authority = check_group_authority(ctx, gid, mode="pre_d", remote_url=remote_url, github_api=github_api)
    state = authority.state
    verify_default_branch_protection(github_api)
    folders = sorted({event_paths(e)["folder"] for e in authority.members})
    anchor = check_live_anchor(repo, [state.s0], remote_url, folders)
    seal = state.seal
    binding = SealBinding(state.composition_id, state.seal_sha256, state.s0, seal["partnerCandidateId"],
                          seal["partnerIdentitySha256"], seal["compositionSha256"])
    return DAuthorization(state.group_id, anchor, (binding,), seal["ordinaryCompositionsSha256"], state.bob_event)


def d_manifest_document(auth: DAuthorization, manifest_id: str, result_sha256: str) -> dict:
    """The canonical protected-D manifest a harness commits as ``<bobEvent>-d-manifest-<manifestId>.json`` in a
    commit descending from the anchor."""
    return {"schema": D_MANIFEST_SCHEMA, "eventId": auth.bob_event, "manifestId": manifest_id,
            "groupId": auth.group_id, "resultSha256": result_sha256, "anchorCommit": auth.anchor_commit,
            "ordinaryCompositionsSha256": auth.ordinary_compositions_sha256,
            "baselineSeals": [{"compositionId": b.composition_id, "sealSha256": b.seal_sha256,
                               "sealCommit": b.seal_commit} for b in auth.seals]}


def verify_d_manifest_binding(manifest: Mapping, repo: Path) -> None:
    """Before scoring a D run: re-run the repository authority and require the manifest to equal it (group, sealed U,
    seal hash and S0) with a recorded anchor that satisfies D3."""
    from .credibility import _validate_repository
    repo = Path(repo)
    _checked, ctx = _validate_repository(repo)
    gid = manifest.get("groupId") if isinstance(manifest, dict) else None
    if gid not in ctx.authorities:
        raise _fail("d_artefact_group_mismatch", "manifest.groupId")
    state = ctx.authorities[gid].state
    name = f"{manifest.get('eventId')}{D_MANIFEST_INFIX}{manifest.get('manifestId')}.json"
    _check_manifest_shape(manifest, state, name)
    if not state.resolved:
        raise _fail("baseline_stopped_no_d_result", name)
    _check_binding_rows(manifest, state, name)
    rel = event_paths(state.bob_event)["folder"] + "/" + name
    check_recorded_anchor(repo, manifest["anchorCommit"], state.s0, ctx.history.adds.get(rel, set()), name)


# ------------------------------------------------------------------ C2-C6: the decision binding


def check_composition_decision(decision: Mapping, state: GroupState, own_event: str) -> dict[str, tuple[str, float | None]]:
    """The mandatory ``compositionAuthority`` block of a group event's decision summary v1 (identical in every group
    event). Returns, per own-event candidate, the composition-derived ``(technicalGates, comparativeScore)``.

    The composition set must EQUAL the sealed U (no omission, no extra, derived ids); the baseline gate, technical
    gates, scores, ranking, strongest composition, top-K and finalists are recomputed; the frontier and the
    implementation composition are ranked compositions; a null baseline D refuses the decision (owner decision O4)."""
    where = f"decision.{AUTHORITY_FIELD}"
    block = _keys(decision.get(AUTHORITY_FIELD), DECISION_KEYS, where)
    if state.seal is None:
        raise _fail("gate_only_composition_unresolved", f"{where}.baselineSeals")
    if state.seal_status != RESOLVED or state.ordinary is None:
        raise _fail("baseline_stopped_decision_refused", f"{state.composition_id}:{state.seal.get('stopReason')}")
    _match(block["anchorCommit"], IMMUTABLE_REVISION_RE, f"{where}.anchorCommit")
    if block["groupId"] != state.group_id:
        raise _fail("d_artefact_group_mismatch", f"{where}.groupId")
    rows = _list(block["baselineSeals"], f"{where}.baselineSeals")
    for index, row in enumerate(rows):
        _keys(row, ("compositionId", "sealSha256", "status", "sealCommit"), f"{where}.baselineSeals[{index}]")
        _match(row["sealCommit"], IMMUTABLE_REVISION_RE, f"{where}.baselineSeals[{index}].sealCommit")
    if len(rows) != 1:
        raise _fail("gate_only_composition_unresolved", f"{where}.baselineSeals")
    if rows[0] != {"compositionId": state.composition_id, "sealSha256": state.seal_sha256, "status": RESOLVED,
                   "sealCommit": state.s0 if state.s0 is not None else rows[0]["sealCommit"]}:
        raise _fail("decision_baseline_seal_mismatch", f"{where}.baselineSeals")
    started = _instant(block["dExecutionStartedAt"], f"{where}.dExecutionStartedAt")
    if not _instant(state.seal["recordedAt"], "seal.recordedAt") < started:
        raise _fail("baseline_resolved_after_d_started", f"{where}.dExecutionStartedAt")
    if started.date() > date.fromisoformat(decision["decidedOn"]):
        raise _fail("d_started_after_decision", f"{where}.dExecutionStartedAt")
    forbidden = set(state.bob_ids) | {state.composition_id}
    universe = state.universe
    mpid = float(universe["mpid"])
    gate_ids = list(universe["compositionGateIds"])
    seal_hashes = {state.composition_id: state.seal_sha256}
    # the gate-only baseline composition (O4: no decision without its D result)
    base = _keys(block["baseline"], ("compositionId", "compositionSha256", "dScore", "dResultSha256"),
                 f"{where}.baseline")
    if base["compositionId"] != state.composition_id or base["compositionSha256"] != state.seal["compositionSha256"]:
        raise _fail("decision_baseline_composition_mismatch", f"{where}.baseline")
    _match(base["dResultSha256"], SHA256_RE, f"{where}.baseline.dResultSha256")
    if base["dScore"] is None:
        raise _fail("baseline_d_unavailable", f"{where}.baseline.dScore")
    base_score = _number(base["dScore"], f"{where}.baseline.dScore")
    # C2: the composition set equals the sealed U, with derived ids and exact components
    expected = {item["compositionId"]: item["components"] for item in state.ordinary}
    candidates = _list(block["compositionCandidates"], f"{where}.compositionCandidates")
    seen: dict[str, dict] = {}
    for index, row in enumerate(candidates):
        at = f"{where}.compositionCandidates[{index}]"
        if isinstance(row, dict) and row.get("compositionId") in forbidden:
            raise _fail("benchmark_baseline_in_composition_candidate", f"{at}.compositionId")
        _keys(row, _ROW_KEYS, at)
        if row["compositionId"] in seen:
            raise _fail("composition_set_differs_from_sealed_universe", f"{at}.compositionId")
        seen[row["compositionId"]] = row
    if set(seen) != set(expected):
        raise _fail("composition_set_differs_from_sealed_universe", f"{where}.compositionCandidates")
    passing: dict[str, float] = {}
    for composition_id, row in sorted(seen.items()):
        at = f"{where}.compositionCandidates.{composition_id}"
        if row["components"] != expected[composition_id]:
            raise _fail("composition_components_not_derived", f"{at}.components")
        gates = row["gates"]
        if not isinstance(gates, dict) or sorted(gates) != gate_ids:
            raise _fail("composition_hard_gate_mapping_invalid", f"{at}.gates")
        for gate, value in gates.items():
            if value not in (PASSED, FAILED):
                raise _fail("value_not_allowed", f"{at}.gates.{gate}")
        score = None if row["dScore"] is None else _number(row["dScore"], f"{at}.dScore")
        _match(row["dResultSha256"], SHA256_RE, f"{at}.dResultSha256")
        if row["baselineSealSha256s"] != seal_hashes:
            raise _fail("d_result_baseline_seal_mismatch", f"{at}.baselineSealSha256s")
        baseline_passed = score is not None and score - base_score >= mpid
        if gates[BASELINE_GATE] != (PASSED if baseline_passed else FAILED):
            raise _fail("composition_baseline_gate_not_derived", f"{at}.gates.{BASELINE_GATE}")
        technical = PASSED if all(v == PASSED for v in gates.values()) else FAILED
        if row["technicalGates"] != technical:
            raise _fail("composition_technical_gates_not_derived", f"{at}.technicalGates")
        if row["comparativeScore"] != (score if technical == PASSED else None):
            raise _fail("composition_score_not_derived", f"{at}.comparativeScore")
        if technical == PASSED:
            passing[composition_id] = score
    if ordinary_compositions_sha256([{"compositionId": c, "components": seen[c]["components"]} for c in
                                     sorted(seen)]) != state.seal["ordinaryCompositionsSha256"]:
        raise _fail("composition_set_differs_from_sealed_universe", f"{where}.compositionCandidates")
    # C3: ranking, strongest and frontier
    for name in ("rankedCompositions", "frontier"):
        members = _list(block[name], f"{where}.{name}")
        if not all(isinstance(m, str) for m in members) or len(set(members)) != len(members):
            raise _fail("ranked_set_not_unique", f"{where}.{name}")
        if set(members) & forbidden:
            raise _fail("benchmark_baseline_in_ranked_set", f"{where}.{name}")
    order = block["rankedCompositions"]
    if set(order) != set(passing) or any(passing[a] < passing[b] for a, b in zip(order, order[1:])):
        raise _fail("ranked_compositions_not_derived", f"{where}.rankedCompositions")
    for member in block["frontier"]:
        if member not in passing:
            raise _fail("frontier_member_not_ranked_composition", f"{where}.frontier")
    strongest = block["strongestEvaluatedComposition"]
    if strongest in forbidden:
        raise _fail("benchmark_baseline_in_derived_output", f"{where}.strongestEvaluatedComposition")
    best = max(passing.values()) if passing else None
    if (strongest is None) != (best is None) or (strongest is not None and passing.get(strongest) != best):
        raise _fail("strongest_composition_not_derived", f"{where}.strongestEvaluatedComposition")
    incumbent = block["incumbent"]
    if incumbent is not None:
        if incumbent in forbidden:
            raise _fail("benchmark_baseline_in_derived_output", f"{where}.incumbent")
        if incumbent not in expected:
            raise _fail("incumbent_not_evaluated", f"{where}.incumbent")
    implementation = block["implementationComposition"]
    if implementation is not None:
        if implementation in forbidden:
            raise _fail("benchmark_baseline_in_derived_output", f"{where}.implementationComposition")
        if implementation not in passing:
            raise _fail("implementation_composition_not_ranked", f"{where}.implementationComposition")
    # C6: top-K and component finalists equal the derivation (diagnostics only)
    for name in ("topK", "componentFinalists"):
        value = block[name]
        if isinstance(value, dict) and any(isinstance(v, list) and set(v) & forbidden for v in value.values()):
            raise _fail("benchmark_baseline_in_ranked_set", f"{where}.{name}")
    if block["topK"] != state.top_k:
        raise _fail("top_k_not_derived", f"{where}.topK")
    finalists = {item["eventId"]: sorted({c["candidateId"] for comp in passing for c in expected[comp]
                                          if c["eventId"] == item["eventId"]})
                 for item in universe["componentEvents"]}
    if block["componentFinalists"] != finalists:
        raise _fail("component_finalists_not_derived", f"{where}.componentFinalists")
    # C4: the own event's row values are composition-derived
    derived: dict[str, tuple[str, float | None]] = {}
    for candidate in {c["candidateId"] for comps in expected.values() for c in comps if c["eventId"] == own_event} | \
            {e["candidateId"] for e in state.frozen_by_event[own_event]["candidates"]
             if e["disposition"]["status"] == SHORTLISTED}:
        scores = [passing[comp] for comp in passing
                  if any(c["eventId"] == own_event and c["candidateId"] == candidate for c in expected[comp])]
        derived[candidate] = (PASSED, max(scores)) if scores else (FAILED, None)
    return derived


def implementation_component(state: GroupState, composition_id: str, own_event: str) -> str:
    for item in state.ordinary or ():
        if item["compositionId"] == composition_id:
            return next(c["candidateId"] for c in item["components"] if c["eventId"] == own_event)
    raise _fail("implementation_composition_not_ranked", composition_id)


def write_canonical(path: Path, document: Mapping) -> Path:
    """Write a canonical-JSON artefact (seal, component ranking or D manifest)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(document))
    return path

