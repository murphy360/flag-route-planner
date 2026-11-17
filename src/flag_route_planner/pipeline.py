"""The whole run: read, clean, locate, zone, order, cut into legs, write."""

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import plan
from .drive import export
from .geo import geocode, osrm_matrix
from .parse import NO_HOUSE_NUMBER, NO_SUFFIX, read_route_owners, read_routes
from .workbook import write_workbook


@dataclass
class Config:
    garage_street: str  # where every run starts and ends, e.g. "123 Main Street"
    garage_city: str  # also the town for any address that names none
    state: str = "OH"  # two-letter state for the geocoder and the map links
    garage_label: str = ""  # how the sheets name the garage; defaults to its address
    overrides: Path | None = None  # hand fixes, see overrides.example.csv

    @property
    def garage_address(self):
        return f"{self.garage_street}, {self.garage_city}, {self.state}"

    @property
    def label(self):
        return self.garage_label or self.garage_address


@dataclass
class Plan:
    """Everything the writers need."""

    src: str
    zones: dict
    before: dict
    stops: list
    issues: list
    raw_count: int
    owners: dict
    cfg: Config


def load_overrides(path):
    if not path or not Path(path).exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _matches(rule, stop):
    if int(rule["route"]) != stop.route:
        return False
    if (
        rule.get("name_contains")
        and rule["name_contains"].lower() not in stop.name.lower()
    ):
        return False
    return not (
        rule.get("address_contains")
        and rule["address_contains"].lower() not in stop.raw_address.lower()
    )


def apply_overrides(stops, rules):
    """Each rule matches by route plus part of the name and/or the address as written, and sets a new
    street and town, fixed coordinates, or both. Its note goes on the Data issues list."""
    for s in stops:
        for rule in (r for r in rules if _matches(r, s)):
            if rule.get("street"):
                s.street, s.city = rule["street"], rule.get("city") or s.city
                s.issues = [
                    i for i in s.issues if i not in (NO_SUFFIX, NO_HOUSE_NUMBER)
                ]
            if rule.get("lat"):
                s.lat, s.lon, s.pinned, s.geo_source = (
                    float(rule["lat"]),
                    float(rule["lon"]),
                    True,
                    "pinned",
                )
            s.issues.append(rule.get("note") or "manual fix")


def find_duplicates(stops):
    """The same house twice under the same name is merged; the same house under different names is
    kept and flagged. Returns (stops kept, issues)."""
    by_key = defaultdict(list)
    for s in stops:
        by_key[s.key].append(s)
    keep, issues = [], []
    for s in stops:
        group = by_key[s.key]
        first_same = next(
            g for g in group if plan.norm_name(g.name) == plan.norm_name(s.name)
        )
        if first_same is not s:
            issues.append(
                (
                    "Duplicate removed",
                    s,
                    f"listed again on Route {first_same.route} row {first_same.row}",
                )
            )
            continue
        others = [g for g in group if plan.norm_name(g.name) != plan.norm_name(s.name)]
        if others:
            names = "; ".join(f"{g.name} (Route {g.route})" for g in others)
            issues.append(("Same address, different names", s, f"also {names}"))
        keep.append(s)
    return keep, issues


def route_owners(src):
    """Family per route: the route tab's title wins over the Route Summary tab; mismatches are issues."""
    owners, issues = {}, []
    for r, o in read_route_owners(src).items():
        tab, summ = o.get("tab", ""), o.get("summary", "")
        owners[r] = tab if tab and tab.upper() != "OPEN" else (summ or "open")
        if summ and tab and summ != tab:
            detail = f"Route {r}: Route Summary tab says {summ}, the route tab says {tab}; using {owners[r]}"
            issues.append(("Route owner mix-up", None, detail))
    return owners, issues


def _locate(stops, cfg, issues):
    """Geocodes every stop that has no pinned coordinates; drops (and reports) any it cannot find."""
    garage = (cfg.garage_street, cfg.garage_city)
    found = geocode(
        [(s.street, s.city) for s in stops if not s.pinned] + [garage],
        cfg.state,
        cfg.garage_city,
    )
    g = found[f"{garage[0]}|{garage[1]}"]
    if not g:
        raise SystemExit(f"Cannot find the garage address: {cfg.garage_address}")
    located = []
    for s in stops:
        if not s.pinned:
            hit = found[f"{s.street}|{s.city}"]
            if not hit:
                issues.append(
                    (
                        "Address not found",
                        s,
                        "left off the plan; fix it in the overrides file",
                    )
                )
                continue
            s.lat, s.lon, s.geo_source = hit["lat"], hit["lon"], hit["source"]
            if (
                hit["source"] == "osm"
                and not hit["matched"].split(",")[0].strip().isdigit()
            ):
                issues.append(
                    (
                        "Street only",
                        s,
                        "no house-level match; the pin is somewhere on the street",
                    )
                )
        located.append(s)
    return (g["lat"], g["lon"]), located


def _note_issues(stops, issues):
    for s in stops:
        for note in s.issues:
            kind = (
                "Address format"
                if note in (NO_SUFFIX, NO_HOUSE_NUMBER)
                else "Manual fix"
            )
            issues.append((kind, s, note))


def _summarise(nodes, M, stops):
    hops = [M[a][b] for a, b in zip([0, *nodes], [*nodes, 0], strict=True)]
    return {
        "nodes": nodes,
        "hops": hops,
        "drive": sum(hops),
        "service": sum(plan.service_min(stops[n - 1]) for n in nodes),
    }


def build_plan(src, cfg):
    stops = read_routes(src, cfg.garage_city)
    n_routes = max(s.route for s in stops)
    apply_overrides(stops, load_overrides(cfg.overrides))
    raw_count = len(stops)
    stops, issues = find_duplicates(stops)
    owners, owner_issues = route_owners(src)
    issues += owner_issues
    depot, located = _locate(stops, cfg, issues)
    _note_issues(located, issues)

    M = osrm_matrix([depot] + [(s.lat, s.lon) for s in located])
    S = plan.symmetric(M)
    before = {}
    for r in sorted({s.route for s in located}):
        listed = [i + 1 for i, s in enumerate(located) if s.route == r]
        before[r] = {
            "listed": _summarise(listed, M, located),
            "reordered": _summarise(plan.solve_tour(listed, S), M, located),
        }

    zone_of = plan.rebalance(located, S, n_routes)
    for s, z in zip(located, zone_of, strict=True):
        s.zone = z
    zones = {}
    for z in range(1, n_routes + 1):
        d = _summarise(
            plan.solve_tour([i + 1 for i, zz in enumerate(zone_of) if zz == z], S),
            M,
            located,
        )
        d["stops"] = [located[n - 1] for n in d["nodes"]]
        d["legs"] = plan.split_legs(len(d["stops"]), d["hops"][1:-1])
        zones[z] = d
    owners = {z: owners.get(z, "open") for z in zones}
    return Plan(Path(src).name, zones, before, located, issues, raw_count, owners, cfg)


def run(src, out_dir, cfg):
    p = build_plan(src, cfg)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_workbook(out / "plan.xlsx", p)
    export(out / "drive", p)
    return p
