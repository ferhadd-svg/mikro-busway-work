from app.schemas.boq import BusRun
from app.services.drawing_reader import SYSTEM_PROMPT, _normalise_run, _parse_json_response


# ------------------------------------------------------------------ #
#  _parse_json_response                                                #
# ------------------------------------------------------------------ #

def test_parse_plain_json():
    assert _parse_json_response('{"runs": []}') == {"runs": []}

def test_parse_fenced_json():
    raw = '```json\n{"runs": []}\n```'
    assert _parse_json_response(raw) == {"runs": []}

def test_parse_json_wrapped_in_prose():
    raw = 'Here is the extraction:\n{"runs": [], "raw_notes": "x"}\nHope this helps!'
    assert _parse_json_response(raw) == {"runs": [], "raw_notes": "x"}

def test_parse_garbage_returns_none():
    assert _parse_json_response("I could not read the drawing.") is None

def test_parse_non_object_returns_none():
    assert _parse_json_response("[1, 2, 3]") is None

def test_parse_empty_returns_none():
    assert _parse_json_response("") is None


# ------------------------------------------------------------------ #
#  _normalise_run                                                      #
# ------------------------------------------------------------------ #

def _minimal_run(**overrides) -> dict:
    run = {
        "run_id": "RUN-1",
        "run_type": "TX-MSB",
        "rating_a": 500,
        "material": "AL",
        "earth_pct": 50,
        "routing": "FROM TX TO MSB",
    }
    run.update(overrides)
    return run


def test_normalised_run_validates_as_busrun():
    run = BusRun(**_normalise_run(_minimal_run(), 1))
    assert run.rating_a == 500
    assert run.frame_rating_a == 630


def test_frame_rating_recomputed_locally():
    # Even if the model reports the wrong frame, we recompute from nominal.
    r = _normalise_run(_minimal_run(rating_a=500, frame_rating_a=800), 1)
    assert r["frame_rating_a"] == 630


def test_null_rating_defaults_to_200_and_flags():
    r = _normalise_run(_minimal_run(rating_a=None), 1)
    assert r["rating_a"] == 200
    assert r["frame_rating_a"] == 200
    assert any("rating" in f for f in r["flags"])


def test_material_variants_normalised():
    assert _normalise_run(_minimal_run(material="copper"), 1)["material"] == "CU"
    assert _normalise_run(_minimal_run(material="cu"), 1)["material"] == "CU"
    assert _normalise_run(_minimal_run(material="Aluminium"), 1)["material"] == "AL"
    r = _normalise_run(_minimal_run(material="XYZ"), 1)
    assert r["material"] == "AL"
    assert any("material" in f for f in r["flags"])


def test_earth_pct_coerced_and_snapped():
    assert _normalise_run(_minimal_run(earth_pct="100"), 1)["earth_pct"] == 100
    assert _normalise_run(_minimal_run(earth_pct=None), 1)["earth_pct"] == 50
    r = _normalise_run(_minimal_run(earth_pct=30), 1)
    assert r["earth_pct"] == 50
    assert any("earth" in f for f in r["flags"])


def test_run_type_case_insensitive():
    assert _normalise_run(_minimal_run(run_type="msb-riser"), 1)["run_type"] == "MSB-Riser"
    r = _normalise_run(_minimal_run(run_type="mystery"), 1)
    assert r["run_type"] == "RISER"
    assert any("run type" in f for f in r["flags"])


def test_piu_ratings_parsed_from_strings():
    r = _normalise_run(_minimal_run(piu_ratings=["60A TPN MCCB", 150, "junk"]), 1)
    assert r["piu_ratings"] == [60, 150]
    assert any("junk" in f for f in r["flags"])


def test_missing_run_id_gets_index():
    raw = _minimal_run()
    del raw["run_id"]
    assert _normalise_run(raw, 3)["run_id"] == "RUN-3"


def test_explicit_nulls_dropped_for_defaulted_fields():
    r = _normalise_run(_minimal_run(hanger_spacing_m=None, phases=None), 1)
    run = BusRun(**r)
    assert run.hanger_spacing_m == 1.5
    assert run.phases == "3P4W"


def test_needs_bimetal_defaults_from_material():
    assert _normalise_run(_minimal_run(material="AL"), 1)["needs_bimetal"] is True
    assert _normalise_run(_minimal_run(material="CU"), 1)["needs_bimetal"] is False


# ------------------------------------------------------------------ #
#  SYSTEM_PROMPT guidance                                              #
# ------------------------------------------------------------------ #

def test_prompt_covers_offsheet_piu_ratings():
    """Real project evidence (a 537-unit residential tower): the main riser
    sheet shows only a tap symbol (M1/M2/M3) per level with no ampere rating
    — the actual MCCB rating (e.g. 60A TPN) is only on a separate "typical
    metering panel" detail sheet elsewhere in the set. The model must be told
    to check other supplied pages before flagging a tap as unrated."""
    assert "TYPICAL METERING PANEL" in SYSTEM_PROMPT
    assert "PIU rating not labelled anywhere in the supplied pages" in SYSTEM_PROMPT


def test_prompt_covers_existing_vs_new_busduct_scope():
    """Real project evidence (a retrofit/extension job, "Twin Pavilion Blok
    F"): the riser is split by a dashed marker into "EXISTING BUSDUCT (up to
    Level 7)" — already installed, not this job's scope — and "NEW BUSDUCT
    (by this contractor)". Quoting the whole riser as new would double the
    price or claim work that's already done; the model must be told to
    extract only the new portion's actual level range."""
    assert "EXISTING BUSDUCT" in SYSTEM_PROMPT
    assert "RETROFIT/EXTENSION" in SYSTEM_PROMPT


def test_prompt_covers_busbar_trunking_synonym():
    """Real project evidence ("PRISMA MELODY" service apartments): the
    TX-to-meter-kiosk busduct feed is labelled "BUSBAR TRUNKING", not
    "BUSDUCT" or "BUS TRUNKING". Because the prompt's own warning about
    excluding a switchboard's internal busbar uses the word "BUSBAR", the
    model needs an explicit note that "BUSBAR TRUNKING" is busduct, not the
    excluded case, to avoid a false-negative on this label."""
    assert "BUSBAR TRUNKING" in SYSTEM_PROMPT


# ------------------------------------------------------------------ #
#  API call shape                                                     #
# ------------------------------------------------------------------ #

class _FakeStream:
    def __init__(self, sink, kwargs):
        sink.update(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return "final"


class _FakeMessages:
    def __init__(self, sink):
        self.sink = sink

    def stream(self, **kwargs):
        return _FakeStream(self.sink, kwargs)


class _FakeClient:
    def __init__(self):
        self.plain, self.beta_sink = {}, {}
        self.messages = _FakeMessages(self.plain)
        self.beta = type("B", (), {"messages": _FakeMessages(self.beta_sink)})()


def test_call_uses_structured_output_and_streaming():
    from app.services.drawing_reader import _call_claude, EXTRACTION_SCHEMA
    client = _FakeClient()
    assert _call_claude(client, "claude-opus-4-8", [{"type": "text", "text": "x"}]) == "final"
    assert client.plain["output_config"]["format"]["schema"] is EXTRACTION_SCHEMA
    assert client.plain["thinking"] == {"type": "adaptive"}
    assert "fallbacks" not in client.plain and not client.beta_sink


def test_opus5_family_opts_into_default_fallbacks():
    from app.services.drawing_reader import _call_claude
    client = _FakeClient()
    _call_claude(client, "claude-opus-5", [])
    assert client.beta_sink["fallbacks"] == "default"
    assert client.beta_sink["betas"] == ["server-side-fallback-2026-07-01"]
    assert not client.plain


def test_schema_output_normalises_into_busruns():
    """A reply shaped exactly like EXTRACTION_SCHEMA must pass through
    _normalise_run into a valid BusRun (nulls included)."""
    from app.schemas.boq import BusRun
    from app.services.drawing_reader import _normalise_run
    run = {
        "run_id": "RUN-1", "run_type": "RISER", "rating_a": 1250, "frame_rating_a": 1250,
        "material": "AL", "earth_pct": 50, "routing": "FROM LEVEL 1 TO LEVEL 9",
        "phases": "3P4W", "length_m": None, "hanger_spacing_m": 1.5,
        "num_fixed_hangers": None, "num_spring_hangers": None, "piu_ratings": [100, 250],
        "spare_openings": 0, "needs_bimetal": True, "flags": [],
    }
    assert BusRun(**_normalise_run(run, 1)).frame_rating_a == 1250


def test_eval_scorer():
    from types import SimpleNamespace as NS
    from scripts.eval_drawings import score
    ext = NS(runs=[NS(rating_a=1250, material="AL", earth_pct=50, run_type="RISER",
                      piu_ratings=[100], flags=["Existing busduct up to L7 excluded"])],
             global_flags=[])
    res = dict(score(ext, {"min_runs": 1,
                           "must_include": [{"rating": 1250, "run_type": ["RISER", "MSB-Riser"]}],
                           "forbid_ratings": [2000], "piu_includes": [60],
                           "flag_contains": ["existing"]}))
    assert list(res.values()) == [True, True, True, False, True]


def test_out_of_credit_gets_a_plain_message(tmp_path, monkeypatch):
    """A drained balance mid-stream surfaces as APIStatusError(200) with the
    real reason only in the body — the user must be told to add credit."""
    import anthropic
    import httpx2
    import pytest
    from PIL import Image
    from app.config import settings
    from app.services import drawing_reader as dr

    img = tmp_path / "sld.png"
    Image.new("RGB", (100, 100), "white").save(img)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    def boom(*a, **k):
        resp = httpx2.Response(200, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
        raise anthropic.APIStatusError(
            "Your credit balance is too low to access the Anthropic API.", response=resp, body=None)

    monkeypatch.setattr(dr, "_call_claude", boom)
    with pytest.raises(RuntimeError, match="out of credit"):
        dr.read_drawing(img)
