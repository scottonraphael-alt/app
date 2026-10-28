"""Mini-formations internes : modules courts avec QCM et suivi de complétion par membre."""
from database import db

PASS_DEFAULT = 70


def question_view(q: dict, *, with_answers: bool) -> dict:
    out = {"text": q["text"], "options": list(q["options"])}
    if with_answers:
        out["correct"] = q["correct"]
        out["explanation"] = q.get("explanation", "")
    return out


def module_view(doc: dict, *, manager: bool, progress: dict | None = None) -> dict:
    out = {
        "id": doc["id"], "title": doc["title"], "summary": doc.get("summary", ""),
        "duration_min": doc.get("duration_min", 5), "pass_percent": doc.get("pass_percent", PASS_DEFAULT),
        "published": doc.get("published", True), "version": doc.get("version", 1),
        "question_count": len(doc.get("questions") or []),
        "updated_at": doc.get("updated_at"),
    }
    prog = progress or {}
    out["completed"] = bool(prog.get("passed") and prog.get("version") == out["version"])
    out["outdated"] = bool(prog.get("passed") and prog.get("version") != out["version"])
    out["best_score"] = prog.get("best_score")
    out["completed_at"] = prog.get("completed_at")
    return out


def detail_view(doc: dict, *, manager: bool, progress: dict | None) -> dict:
    out = module_view(doc, manager=manager, progress=progress)
    out["sections"] = [dict(s) for s in doc.get("sections") or []]
    out["questions"] = [question_view(q, with_answers=manager) for q in doc.get("questions") or []]
    return out


def grade(doc: dict, answers: list[int]) -> dict:
    questions = doc.get("questions") or []
    results = []
    good = 0
    for index, q in enumerate(questions):
        ok = index < len(answers) and answers[index] == q["correct"]
        good += 1 if ok else 0
        results.append({"correct": ok, "explanation": q.get("explanation", "")})
    total = len(questions)
    percent = round(100 * good / total) if total else 100
    return {"score": good, "total": total, "percent": percent,
            "passed": percent >= doc.get("pass_percent", PASS_DEFAULT), "results": results}


async def progress_for(user_id: str) -> dict[str, dict]:
    return {p["training_id"]: p async for p in db.training_progress.find({"user_id": user_id}, {"_id": 0})}
