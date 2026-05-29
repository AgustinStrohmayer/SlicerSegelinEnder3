from __future__ import annotations

import zipfile

import pytest

from appSlicerSegelin.v2.core.geometry import Point, Segment, SegmentKind
from appSlicerSegelin.v2.core.machine import MachineProfile
from appSlicerSegelin.v2.core.manual_cuts import make_y_cut
from appSlicerSegelin.v2.core.project import Project
from appSlicerSegelin.v2.io.project_archive import (
    ARCHIVE_EXTENSION,
    ARCHIVE_MAGIC,
    load_archive,
    quick_inspect,
    save_archive,
)


def _project_with_state() -> Project:
    p = Project()
    p.machine = MachineProfile(name="Bench", feed_cut_mm_min=200)
    p.segments = [
        Segment(Point(0, 0), Point(50, 0), SegmentKind.CUT),
        Segment(Point(50, 0), Point(50, 25), SegmentKind.CUT),
    ]
    p.manual_cuts = [make_y_cut(20.0)]
    p.offset_y = 10.0
    p.offset_z = -2.0
    p.speed_mm_s = 8.5
    p.reverse_cut = True
    p.use_manual_cuts = True
    p.batch_basename = "wing"
    p.source_dxf_name = "wing.dxf"
    return p


def test_archive_extension_normalised(tmp_path):
    out = save_archive(tmp_path / "wing", _project_with_state())
    assert out.suffix == ARCHIVE_EXTENSION
    assert out.exists()


def test_archive_is_a_valid_zip(tmp_path):
    out = save_archive(tmp_path / "p.ssproj", _project_with_state())
    assert zipfile.is_zipfile(out)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "project.json" in names


def test_round_trip_preserves_state(tmp_path):
    src = _project_with_state()
    out = save_archive(tmp_path / "p.ssproj", src)
    content = load_archive(out)

    assert content.manifest["magic"] == ARCHIVE_MAGIC
    p = content.project
    assert p.machine.name == "Bench"
    assert p.machine.feed_cut_mm_min == 200
    assert len(p.segments) == 2
    assert p.offset_y == 10.0
    assert p.offset_z == -2.0
    assert p.speed_mm_s == 8.5
    assert p.reverse_cut is True
    assert p.use_manual_cuts is True
    assert p.batch_basename == "wing"
    assert p.source_dxf_name == "wing.dxf"
    assert len(p.manual_cuts) == 1
    assert content.source_dxf_bytes is None
    assert content.thumbnail_png is None


def test_archive_embeds_source_dxf(tmp_path):
    dxf_bytes = b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n"
    out = save_archive(tmp_path / "p.ssproj", _project_with_state(), source_dxf_bytes=dxf_bytes)
    content = load_archive(out)
    assert content.source_dxf_bytes == dxf_bytes
    assert content.manifest["entries"]["source_dxf"] == "source.dxf"


def test_archive_embeds_thumbnail(tmp_path):
    fake_png = b"\x89PNG\r\n\x1a\nfakepayload"
    out = save_archive(tmp_path / "p.ssproj", _project_with_state(), thumbnail_png=fake_png)
    content = load_archive(out)
    assert content.thumbnail_png == fake_png


def test_quick_inspect_returns_manifest(tmp_path):
    out = save_archive(tmp_path / "p.ssproj", _project_with_state(), title="My Wing", author="me")
    manifest = quick_inspect(out)
    assert manifest is not None
    assert manifest["title"] == "My Wing"
    assert manifest["author"] == "me"


def test_quick_inspect_handles_non_archive(tmp_path):
    p = tmp_path / "not.ssproj"
    p.write_text("not a zip")
    assert quick_inspect(p) is None


def test_load_rejects_non_archive_file(tmp_path):
    from appSlicerSegelin.v2.core.errors import ProjectIOError

    p = tmp_path / "fake.ssproj"
    p.write_text("hello")
    with pytest.raises(ProjectIOError):
        load_archive(p)


def test_load_rejects_zip_without_magic(tmp_path):
    from appSlicerSegelin.v2.core.errors import ProjectIOError

    p = tmp_path / "wrong.ssproj"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", '{"magic": "Other"}')
        zf.writestr("project.json", "{}")
    with pytest.raises(ProjectIOError, match="not a SlicerSegelinEnder3"):
        load_archive(p)


def test_load_rejects_newer_format(tmp_path):
    from appSlicerSegelin.v2.core.errors import ProjectIOError

    p = tmp_path / "futuristic.ssproj"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(
            "manifest.json",
            f'{{"magic": "{ARCHIVE_MAGIC}", "format_version": 999}}',
        )
        zf.writestr("project.json", "{}")
    with pytest.raises(ProjectIOError, match="newer than this app"):
        load_archive(p)
