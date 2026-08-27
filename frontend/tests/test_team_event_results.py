from pathlib import Path

from app.services.iracing_ingest import parse_event_json
from app.services.team_event_results import _compute_class_standings

MULTICLASS_TEAM_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "discord-bot"
    / "tests"
    / "fixtures"
    / "eventresult-87448524.json"
)


def test_compute_class_standings_ranks_within_car_class_only():
    # Two classes (0 and 1), each with its own finish/start order —
    # a class-1 entrant finishing worse overall than every class-0
    # entrant still ranks 1st within class 1.
    results = [
        {"iracing_cust_id": 1, "car_class_id": 0, "finish_position": 1, "start_position": 2},
        {"iracing_cust_id": 2, "car_class_id": 0, "finish_position": 3, "start_position": 1},
        {"iracing_cust_id": 3, "car_class_id": 1, "finish_position": 2, "start_position": 3},
    ]

    standings = _compute_class_standings(results)

    assert standings[1] == {"finish_position": 1, "start_position": 2}
    assert standings[2] == {"finish_position": 2, "start_position": 1}
    assert standings[3] == {"finish_position": 1, "start_position": 1}


def test_compute_class_standings_multi_driver_car_does_not_inflate_class_rank():
    # A 3-driver car shares one overall finish/start position across all
    # three rows — ranking must be dense over distinct positions within
    # the class, not over every row, or a class-mate behind it drops 3
    # ranks instead of 1.
    results = [
        {"iracing_cust_id": 1, "car_class_id": 0, "finish_position": 1, "start_position": 1},
        {"iracing_cust_id": 2, "car_class_id": 0, "finish_position": 1, "start_position": 1},
        {"iracing_cust_id": 3, "car_class_id": 0, "finish_position": 1, "start_position": 1},
        {"iracing_cust_id": 4, "car_class_id": 0, "finish_position": 2, "start_position": 2},
    ]

    standings = _compute_class_standings(results)

    assert standings[1]["finish_position"] == 1
    assert standings[2]["finish_position"] == 1
    assert standings[3]["finish_position"] == 1
    assert standings[4]["finish_position"] == 2


def test_compute_class_standings_single_class_is_a_no_op():
    results = [
        {"iracing_cust_id": 1, "car_class_id": 0, "finish_position": 1, "start_position": 1},
        {"iracing_cust_id": 2, "car_class_id": 0, "finish_position": 2, "start_position": 2},
    ]

    standings = _compute_class_standings(results)

    assert standings[1] == {"finish_position": 1, "start_position": 1}
    assert standings[2] == {"finish_position": 2, "start_position": 2}


def test_compute_class_standings_against_a_real_multiclass_team_race():
    # A real 3-class endurance race (GTP/Dallara P217/IMSA23) — the
    # class winners for the two slower classes finish well back in the
    # overall order (7th and 14th) but must still rank 1st within their
    # own class.
    parsed = parse_event_json(MULTICLASS_TEAM_FIXTURE_PATH.read_bytes())

    standings = _compute_class_standings(parsed["results"])

    james_costlow = next(r for r in parsed["results"] if r["iracing_display_name"] == "James Costlow")
    jason_carlin = next(r for r in parsed["results"] if r["iracing_display_name"] == "Jason Carlin")
    daniel_turner = next(r for r in parsed["results"] if r["iracing_display_name"] == "Daniel Turner2")

    assert james_costlow["finish_position"] == 1  # GTP, also overall P1
    assert jason_carlin["finish_position"] == 7  # Dallara P217, overall P7
    assert daniel_turner["finish_position"] == 14  # IMSA23, overall P14

    assert standings[james_costlow["iracing_cust_id"]]["finish_position"] == 1
    assert standings[jason_carlin["iracing_cust_id"]]["finish_position"] == 1
    assert standings[daniel_turner["iracing_cust_id"]]["finish_position"] == 1
