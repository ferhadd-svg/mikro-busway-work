"""
Regression tests for the pricing / input-validation fixes:

  - 50%E feeders priced from the 4-wire row, not the 5-wire row after it
  - PIU rates parsed from the real "26 KA" header
  - the 6300A frame is priced
  - the net accessory table wins over the repeated gross (x2) table
  - copper runs below the smallest copper size, and 200A bi-metal plates,
    price at the next listed size instead of RM 0
  - 3P5W runs priced from the 5-wire row
  - a run with no length is refused instead of priced at 0 m
  - a price list missing sheets doesn't keep the previous list's rates,
    and a list with no feeder rates is never activated
  - .xls templates refused, drawing size capped, manual-entry errors are 400
  - customer page only shows a rep their own projects
  - the quotation date is Malaysia's, not the UTC server's

Where possible the expected numbers are read out of the bundled price list
itself (by row label), so these keep passing when the list is updated.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import openpyxl
import pytest
import xlrd
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main
from app.config import settings
from app.database import Base
from app.models.customer import Customer
from app.models.project import Project
from app.models.salesperson import Salesperson
from app.models.user import User
from app.schemas.boq import BusRun, DrawingExtraction, FlagAnswers
from app.services import boq_builder as bb
from app.services.price_list import PriceList, _parse_price_sheet, _parse_piu_sheet


# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def bundled():
    pl = PriceList()
    pl.load(main._bundled_price_list_source())
    return pl


def _sheet_rate(sheet_name: str, label: str, frame: int) -> float:
    """Read one rate straight out of the bundled workbook by row label and
    frame column header — independent of the parser under test."""
    wb = xlrd.open_workbook(str(main._bundled_price_list_source()))
    sh = wb.sheet_by_name(sheet_name)
    header = sh.row_values(2)
    col = next(
        i for i, v in enumerate(header)
        if (isinstance(v, float) and int(v) == frame) or str(v).strip() == f"{frame}A"
    )
    row = next(r for r in range(sh.nrows) if str(sh.cell_value(r, 0)).strip() == label)
    return sh.cell_value(row, col)


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


class _FakeUpload:
    def __init__(self, filename, content=b"x", size=None):
        self.filename, self._content, self.size = filename, content, size

    async def read(self):
        return self._content


def _run(**kw):
    base = dict(run_id="R1", run_type="RISER", rating_a=800, frame_rating_a=800,
                material="AL", earth_pct=50, routing="FROM L1 TO L5", length_m=12.0)
    base.update(kw)
    return BusRun(**base)


def _flags():
    return FlagAnswers(lme_usd_per_mt=2600.0, usd_to_myr=4.45)


@pytest.fixture
def priced_with(monkeypatch, tmp_path):
    """Build BOQs against a given PriceList, writing files into tmp_path."""
    monkeypatch.setattr(settings, "projects_dir", tmp_path)

    def _use(pl):
        monkeypatch.setattr(bb, "price_list", pl)
    return _use


# ------------------------------------------------------------------ #
#  Bundled price list — parsed values match the sheet                 #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("material,sheet,frame", [
    ("AL", "List Price (Al)", 630),
    ("AL", "List Price (Al)", 2000),
    ("CU", "List Price (Cu)", 800),
])
def test_50e_feeder_is_the_4w_row_not_the_5w_row(bundled, material, sheet, frame):
    four_wire = _sheet_rate(sheet, "Feeder 3P (4W) + 50%E", frame)
    five_wire = _sheet_rate(sheet, "Feeder 3P (5W) + 50%E", frame)
    assert four_wire != five_wire
    assert bundled.feeder(frame, 50, material) == pytest.approx(four_wire)
    assert bundled.feeder(frame, 50, material, "3P5W") == pytest.approx(five_wire)


def test_100e_feeder_is_the_4w_row(bundled):
    assert bundled.feeder(630, 100, "AL") == pytest.approx(
        _sheet_rate("List Price (Al)", "Feeder 3P (4W) + 100%E", 630))


def test_6300a_frame_is_priced(bundled):
    assert bundled.feeder(6300, 50, "AL") == pytest.approx(
        _sheet_rate("List Price (Al)", "Feeder 3P (4W) + 50%E", 6300))


def test_accessories_come_from_the_net_table(bundled):
    # The first "Elbow" row is the net price; the sheet later repeats the
    # table at 2x (gross, with an x0.5 note). The net one must be used.
    assert bundled.elbow(630, "AL") == pytest.approx(_sheet_rate("List Price (Al)", "Elbow", 630))


def test_piu_rates_load_from_bundled_list(bundled):
    for rating in (60, 100, 125, 200, 250, 400):
        assert bundled.piu(rating, 26) > 0, rating
        assert bundled.piu(rating, 50) > bundled.piu(rating, 26), rating


def test_bundled_list_has_no_coverage_problems(bundled):
    assert bundled.coverage_problems() == []


def test_bimetal_below_smallest_plate_uses_smallest_plate(bundled):
    assert bundled.bimetal(200) == bundled.bimetal(400) > 0
    assert bundled.bimetal_dims(200) == bundled.bimetal_dims(400)


# ------------------------------------------------------------------ #
#  Parser — synthetic layouts                                         #
# ------------------------------------------------------------------ #

def test_5w_row_after_4w_rows_does_not_overwrite_them():
    rows = [
        ["Description", "Unit", 400.0, "630A", 800.0],
        ["Feeder 3P (4W) + 50%E", "M", 100.0, 200.0, 300.0],
        ["Feeder 3P (4W) + 100%E", "M", 110.0, 210.0, 310.0],
        ["Feeder 3P (5W) + 50%E", "M", 130.0, 230.0, 330.0],
    ]
    r = _parse_price_sheet(rows)
    assert r["feeder_630_50"] == 200.0
    assert r["feeder5w_630_50"] == 230.0


def test_repeated_accessory_table_keeps_first_occurrence():
    rows = [
        ["Description", "Unit", 400.0, "630A", 800.0],
        ["Elbow", "No.", 10.0, 20.0, 30.0],
        ["", "", 400.0, "630A", 800.0],
        ["Elbow", "No.", 20.0, 40.0, 60.0],   # gross table
    ]
    assert _parse_price_sheet(rows)["elbow_630"] == 20.0


def test_piu_header_in_upper_case_ka():
    rows = [
        ["AMPERE", "", "BREAKER (3P ) 26 KA", "", "", "BREAKER (3P) 50 KA"],
        ["32A-100A", "", 900.0, "", "", 950.0],
    ]
    assert _parse_piu_sheet(rows) == {"piu_100_26": 900.0, "piu_100_50": 950.0}


def _xlsx(path, sheets: dict):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    wb.save(path)
    return path


_AL_ONLY = {"List Price (Al)": [
    ["Description", "Unit", 400, "630A", 800],
    ["Feeder 3P (4W) + 50%E", "M", 1, 2, 3],
]}


def test_loading_a_list_without_a_sheet_drops_old_rates(bundled, tmp_path):
    pl = PriceList()
    pl.load(main._bundled_price_list_source())
    assert pl.feeder(800, 50, "CU") > 0
    pl.load(_xlsx(tmp_path / "al_only.xlsx", _AL_ONLY))
    assert pl.feeder(630, 50, "AL") == 2
    assert pl.feeder(800, 50, "CU") == 0          # not the previous list's rate
    assert pl.piu(100) == 0
    assert any("copper" in p for p in pl.coverage_problems())


# ------------------------------------------------------------------ #
#  BOQ builder                                                        #
# ------------------------------------------------------------------ #

def test_run_without_length_is_refused(bundled, priced_with):
    priced_with(bundled)
    with pytest.raises(bb.BOQInputError, match="no length"):
        bb.build_boq(DrawingExtraction(runs=[_run(length_m=None)]), _flags(), "Q-1", "C")


def test_small_copper_run_priced_at_smallest_copper_size(bundled, priced_with):
    priced_with(bundled)
    boq = bb.build_boq(DrawingExtraction(runs=[_run(material="CU", rating_a=150, frame_rating_a=200)]),
                       _flags(), "Q-1", "C")
    run = boq.runs[0]
    assert run.frame_rating_a == 400
    feeder = run.items[0]
    assert feeder.unit_rate_myr == round(bundled.feeder(400, 50, "CU"))
    assert any("priced at 400A" in w for w in boq.warnings)
    assert not any("RM 0" in w for w in boq.warnings)


def test_rating_above_largest_frame_warns(bundled, priced_with):
    priced_with(bundled)
    boq = bb.build_boq(DrawingExtraction(runs=[_run(rating_a=7000, frame_rating_a=6300)]),
                       _flags(), "Q-1", "C")
    assert any("above the largest listed frame" in w for w in boq.warnings)


def test_five_wire_run_uses_5w_feeder_rate(bundled, priced_with):
    priced_with(bundled)
    boq = bb.build_boq(DrawingExtraction(runs=[_run(phases="3P5W")]), _flags(), "Q-1", "C")
    assert boq.runs[0].items[0].unit_rate_myr == round(bundled.feeder(800, 50, "AL", "3P5W"))


def test_riser_piu_lines_are_priced(bundled, priced_with):
    priced_with(bundled)
    boq = bb.build_boq(DrawingExtraction(runs=[_run(piu_ratings=[100, 250, 250])]),
                       _flags(), "Q-1", "C")
    assert boq.warnings == []
    assert all(i.unit_rate_myr > 0 for i in boq.runs[0].piu_items)


# ------------------------------------------------------------------ #
#  Endpoints                                                          #
# ------------------------------------------------------------------ #

def test_price_list_upload_without_feeders_is_rejected(tmp_path, monkeypatch, bundled):
    from app.routers import price_list as router
    monkeypatch.setattr(settings, "price_list_dir", tmp_path)
    active = PriceList()
    active.load(main._bundled_price_list_source())
    monkeypatch.setattr(router, "price_list", active)
    db = _db()
    admin = User(email="a@x.com", name="A", hashed_password="x", role="admin")
    db.add(admin); db.commit()

    junk = _xlsx(tmp_path / "src.xlsx", {"Sheet1": [["nothing", "here"]]}).read_bytes()
    with pytest.raises(HTTPException) as e:
        asyncio.run(router.upload_price_list(_FakeUpload("junk.xlsx", junk), db, admin))
    assert e.value.status_code == 400
    assert active.feeder(800, 50, "CU") > 0         # still the old list
    assert not list(tmp_path.glob("*_junk.xlsx"))  # rejected file not kept


def test_price_list_upload_reports_missing_sheets(tmp_path, monkeypatch):
    from app.routers import price_list as router
    monkeypatch.setattr(settings, "price_list_dir", tmp_path)
    monkeypatch.setattr(router, "price_list", PriceList())
    db = _db()
    admin = User(email="a@x.com", name="A", hashed_password="x", role="admin")
    db.add(admin); db.commit()

    content = _xlsx(tmp_path / "src.xlsx", _AL_ONLY).read_bytes()
    res = asyncio.run(router.upload_price_list(_FakeUpload("al.xlsx", content), db, admin))
    assert any("copper" in w for w in res["warnings"])


def test_xls_template_upload_is_refused():
    from app.routers.projects import upload_template
    with pytest.raises(HTTPException) as e:
        asyncio.run(upload_template(_FakeUpload("QUOTATION_TEMPLATE_ERIC.xls"), _db()))
    assert e.value.status_code == 400


def test_oversized_drawing_is_refused(tmp_path, monkeypatch):
    from app.routers.projects import _save_uploaded_drawing
    monkeypatch.setattr(settings, "projects_dir", tmp_path)
    monkeypatch.setattr(settings, "max_drawing_mb", 1)
    project = Project(id=1, our_ref="R", client_name="C")
    big = b"0" * (2 * 1024 * 1024)
    for upload in (_FakeUpload("a.pdf", big), _FakeUpload("a.pdf", b"", size=len(big))):
        with pytest.raises(HTTPException) as e:
            asyncio.run(_save_uploaded_drawing(project, upload, _db()))
        assert e.value.status_code == 413


@pytest.mark.parametrize("bad_run", [
    {"run_type": "RISER", "rating_a": "big", "material": "AL", "earth_pct": 50, "routing": "x"},
    {"run_type": "RISER", "rating_a": 800, "material": "AL", "earth_pct": 75, "routing": "x"},
    {"run_type": "SIDEWAYS", "rating_a": 800, "material": "AL", "earth_pct": 50, "routing": "x"},
])
def test_bad_manual_run_is_a_400(bad_run):
    from app.routers.projects import submit_runs_manually
    db = _db()
    db.add(Project(id=1, our_ref="R", client_name="C")); db.commit()
    admin = User(email="a@x.com", name="A", hashed_password="x", role="admin")
    with pytest.raises(HTTPException) as e:
        submit_runs_manually(1, [bad_run], db, admin)
    assert e.value.status_code == 400


def test_customer_page_shows_rep_only_their_projects():
    from app.routers.customers import get_customer
    db = _db()
    mine, theirs = Salesperson(name="A", title="", mobile="", email=""), Salesperson(name="B", title="", mobile="", email="")
    db.add_all([mine, theirs]); db.commit()
    customer = Customer(company_name="Acme")
    db.add(customer); db.commit()
    db.add_all([
        Project(our_ref="MINE", client_name="Acme", customer_id=customer.id, salesperson_id=mine.id),
        Project(our_ref="THEIRS", client_name="Acme", customer_id=customer.id,
                salesperson_id=theirs.id, quoted_value_myr=999999),
    ])
    rep = User(email="r@x.com", name="R", hashed_password="x", role="sales", salesperson_id=mine.id)
    admin = User(email="a@x.com", name="A", hashed_password="x", role="admin")
    db.add_all([rep, admin]); db.commit()

    assert [p.our_ref for p in get_customer(customer.id, db, rep).projects] == ["MINE"]
    assert get_customer(customer.id, db, rep).project_count == 1
    assert {p.our_ref for p in get_customer(customer.id, db, admin).projects} == {"MINE", "THEIRS"}


def test_quotation_date_is_malaysia_time():
    from app.services.quotation_builder import _today
    assert _today() == datetime.now(timezone(timedelta(hours=8))).date()
