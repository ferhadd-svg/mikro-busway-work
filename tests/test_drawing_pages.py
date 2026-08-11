"""Unit tests for page-selective PDF rendering + the page-thumbnail helper."""
import pymupdf as fitz

from app.services import drawing_reader as dr


def _make_pdf(path, pages=3):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=600, height=400)
        page.insert_text((60, 200), f"PAGE {i + 1}")
    doc.save(str(path))
    doc.close()
    return path


def test_pdf_to_images_defaults_to_first_max_pages(tmp_path):
    pdf = _make_pdf(tmp_path / "d.pdf", pages=10)
    paths, total = dr._pdf_to_images(pdf)  # no pages, default cap
    assert total == 10
    assert len(paths) == dr.MAX_PDF_PAGES
    assert paths[0].name.endswith("_p1.png")


def test_pdf_to_images_renders_only_selected_pages(tmp_path):
    pdf = _make_pdf(tmp_path / "d.pdf", pages=10)
    paths, total = dr._pdf_to_images(pdf, pages=[3, 7])
    assert total == 10
    assert [p.name for p in paths] == [f"{pdf.stem}_p3.png", f"{pdf.stem}_p7.png"]


def test_pdf_to_images_ignores_out_of_range_pages(tmp_path):
    pdf = _make_pdf(tmp_path / "d.pdf", pages=3)
    paths, total = dr._pdf_to_images(pdf, pages=[2, 99])
    assert total == 3
    assert [p.name for p in paths] == [f"{pdf.stem}_p2.png"]


def test_page_thumbnails_returns_data_urls_per_page(tmp_path):
    pdf = _make_pdf(tmp_path / "d.pdf", pages=4)
    total, thumbs, hints = dr.pdf_page_thumbnails(pdf)
    assert total == 4
    assert len(thumbs) == 4
    assert len(hints) == 4
    assert all(t.startswith("data:image/png;base64,") for t in thumbs)


def test_page_thumbnails_caps_at_max(tmp_path):
    pdf = _make_pdf(tmp_path / "d.pdf", pages=dr.MAX_THUMBNAIL_PAGES + 5)
    total, thumbs, hints = dr.pdf_page_thumbnails(pdf)
    assert total == dr.MAX_THUMBNAIL_PAGES + 5
    assert len(thumbs) == dr.MAX_THUMBNAIL_PAGES
    assert len(hints) == dr.MAX_THUMBNAIL_PAGES


# ------------------------------------------------------------------ #
#  _score_page_relevance — page-picker relevance hints                #
# ------------------------------------------------------------------ #

def test_score_page_relevance_no_text_is_unknown():
    """Many real drawings are vector-only CAD exports with zero extractable
    text (confirmed on a real project PDF) — must never read as "unlikely"."""
    assert dr._score_page_relevance("") == "unknown"
    assert dr._score_page_relevance("   \n  ") == "unknown"


def test_score_page_relevance_detects_sld_signals():
    assert dr._score_page_relevance("ELECTRICAL SCHEMATIC SINGLE LINE DIAGRAM\nMSB-1\n1600A TPN BUSDUCT") == "likely"


def test_score_page_relevance_detects_non_sld_signals():
    assert dr._score_page_relevance("SCHEDULE OF UNIT RATES\nGENERAL NOTES\nBILL OF QUANTITIES") == "unlikely"


def test_score_page_relevance_weak_or_mixed_signals_stay_unknown():
    # A single weak signal alone isn't enough to call it either way.
    assert dr._score_page_relevance("TRANSFORMER ROOM ACCESS NOTES") == "unknown"


def test_score_page_relevance_strong_positive_beats_boilerplate_negative():
    """Real project evidence: a genuine SLD title page ("SINGLE LINE DIAGRAM
    ELECTRICAL ... ELECTRICAL SINGLE LINE DIAGRAM") also carries a standing
    "GENERAL NOTES" field as part of its title-block border template — every
    sheet in that set has one, SLD or not. Summing scores let that boilerplate
    cancel the genuine SLD title down to "unknown"; a strong positive title
    must win outright instead."""
    real_text = (
        "SINGLE LINE DIAGRAM ELECTRICAL\nGS\nQ.01\nELECTRICAL SINGLE LINE DIAGRAM\n"
        "DED-0-EL-102-R3\nGENERAL NOTES\nDRAWING TITLE :\nCHECKED BY:"
    )
    assert dr._score_page_relevance(real_text) == "likely"


def test_page_thumbnails_hints_match_real_page_content(tmp_path):
    doc = fitz.open()
    p1 = doc.new_page(width=600, height=400)
    p1.insert_text((60, 200), "GENERAL NOTES\nSCHEDULE OF UNIT RATES")
    p2 = doc.new_page(width=600, height=400)
    p2.insert_text((60, 200), "SINGLE LINE DIAGRAM\nMSB-1 BUSDUCT 1250A")
    pdf = tmp_path / "d.pdf"
    doc.save(str(pdf))
    doc.close()

    total, thumbs, hints = dr.pdf_page_thumbnails(pdf)
    assert hints == ["unlikely", "likely"]
