"""Writes the planning workbook: Read me, Summary, one driver tab per zone, Changes, Data issues and
Volunteers (to fill in)."""

import os
import zipfile
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import plan

BOLD = Font(bold=True)
TITLE = Font(bold=True, size=14)
HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(bold=True, color="FFFFFF")
LEG_FILL = PatternFill("solid", fgColor="D9E1F2")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
LINK = Font(color="0563C1", underline="single", bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")

WORKBOOK_CONTENTS = [
    "Summary: one row per zone, with the comparison against the routes as listed.",
    "Zone 1 to N: the driver sheets. Legs, Google Maps links, stops in order, notes and curb distances.",
    "Changes: houses moved between zones. Veto any of them.",
    "Data issues: duplicates, addresses that needed fixing, approximate map pins, name mix-ups.",
    "Volunteers: to fill in. Each family's home address and the holidays they can do.",
]


def total(d):
    return d["drive"] + d["service"]


def _header(ws, row, names, widths):
    for c, name in enumerate(names, 1):
        cell = ws.cell(row=row, column=c, value=name)
        cell.font, cell.fill = HEAD_FONT, HEAD_FILL
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _fill_row(ws, row, cols):
    for c in range(1, cols + 1):
        ws.cell(row=row, column=c).fill = LEG_FILL


def maps_formula(parts, text):
    """parts: one sheet expression per stop, in order; the last is the destination."""
    return plan.nav_formula(parts[-1], '&"|"&'.join(parts[:-1]) or None, text)


def _stop_notes(s):
    notes = [f"{s.qty} flags"] if s.qty > 1 else []
    notes += [s.notes] if s.notes else []
    if s.geo_source == "osm":
        notes.append("map pin is approximate: check the house number")
    return "; ".join(notes)


def _zone_sheet(wb, z, d, p):
    ws = wb.create_sheet(f"Zone {z}")
    ws["A1"] = f"Zone {z} — {p.owners[z]}"
    ws["A1"].font = TITLE
    ws["A2"] = (
        f"{len(d['stops'])} stops · {sum(s.qty for s in d['stops'])} flags · about {total(d):.0f} min "
        f"from {p.cfg.label} and back"
    )
    ws["A3"] = (
        "Tap a leg's link on your phone: Maps starts navigating from where you are. Then the next leg."
    )
    _header(
        ws,
        5,
        ["Stop", "Name", "Address", "Notes", "Curb distance", "Moved from"],
        [7, 26, 34, 50, 10, 11],
    )
    r = 6
    for n, (a, b) in enumerate(d["legs"], 1):
        leg = d["stops"][a:b]
        _fill_row(ws, r, 6)
        ws.cell(row=r, column=1, value=f"Leg {n}").font = BOLD
        parts = [
            f'"{plan.nav_target(s, p.cfg.state)}"'
            if s.pinned
            else f'C{r + 1 + k}&", {p.cfg.state}"'
            for k, s in enumerate(leg)
        ]
        ws.cell(
            row=r, column=2, value=maps_formula(parts, f"Open leg {n} in Google Maps")
        ).font = LINK
        ws.cell(row=r, column=3, value=f"stops {a + 1}–{b}")
        r += 1
        for k, s in enumerate(leg, a + 1):
            row = [
                k,
                s.name,
                s.full_address,
                _stop_notes(s),
                s.curb or None,
                f"Route {s.route}" if s.route != z else None,
            ]
            for c, v in enumerate(row, 1):
                ws.cell(row=r, column=c, value=v)
            r += 1
    _fill_row(ws, r, 6)
    ws.cell(row=r, column=1, value="End").font = BOLD
    ws.cell(
        row=r,
        column=2,
        value=maps_formula([f'"{p.cfg.garage_address}"'], "Back to the garage"),
    ).font = LINK


def _summary_sheet(ws, p):
    ws["A1"] = "Proposed zones"
    ws["A1"].font = TITLE
    ws["A2"] = (
        "Minutes are estimates for one run (install or removal), garage to garage."
    )
    cols = [
        "Zone",
        "Family",
        "Stops",
        "Flags",
        "Legs",
        "Drive (min)",
        "At stops (min)",
        "Total (min)",
        "As listed (min)",
        "Saved (min)",
        "Moved in",
        "Moved out",
        "Bundles of 5",
    ]
    _header(ws, 4, cols, [6, 16, 7, 7, 6, 10, 11, 10, 13, 11, 10, 10, 11])
    first = 5
    for r, (z, d) in enumerate(p.zones.items(), first):
        b = p.before.get(z, {}).get("listed", {"drive": 0, "service": 0})
        row = [
            z,
            p.owners[z],
            len(d["stops"]),
            sum(s.qty for s in d["stops"]),
            len(d["legs"]),
            round(d["drive"], 1),
            round(d["service"], 1),
            f"=F{r}+G{r}",
            round(total(b), 1),
            f"=I{r}-H{r}",
            sum(1 for s in d["stops"] if s.route != z),
            sum(1 for s in p.stops if s.route == z and s.zone != z),
            f"=ROUNDUP(D{r}/5,0)",
        ]
        for c, v in enumerate(row, 1):
            ws.cell(row=r, column=c, value=v)
    last = first + len(p.zones) - 1
    ws.cell(row=last + 1, column=2, value="All zones").font = BOLD
    for c in range(3, 14):
        col = get_column_letter(c)
        ws.cell(
            row=last + 1, column=c, value=f"=SUM({col}{first}:{col}{last})"
        ).font = BOLD
    ws.cell(row=last + 3, column=2, value="Longest zone (min)")
    ws.cell(row=last + 3, column=3, value=f"=MAX(H{first}:H{last})")
    ws.cell(row=last + 4, column=2, value="Longest route as listed (min)")
    ws.cell(row=last + 4, column=3, value=f"=MAX(I{first}:I{last})")


def _table_sheet(wb, title, intro, head, widths, rows):
    ws = wb.create_sheet(title)
    ws["A1"] = title
    ws["A1"].font = TITLE
    ws["A2"] = intro
    _header(ws, 4, head, widths)
    for r, row in enumerate(rows, 5):
        for c, v in enumerate(row, 1):
            ws.cell(row=r, column=c, value=v).alignment = WRAP
    return ws


def issue_rows(issues):
    return [
        [
            kind,
            s.route if s else None,
            s.row if s else None,
            s.name if s else None,
            s.raw_address if s else None,
            detail,
        ]
        for kind, s, detail in sorted(
            issues, key=lambda x: (x[0], x[1].route if x[1] else 0)
        )
    ]


def moved_rows(p):
    moved = sorted(
        (s for s in p.stops if s.zone != s.route),
        key=lambda s: (s.route, s.zone, s.street),
    )
    return [
        [
            s.name,
            s.full_address,
            f"{s.route} ({p.owners.get(s.route, '')})",
            f"{s.zone} ({p.owners[s.zone]})",
        ]
        for s in moved
    ]


def _volunteers_sheet(wb, p):
    families = {}
    for z, name in p.owners.items():
        families.setdefault(name, []).append(str(z))
    rows = [[name, ", ".join(routes)] for name, routes in sorted(families.items())]
    ws = _table_sheet(
        wb,
        "Volunteers",
        "Yellow cells are inputs: each family's home address and the holidays they can do.",
        [
            "Family",
            "Routes",
            "Home address",
            "Holiday 1",
            "Holiday 2",
            "Holiday 3",
            "Holiday 4",
            "Holiday 5",
            "Max flags per run",
        ],
        [16, 10, 34, 10, 10, 10, 10, 10, 12],
        rows,
    )
    for r in range(5, 5 + len(rows)):
        for c in range(3, 10):
            ws.cell(row=r, column=c).fill = INPUT_FILL


def readme_lines(p, contents):
    """The Read me text as (text, kind) pairs; kind is "title", "head" or None."""
    listed = sum(total(b["listed"]) for b in p.before.values())
    reordered = sum(total(b["reordered"]) for b in p.before.values())
    zoned = sum(total(d) for d in p.zones.values())
    moved = sum(1 for s in p.stops if s.zone != s.route)
    return [
        ("Flag route plan", "title"),
        (
            f"Built {date.today():%B %-d, %Y} from {p.src}. The source workbook is not changed.",
            None,
        ),
        ("What this is", "head"),
        (
            "The orders, cleaned up, put on a map, rebalanced into zones and put in driving order. Every run starts "
            "and ends at the garage. Each zone is cut into legs short enough for one Google Maps link.",
            None,
        ),
        ("Headline numbers (estimates for one run, install or removal)", "head"),
        (
            f"Routes as listed: {listed:.0f} min in all. The same routes in the best order: {reordered:.0f} min. "
            f"Proposed zones: {zoned:.0f} min.",
            None,
        ),
        (
            f"Longest route as listed: {max(total(b['listed']) for b in p.before.values()):.0f} min. "
            f"Longest proposed zone: {max(total(d) for d in p.zones.values()):.0f} min.",
            None,
        ),
        ("Contents", "head"),
        *[(line, None) for line in contents],
        ("How it works", "head"),
        ("1. Reads each Route tab, tidies the addresses and merges duplicates.", None),
        (
            "2. Finds each address with the US Census geocoder, or OpenStreetMap if that fails. Hand fixes and "
            "pins come from the overrides file.",
            None,
        ),
        (
            "3. Gets real drive times between every pair of stops from OSRM (OpenStreetMap road data).",
            None,
        ),
        (
            "4. Starts from the routes as listed and moves a house, or a cluster of nearby houses, to a "
            "neighbouring zone only when that evens out the work and cuts total driving. Each move costs a "
            "penalty, so families keep the streets they know.",
            None,
        ),
        (
            f"5. Orders each zone garage to garage, then cuts it into legs of {plan.MIN_LEG_STOPS} to "
            f"{plan.MAX_LEG_STOPS} stops at the longest drives.",
            None,
        ),
        ("Assumptions", "head"),
        (
            f"Start and finish: {p.cfg.label}. Time at each stop: {plan.SERVICE_MIN * 60:.0f} seconds, plus "
            f"{plan.EXTRA_FLAG_MIN * 60:.0f} seconds for each extra flag. Check the estimates against your own "
            "timed runs before promising times.",
            None,
        ),
        ("Things to check", "head"),
        (
            f"{moved} houses moved to another zone (see the changes list). A route may run somewhere on purpose, "
            "for example so a family finishes near home. Put any such house back.",
            None,
        ),
        (
            f"{len(p.issues)} data issues are listed. Fix the source list or the overrides file, then run again.",
            None,
        ),
    ]


def _readme_sheet(ws, p):
    ws.column_dimensions["A"].width = 110
    style = {"title": TITLE, "head": BOLD, None: None}
    for r, (text, kind) in enumerate(readme_lines(p, WORKBOOK_CONTENTS), 1):
        c = ws.cell(row=r, column=1, value=text)
        c.alignment = WRAP
        if style[kind]:
            c.font = style[kind]


def _recompress(path):
    """openpyxl's default deflate level leaves bytes on the table."""
    tmp = f"{path}.tmp"
    with (
        zipfile.ZipFile(path) as zin,
        zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout,
    ):
        for item in zin.infolist():
            zout.writestr(item.filename, zin.read(item.filename))
    os.replace(tmp, path)


def write_workbook(out, p):
    wb = Workbook()
    _readme_sheet(wb.active, p)
    wb.active.title = "Read me"
    _summary_sheet(wb.create_sheet("Summary"), p)
    for z, d in p.zones.items():
        _zone_sheet(wb, z, d, p)
    _table_sheet(
        wb,
        "Changes",
        "Houses the planner moved to a different zone. Veto any by putting it back.",
        ["Name", "Address", "Route as listed", "Proposed zone"],
        [26, 34, 16, 16],
        moved_rows(p),
    )
    _table_sheet(
        wb,
        "Data issues",
        f"{p.raw_count} rows read from {p.src}; {len(p.stops)} stops planned.",
        ["Issue", "Route", "Source row", "Name", "Address as written", "Detail"],
        [26, 8, 10, 26, 34, 60],
        issue_rows(p.issues),
    )
    _volunteers_sheet(wb, p)
    wb.save(out)
    _recompress(out)
