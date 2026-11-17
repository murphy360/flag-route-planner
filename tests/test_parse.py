from conftest import TOWN, make_workbook

from flag_route_planner.parse import (
    NO_HOUSE_NUMBER,
    NO_SUFFIX,
    clean_address,
    dedupe_repeat,
    read_route_owners,
    read_routes,
)


def test_clean_address_expands_suffix_and_keeps_default_town():
    assert clean_address("120 elm st", TOWN) == ("120 Elm Street", TOWN, [])


def test_clean_address_reads_town_after_the_comma():
    street, city, _ = clean_address("7 Birch Ln, Shelbyville (County), OH", TOWN)
    assert (street, city) == ("7 Birch Lane", "Shelbyville")


def test_clean_address_drops_township_and_stray_letters():
    assert clean_address("7 Birch Ln, Shelbyville Township x", TOWN)[1] == "Shelbyville"


def test_clean_address_flags_missing_parts():
    assert clean_address("Corner of the park", TOWN)[2] == [NO_HOUSE_NUMBER]
    assert clean_address("40 Maple", TOWN)[2] == [NO_SUFFIX]


def test_clean_address_fixes_mc_and_saint():
    assert (
        clean_address("5 mccarthy saint james way", TOWN)[0]
        == "5 McCarthy St James Way"
    )


def test_dedupe_repeat():
    assert dedupe_repeat("12 Oak Ct 12 Oak Ct") == "12 Oak Ct"
    assert dedupe_repeat("12 Oak Ct") == "12 Oak Ct"


def test_read_routes_skips_blank_moved_and_total_rows(tmp_path):
    path = make_workbook(
        tmp_path / "r.xlsx",
        {
            1: (
                "Able",
                [
                    (1, "Resident A", "100 Elm St", "left of mailbox"),
                    (None, "Resident B", "Moved to Route 2", None),
                    (
                        2,
                        "Resident C",
                        "200 Elm St",
                        "Route 1: https://example.invalid/x",
                    ),
                ],
            ),
            2: (
                "Baker",
                [
                    (1, "Resident D", "40 Maple", None),
                    (1, "Resident E", "44 Maple Lane", None),
                ],
            ),
        },
    )
    stops = read_routes(path, TOWN)
    assert [s.name for s in stops] == [
        "Resident A",
        "Resident C",
        "Resident D",
        "Resident E",
    ]
    assert stops[1].qty == 2
    assert stops[1].notes == ""  # the volunteer's own leg link is dropped
    assert stops[2].street == "40 Maple Lane"  # suffix taken from the neighbour


def test_read_route_owners_prefers_both_sources(tmp_path):
    path = make_workbook(
        tmp_path / "r.xlsx",
        {1: ("Able", []), 2: ("Baker", [])},
        summary={1: "Able", 2: "Carter"},
    )
    owners = read_route_owners(path)
    assert owners[1] == {"summary": "Able", "tab": "Able"}
    assert owners[2] == {"summary": "Carter", "tab": "Baker"}
