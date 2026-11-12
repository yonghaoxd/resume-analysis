"""Orchestrates one analysis: JD breakdown -> requirement check -> score -> save."""
import hashlib
import json
from datetime import datetime

from . import db, llm, scoring

MAX_RESUME_CHARS = 20000
MAX_JD_CHARS = 12000

JD_SYSTEM = """You analyse job descriptions. Write everything in English, even if the input is in another language.
Return a JSON object with exactly these fields:
{
  "job_title": string,
  "company": string or null,
  "requirements": [
    {"text": string, "category": "skill" | "experience" | "education", "importance": "must" | "nice"}
  ],
  "keywords": [string]
}
Rules:
- requirements: 6 to 18 distinct, concrete, checkable requirements taken from the job description. One requirement per item; do not merge unrelated ones and do not invent requirements that are not stated or clearly implied.
- category "skill" = tools, technologies, languages, soft skills. "experience" = years, responsibilities, domain or industry background. "education" = degrees, certifications, licences.
- importance "must" = required or core to the role. "nice" = preferred, bonus, or "a plus".
- keywords: 10 to 20 short terms (1-3 words) a recruiter or ATS would search for, written exactly as they appear in the job description."""

EVAL_SYSTEM = """You are a strict, fair resume reviewer. Compare the resume against the numbered job requirements. Write everything in English, even if the inputs are in another language.
Return a JSON object with exactly these fields:
{
  "summary": string,
  "requirements": [
    {"id": string, "status": "met" | "partial" | "missing", "evidence": string, "comment": string}
  ],
  "quality": {
    "quantified": integer 0-5,
    "clarity": integer 0-5,
    "structure": integer 0-5,
    "strengths": [string],
    "weaknesses": [string]
  },
  "suggestions": [
    {"priority": "high" | "medium" | "low", "section": string, "original": string,
     "suggested": string, "reason": string, "requirement_ids": [string]}
  ]
}
Rules:
- summary: 2-3 sentences on overall fit for this job.
- requirements: one entry for every requirement id given, no extras. "met" = clearly demonstrated. "partial" = related or weaker evidence. "missing" = nothing in the resume supports it.
- evidence: a short quote copied word-for-word from the resume (max 200 characters) that supports the status. Use "" when status is "missing". Never paraphrase or invent a quote.
- comment: one sentence explaining the status.
- quality rates the resume itself: "quantified" = achievements backed by numbers; "clarity" = concise, specific, strong action verbs; "structure" = logical sections and ordering. strengths and weaknesses: up to 3 short items each.
- suggestions: 5 to 10 concrete edits that would make the resume fit this job better, most impactful first.
  - To improve existing wording: "original" is the exact sentence or bullet from the resume and "suggested" is the rewritten version.
  - NEVER invent experience, skills, employers, numbers or qualifications. Rewrites may only rephrase, reorder or emphasise what the resume already states. If a number would help but is not in the resume, use a placeholder such as [X%].
  - For a requirement the resume does not cover: set "original" to "" and make "suggested" a template line with [placeholders], and start "reason" with "Only add this if it is true:".
  - "section" is the resume section the edit belongs to (e.g. Summary, Experience, Skills).
  - "requirement_ids" lists the requirement ids the edit helps with (may be empty)."""


class InputError(Exception):
    pass


def _clean_job(raw: dict) -> dict:
    reqs = []
    for item in raw.get("requirements") or []:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        category = item.get("category") if item.get("category") in scoring.CATEGORY_TO_DIM else "skill"
        importance = item.get("importance") if item.get("importance") in scoring.IMPORTANCE_WEIGHT else "must"
        reqs.append({"id": f"R{len(reqs) + 1}", "text": str(item["text"]).strip(),
                     "category": category, "importance": importance})
    if not reqs:
        raise llm.LLMError("Could not find any requirements in the job description. Is it complete?")
    keywords = [str(k).strip() for k in raw.get("keywords") or [] if str(k).strip()]
    return {
        "job_title": str(raw.get("job_title") or "Untitled role").strip(),
        "company": (str(raw["company"]).strip() if raw.get("company") else None),
        "requirements": reqs,
        "keywords": keywords,
    }


def _rating(value) -> int:
    try:
        return max(0, min(5, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _strings(value, limit):
    return [str(v).strip() for v in (value or []) if str(v).strip()][:limit]


def _merge_evaluation(job: dict, raw: dict, resume_text: str):
    by_id = {str(e.get("id")): e for e in raw.get("requirements") or [] if isinstance(e, dict)}
    norm_resume = scoring.normalize(resume_text)
    requirements = []
    for req in job["requirements"]:
        ev = by_id.get(req["id"], {})
        status = ev.get("status") if ev.get("status") in scoring.STATUS_VALUE else "missing"
        evidence = str(ev.get("evidence") or "").strip()
        verified = bool(evidence) and scoring.normalize(evidence).strip(" .…\"'") in norm_resume
        requirements.append({**req, "status": status, "evidence": evidence,
                             "evidence_verified": verified,
                             "comment": str(ev.get("comment") or "").strip()})

    q = raw.get("quality") if isinstance(raw.get("quality"), dict) else {}
    quality = {
        "quantified": _rating(q.get("quantified")),
        "clarity": _rating(q.get("clarity")),
        "structure": _rating(q.get("structure")),
        "strengths": _strings(q.get("strengths"), 3),
        "weaknesses": _strings(q.get("weaknesses"), 3),
    }

    valid_ids = {r["id"] for r in job["requirements"]}
    order = {"high": 0, "medium": 1, "low": 2}
    suggestions = []
    for s in raw.get("suggestions") or []:
        if not isinstance(s, dict) or not str(s.get("suggested", "")).strip():
            continue
        suggestions.append({
            "priority": s.get("priority") if s.get("priority") in order else "medium",
            "section": str(s.get("section") or "General").strip(),
            "original": str(s.get("original") or "").strip(),
            "suggested": str(s["suggested"]).strip(),
            "reason": str(s.get("reason") or "").strip(),
            "requirement_ids": [str(i) for i in (s.get("requirement_ids") or []) if str(i) in valid_ids],
        })
    suggestions.sort(key=lambda s: order[s["priority"]])
    return requirements, quality, suggestions


def analyze(resume_text: str, jd_text: str, resume_name: str) -> dict:
    resume_text = (resume_text or "").strip()[:MAX_RESUME_CHARS]
    jd_text = (jd_text or "").strip()[:MAX_JD_CHARS]
    if len(resume_text) < 50:
        raise InputError("The resume is empty or too short.")
    if len(jd_text) < 50:
        raise InputError("The job scope is empty or too short.")

    # The same job description always reuses its first breakdown, so re-tests
    # of an edited resume are scored against identical requirements.
    jd_hash = hashlib.sha256(scoring.normalize(jd_text).encode()).hexdigest()
    previous_row = db.latest_for_jd(jd_hash)
    if previous_row:
        job = json.loads(previous_row["jd_json"])
    else:
        job = _clean_job(llm.chat_json(JD_SYSTEM, f"JOB DESCRIPTION:\n{jd_text}"))

    req_lines = "\n".join(
        f"{r['id']} [{r['category']}, {r['importance']}]: {r['text']}" for r in job["requirements"]
    )
    raw = llm.chat_json(
        EVAL_SYSTEM,
        f"JOB TITLE: {job['job_title']}\n\nJOB REQUIREMENTS:\n{req_lines}\n\n"
        f"FULL JOB DESCRIPTION:\n{jd_text}\n\nRESUME:\n{resume_text}",
    )
    requirements, quality, suggestions = _merge_evaluation(job, raw, resume_text)
    found, missing = scoring.split_keywords(job["keywords"], resume_text)
    total, dimensions = scoring.compute(requirements, found, missing, quality)

    previous = None
    if previous_row:
        prev = json.loads(previous_row["result_json"])
        previous = {
            "id": previous_row["id"],
            "created_at": previous_row["created_at"],
            "total": previous_row["total"],
            "dimensions": {d["key"]: d["earned"] for d in prev["dimensions"]},
        }

    created_at = datetime.now().isoformat(timespec="seconds")
    result = {
        "created_at": created_at,
        "job_title": job["job_title"],
        "company": job["company"],
        "resume_name": resume_name,
        "total": total,
        "summary": str(raw.get("summary") or "").strip(),
        "dimensions": dimensions,
        "requirements": requirements,
        "keywords": {"found": found, "missing": missing},
        "suggestions": suggestions,
        "previous": previous,
        "jd_text": jd_text,
        "resume_text": resume_text,
    }
    result["id"] = db.save(created_at, jd_hash, job, resume_name, total, result)
    return result
