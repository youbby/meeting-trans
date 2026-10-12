"""Atomic Markdown export and offline conversion of that exact file to PDF."""
from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
import re
import threading
import uuid

from .models import local_path
from .paths import resource_root
from .session import atomic_text, timestamp, SOURCES

_pdf_lock = threading.Lock()


def md_escape(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]<>()#+.!|~-])", r"\\\1", text)


def markdown(snapshot: dict) -> str:
    speakers = {s["id"]: s for s in snapshot["speakers"]}
    state = "종료된 회의" if snapshot.get("ended_at") else "중간 저장본"
    lines = [f"# {md_escape(snapshot['title'])}", "", f"- 시작: {snapshot['started_at']}",
        f"- 종료: {snapshot.get('ended_at') or '진행 중'}", f"- 상태: {state}",
        f"- 문서 생성: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 세션: {snapshot['id']}", f"- 수정 버전: {snapshot['revision']}", "", "## 발화자", ""]
    if not speakers:
        lines.append("아직 분류된 발화자가 없습니다.")
    for s in speakers.values():
        lines.append(f"- **{md_escape(s['name'])}** · {SOURCES[s['source']]} ({s['source']}) · {s['id']}")
    lines.extend(["", "## 전사 기록", ""])
    if not snapshot["segments"]:
        lines.append("저장된 전사문이 없습니다.")
    for segment in snapshot["segments"]:
        speaker = speakers.get(segment["speaker_id"])
        name = speaker["name"] if speaker else "발화자 미확정"
        source = segment["source"]
        lines.append(f"### {timestamp(segment['start'])} - {timestamp(segment['end'])} | {md_escape(name)} | {SOURCES[source]} ({source})")
        if segment["status"] not in {"분류됨", "수동 수정"}:
            lines.extend(["", f"상태: {md_escape(segment['status'])}"])
        lines.extend(["", md_escape(segment["text"]), ""])
    if snapshot["events"]:
        lines.extend(["## 처리 상태 및 공백", ""])
        for event in snapshot["events"]:
            lines.append(f"- {timestamp(event['time'])} {md_escape(event.get('source', ''))} {md_escape(event['message'])}")
    return "\n".join(lines).rstrip() + "\n"


def _inline(children) -> str:
    result = []
    for token in children or []:
        if token.type in {"text", "code_inline"}:
            result.append(escape(token.content))
        elif token.type in {"softbreak", "hardbreak"}:
            result.append("<br/>")
        elif token.type == "strong_open":
            result.append("<b>")
        elif token.type == "strong_close":
            result.append("</b>")
        elif token.type == "em_open":
            result.append("<i>")
        elif token.type == "em_close":
            result.append("</i>")
        elif token.type == "image":
            # Never load remote or local images referenced by meeting text.
            result.append(escape(token.content))
    return "".join(result)


def markdown_to_pdf(md_path: Path, pdf_path: Path):
    from markdown_it import MarkdownIt
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    md_path, pdf_path = local_path(md_path), local_path(pdf_path)
    fonts = resource_root() / "assets/fonts"
    for name in ("NanumGothic-Regular.ttf", "NanumGothic-Bold.ttf"):
        if not (fonts / name).is_file():
            raise FileNotFoundError(f"PDF 한국어 폰트가 없습니다: {name}")
    with _pdf_lock:
        if "MeetingKorean" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("MeetingKorean", str(fonts / "NanumGothic-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("MeetingKoreanBold", str(fonts / "NanumGothic-Bold.ttf")))
            pdfmetrics.registerFontFamily("MeetingKorean", normal="MeetingKorean", bold="MeetingKoreanBold", italic="MeetingKorean", boldItalic="MeetingKoreanBold")
        body = ParagraphStyle("Body", fontName="MeetingKorean", fontSize=10, leading=16,
            spaceAfter=7, wordWrap="CJK", alignment=TA_LEFT, textColor=colors.HexColor("#243147"))
        styles = {"p": body}
        for tag, size, leading, before in [("h1", 21, 29, 0), ("h2", 14, 21, 14), ("h3", 10, 16, 8)]:
            styles[tag] = ParagraphStyle(tag, parent=body, fontName="MeetingKoreanBold", fontSize=size,
                leading=leading, spaceBefore=before, spaceAfter=8, keepWithNext=True)
        tokens = MarkdownIt("commonmark", {"html": False}).parse(md_path.read_text(encoding="utf-8"))
        story, style, in_item = [], "p", False
        for token in tokens:
            if token.type == "heading_open":
                style = token.tag
            elif token.type == "paragraph_open":
                style = "p"
            elif token.type == "list_item_open":
                in_item = True
            elif token.type == "list_item_close":
                in_item = False
            elif token.type == "inline":
                text = _inline(token.children)
                story.append(Paragraph(("• " if in_item else "") + text, styles.get(style, body)))
            elif token.type in {"fence", "code_block"}:
                story.append(Paragraph(escape(token.content).replace("\n", "<br/>"), body))
        if not story:
            story = [Paragraph("기록 없음", body)]
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        temp = pdf_path.with_name(f".{pdf_path.name}.{uuid.uuid4().hex}.tmp")

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("MeetingKorean", 8)
            canvas.setFillColor(colors.HexColor("#6b7280"))
            canvas.drawString(20 * mm, 12 * mm, "Standalone Meeting Transcriber · 로컬 회의 기록")
            canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, str(doc.page))
            canvas.restoreState()

        try:
            doc = SimpleDocTemplate(str(temp), pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm,
                topMargin=19 * mm, bottomMargin=23 * mm, title=md_path.stem, author="Standalone Meeting Transcriber")
            doc.build(story, onFirstPage=footer, onLaterPages=footer)
            temp.replace(pdf_path)
        finally:
            temp.unlink(missing_ok=True)


def export_session(snapshot: dict, folder: Path) -> tuple[Path, Path | None, str | None]:
    folder = local_path(folder)
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", snapshot["title"]).strip(" .")[:60] or "회의기록"
    started = datetime.fromisoformat(snapshot["started_at"]).strftime("%Y-%m-%d_%H%M%S")
    stem = f"{started}_{title}_{snapshot['id'][:8]}"
    md_path, pdf_path = folder / f"{stem}.md", folder / f"{stem}.pdf"
    atomic_text(md_path, markdown(snapshot))
    try:
        markdown_to_pdf(md_path, pdf_path)
        return md_path, pdf_path, None
    except Exception as exc:
        from .runtime_log import failure
        failure("export", exc)
        return md_path, None, str(exc)
