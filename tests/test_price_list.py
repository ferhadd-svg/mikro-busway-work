from app.services.price_list import FRAME_LADDER, resolve_frame_rating, PriceList


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


# ------------------------------------------------------------------ #
#  PriceList.all_rates()                                               #
# ------------------------------------------------------------------ #

def test_all_rates_extracts_feeder_fields():
    pl = PriceList()
    pl._al = {"feeder_630_50": 120.5, "feeder_630_100": 150.0}
    rates = pl.all_rates()
    assert {"category": "Feeder", "material": "AL", "frame_a": 630,
            "earth_pct": 50, "rate": 120.5} in rates
    assert {"category": "Feeder", "material": "AL", "frame_a": 630,
            "earth_pct": 100, "rate": 150.0} in rates


def test_all_rates_extracts_elbow_fields_both_materials():
    pl = PriceList()
    pl._al = {"elbow_800": 300.0}
    pl._cu = {"elbow_800": 450.0}
    rates = pl.all_rates()
    assert any(r["category"] == "Elbow" and r["material"] == "AL" and r["frame_a"] == 800
               and r["rate"] == 300.0 for r in rates)
    assert any(r["category"] == "Elbow" and r["material"] == "CU" and r["frame_a"] == 800
               and r["rate"] == 450.0 for r in rates)


def test_all_rates_extracts_piu_fields():
    pl = PriceList()
    pl._piu = {"piu_150_26": 999.0}
    rates = pl.all_rates()
    assert {"category": "PIU", "rating_a": 150, "ka": 26, "rate": 999.0} in rates


def test_all_rates_extracts_bimetal_fields():
    pl = PriceList()
    pl._bimetal = {"bimetal_3200": 88.0}
    rates = pl.all_rates()
    assert {"category": "Bi-Metal Plate", "frame_a": 3200, "rate": 88.0} in rates


def test_all_rates_distinguishes_flange_end_from_flange_end_box():
    pl = PriceList()
    pl._al = {"flange_end_630": 10.0, "flange_end_box_630": 20.0}
    rates = pl.all_rates()
    cats = {(r["category"], r["frame_a"]) for r in rates}
    assert ("Flange End", 630) in cats
    assert ("Flange End Box", 630) in cats


def test_all_rates_empty_when_nothing_loaded():
    assert PriceList().all_rates() == []
