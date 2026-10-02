"""Command line for the B0 source-acquisition pilot (Development only).

    discover --store S --contact C (--search TEXT | --category "Category:...") [--limit N]
    acquire  --store S --contact C [--decisions reviewed-decisions.json] [--purpose-approvals approvals.json]
    verify   --store S
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import commons
from .acquire import StoreError, acquire, discover, load_decisions, load_purpose_approvals, verify
from .transport import Transport, TransportError

USER_AGENT = "MAVI-S2c-B0-source-acquisition/1.0 (Development qualification tooling; contact: {contact})"


def _transport(contact: str) -> Transport:
    if not contact or any(c in contact for c in "\r\n()"):
        raise StoreError("--contact (an operator e-mail or URL for the User-Agent) is required")
    return Transport(commons.ALLOWED_HOSTS, USER_AGENT.format(contact=contact))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="source_acquisition", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--store", required=True, type=Path)
    d.add_argument("--contact", required=True)
    group = d.add_mutually_exclusive_group(required=True)
    group.add_argument("--search")
    group.add_argument("--category")
    d.add_argument("--limit", type=int, default=60)
    a = sub.add_parser("acquire")
    a.add_argument("--store", required=True, type=Path)
    a.add_argument("--contact", required=True)
    a.add_argument("--decisions", type=Path)
    a.add_argument("--purpose-approvals", type=Path)
    v = sub.add_parser("verify")
    v.add_argument("--store", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            problems = verify(args.store)
            print(json.dumps({"problems": problems}, indent=2))
            return 1 if problems else 0
        transport = _transport(args.contact)
        if args.command == "discover":
            url = commons.search_query_url(args.search, args.limit) if args.search else commons.category_query_url(args.category, args.limit)
            titles = commons.discovered_titles(json.loads(transport.get_bytes(url).decode("utf-8")))
            result = discover(args.store, titles, transport)
            print(json.dumps({"discoveryReportSha256": result["discoveryReportSha256"], "decisionsTemplate": result["decisionsTemplate"],
                              "states": sorted({str(i["admissionState"]) for i in result["items"]}), "items": len(result["items"])}, indent=2))
            return 0
        if args.decisions is None and args.purpose_approvals is None:
            raise StoreError("acquire needs --decisions, --purpose-approvals or both")
        decisions = load_decisions(args.decisions) if args.decisions else []
        approvals = load_purpose_approvals(args.purpose_approvals) if args.purpose_approvals else []
        summary = acquire(args.store, decisions, transport, approvals)
        print(json.dumps({"counts": summary["counts"], "purposeApproved": summary["purposeApproved"], "failed": summary["failed"]}, indent=2))
        return 1 if summary["failed"] else 0
    except (StoreError, TransportError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
