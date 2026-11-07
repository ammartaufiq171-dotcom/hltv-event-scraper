"""Command line entry point: python -m hltv <command>."""
from __future__ import annotations

import argparse
import sys

from . import build as build_mod
from . import report as report_mod
from . import scrape as scrape_mod
from . import verify as verify_mod
from .cdp import CDP


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="hltv",
        description="Scrape an HLTV event's results and player stats via a real Chrome window.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--out", default="./data", help="output directory (default: ./data)")

    sp_scrape = sub.add_parser("scrape", help="fetch raw pages from HLTV (needs Chrome on --port)")
    sp_scrape.add_argument("--event", required=True, help="HLTV event id, e.g. 8245")
    sp_scrape.add_argument("--port", type=int, default=9222, help="Chrome remote-debugging port")
    sp_scrape.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    sp_scrape.add_argument("--limit", type=int, default=None, help="only scrape N matches (testing)")
    sp_scrape.add_argument("--no-details", action="store_true",
                           help="skip the detailed-stats pages (no headshots)")
    common(sp_scrape)

    sp_details = sub.add_parser("details", help="fetch only the detailed-stats pages (headshots)")
    sp_details.add_argument("--port", type=int, default=9222)
    sp_details.add_argument("--delay", type=float, default=1.5)
    sp_details.add_argument("--limit", type=int, default=None)
    common(sp_details)

    for name, helptext in [("build", "turn raw JSON into CSVs + bundle"),
                           ("report", "write summary.md and derived player totals"),
                           ("verify", "self-check the built CSVs")]:
        sp = sub.add_parser(name, help=helptext)
        common(sp)

    sp_all = sub.add_parser("all", help="scrape + build + report + verify")
    sp_all.add_argument("--event", required=True, help="HLTV event id, e.g. 8245")
    sp_all.add_argument("--port", type=int, default=9222)
    sp_all.add_argument("--delay", type=float, default=1.5)
    sp_all.add_argument("--limit", type=int, default=None)
    sp_all.add_argument("--no-details", action="store_true",
                        help="skip the detailed-stats pages (no headshots)")
    common(sp_all)

    a = p.parse_args(argv)

    if a.cmd == "scrape":
        scrape_mod.scrape(a.event, a.out, port=a.port, delay=a.delay, limit=a.limit,
                          details=not a.no_details)
        return 0
    if a.cmd == "details":
        with CDP(port=a.port) as c:
            scrape_mod.scrape_details(c, a.out, delay=a.delay, limit=a.limit)
        return 0
    if a.cmd == "build":
        build_mod.build(a.out)
        return 0
    if a.cmd == "report":
        report_mod.build_report(a.out)
        return 0
    if a.cmd == "verify":
        return verify_mod.run(a.out)
    if a.cmd == "all":
        scrape_mod.scrape(a.event, a.out, port=a.port, delay=a.delay, limit=a.limit,
                          details=not a.no_details)
        build_mod.build(a.out)
        report_mod.build_report(a.out)
        return verify_mod.run(a.out)
    return 1


if __name__ == "__main__":
    sys.exit(main())
