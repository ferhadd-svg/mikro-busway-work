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
    total, thumbs = dr.pdf_page_thumbnails(pdf)
    assert total == 4
    assert len(thumbs) == 4
    assert all(t.startswith("data:image/png;base64,") for t in thumbs)


def test_page_thumbnails_caps_at_max(tmp_path):
    pdf = _make_pdf(tmp_path / "d.pdf", pages=dr.MAX_THUMBNAIL_PAGES + 5)
    total, thumbs = dr.pdf_page_thumbnails(pdf)
    assert total == dr.MAX_THUMBNAIL_PAGES + 5
    assert len(thumbs) == dr.MAX_THUMBNAIL_PAGES
