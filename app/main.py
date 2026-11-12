from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import analyzer, db, editing, llm, parsing

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

app = FastAPI(title="Resume Match Checker")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-store"})


@app.post("/api/analyze")
def analyze(
    jd_text: str = Form(""),
    resume_text: str = Form(""),
    resume_file: UploadFile | None = File(None),
    resume_label: str = Form(""),
):
    resume_name = resume_label.strip()[:80] or "Pasted text"
    try:
        if resume_file is not None and resume_file.filename:
            data = resume_file.file.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                raise parsing.ParseError("File is larger than 10 MB.")
            resume_text = parsing.extract_text(resume_file.filename, data)
            resume_name = resume_file.filename
        return analyzer.analyze(resume_text, jd_text, resume_name)
    except (parsing.ParseError, analyzer.InputError) as exc:
        raise HTTPException(400, str(exc))
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))


class EditChoice(BaseModel):
    index: int
    suggested: str


class ApplyRequest(BaseModel):
    analysis_id: int
    edits: list[EditChoice]


class ExportRequest(BaseModel):
    text: str


@app.post("/api/apply")
def apply_edits(req: ApplyRequest):
    result = db.get(req.analysis_id)
    if not result:
        raise HTTPException(404, "Analysis not found.")
    if not result.get("resume_text"):
        raise HTTPException(400, "This older analysis did not save the resume text. Run a new analysis first.")
    suggestions = result["suggestions"]
    edits = []
    for choice in req.edits:
        if not 0 <= choice.index < len(suggestions):
            raise HTTPException(400, "Unknown suggestion.")
        source = suggestions[choice.index]
        edits.append({"index": choice.index, "original": source["original"],
                      "section": source["section"], "suggested": choice.suggested})
    return editing.apply_edits(result["resume_text"], edits)


@app.post("/api/export-docx")
def export_docx(req: ExportRequest):
    if not req.text.strip():
        raise HTTPException(400, "Nothing to export.")
    return Response(
        editing.build_docx(req.text),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="resume-edited.docx"'},
    )


@app.get("/api/history")
def history():
    return db.list_all()


@app.get("/api/analysis/{analysis_id}")
def get_analysis(analysis_id: int):
    result = db.get(analysis_id)
    if not result:
        raise HTTPException(404, "Analysis not found.")
    return result


@app.delete("/api/analysis/{analysis_id}")
def delete_analysis(analysis_id: int):
    if not db.delete(analysis_id):
        raise HTTPException(404, "Analysis not found.")
    return {"ok": True}
