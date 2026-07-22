from app.schemas.boq import BusRun, DrawingExtraction, FlagAnswers
from app.services.boq_builder import build_boq
from app.services.price_list import resolve_frame_rating


def _extraction():
    return DrawingExtraction(runs=[
        BusRun(
            run_id="R1",
            run_type="TX-MSB",
            rating_a=300,
            frame_rating_a=resolve_frame_rating(300),
            material="AL",
            earth_pct=50,
            routing="FROM TX TO MSB",
            length_m=10.0,
        ),
    ])


def _flags(run_overrides=None):
    return FlagAnswers(lme_usd_per_mt=2600.0, usd_to_myr=4.4500, run_overrides=run_overrides or {})


def test_frame_rating_recomputed_when_rating_a_is_overridden():
    boq = build_boq(_extraction(), _flags({"R1": {"rating_a": 800}}), our_ref="Q-1", client_name="ACME")
    assert boq.runs[0].frame_rating_a == resolve_frame_rating(800)
    assert boq.runs[0].frame_rating_a != resolve_frame_rating(300)


def test_frame_rating_override_is_respected_when_explicitly_given():
    boq = build_boq(_extraction(), _flags({"R1": {"rating_a": 800, "frame_rating_a": 1000}}), our_ref="Q-1", client_name="ACME")
    assert boq.runs[0].frame_rating_a == 1000


def test_no_override_keeps_original_frame_rating():
    boq = build_boq(_extraction(), _flags(), our_ref="Q-1", client_name="ACME")
    assert boq.runs[0].frame_rating_a == resolve_frame_rating(300)


# ------------------------------------------------------------------ #
#  House-format accessory completeness per run type                   #
# ------------------------------------------------------------------ #

from app.services.boq_builder import _build_tx_msb, _build_msb_riser, _build_riser


def _run(run_type, material="CU", earth=50, length=10.0, piu=None):
    return BusRun(
        run_id="R1", run_type=run_type, rating_a=1200,
        frame_rating_a=resolve_frame_rating(1200), material=material,
        earth_pct=earth, routing="FROM TX TO MSB", length_m=length,
        piu_ratings=piu or [],
    )


def _descs(items):
    return [it.description for it in items]


def test_tx_msb_has_full_house_accessory_list():
    items = _build_tx_msb(_run("TX-MSB", material="CU"))
    d = _descs(items)
    assert "FEEDER C/W INTEGRAL EARTH  (Horizontal)" in d
    assert "FLANGE END" in d
    assert "HORIZONTAL ELBOW" in d
    assert "VERTICAL ELBOW" in d
    assert "FLEXIBLE LINK (BRAIDED TYPE)" in d
    assert "OPTIONAL" in d
    assert "MOUNTING CLAMP (W/O ROD & C-CHANNEL)" in d
    assert "CONNECTION BARS (TX & MSB)" in d
    # Copper → no bi-metal
    assert not any("BI-METAL" in x for x in d)


def test_tx_msb_flange_and_elbows_are_qty_two():
    items = {it.description: it for it in _build_tx_msb(_run("TX-MSB"))}
    assert items["FLANGE END"].qty == 2
    assert items["HORIZONTAL ELBOW"].qty == 2
    assert items["VERTICAL ELBOW"].qty == 2


def test_tx_msb_uses_house_units():
    items = {it.description: it for it in _build_tx_msb(_run("TX-MSB"))}
    assert items["FEEDER C/W INTEGRAL EARTH  (Horizontal)"].unit == "MTR"
    assert items["FLANGE END"].unit == "NOS"
    assert items["FLEXIBLE LINK (BRAIDED TYPE)"].unit == "SETS"
    assert items["CONNECTION BARS (TX & MSB)"].unit == "LOTS"


def test_connection_bars_is_excluded_and_optional_is_subheader():
    items = {it.description: it for it in _build_tx_msb(_run("TX-MSB"))}
    assert items["CONNECTION BARS (TX & MSB)"].is_excluded is True
    assert items["CONNECTION BARS (TX & MSB)"].amount_myr == 0
    assert items["OPTIONAL"].is_subheader is True


def test_aluminium_tx_msb_includes_bimetal():
    d = _descs(_build_tx_msb(_run("TX-MSB", material="AL")))
    assert "BI-METAL PLATE" in d


def test_msb_riser_has_full_house_accessory_list():
    items, piu = _build_msb_riser(_run("MSB-Riser", piu=[150, 150]), 26)
    d = _descs(items)
    for expected in ("FLANGE END", "END CLOSURE", "HORIZONTAL ELBOW", "VERTICAL ELBOW",
                     "FIXED HANGER", "SPRING HANGER", "PLUG-IN OPENING", "OPTIONAL",
                     "MOUNTING CLAMP (W/O ROD & C-CHANNEL)"):
        assert expected in d, f"missing {expected}"
    assert any("MCCB" in x for x in _descs(piu))


def test_riser_has_full_house_accessory_list():
    items, piu = _build_riser(_run("RISER", piu=[100, 100, 100]), 26)
    d = _descs(items)
    for expected in ("CABLE ENTRY BOX", "END CLOSURE", "FIXED HANGER",
                     "SPRING HANGER", "PLUG-IN OPENING"):
        assert expected in d, f"missing {expected}"
    assert len(piu) == 1 and piu[0].qty == 3


def test_riser_spare_openings_render_as_optional_spare_line():
    run = _run("RISER", piu=[100])
    run.spare_openings = 2
    items, _ = _build_riser(run, 26)
    d = _descs(items)
    assert "PLUG-IN OPENING (SPARE)" in d
    assert "OPTIONAL" in d


def test_bimetal_line_uses_price_list_dimensions(monkeypatch):
    from app.services import boq_builder as bb
    monkeypatch.setattr(bb.price_list, "bimetal_dims", lambda fa: (3, 80.0, 230.0))
    monkeypatch.setattr(bb.price_list, "bimetal", lambda fa: 1800)
    line = bb._bimetal_line(6300)
    assert line.description == "BI-METAL PLATE (3 x 80mm x 230mm, 12 pcs/set)"
    assert line.qty == 1 and line.unit == "SETS" and line.unit_rate_myr == 1800


def test_bimetal_line_falls_back_without_dimensions(monkeypatch):
    from app.services import boq_builder as bb
    monkeypatch.setattr(bb.price_list, "bimetal_dims", lambda fa: None)
    monkeypatch.setattr(bb.price_list, "bimetal", lambda fa: 480)
    line = bb._bimetal_line(2000)
    assert line.description == "BI-METAL PLATE" and line.qty == 1
