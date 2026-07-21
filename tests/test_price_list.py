from app.services.price_list import (
    FRAME_LADDER, resolve_frame_rating, PriceList,
    _extract_amperage, _extract_upper_amperage, _parse_price_sheet, _parse_piu_sheet, _parse_bimetal_sheet,
)


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


# ------------------------------------------------------------------ #
#  Sheet parsing — regression coverage for real-file quirks           #
#  (synthetic values below, not the real Mikro price list figures)    #
# ------------------------------------------------------------------ #

def test_extract_amperage_handles_numeric_cells_without_a_suffix():
    # xlrd/openpyxl hand back numeric header cells as plain int/float —
    # str(800.0) == "800.0" has no trailing "A" and fails a naive regex.
    assert _extract_amperage(800.0) == 800
    assert _extract_amperage(1000) == 1000
    assert _extract_amperage("630A") == 630
    assert _extract_amperage("not a number") is None


def test_extract_upper_amperage_takes_the_range_upper_bound():
    assert _extract_upper_amperage("32A - 100A") == 100
    assert _extract_upper_amperage("630A (c/w busbar)") == 630
    assert _extract_upper_amperage(800.0) == 800


def test_parse_price_sheet_header_mixes_text_and_numeric_cells():
    # Only some frame columns are stored as text ("400A"); the rest are
    # plain floats (800.0) with no "A" suffix — both must be detected.
    rows = [
        ["Description", "", "", "Unit", "400A", 800.0, "1250A", 2000.0],
        ["Feeder 3P (4W)", "", "", "M", 10.0, 20.0, 30.0, 40.0],
        ["Feeder 3P (4W) + 50%E", "", "", "M", 11.0, 21.0, 31.0, 41.0],
        ["Elbow", "", "", "No.", 1.0, 2.0, 3.0, 4.0],
    ]
    result = _parse_price_sheet(rows)
    assert result["feeder_400_50"] == 11.0
    assert result["feeder_800_50"] == 21.0
    assert result["feeder_1250_50"] == 31.0
    assert result["feeder_2000_50"] == 41.0


def test_parse_price_sheet_feeder_earth_pct_in_same_row():
    # Real sheet embeds the earth-% qualifier in the same row as "feeder"
    # ("Feeder 3P (4W) + 50%E"), not on a separate indented sub-row.
    rows = [
        ["Description", "", "", "Unit", "400A", "630A", "1250A"],
        ["Feeder 3P (4W)", "", "", "M", 1.0, 2.0, 3.0],
        ["Feeder 3P (4W) + 50%E", "", "", "M", 11.0, 12.0, 13.0],
        ["Feeder 3P (4W) + 100%E", "", "", "M", 21.0, 22.0, 23.0],
    ]
    result = _parse_price_sheet(rows)
    assert result["feeder_400_50"] == 11.0
    assert result["feeder_400_100"] == 21.0
    assert "feeder_400" not in result  # plain 4W row (no earth%) is never used


def test_parse_price_sheet_feeder_uses_4w_not_3w_variant():
    # The sheet lists both 3-wire and 4-wire feeder rows for each earth %,
    # adjacent to each other. Mikro quotes 3P4W as standard, so the 4W price
    # must win — the later 3W row must NOT overwrite it (same collision class
    # as the elbow variant rows).
    rows = [
        ["Description", "", "", "Unit", "400A", "630A", "1250A"],
        ["Feeder 3P (4W) + 50%E", "", "", "M", 100.0, 200.0, 300.0],
        ["Feeder 3P (3W) + 50%E", "", "", "M", 80.0, 160.0, 240.0],
        ["Feeder 3P (4W) + 100%E", "", "", "M", 110.0, 210.0, 310.0],
        ["Feeder 3P (3W) + 100%E", "", "", "M", 88.0, 168.0, 248.0],
    ]
    result = _parse_price_sheet(rows)
    assert result["feeder_400_50"] == 100.0    # 4W, not the 80.0 3W row
    assert result["feeder_1250_50"] == 300.0
    assert result["feeder_400_100"] == 110.0
    assert result["feeder_1250_100"] == 310.0


def test_parse_price_sheet_elbow_not_clobbered_by_variant_rows():
    # Multiple rows contain the substring "elbow" — only the exact "Elbow"
    # label should populate elbow_*, not Vertical/Special Angle variants.
    rows = [
        ["Description", "", "", "Unit", "400A", "630A", "1250A"],
        ["Elbow", "", "", "No.", 100.0, 200.0, 300.0],
        ["Vertical T Elbow", "", "", "No.", 999.0, 999.0, 999.0],
        ["Special Angle Elbow", "", "", "No.", 888.0, 888.0, 888.0],
    ]
    result = _parse_price_sheet(rows)
    assert result["elbow_400"] == 100.0
    assert result["elbow_630"] == 200.0
    assert result["elbow_1250"] == 300.0


def test_parse_piu_sheet_range_label_and_blank_spacer_column():
    # Real sheet has a blank spacer column before the rating label, and
    # range labels like "32A - 100A" must resolve to the upper bound.
    rows = [
        ["", "Ampere", "Breaker (3P) 26kA", "Breaker (3P) 50kA"],
        ["", "32A - 100A", 900.0, 950.0],
        ["", "630A (c/w busbar)", 3200.0, ""],
    ]
    result = _parse_piu_sheet(rows)
    assert result["piu_100_26"] == 900.0
    assert result["piu_100_50"] == 950.0
    assert result["piu_630_26"] == 3200.0
    assert "piu_630_50" not in result


def test_parse_bimetal_sheet_blank_spacer_and_trailing_price_column():
    # Real sheet: blank spacer column, then label, then several unrelated
    # numeric columns (No/W(mm)/L(mm)), with the actual price last.
    rows = [
        ["", "Amp", "", "BI-METAL PLATE", "", ""],
        ["", "", "No", "W(mm)", "L(mm)", "RM/SET"],
        ["", "400A", 1.0, 80.0, 40.0, 100.0],
        ["", "630A", 1.0, 80.0, 50.0, 120.0],
    ]
    result = _parse_bimetal_sheet(rows)
    assert result["bimetal_400"] == 100.0
    assert result["bimetal_630"] == 120.0
