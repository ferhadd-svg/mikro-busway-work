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
