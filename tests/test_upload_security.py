"""
Filenames come straight from the client's multipart Content-Disposition
header and are attacker-controlled — a crafted filename containing "../"
segments could otherwise make an upload endpoint write outside its intended
directory (see app/routers/projects.py and app/routers/price_list.py).
These tests pin down that every upload path strips directory components
before touching the filesystem.
"""
import asyncio

import pytest

from app.config import settings
from app.models.project import Project
from app.routers.projects import _save_uploaded_drawing


class _FakeUploadFile:
    """Minimal stand-in for fastapi.UploadFile — _save_uploaded_drawing only
    touches .filename and awaits .read()."""
    def __init__(self, filename: str, content: bytes = b"fake-bytes"):
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


def _project(id_=1):
    return Project(id=id_, our_ref="TEST-1", client_name="Test Client")


def test_save_uploaded_drawing_strips_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_dir", tmp_path)
    (tmp_path / "1").mkdir()
    project = _project()

    fake = _FakeUploadFile("../../../evil.pdf")
    saved_path = asyncio.run(_save_uploaded_drawing(project, fake))

    # Must land inside this project's own directory, never above it.
    assert saved_path.parent == tmp_path / "1"
    assert saved_path.name == "evil.pdf"
    assert saved_path.is_relative_to(tmp_path)


def test_save_uploaded_drawing_strips_windows_style_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_dir", tmp_path)
    (tmp_path / "1").mkdir()
    project = _project()

    fake = _FakeUploadFile("..\\..\\evil.pdf")
    saved_path = asyncio.run(_save_uploaded_drawing(project, fake))

    assert saved_path.parent == tmp_path / "1"
    assert saved_path.is_relative_to(tmp_path)


def test_save_uploaded_drawing_records_sanitized_filename_on_project(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_dir", tmp_path)
    (tmp_path / "1").mkdir()
    project = _project()

    fake = _FakeUploadFile("../../secret.png")
    asyncio.run(_save_uploaded_drawing(project, fake))

    assert project.drawing_filename == "secret.png"


def test_save_uploaded_drawing_still_rejects_bad_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_dir", tmp_path)
    project = _project()

    fake = _FakeUploadFile("../../evil.exe")
    with pytest.raises(Exception) as exc_info:
        asyncio.run(_save_uploaded_drawing(project, fake))
    assert "Unsupported file type" in str(exc_info.value)
