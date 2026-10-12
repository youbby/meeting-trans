import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from meeting_app.export import export_session, markdown_to_pdf
from meeting_app.session import Session, Segment


def sample():
    session = Session("현장·원격 회의 <검증>")
    mic = session.add_speaker("MIC")
    remote = session.add_speaker("SYSTEM")
    session.rename(mic, "김대리")
    session.add_segment(Segment("a", 1, 3, "MIC", "음성은 외부로 전송하지 않습니다. <script> & **기호**", mic, "분류됨"))
    session.add_segment(Segment("b", 5, 8, "SYSTEM", "PDF에서도 한글과 입력 출처를 확인합니다.", remote, "분류됨"))
    return session, mic, remote


def test_rename_persists_and_source_cannot_change(tmp_path):
    session, mic, remote = sample()
    session.rename(mic, "수정한 이름")
    session.save(tmp_path / "session.json")
    loaded = Session.load(tmp_path / "session.json")
    assert loaded.speakers[mic].name == "수정한 이름"
    assert loaded.segments["a"].source == "MIC"
    with pytest.raises(ValueError):
        loaded.edit_segment("a", "오류", remote)


def test_manual_edit_wins_over_background_diarization():
    session, mic, _ = sample()
    session.edit_segment("a", "사람이 수정한 발언", mic)
    session.replace_segments(["a"], [Segment("replacement", 1, 3, "MIC", "자동 분석 결과")])
    assert session.segments["a"].text == "사람이 수정한 발언"
    assert "replacement" not in session.segments


def test_pdf_matches_markdown_and_paginates(tmp_path):
    session, mic, _ = sample()
    for i in range(35):
        session.add_segment(Segment(f"long{i}", 10 + i * 10, 18 + i * 10, "MIC",
            "긴 발언도 페이지에서 잘리지 않고 읽을 수 있어야 합니다. " * 7, mic, "분류됨"))
    session.finish()
    md, pdf, error = export_session(session.snapshot(), tmp_path)
    assert error is None and pdf
    text = "\n".join(page.extract_text() for page in PdfReader(pdf).pages)
    assert len(PdfReader(pdf).pages) > 2
    for needle in ("김대리", "MIC", "SYSTEM", "외부로", "긴 발언도"):
        assert needle in text
        assert needle in md.read_text(encoding="utf-8")
    assert "<script>" in text


def test_pdf_failure_preserves_markdown(tmp_path, monkeypatch):
    import meeting_app.export as exporter
    session, _, _ = sample()
    def fail(*args):
        raise OSError("PDF 파일이 열려 있습니다")
    monkeypatch.setattr(exporter, "markdown_to_pdf", fail)
    md, pdf, error = export_session(session.snapshot(), tmp_path)
    assert md.is_file() and pdf is None and "열려" in error


def test_generated_markdown_does_not_load_links(tmp_path):
    md = tmp_path / "input.md"
    md.write_text("# 회의\n\n![remote](https://example.com/no-image.png)\n", encoding="utf-8")
    markdown_to_pdf(md, tmp_path / "result.pdf")
    assert (tmp_path / "result.pdf").is_file()
