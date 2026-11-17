"""Command line: python -m flag_route_planner ROUTES.xlsx --garage "123 Main Street, Springfield"."""

import argparse
from pathlib import Path

from .pipeline import Config, run


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="flag_route_planner", description=__doc__)
    ap.add_argument("routes", help="the route workbook: one 'Route N' tab per route")
    ap.add_argument(
        "--garage",
        required=True,
        help='where every run starts and ends: "street, town"',
    )
    ap.add_argument("--state", default="OH", help="two-letter state (default OH)")
    ap.add_argument("--garage-label", default="", help="how the sheets name the garage")
    ap.add_argument(
        "--overrides",
        type=Path,
        default=Path("overrides.csv"),
        help="hand fixes (see the example)",
    )
    ap.add_argument(
        "--out", type=Path, default=Path("out"), help="output directory (default out/)"
    )
    args = ap.parse_args(argv)
    street, _, town = args.garage.partition(",")
    if not town.strip():
        ap.error(
            '--garage needs a street and a town, e.g. "123 Main Street, Springfield"'
        )
    cfg = Config(
        street.strip(), town.strip(), args.state, args.garage_label, args.overrides
    )
    return args, cfg


def main(argv=None):
    args, cfg = parse_args(argv)
    p = run(args.routes, args.out, cfg)
    listed = sum(
        b["listed"]["drive"] + b["listed"]["service"] for b in p.before.values()
    )
    zoned = sum(d["drive"] + d["service"] for d in p.zones.values())
    print(
        f"{len(p.stops)} stops, {sum(s.qty for s in p.stops)} flags, {len(p.issues)} issues"
    )
    print(
        f"minutes per run: {listed:.0f} as listed -> {zoned:.0f} in the proposed zones"
    )
    print(f"wrote {args.out}/plan.xlsx and {args.out}/drive/")


if __name__ == "__main__":
    main()
