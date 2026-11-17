"""Reads a route workbook (one "Route N" tab per route) into a flat list of stops."""

import re
from dataclasses import dataclass, field

from openpyxl import load_workbook

SUFFIXES = {
    "dr": "Drive",
    "drive": "Drive",
    "ln": "Lane",
    "lane": "Lane",
    "rd": "Road",
    "road": "Road",
    "ct": "Court",
    "court": "Court",
    "cir": "Circle",
    "cr": "Circle",
    "circle": "Circle",
    "blvd": "Boulevard",
    "boulevard": "Boulevard",
    "pkwy": "Parkway",
    "parkway": "Parkway",
    "st": "Street",
    "street": "Street",
    "ave": "Avenue",
    "avenue": "Avenue",
    "pl": "Place",
    "place": "Place",
    "wy": "Way",
    "way": "Way",
    "rdg": "Ridge",
    "ridge": "Ridge",
    "trl": "Trail",
    "trail": "Trail",
    "oval": "Oval",
    "run": "Run",
    "cove": "Cove",
    "crossing": "Crossing",
    "view": "View",
}
NO_HOUSE_NUMBER = "no house number"
NO_SUFFIX = "no street suffix"


@dataclass
class Stop:
    route: int  # route number in the source workbook
    row: int  # row in the source tab, for tracing back
    qty: int
    name: str
    raw_address: str
    street: str  # cleaned street address, e.g. "120 Elm Street"
    city: str
    notes: str = ""
    curb: str = ""  # distance-from-curb measurement, where the route records one
    issues: list = field(default_factory=list)
    lat: float = 0.0
    lon: float = 0.0
    pinned: bool = False  # coordinates set by hand in the overrides file
    geo_source: str = ""  # census, osm or pinned
    zone: int = 0

    @property
    def key(self):
        """Normalised address, for spotting the same house twice."""
        return f"{self.street.lower()}|{self.city.lower()}"

    @property
    def full_address(self):
        return f"{self.street}, {self.city}"


def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def dedupe_repeat(s):
    """'12 Oak Ct 12 Oak Ct' -> '12 Oak Ct' (a cell pasted twice)."""
    words = s.split()
    n = len(words)
    if n % 2 == 0 and words[: n // 2] == words[n // 2 :]:
        return " ".join(words[: n // 2])
    return s


def _city(rest, default_city):
    """The town from the text after the street: drops county notes, state, zip and stray letters."""
    rest = re.sub(r"\(.*?\)", "", rest.split(",")[0])
    words = [w for w in rest.split() if len(w) > 1 and not w.isdigit()]
    words = [w for w in words if w.lower() != "township"]
    return " ".join(w.capitalize() for w in words) or default_city


def _street_words(rest):
    words = rest.split()
    issues = []
    if words and words[-1].lower() in SUFFIXES:
        words[-1] = SUFFIXES[words[-1].lower()]
    elif words and words[-1] not in SUFFIXES.values():
        issues.append(NO_SUFFIX)
    words = [w if w.isupper() and len(w) <= 2 else w.capitalize() for w in words]
    words = [re.sub(r"^Mc(\w)", lambda m: "Mc" + m.group(1).upper(), w) for w in words]
    return " ".join(words).replace("Saint ", "St "), issues


def clean_address(raw, default_city):
    """Splits a free-text address cell into (street, city, issues)."""
    s = dedupe_repeat(_text(raw))
    street, _, rest = s.partition(",")
    city = _city(rest, default_city) if rest else default_city
    street = re.sub(r"\b(N/A|Address 2)\b.*$", "", street, flags=re.I)
    street = re.sub(r"\(.*?\)", "", street).replace(".", " ")
    street = re.sub(r"\s+", " ", street).strip()
    m = re.match(r"^(\d+)\s+(.*)$", street)
    if not m:
        return street.title(), city, [NO_HOUSE_NUMBER]
    number, rest_of_street = m.groups()
    words, issues = _street_words(rest_of_street)
    return f"{number} {words}", city, issues


def _header(ws):
    """Finds the 'Qty | Recipient Name | Address' header row and maps column names to indexes."""
    for r in range(1, 10):
        vals = [_text(c.value).lower() for c in ws[r]]
        if "qty" in vals and "address" in vals:
            cols = {}
            for i, v in enumerate(vals):
                if v in ("qty", "address", "notes"):
                    cols[v] = i
                elif "name" in v:
                    cols["name"] = i
                elif "curb" in v:
                    cols["curb"] = i
            return r, cols
    raise ValueError(f"{ws.title}: no Qty/Address header")


def _cell(row, cols, key):
    i = cols.get(key)
    return _text(row[i]) if i is not None and i < len(row) else ""


def _strip_leg_link(notes):
    """A volunteer's own leg marker ('Route 2: https://...') is dropped: the planner makes its own."""
    return re.sub(r"^Route \d+:\s*\S+\s*", "", notes)


def _read_tab(ws, route, default_city):
    hdr, cols = _header(ws)
    stops = []
    for offset, row in enumerate(ws.iter_rows(min_row=hdr + 1, values_only=True)):
        qty, name, addr = (_cell(row, cols, k) for k in ("qty", "name", "address"))
        if qty.lower() == "qty" or "total" in (qty + name + addr).lower():
            break  # a second copy of the list, or the totals line, ends the route
        if not addr or not qty:
            continue  # blank rows and "moved to another route" rows
        street, city, issues = clean_address(addr, default_city)
        stops.append(
            Stop(
                route=route,
                row=hdr + 1 + offset,
                qty=int(float(qty)) if qty.replace(".", "").isdigit() else 1,
                name=dedupe_repeat(name),
                raw_address=addr,
                street=street,
                city=city,
                notes=_strip_leg_link(_cell(row, cols, "notes")),
                curb=_cell(row, cols, "curb"),
                issues=issues,
            )
        )
    return stops


def read_routes(path, default_city):
    wb = load_workbook(path, read_only=True, data_only=True)
    stops = []
    for ws in wb.worksheets:
        m = re.fullmatch(r"Route (\d+)", ws.title.strip())
        if m:
            stops += _read_tab(ws, int(m.group(1)), default_city)
    fill_missing_suffixes(stops)
    return stops


def fill_missing_suffixes(stops):
    """'40 Maple' -> '40 Maple Lane' when every other house on that street agrees."""
    known = {}
    for s in stops:
        if NO_SUFFIX not in s.issues:
            _, _, rest = s.street.partition(" ")
            name, _, suffix = rest.rpartition(" ")
            if name:
                known.setdefault((name.lower(), s.city), set()).add(suffix)
    for s in stops:
        if NO_SUFFIX in s.issues:
            num, _, rest = s.street.partition(" ")
            suffixes = known.get((rest.lower(), s.city), set())
            if len(suffixes) == 1:
                s.street = f"{num} {rest} {suffixes.pop()}"
                s.issues.remove(NO_SUFFIX)
                s.issues.append(
                    "street suffix taken from neighbours on the same street"
                )


def read_route_owners(path):
    """{route: {"summary": family on the Route Summary tab, "tab": name in the route tab's title}}."""
    wb = load_workbook(path, read_only=True, data_only=True)
    owners = {}
    if "Route Summary" in wb.sheetnames:
        for row in wb["Route Summary"].iter_rows(values_only=True):
            m = re.fullmatch(r"Route (\d+)", _text(row[0])) if row else None
            if m and len(row) > 1:
                owners.setdefault(int(m.group(1)), {})["summary"] = _text(row[1])
    for ws in wb.worksheets:
        m = re.fullmatch(r"Route (\d+)", ws.title.strip())
        if m:
            first = next(ws.iter_rows(max_row=1, values_only=True), ())
            title = _text(first[0]) if first else ""
            parts = re.split(r"\s[—-]\s*", title, maxsplit=1)
            # Only the family name: drop any "Updated Order" note and trailing numbers.
            tab = parts[1] if len(parts) > 1 else ""
            tab = re.sub(r"\s*-\s*Updated Order.*$|\s+\d+$", "", tab).strip()
            owners.setdefault(int(m.group(1)), {})["tab"] = tab
    return owners
