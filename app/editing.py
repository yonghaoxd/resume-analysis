"""Apply accepted suggestions to the resume text, and export the result as a Word file.

Edits are applied by plain find-and-replace, never by the AI, so nothing changes
except what the user ticked.
"""
import io
import re

BULLET_CHARS = " \t•-–—*·▪●○■◦"


def _flex_pattern(snippet: str) -> str:
    """Match the snippet regardless of how its whitespace/line breaks fall in the resume."""
    return r"\s+".join(re.escape(tok) for tok in snippet.split())


def _locate(text: str, original: str):
    """Return (start, end, trimmed) for the original sentence in the resume, or None."""
    trimmed_original = original.strip(BULLET_CHARS + ".")
    for candidate, trimmed in ((original.strip(), False), (trimmed_original, True)):
        if len(candidate) < 8:
            continue
        for flags in (0, re.IGNORECASE):
            match = re.search(_flex_pattern(candidate), text, flags)
            if match:
                return match.start(), match.end(), trimmed
    return None


def _section_end_of_heading(text: str, section: str):
    """Position just after the heading line of the named resume section, or None."""
    wanted = section.strip().lower()
    if len(wanted) < 3:
        return None
    for match in re.finditer(r"^[ \t]*(\S.*?)[ \t]*$", text, re.MULTILINE):
        line = match.group(1).lower().strip(":")
        if len(line) <= 40 and (wanted in line or (len(line) >= 4 and line in wanted)):
            return match.end()
    return None


def apply_edits(resume_text: str, edits: list) -> dict:
    """edits: [{"index", "original", "suggested", "section"}] -> segments + what happened to each."""
    ops, appended, not_applied = [], [], []
    for edit in edits:
        suggested = edit["suggested"].strip()
        if not suggested:
            continue
        if edit["original"]:
            found = _locate(resume_text, edit["original"])
            if not found:
                not_applied.append({"index": edit["index"], "suggested": suggested,
                                    "reason": "The original sentence could not be found in the resume text."})
                continue
            start, end, trimmed = found
            new_text = suggested.strip(BULLET_CHARS + ".") if trimmed else suggested
            ops.append((start, end, new_text, edit["index"]))
        else:
            pos = _section_end_of_heading(resume_text, edit["section"])
            if pos is None:
                appended.append((edit["index"], suggested))
            else:
                ops.append((pos, pos, "\n" + suggested, edit["index"]))

    ops.sort(key=lambda op: (op[0], op[1]))
    segments, applied, cursor = [], [], 0
    for start, end, new_text, index in ops:
        if start < cursor:
            not_applied.append({"index": index, "suggested": new_text.strip(),
                                "reason": "It overlaps another selected edit of the same sentence."})
            continue
        if start > cursor:
            segments.append({"text": resume_text[cursor:start], "changed": False})
        segments.append({"text": new_text, "changed": True})
        applied.append(index)
        cursor = end
    if cursor < len(resume_text):
        segments.append({"text": resume_text[cursor:], "changed": False})
    for index, suggested in appended:
        segments.append({"text": "\n", "changed": False})
        segments.append({"text": suggested, "changed": True})

    return {
        "segments": segments,
        "applied": applied,
        "appended": [index for index, _ in appended],
        "not_applied": sorted(not_applied, key=lambda item: item["index"]),
    }


def build_docx(text: str) -> bytes:
    """A clean, simply formatted Word document from plain resume text."""
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    first = True
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        bullet = line[0] in "•-–*·▪●○■◦" and len(line) > 2
        content = line.lstrip(BULLET_CHARS) if bullet else line
        letters = [c for c in content if c.isalpha()]
        is_heading = len(content) <= 40 and len(letters) >= 3 and all(c.isupper() for c in letters)
        if first:
            run = doc.add_paragraph().add_run(content)
            run.bold = True
            run.font.size = Pt(18)
            first = False
        elif bullet:
            doc.add_paragraph(content, style="List Bullet")
        elif is_heading:
            para = doc.add_paragraph()
            para.paragraph_format.space_before = Pt(10)
            para.add_run(content).bold = True
        else:
            doc.add_paragraph(content)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
