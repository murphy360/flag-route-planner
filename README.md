# flag-route-planner

Plans the routes for a community flag program, where volunteers put flags out at subscribers' homes on each
holiday and take them down again. It reads the route workbook the volunteers already keep and produces:

- **Zones.** The routes rebalanced so each family's run takes about the same time. Houses only move between
  neighbouring zones, and only when that clearly helps, so families keep the streets they know.
- **Driving order.** Each zone ordered from the garage and back, on real drive times.
- **Legs.** Each zone cut into stretches of three to eight stops, each with one Google Maps link. Tap it on a
  phone and Maps starts turn-by-turn navigation from where you are, through every stop of the leg.
- **A data-issues list.** Duplicates, addresses that could not be found, map pins that are only approximate, and
  route owners that disagree between tabs.

## What it needs

A workbook (`.xlsx`) with one tab per route named `Route 1`, `Route 2` and so on. Each tab has:

- a title in the first cell, `Route N — Family`, which names the family that runs it;
- a header row with `Qty`, `Recipient Name`, `Address` and `Notes`, and optionally a column whose name contains
  `Curb` (distance from the curb);
- one row per stop. A row with "Total" in it ends the list.

An optional `Route Summary` tab (`Route N` | family) is checked against the tab titles.

Addresses can be loose: `120 elm st`, `7 Birch Ln, Shelbyville`. An address with no town is in the garage's town.

## Run it

With Docker, from a folder that holds the workbook (outputs and caches are written there):

```bash
docker build -t flag-route-planner .
docker run --rm -v "$PWD:/work" -w /work flag-route-planner \
  python -m flag_route_planner routes.xlsx --garage "123 Main Street, Springfield" --state OH \
  --garage-label "the town garage"
```

Or with Python 3.12: `pip install .`, then `flag-route-planner routes.xlsx --garage "123 Main Street, Springfield"`.

It writes to `out/`:

| File | What it is |
|---|---|
| `plan.xlsx` | Read me, Summary, one driver tab per zone, Changes, Data issues and a Volunteers sheet to fill in |
| `drive/zones/zone_NN.csv` | one driver sheet per zone; upload to Google Drive and it becomes a Google Sheet with working links |
| `drive/summary.html` | the summary, changes and data issues; upload to Drive and it becomes a Google Doc |
| `drive/map.csv` | every stop with its coordinates and zone, to import into Google My Maps |

The first run takes a few minutes: it geocodes every address and fetches drive times between every pair of
stops. Answers are cached in `cache/`, so later runs are quick.

## Fix what it gets wrong

Put hand fixes in `overrides.csv` (copy `overrides.example.csv`). A rule matches a stop by route plus part of
the name and/or the address as written, and sets a corrected street and town, fixed coordinates, or both. Its
note shows on the Data issues list. Run again after editing it.

## How it works

1. **Read and clean.** Each Route tab is read, street suffixes are spelled out, a cell pasted twice is fixed, and a
   missing suffix is taken from neighbours on the same street. The same house listed twice under the same name is
   merged.
2. **Locate.** Each address goes to the US Census geocoder, then to OpenStreetMap's Nominatim if the Census finds
   nothing.
3. **Drive times.** OSRM (OpenStreetMap road data) gives the minutes between every pair of stops.
4. **Zones.** A local search starts from the routes as listed. It moves a house, or a cluster of nearby houses, to
   a neighbouring zone when that lowers total minutes plus an imbalance penalty, minus a penalty for each house
   moved. The weights are at the top of `src/flag_route_planner/plan.py`.
5. **Order.** Each zone is ordered garage to garage: nearest neighbour, then 2-opt and or-opt.
6. **Legs.** The order is cut at the longest drives into legs of three to eight stops.

Minutes are estimates (drive time plus 36 seconds a stop). Use them to compare routes, and check them against
your own timed runs before promising anyone a time.

The geocoders and OSRM used here are free public services with fair-use limits. The planner caches every answer
and paces Nominatim at one request a second. For heavy use, run your own OSRM.

## Privacy

Route data holds people's names and addresses. Keep the workbook, `overrides.csv`, `cache/` and `out/` out of any
repository; `.gitignore` already does. Share each family only their own zone sheet.

## Develop

Tests run in Docker and never touch the network:

```bash
docker build -t flag-route-planner:test .
docker run --rm -v "$PWD:/src" -w /src flag-route-planner:test pytest -q
```

Before a push: `pip install pre-commit && pre-commit install`, then `pre-commit run --all-files`. The project
follows [murphy360/standards](https://github.com/murphy360/standards); `AGENTS.md` has the working rules.

## License

MIT. See `LICENSE`.
