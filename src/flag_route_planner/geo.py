"""Geocoding (US Census, then OpenStreetMap Nominatim) and drive times (OSRM), cached on disk.

Both services are free public endpoints; the cache keeps a re-run from asking them again.
"""

import csv
import hashlib
import io
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path(
    "cache"
)  # relative to where the planner runs; holds answers, so re-runs stay offline
CENSUS_BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSRM = "https://router.project-osrm.org"
USER_AGENT = "flag-route-planner/0.1 (volunteer route planning)"


def _load(name):
    p = CACHE / name
    return json.loads(p.read_text()) if p.exists() else {}


def _save(name, data):
    CACHE.mkdir(exist_ok=True)
    (CACHE / name).write_text(json.dumps(data, indent=1, sort_keys=True))


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _census_batch(rows, state):
    """rows: [(id, street, city)] -> {id: (lat, lon, matched_address)} for exact or non-exact matches."""
    buf = io.StringIO()
    w = csv.writer(buf)
    for rid, street, city in rows:
        w.writerow([rid, street, city, state, ""])
    boundary = "----flagplanner"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="benchmark"\r\n\r\nPublic_AR_Current\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="addressFile"; filename="a.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n{buf.getvalue()}\r\n--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        CENSUS_BATCH,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        text = r.read().decode()
    out = {}
    for rec in csv.reader(io.StringIO(text)):
        # id, input, Match/No_Match/Tie, Exact/Non_Exact, matched address, "lon,lat", tiger id, side
        if len(rec) >= 6 and rec[2] == "Match":
            lon, lat = (float(x) for x in rec[5].split(","))
            out[rec[0]] = (lat, lon, rec[4])
    return out


def _nominatim(street, city, state):
    q = urllib.parse.urlencode(
        {
            "street": street,
            "city": city,
            "state": state,
            "country": "USA",
            "format": "json",
            "limit": 1,
        }
    )
    time.sleep(1.1)  # Nominatim's usage policy: at most one request a second
    res = json.loads(_get(f"{NOMINATIM}?{q}"))
    if res:
        return float(res[0]["lat"]), float(res[0]["lon"]), res[0]["display_name"]
    return None


def _lookup(street, city, state, default_city, census_hit):
    """Census first; then OpenStreetMap, in the given town and then in the default town."""
    if census_hit:
        return {
            "lat": census_hit[0],
            "lon": census_hit[1],
            "matched": census_hit[2],
            "source": "census",
        }
    for town in dict.fromkeys([city, default_city]):
        hit = _nominatim(street, town, state)
        if hit:
            return {"lat": hit[0], "lon": hit[1], "matched": hit[2], "source": "osm"}
    return None


def geocode(addresses, state, default_city):
    """addresses: [(street, city)] -> {"street|city": {"lat", "lon", "matched", "source"} or None}."""
    cache = _load("geocode.json")
    todo = [(s, c) for s, c in dict.fromkeys(addresses) if f"{s}|{c}" not in cache]
    if todo:
        found = _census_batch([(str(i), s, c) for i, (s, c) in enumerate(todo)], state)
        for i, (s, c) in enumerate(todo):
            cache[f"{s}|{c}"] = _lookup(s, c, state, default_city, found.get(str(i)))
        _save("geocode.json", cache)
    return {f"{s}|{c}": cache[f"{s}|{c}"] for s, c in addresses}


def haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 12742 * math.asin(math.sqrt(h))


def osrm_matrix(points, block=50):
    """Full drive-time matrix in minutes, fetched in blocks (the public server takes ~100
    coordinates per request) and cached as a whole."""
    key = hashlib.sha1(
        ";".join(f"{a:.6f},{b:.6f}" for a, b in points).encode()
    ).hexdigest()
    path = CACHE / f"matrix_{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    n = len(points)
    m = [[0.0] * n for _ in range(n)]
    for si in range(0, n, block):
        for di in range(0, n, block):
            src = list(range(si, min(si + block, n)))
            dst = list(range(di, min(di + block, n)))
            both = src + [d for d in dst if d not in src]
            coords = ";".join(f"{points[i][1]:.6f},{points[i][0]:.6f}" for i in both)
            q = (
                f"?annotations=duration&sources={';'.join(str(k) for k in range(len(src)))}"
                f"&destinations={';'.join(str(both.index(d)) for d in dst)}"
            )
            res = json.loads(_get(f"{OSRM}/table/v1/driving/{coords}{q}"))
            if res.get("code") != "Ok":
                raise RuntimeError(
                    f"OSRM table: {res.get('code')} {res.get('message')}"
                )
            for a, row in zip(src, res["durations"], strict=True):
                for b, d in zip(dst, row, strict=True):
                    m[a][b] = d / 60
            time.sleep(1)
    CACHE.mkdir(exist_ok=True)
    path.write_text(json.dumps(m))
    return m
