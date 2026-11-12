"""Deterministic scoring. The AI supplies judgements; all arithmetic happens here."""
import re

DIMENSIONS = [
    ("skills", "Skills Match", 30),
    ("experience", "Experience Relevance", 30),
    ("keywords", "Keyword Coverage", 15),
    ("quality", "Resume Quality", 15),
    ("education", "Education & Certifications", 10),
]
CATEGORY_TO_DIM = {"skill": "skills", "experience": "experience", "education": "education"}
STATUS_VALUE = {"met": 1.0, "partial": 0.5, "missing": 0.0}
IMPORTANCE_WEIGHT = {"must": 2, "nice": 1}
QUALITY_ASPECTS = [
    ("quantified", "Quantified achievements"),
    ("clarity", "Clarity and conciseness"),
    ("structure", "Structure and formatting"),
]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def keyword_in_text(keyword: str, norm_text: str) -> bool:
    kw = normalize(keyword)
    if not kw:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", norm_text) is not None


def split_keywords(keywords, resume_text):
    norm = normalize(resume_text)
    found, missing, seen = [], [], set()
    for kw in keywords:
        key = normalize(kw)
        if not key or key in seen:
            continue
        seen.add(key)
        (found if keyword_in_text(kw, norm) else missing).append(kw.strip())
    return found, missing


def compute(requirements, keywords_found, keywords_missing, quality):
    """Fill per-requirement points in place and return (total, dimensions)."""
    dims = []
    for key, label, max_pts in DIMENSIONS:
        dim = {"key": key, "label": label, "max": max_pts, "earned": 0.0,
               "applicable": True, "gained": [], "lost": []}

        if key in ("skills", "experience", "education"):
            reqs = [r for r in requirements if CATEGORY_TO_DIM[r["category"]] == key]
            total_weight = sum(IMPORTANCE_WEIGHT[r["importance"]] for r in reqs)
            if not reqs:
                dim["applicable"] = False
            for r in reqs:
                r["max_points"] = round(max_pts * IMPORTANCE_WEIGHT[r["importance"]] / total_weight, 1)
                r["points"] = round(r["max_points"] * STATUS_VALUE[r["status"]], 1)
                dim["earned"] += r["points"]
                tag = "Must-have" if r["importance"] == "must" else "Nice-to-have"
                if r["points"] > 0:
                    dim["gained"].append({"points": r["points"], "text": f"{tag}: {r['text']}",
                                          "note": r["comment"]})
                lost = round(r["max_points"] - r["points"], 1)
                if lost > 0:
                    dim["lost"].append({"points": lost, "text": f"{tag}: {r['text']}",
                                        "note": r["comment"]})

        elif key == "keywords":
            n = len(keywords_found) + len(keywords_missing)
            if n == 0:
                dim["applicable"] = False
            else:
                dim["earned"] = max_pts * len(keywords_found) / n
                if keywords_found:
                    dim["gained"].append({
                        "points": round(dim["earned"], 1),
                        "text": f"{len(keywords_found)} of {n} job keywords appear in the resume",
                        "note": ", ".join(keywords_found)})
                if keywords_missing:
                    dim["lost"].append({
                        "points": round(max_pts - dim["earned"], 1),
                        "text": f"{len(keywords_missing)} job keywords not found in the resume",
                        "note": ", ".join(keywords_missing)})

        else:  # quality
            per = max_pts / len(QUALITY_ASPECTS)
            for aspect, aspect_label in QUALITY_ASPECTS:
                rating = quality[aspect]
                pts = round(per * rating / 5, 1)
                dim["earned"] += pts
                if pts > 0:
                    dim["gained"].append({"points": pts, "text": f"{aspect_label}: {rating}/5", "note": ""})
                if per - pts > 0.05:
                    dim["lost"].append({"points": round(per - pts, 1),
                                        "text": f"{aspect_label}: {rating}/5", "note": ""})
            for s in quality["strengths"]:
                dim["gained"].append({"points": None, "text": s, "note": ""})
            for w in quality["weaknesses"]:
                dim["lost"].append({"points": None, "text": w, "note": ""})

        dim["earned"] = round(min(dim["earned"], max_pts), 1) if dim["applicable"] else None
        dims.append(dim)

    # Dimensions the job description says nothing about are left out and the
    # rest is rescaled, so a job with no education requirement can still reach 100.
    applicable_max = sum(d["max"] for d in dims if d["applicable"])
    earned = sum(d["earned"] for d in dims if d["applicable"])
    total = round(100 * earned / applicable_max) if applicable_max else 0
    return total, dims
