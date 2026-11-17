"""Made-up route workbooks and a fake map, so the tests need no network and hold no real data."""

import math

import pytest
from openpyxl import Workbook

from flag_route_planner import geo, pipeline

# A made-up town on a grid: house n on a street sits at (lat, lon) offsets below.
TOWN = "Springfield"
GARAGE = (40.0, -80.0)


def make_workbook(path, routes, summary=None):
    """routes: {route: (family, [(qty, name, address, notes), ...])}."""
    wb = Workbook()
    wb.remove(wb.active)
    if summary:
        ws = wb.create_sheet("Route Summary")
        ws.append(["Route", "Description"])
        for r, fam in summary.items():
            ws.append([f"Route {r}", fam])
    for r, (family, rows) in routes.items():
        ws = wb.create_sheet(f"Route {r}")
        ws.append([f"Route {r} — {family}"])
        ws.append(["Qty", "Recipient Name", "Address", "Notes"])
        for row in rows:
            ws.append(list(row))
        ws.append([None, "Total", None, None])
    wb.save(path)
    return path


def fake_point(street):
    """Houses on 'N Elm Street' line up east of the garage, 'N Oak Street' north of it."""
    number = int(street.split()[0])
    step = number / 1000
    if "Oak" in street:
        return GARAGE[0] + step, GARAGE[1]
    return GARAGE[0], GARAGE[1] + step


@pytest.fixture
def offline(monkeypatch):
    """Geocoding from fake_point and drive minutes from straight-line distance."""

    def fake_geocode(addresses, state, default_city):
        out = {}
        for street, city in addresses:
            if street.split()[0].isdigit():
                lat, lon = fake_point(street)
                out[f"{street}|{city}"] = {
                    "lat": lat,
                    "lon": lon,
                    "matched": street,
                    "source": "census",
                }
            else:
                out[f"{street}|{city}"] = None
        return out

    def fake_matrix(points):
        return [[geo.haversine_km(a, b) * 2 for b in points] for a in points]

    monkeypatch.setattr(pipeline, "geocode", fake_geocode)
    monkeypatch.setattr(pipeline, "osrm_matrix", fake_matrix)


def grid_matrix(points):
    return [[math.dist(a, b) for b in points] for a in points]
