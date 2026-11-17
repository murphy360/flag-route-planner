"""Zones and stop order: rebalance the routes, order each one from the garage and back, and cut it
into legs short enough for one Google Maps link each.

Everything works on one drive-time matrix (minutes) over "nodes": node 0 is the garage and node
i+1 is stop i.
"""

import math
import re
from urllib.parse import quote

from .geo import haversine_km

SERVICE_MIN = (
    0.6  # minutes out of the car per stop (find the anchor, place or pull the flag)
)
EXTRA_FLAG_MIN = 0.3  # each extra flag at the same stop
BALANCE_WEIGHT = (
    0.05  # cost per (minute over or under the average)^2: pulls zones toward even work
)
MOVE_PENALTY_MIN = (
    3.0  # cost of moving a house off its old route: families keep streets they know
)
NEIGHBOUR_KM = (
    4.0  # a house may only move to a zone that already has a house this close
)
LINK_KMS = (
    0.5,
    1.5,
)  # houses this close chain into a cluster that can move as one (each size tried)
MAX_CLUSTER = 12  # largest cluster tried as a single move
MAX_LEG_STOPS = (
    8  # stops per Google Maps link (the app takes up to 9 stops plus the destination)
)
MIN_LEG_STOPS = 3  # no one- or two-stop legs
LEG_BREAK_MIN = (
    4.0  # how much a long drive between stops is worth as a place to start a new leg
)
NAV_URL = (
    "https://www.google.com/maps/dir/?api=1&travelmode=driving&dir_action=navigate"
)
EPS = 1e-9


def service_min(stop):
    return SERVICE_MIN + EXTRA_FLAG_MIN * (stop.qty - 1)


def symmetric(m):
    n = len(m)
    return [[(m[a][b] + m[b][a]) / 2 for b in range(n)] for a in range(n)]


def tour_minutes(nodes, m):
    """Garage -> nodes in order -> garage, on matrix m."""
    seq = [0, *nodes, 0]
    return sum(m[a][b] for a, b in zip(seq, seq[1:], strict=False))


# ---------------------------------------------------------------- one zone's order
def _nearest_neighbour(nodes, S):
    left, tour, cur = set(nodes), [0], 0
    while left:
        cur = min(left, key=lambda j: S[cur][j])
        tour.append(cur)
        left.remove(cur)
    return [*tour, 0]


def _two_opt(tour, S):
    """Reverses a stretch of the tour wherever that shortens it. Returns True if anything changed."""
    changed = False
    m = len(tour)
    for i in range(1, m - 2):
        for j in range(i + 1, m - 1):
            a, b, c, d = tour[i - 1], tour[i], tour[j], tour[j + 1]
            if S[a][c] + S[b][d] < S[a][b] + S[c][d] - EPS:
                tour[i : j + 1] = tour[i : j + 1][::-1]
                changed = True
    return changed


def _best_insertion(rest, run, saving, S):
    best = None
    for k in range(len(rest) - 1):
        a, b = rest[k], rest[k + 1]
        for r in (run, run[::-1]):
            add = S[a][r[0]] + S[r[-1]][b] - S[a][b]
            if add < saving - EPS and (best is None or add < best[0]):
                best = (add, k, r)
    return best


def _or_opt(tour, S):
    """Moves a run of 1-3 stops to a better place. Returns (tour, changed)."""
    changed = False
    for seg in (1, 2, 3):
        i = 1
        while i + seg < len(tour):
            run = tour[i : i + seg]
            p, q = tour[i - 1], tour[i + seg]
            rest = tour[:i] + tour[i + seg :]
            best = _best_insertion(rest, run, S[p][run[0]] + S[run[-1]][q] - S[p][q], S)
            if best:
                _, k, r = best
                tour = rest[: k + 1] + r + rest[k + 1 :]
                changed = True
            i += 1
    return tour, changed


def solve_tour(nodes, S):
    """Nearest neighbour, then 2-opt and or-opt until nothing improves. Returns nodes in order."""
    if len(nodes) <= 2:
        return list(nodes)
    tour = _nearest_neighbour(nodes, S)
    changed = True
    while changed:
        changed = _two_opt(tour, S)
        tour, moved = _or_opt(tour, S)
        changed = changed or moved
    return tour[1:-1]


# ---------------------------------------------------------------- zoning
def clusters(members, stops, link_km):
    """Single-linkage groups of a zone's stops (stops within link_km of each other chain together)."""
    left, groups = set(members), []
    while left:
        group = [left.pop()]
        frontier = list(group)
        while frontier:
            cur = frontier.pop()
            here = (stops[cur].lat, stops[cur].lon)
            near = [
                j
                for j in left
                if haversine_km(here, (stops[j].lat, stops[j].lon)) <= link_km
            ]
            for j in near:
                left.remove(j)
            group += near
            frontier += near
        groups.append(group)
    return groups


class _Rebalancer:
    """Local search over zone assignments: moves a house, or a cluster of nearby houses, to a
    neighbouring zone while that lowers total minutes + imbalance + a penalty per moved house."""

    def __init__(self, stops, S, n_zones):
        self.stops, self.S = stops, S
        self.zone = [s.route for s in stops]
        self.tours = {
            z: solve_tour([i + 1 for i, zz in enumerate(self.zone) if zz == z], S)
            for z in range(1, n_zones + 1)
        }
        self.serv = [service_min(s) for s in stops]
        self.near = [self._neighbours(i) for i in range(len(stops))]
        self.times = {z: self.zone_time(t) for z, t in self.tours.items()}

    def _neighbours(self, i):
        here = (self.stops[i].lat, self.stops[i].lon)
        return [
            j
            for j, s in enumerate(self.stops)
            if j != i and haversine_km(here, (s.lat, s.lon)) <= NEIGHBOUR_KM
        ]

    def zone_time(self, order):
        return tour_minutes(order, self.S) + sum(self.serv[n - 1] for n in order)

    def cost(self, times, assign):
        mean = sum(times.values()) / len(times)
        imbalance = BALANCE_WEIGHT * sum((t - mean) ** 2 for t in times.values())
        moved = MOVE_PENALTY_MIN * sum(
            z != s.route for z, s in zip(assign, self.stops, strict=True)
        )
        return sum(times.values()) + imbalance + moved

    def insert(self, order, node):
        S, seq = self.S, [0, *order, 0]
        k = min(
            range(len(seq) - 1),
            key=lambda k: S[seq[k]][node] + S[node][seq[k + 1]] - S[seq[k]][seq[k + 1]],
        )
        return order[:k] + [node] + order[k:]

    def units(self):
        out = [[i] for i in range(len(self.stops))]
        for tour in self.tours.values():
            for link in LINK_KMS:
                out += [
                    g
                    for g in clusters([n - 1 for n in tour], self.stops, link)
                    if 1 < len(g) <= MAX_CLUSTER
                ]
        return out

    def _try_unit(self, unit):
        src = self.zone[unit[0]]
        if (
            any(self.zone[i] != src for i in unit)
            or len(self.tours[src]) - len(unit) < 3
        ):
            return False
        nodes = {i + 1 for i in unit}
        src_order = [n for n in self.tours[src] if n not in nodes]
        src_time = self.zone_time(src_order)
        base = self.cost(self.times, self.zone)
        best = None
        for dst in {self.zone[j] for i in unit for j in self.near[i]} - {src}:
            dst_order = self.tours[dst]
            for n in sorted(nodes):
                dst_order = self.insert(dst_order, n)
            if len(unit) > 1:
                dst_order = solve_tour(dst_order, self.S)
            times = {**self.times, src: src_time, dst: self.zone_time(dst_order)}
            trial = [dst if k in unit else zz for k, zz in enumerate(self.zone)]
            c = self.cost(times, trial)
            if c < base - 0.05 and (best is None or c < best[0]):
                best = (c, dst, dst_order, times)
        if not best:
            return False
        _, dst, self.tours[dst], self.times = best
        self.tours[src] = src_order
        for i in unit:
            self.zone[i] = dst
        return True

    def run(self, passes=40):
        for _ in range(passes):
            moved = sum(self._try_unit(u) for u in self.units())
            self.tours = {z: solve_tour(t, self.S) for z, t in self.tours.items()}
            self.times = {z: self.zone_time(t) for z, t in self.tours.items()}
            if not moved:
                break
        return self.zone


def rebalance(stops, S, n_zones):
    """Returns the zone number for each stop, starting from each stop's old route."""
    return _Rebalancer(stops, S, n_zones).run()


# ---------------------------------------------------------------- legs and links
def _leg_table(n, gaps, max_legs):
    """best[(k, j)]: (sum of gaps cut, previous cut) covering the first k stops with j legs."""
    best = {(0, 0): (0.0, None)}
    smallest = min(MIN_LEG_STOPS, n)
    for k in range(1, n + 1):
        for j in range(1, max_legs + 1):
            for size in range(smallest, MAX_LEG_STOPS + 1):
                prev = best.get((k - size, j - 1))
                if prev is None:
                    continue
                score = prev[0] + (gaps[k - 1] if k < n else 0.0)
                if (k, j) not in best or score > best[(k, j)][0]:
                    best[(k, j)] = (score, k - size)
    return best


def split_legs(n, gaps):
    """Cuts n ordered stops into legs of MIN_LEG_STOPS to MAX_LEG_STOPS, as few as possible (one more
    only if it buys a long natural break), cutting at the longest drives.
    gaps[k] = minutes from stop k to stop k+1. Returns [(start, end)] slices."""
    min_legs = math.ceil(n / MAX_LEG_STOPS)
    best = _leg_table(n, gaps, min_legs + 1)
    options = [
        (best[(n, j)][0] - LEG_BREAK_MIN * j, j)
        for j in (min_legs, min_legs + 1)
        if (n, j) in best
    ]
    _, legs = max(options)
    cuts, k = [], n
    for j in range(legs, 0, -1):
        start = best[(k, j)][1]
        cuts.append((start, k))
        k = start
    return cuts[::-1]


def nav_target(stop, state):
    if stop.pinned:
        return f"{stop.lat:.6f},{stop.lon:.6f}"
    return f"{stop.full_address}, {state}"


def maps_link(targets):
    """A plain Google Maps navigation URL through the targets in order, from the phone's location."""
    url = NAV_URL + "&destination=" + quote(targets[-1])
    if len(targets) > 1:
        url += "&waypoints=" + quote("|".join(targets[:-1]))
    return url


def nav_formula(dest, waypoints, text):
    """Sheet HYPERLINK to Google Maps turn-by-turn navigation. dest and waypoints are sheet
    expressions (waypoints already joined with "|", or None). With no origin and dir_action=navigate,
    Maps starts from the phone's own location and goes straight into navigation."""
    url = f'"{NAV_URL}&destination="&ENCODEURL({dest})'
    if waypoints:
        url += f'&"&waypoints="&ENCODEURL({waypoints})'
    return f'=HYPERLINK({url},"{text}")'


def norm_name(name):
    return re.sub(r"\(.*?\)|[^a-z]", "", name.lower())
