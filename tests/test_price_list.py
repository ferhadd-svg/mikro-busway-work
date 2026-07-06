from app.services.price_list import FRAME_LADDER, resolve_frame_rating


def test_exact_ladder_values_map_to_themselves():
    for frame in FRAME_LADDER:
        assert resolve_frame_rating(frame) == frame


def test_rounds_up_to_next_frame():
    assert resolve_frame_rating(500) == 630
    assert resolve_frame_rating(100) == 200
    assert resolve_frame_rating(201) == 400


def test_below_minimum_clamps_to_smallest_frame():
    assert resolve_frame_rating(1) == 200
    assert resolve_frame_rating(0) == 200


def test_above_maximum_clamps_to_largest_frame():
    assert resolve_frame_rating(5000) == 5000
    assert resolve_frame_rating(6000) == 5000
