"""Cold-start price-list fallback.

Render's free tier wipes the uploaded price_list_dir on every deploy, so the
app must fall back to a price list bundled in the repo. These tests exercise
that fallback without touching the real on-disk singleton.
"""

from pathlib import Path

import app.main as main
from app.config import settings
from app.services.price_list import PriceList


def test_a_price_list_is_actually_bundled():
    """The repo must ship a real, parseable default price list — otherwise the
    cold-start fallback silently loads nothing."""
    src = main._bundled_price_list_source()
    assert src is not None, "no price list bundled under app/bundled_price_list/"
    assert src.is_file()
    pl = PriceList()
    pl.load(src)
    assert pl.is_loaded()
    assert len(pl.all_rates()) > 0


def test_cold_start_loads_bundled_when_dir_empty(tmp_path, monkeypatch):
    """Fresh deploy: price_list_dir is empty → the bundled default is copied in
    and loaded, so the app has prices without any manual upload."""
    empty_dir = tmp_path / "price_list"
    empty_dir.mkdir()
    monkeypatch.setattr(settings, "price_list_dir", empty_dir)
    fresh = PriceList()
    monkeypatch.setattr(main, "price_list", fresh)

    main._load_price_list_on_startup()

    assert fresh.is_loaded()
    assert len(fresh.all_rates()) > 0
    # It was persisted into the dir so the info/versions UI sees it.
    copied = list(empty_dir.glob("*.xls*"))
    assert len(copied) == 1


def test_uploaded_price_list_takes_precedence(tmp_path, monkeypatch):
    """When an admin has uploaded a list, the bundled default must NOT override
    it — the uploaded file in price_list_dir wins."""
    d = tmp_path / "price_list"
    d.mkdir()
    bundled = main._bundled_price_list_source()
    uploaded = d / "999_uploaded.xls"
    uploaded.write_bytes(Path(bundled).read_bytes())

    monkeypatch.setattr(settings, "price_list_dir", d)
    fresh = PriceList()
    monkeypatch.setattr(main, "price_list", fresh)

    main._load_price_list_on_startup()

    assert fresh.is_loaded()
    assert Path(fresh.loaded_file()).name == "999_uploaded.xls"
    # No extra copy was made — only the uploaded file is present.
    assert len(list(d.glob("*.xls*"))) == 1


def test_explicit_override_path_is_preferred(tmp_path, monkeypatch):
    """PRICE_LIST_BUNDLED_FILE (e.g. a Render Secret File) overrides the
    in-repo default, so pricing can live outside git with no code change."""
    bundled = main._bundled_price_list_source()
    override = tmp_path / "secret_price_list.xls"
    override.write_bytes(Path(bundled).read_bytes())
    monkeypatch.setattr(settings, "price_list_bundled_file", str(override))

    assert main._bundled_price_list_source() == override
