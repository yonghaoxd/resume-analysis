"""Turn an uploaded resume file into plain text."""
import io
import os
import re
import shutil
import subprocess
from pathlib import Path


class ParseError(Exception):
    pass


OCR_MAX_PAGES = 10


def _find_tesseract():
    found = shutil.which("tesseract")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidate = Path(base) / "Tesseract-OCR" / "tesseract.exe"
            if candidate.exists():
                return str(candidate)
    return None


def _ocr_pdf(data: bytes) -> str:
    """Render each page to an image and read it with OCR."""
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = [page.get_pixmap(dpi=300).tobytes("png") for page in list(doc)[:OCR_MAX_PAGES]]

    tesseract = _find_tesseract()
    if tesseract:
        parts = []
        for png in pages:
            run = subprocess.run([tesseract, "stdin", "stdout", "-l", "eng", "--psm", "3"],
                                 input=png, capture_output=True, timeout=120)
            parts.append(run.stdout.decode("utf-8", errors="replace"))
        text = "\n".join(parts)
        # Tesseract's usual misreads in resumes: "AI" as "Al", and the pronoun "I" as "|".
        text = re.sub(r"\bAl\b", "AI", text)
        text = re.sub(r"(?<=[a-zA-Z,.;] )\|(?= [a-z])", "I", text)
        return text

    # Fallback when Tesseract is not installed (slower, and may drop spaces between words).
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    lines = []
    for png in pages:
        result, _ = engine(png)
        lines.extend(item[1] for item in (result or []))
    return "\n".join(lines)


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            if len(text.strip()) < 50:
                # No text layer (scanned, or made with "Microsoft Print to PDF"): read it with OCR.
                text = _ocr_pdf(data)
        elif name.endswith(".docx"):
            from docx import Document

            doc = Document(io.BytesIO(data))
            parts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    parts.extend(cell.text for cell in row.cells)
            text = "\n".join(parts)
        elif name.endswith((".txt", ".md")):
            text = data.decode("utf-8", errors="replace")
        else:
            raise ParseError("Unsupported file type. Upload a PDF, DOCX or TXT file, or paste the text.")
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"Could not read this file ({exc}). Try pasting the resume text instead.")

    if len(text.strip()) < 50:
        raise ParseError(
            "No readable text found in this file. It may be a scanned image. "
            "Paste the resume text instead."
        )
    return text
