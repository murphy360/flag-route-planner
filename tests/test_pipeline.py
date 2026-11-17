import csv

from conftest import TOWN, make_workbook

from flag_route_planner import drive, pipeline
from flag_route_planner.__main__ import parse_args
from flag_route_planner.parse import Stop


def _stop(route, name, street, raw=None):
    return Stop(
        route=route,
        row=1,
        qty=1,
        name=name,
        raw_address=raw or street,
        street=street,
        city=TOWN,
    )


def test_find_duplicates_merges_same_name_and_flags_different_names():
    stops = [
        _stop(1, "Resident A", "1 Elm Street"),
        _stop(1, "Resident A (2nd)", "1 Elm Street"),
        _stop(2, "Resident B", "1 Elm Street"),
    ]
    keep, issues = pipeline.find_duplicates(stops)
    assert [s.name for s in keep] == ["Resident A", "Resident B"]
    kinds = sorted(k for k, _, _ in issues)
    assert kinds == [
        "Duplicate removed",
        "Same address, different names",
        "Same address, different names",
    ]


def test_apply_overrides_sets_street_and_pin():
    stops = [
        _stop(3, "Entrance", "Both Sides", raw="BOTH SIDES"),
        _stop(3, "Resident C", "9 Oak Street"),
    ]
    stops[0].issues = ["no house number"]
    rules = [
        {
            "route": "3",
            "name_contains": "entrance",
            "address_contains": "",
            "street": "1 Gate Road",
            "city": "",
            "lat": "40.1",
            "lon": "-80.1",
            "note": "entrance flags",
        },
    ]
    pipeline.apply_overrides(stops, rules)
    assert stops[0].street == "1 Gate Road"
    assert stops[0].pinned and stops[0].lat == 40.1
    assert stops[0].issues == ["entrance flags"]
    assert not stops[1].pinned


def _routes(tmp_path):
    rows1 = [(1, f"Resident {i}", f"{i * 10} Elm St", None) for i in range(1, 9)]
    rows2 = [(1, f"Neighbour {i}", f"{i * 10} Oak St", None) for i in range(1, 9)]
    rows2.append((2, "Corner Lot", "Behind the school", "two flags"))
    return make_workbook(
        tmp_path / "routes.xlsx",
        {1: ("Able", rows1), 2: ("Baker", rows2)},
        summary={1: "Able", 2: "Carter"},
    )


def test_build_plan_end_to_end(tmp_path, offline):
    cfg = pipeline.Config("1 Main Street", TOWN, overrides=tmp_path / "none.csv")
    p = pipeline.build_plan(_routes(tmp_path), cfg)
    assert len(p.stops) == 16
    assert sorted(z for z in p.zones) == [1, 2]
    kinds = {k for k, _, _ in p.issues}
    assert {"Address not found", "Route owner mix-up"} <= kinds
    for d in p.zones.values():
        assert sum(b - a for a, b in d["legs"]) == len(d["stops"])


def test_run_writes_workbook_and_drive_files(tmp_path, offline):
    cfg = pipeline.Config(
        "1 Main Street",
        TOWN,
        garage_label="the garage",
        overrides=tmp_path / "none.csv",
    )
    pipeline.run(_routes(tmp_path), tmp_path / "out", cfg)
    out = tmp_path / "out"
    assert (out / "plan.xlsx").stat().st_size > 0
    assert (out / "drive" / "summary.html").read_text().startswith("<html>")
    with open(out / "drive" / "zones" / "zone_01.csv", newline="") as f:
        rows = list(csv.reader(f))
    leg = next(r for r in rows if r and r[0] == "Leg 1")
    first_stop = rows.index(leg) + 2  # 1-based sheet row of the leg's first stop
    assert f"C{first_stop}:" in leg[1]
    assert rows[-1][0] == "End"


def test_leg_formula_handles_other_towns():
    f = drive.leg_formula(5, 8, [TOWN, "Shelbyville", TOWN, TOWN], TOWN, "OH", "Go")
    assert 'IF(D5:D7="","Springfield",D5:D7)' in f
    assert 'IF(D8="","Springfield",D8)' in f


def test_cli_needs_a_town_in_the_garage():
    _, cfg = parse_args(
        ["r.xlsx", "--garage", "1 Main Street, Springfield", "--state", "PA"]
    )
    assert (cfg.garage_street, cfg.garage_city, cfg.state) == (
        "1 Main Street",
        "Springfield",
        "PA",
    )
    try:
        parse_args(["r.xlsx", "--garage", "1 Main Street"])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("expected a usage error")
