"""Text exports for Google Drive, which converts them on upload: each zones/zone_NN.csv becomes a
Google Sheet and summary.html a Google Doc. map.csv imports into Google My Maps.

They are kept compact on purpose: text uploads are cheap where a binary workbook is not."""

import csv
import html
from pathlib import Path

from . import plan
from .workbook import issue_rows, moved_rows, readme_lines, total

DRIVE_CONTENTS = [
    "Zone routes: one Google Sheet per zone, in driving order. A row per leg with its Google Maps link, then "
    "that leg's stops. Share each family only their own sheet. A blank Town means the garage's town.",
    "This document: the summary table, the houses moved between zones, and the data issues.",
]


def _maps_formula(parts, text):
    return plan.nav_formula(parts[-1], '&"|"&'.join(parts[:-1]) or None, text)


def _addr(first, last, mixed, town, state):
    """Sheet expression for Street + Town (blank Town = the default town) of one row or a range."""
    if last is None:
        if mixed:
            return f'C{first}&", "&IF(D{first}="","{town}",D{first})&", {state}"'
        return f'C{first}&", {town}, {state}"'
    if mixed:
        return f'ARRAYFORMULA(C{first}:C{last}&", "&IF(D{first}:D{last}="","{town}",D{first}:D{last})&", {state}")'
    return f'ARRAYFORMULA(C{first}:C{last}&", {town}, {state}")'


def leg_formula(first, last, towns, town, state, text):
    """Rows first..last-1 are the waypoints, row last the destination."""
    mixed = any(t != town for t in towns)
    wps = (
        f'TEXTJOIN("|",1,{_addr(first, last - 1, mixed, town, state)})'
        if last > first
        else None
    )
    return plan.nav_formula(_addr(last, None, mixed, town, state), wps, text)


def _stop_row(k, s, z, town):
    notes = [f"{s.qty} flags"] if s.qty > 1 else []
    notes += [s.notes] if s.notes else []
    if s.geo_source == "osm":
        notes.append("approx. pin")
    row = [
        k,
        s.name,
        s.street,
        "" if s.city == town else s.city,
        "; ".join(notes),
        s.curb,
        f"Route {s.route}" if s.route != z else "",
    ]
    while row and row[-1] in ("", None):
        row.pop()
    return row


def zone_rows(z, d, owner, cfg):
    """Columns: Stop | Name | Street | Town (blank = the garage's town) | Notes | Curb | Moved from."""
    town, state = cfg.garage_city, cfg.state
    rows = [
        [
            f"Zone {z} — {owner} — {len(d['stops'])} stops, {sum(s.qty for s in d['stops'])} flags, "
            f"about {total(d):.0f} min from {cfg.label} and back"
        ],
        [
            "Tap a leg link on your phone: Maps starts navigating from where you are. Then open the next leg."
        ],
        ["Stop", "Name", "Street", "Town", "Notes", "Curb", "Moved from"],
    ]
    for n, (a, b) in enumerate(d["legs"], 1):
        leg_row = len(rows) + 1  # 1-based sheet row of this leg row
        leg = d["stops"][a:b]
        text = f"LEG {n}: open in Google Maps"
        if any(s.pinned for s in leg):
            parts = [
                f'"{plan.nav_target(s, state)}"'
                if s.pinned
                else _addr(leg_row + 1 + k, None, True, town, state)
                for k, s in enumerate(leg)
            ]
            link = _maps_formula(parts, text)
        else:
            link = leg_formula(
                leg_row + 1,
                leg_row + len(leg),
                [s.city for s in leg],
                town,
                state,
                text,
            )
        rows.append([f"Leg {n}", link, f"stops {a + 1}–{b}"])
        rows += [_stop_row(k, s, z, town) for k, s in enumerate(leg, a + 1)]
    rows.append(
        ["End", _maps_formula([f'"{cfg.garage_address}"'], "Back to the garage")]
    )
    return rows


def _table(head, rows):
    out = ["<table border='1' cellpadding='3' style='border-collapse:collapse'><tr>"]
    out += [f"<th>{html.escape(str(h))}</th>" for h in head]
    out.append("</tr>")
    for r in rows:
        out.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(v if v is not None else ''))}</td>" for v in r
            )
            + "</tr>"
        )
    out.append("</table>")
    return "".join(out)


def _summary_rows(p):
    rows = []
    for z, d in p.zones.items():
        b = p.before.get(z, {}).get("listed", {"drive": 0, "service": 0})
        flags = sum(s.qty for s in d["stops"])
        rows.append(
            [
                z,
                p.owners[z],
                len(d["stops"]),
                flags,
                len(d["legs"]),
                f"{total(d):.0f}",
                f"{total(b):.0f}",
                f"{total(b) - total(d):.0f}",
                sum(1 for s in d["stops"] if s.route != z),
                -(-flags // 5),
            ]
        )
    return rows


def summary_html(p):
    parts = ["<html><head><meta charset='utf-8'></head><body>"]
    for text, kind in readme_lines(p, DRIVE_CONTENTS):
        tag = {"title": "h1", "head": "h2"}.get(kind, "p")
        parts.append(f"<{tag}>{html.escape(text)}</{tag}>")
    parts.append("<h2>Summary by zone</h2>")
    parts.append(
        _table(
            [
                "Zone",
                "Family",
                "Stops",
                "Flags",
                "Legs",
                "Total (min)",
                "As listed (min)",
                "Saved (min)",
                "Moved in",
                "Bundles of 5",
            ],
            _summary_rows(p),
        )
    )
    parts.append("<h2>Houses moved to a different zone</h2>")
    parts.append(
        _table(["Name", "Address", "Route as listed", "Proposed zone"], moved_rows(p))
    )
    parts.append(
        f"<h2>Data issues</h2><p>{p.raw_count} rows read from {html.escape(p.src)}; {len(p.stops)} planned.</p>"
    )
    parts.append(
        _table(
            ["Issue", "Route", "Row", "Name", "Address as written", "Detail"],
            issue_rows(p.issues),
        )
    )
    parts.append("</body></html>")
    return "".join(parts)


def _write_csv(path, rows):
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)


def export(outdir, p):
    out = Path(outdir)
    (out / "zones").mkdir(parents=True, exist_ok=True)
    for z, d in p.zones.items():
        _write_csv(
            out / "zones" / f"zone_{z:02d}.csv", zone_rows(z, d, p.owners[z], p.cfg)
        )
    (out / "summary.html").write_text(summary_html(p))
    rows = [
        [
            "Zone",
            "Leg",
            "Stop",
            "Name",
            "Address",
            "Latitude",
            "Longitude",
            "Route as listed",
        ]
    ]
    for z, d in p.zones.items():
        for n, (a, b) in enumerate(d["legs"], 1):
            rows += [
                [
                    f"Zone {z}",
                    n,
                    k + 1,
                    d["stops"][k].name,
                    d["stops"][k].full_address,
                    f"{d['stops'][k].lat:.6f}",
                    f"{d['stops'][k].lon:.6f}",
                    d["stops"][k].route,
                ]
                for k in range(a, b)
            ]
    _write_csv(out / "map.csv", rows)
