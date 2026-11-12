"""End-to-end test with the AI replaced by canned answers. Run: python tests/test_app.py"""
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RESUME_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import llm, scoring  # noqa: E402
from app.main import app  # noqa: E402

RESUME = """Jane Tan - Data Analyst
Experience: Built Python dashboards used by 40 sales staff. Wrote SQL reports for finance.
Education: BSc Statistics, University of Malaya.
Skills: Python, SQL, Excel"""
JD = "Data Analyst at Acme. Must have Python and SQL, 3 years of analytics experience, a bachelor degree. Tableau is a plus."

calls = []


def fake_chat(system, user):
    calls.append(system[:20])
    if "analyse job descriptions" in system:
        return {
            "job_title": "Data Analyst", "company": "Acme",
            "requirements": [
                {"text": "Python", "category": "skill", "importance": "must"},
                {"text": "SQL", "category": "skill", "importance": "must"},
                {"text": "Tableau", "category": "skill", "importance": "nice"},
                {"text": "3 years analytics experience", "category": "experience", "importance": "must"},
                {"text": "Bachelor degree", "category": "education", "importance": "must"},
            ],
            "keywords": ["Python", "SQL", "Tableau", "analytics", "Java"],
        }
    return {
        "summary": "Decent fit.",
        "requirements": [
            {"id": "R1", "status": "met", "evidence": "Built Python dashboards", "comment": "Shown."},
            {"id": "R2", "status": "met", "evidence": "Wrote SQL reports that were never written", "comment": "Shown."},
            {"id": "R3", "status": "missing", "evidence": "", "comment": "No Tableau."},
            {"id": "R4", "status": "partial", "evidence": "used by 40 sales staff", "comment": "Years unclear."},
            {"id": "R5", "status": "met", "evidence": "BSc Statistics", "comment": "Has degree."},
        ],
        "quality": {"quantified": 3, "clarity": 4, "structure": 5, "strengths": ["Clear"], "weaknesses": ["Short"]},
        "suggestions": [
            {"priority": "low", "section": "Skills", "original": "", "suggested": "Tableau: [project]",
             "reason": "Only add this if it is true: JD prefers Tableau.", "requirement_ids": ["R3", "R99"]},
            {"priority": "high", "section": "Experience", "original": "Wrote SQL reports for finance.",
             "suggested": "Wrote [X] SQL reports for finance.", "reason": "Quantify.", "requirement_ids": ["R2"]},
        ],
    }


llm.chat_json = fake_chat
client = TestClient(app)

# keyword matching respects word boundaries ("Java" must not match "JavaScript")
assert scoring.split_keywords(["Java", "C++", "sql"], "I know JavaScript, C++ and SQL.") == (["C++", "sql"], ["Java"])

r = client.post("/api/analyze", data={"jd_text": JD, "resume_text": RESUME})
assert r.status_code == 200, r.text
res = r.json()
dims = {d["key"]: d for d in res["dimensions"]}
assert dims["skills"]["earned"] == 24.0          # 30 * (2+2+0)/5
assert dims["experience"]["earned"] == 15.0      # 30 * 0.5
assert dims["education"]["earned"] == 10.0
assert dims["keywords"]["earned"] == 6.0         # Python, SQL of 5
assert dims["quality"]["earned"] == 12.0         # 15 * 12/15
assert res["total"] == 67, res["total"]
assert res["keywords"]["missing"] == ["Tableau", "analytics", "Java"]
reqs = {q["id"]: q for q in res["requirements"]}
assert reqs["R1"]["evidence_verified"] is True
assert reqs["R2"]["evidence_verified"] is False  # invented quote is flagged
assert [s["priority"] for s in res["suggestions"]] == ["high", "low"]
assert res["suggestions"][1]["requirement_ids"] == ["R3"]  # unknown id dropped
assert res["previous"] is None
assert len(calls) == 2

# re-test of the same job reuses the stored requirement breakdown and reports the previous score
r2 = client.post("/api/analyze", data={"jd_text": JD + "  ", "resume_text": RESUME})
assert len(calls) == 3
assert r2.json()["previous"]["total"] == 67

# file upload path + error handling
up = client.post("/api/analyze", data={"jd_text": JD}, files={"resume_file": ("cv.txt", io.BytesIO(RESUME.encode()))})
assert up.status_code == 200 and up.json()["resume_name"] == "cv.txt"
assert client.post("/api/analyze", data={"jd_text": JD}, files={"resume_file": ("cv.png", io.BytesIO(b"x" * 99))}).status_code == 400
assert client.post("/api/analyze", data={"jd_text": "", "resume_text": RESUME}).status_code == 400

# apply selected edits: rewrite is replaced in place, addition goes under its section heading
ap = client.post("/api/apply", json={"analysis_id": res["id"], "edits": [
    {"index": 0, "suggested": "Wrote 12 SQL reports for finance."},
    {"index": 1, "suggested": "Tableau: sales dashboard"},
]}).json()
edited = "".join(s["text"] for s in ap["segments"])
assert "Wrote 12 SQL reports for finance." in edited and "Wrote SQL reports" not in edited
assert "Skills: Python, SQL, Excel\nTableau: sales dashboard" in edited
assert sorted(ap["applied"]) == [0, 1] and not ap["not_applied"] and not ap["appended"]
assert [s["text"] for s in ap["segments"] if s["changed"]] == ["Wrote 12 SQL reports for finance.", "\nTableau: sales dashboard"]
# untouched text is byte-identical
assert edited.replace("Wrote 12 SQL reports for finance.", "Wrote SQL reports for finance.").replace("\nTableau: sales dashboard", "") == RESUME

from app import editing  # noqa: E402
# original wrapped across lines / different bullet still matches; unknown sentence is reported, not guessed
out = editing.apply_edits("• Built Python\n  dashboards for sales.\nOther line here.", [
    {"index": 0, "original": "Built Python dashboards for sales.", "suggested": "Built 5 Python dashboards.", "section": "Experience"},
    {"index": 1, "original": "A sentence that is not there.", "suggested": "X", "section": "Experience"},
    {"index": 2, "original": "", "suggested": "New cert", "section": "Certifications"},
])
assert "".join(s["text"] for s in out["segments"]) == "• Built 5 Python dashboards.\nOther line here.\nNew cert"
assert out["applied"] == [0] and out["appended"] == [2] and out["not_applied"][0]["index"] == 1

dx = client.post("/api/export-docx", json={"text": edited})
assert dx.status_code == 200 and dx.content[:2] == b"PK"
assert client.post("/api/apply", json={"analysis_id": res["id"], "edits": [{"index": 9, "suggested": "x"}]}).status_code == 400

# history, fetch, delete
hist = client.get("/api/history").json()
assert len(hist) == 3 and hist[0]["id"] > hist[1]["id"]
assert client.get(f"/api/analysis/{res['id']}").json()["total"] == 67
assert client.delete(f"/api/analysis/{res['id']}").status_code == 200
assert client.get(f"/api/analysis/{res['id']}").status_code == 404
assert client.get("/").status_code == 200

print("ALL TESTS PASSED")
