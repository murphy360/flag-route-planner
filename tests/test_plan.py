from conftest import grid_matrix

from flag_route_planner import plan
from flag_route_planner.parse import Stop


def _stop(route, lat, lon, qty=1):
    return Stop(
        route=route,
        row=1,
        qty=qty,
        name="x",
        raw_address="",
        street="1 A St",
        city="T",
        lat=lat,
        lon=lon,
    )


def test_solve_tour_visits_a_line_in_order():
    points = [(0, 0)] + [(0, x) for x in (5, 1, 4, 2, 3)]
    order = plan.solve_tour([1, 2, 3, 4, 5], grid_matrix(points))
    xs = [points[n][1] for n in order]
    assert xs in ([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])


def test_tour_minutes_counts_the_garage_both_ways():
    m = grid_matrix([(0, 0), (0, 3)])
    assert plan.tour_minutes([1], m) == 6


def test_split_legs_respects_sizes_and_cuts_at_the_long_drive():
    gaps = [1.0] * 15
    gaps[6] = 30.0  # a long drive after stop 7
    legs = plan.split_legs(16, gaps)
    assert all(plan.MIN_LEG_STOPS <= b - a <= plan.MAX_LEG_STOPS for a, b in legs)
    assert (0, 7) in legs
    assert legs[-1][1] == 16


def test_split_legs_never_leaves_a_tiny_leg():
    legs = plan.split_legs(17, [1.0] * 16)
    assert min(b - a for a, b in legs) >= plan.MIN_LEG_STOPS


def test_rebalance_moves_a_far_cluster_to_the_zone_beside_it():
    # Route 1 has its own street to the south plus a cluster on route 2's street to the north.
    stops = [_stop(1, -0.3, 0.01 * i) for i in range(1, 6)]
    stops += [_stop(2, 0.3, 0.01 * i) for i in range(1, 6)]
    stops += [_stop(1, 0.3, 0.01 * i + 0.005) for i in range(1, 5)]
    points = [(0, 0)] + [(s.lat, s.lon) for s in stops]
    m = [[d * 100 for d in row] for row in grid_matrix(points)]
    zone = plan.rebalance(stops, plan.symmetric(m), 2)
    assert zone[-4:] == [2, 2, 2, 2]
    assert zone[:5] == [1] * 5


def test_nav_formula_starts_from_the_phone_and_navigates():
    f = plan.nav_formula('"B"', '"A1|A2"', "Go")
    assert f.startswith('=HYPERLINK("https://www.google.com/maps/dir/?api=1')
    assert "dir_action=navigate" in f
    assert "origin" not in f
    assert '&"&waypoints="&ENCODEURL("A1|A2")' in f


def test_maps_link_encodes_waypoints():
    url = plan.maps_link(["1 A St, T, OH", "2 B St, T, OH"])
    assert "destination=2%20B%20St" in url
    assert "waypoints=1%20A%20St" in url


def test_service_minutes_grow_with_flags():
    assert plan.service_min(_stop(1, 0, 0, qty=2)) > plan.service_min(_stop(1, 0, 0))
