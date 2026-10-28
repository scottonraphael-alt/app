"""Parcours d'accueil du staff : modèles de checklist par rôle (surchargeables) et progression par membre."""
from database import db
from services import team

MAX_ITEMS, MAX_LABEL = 30, 140

DEFAULT_LABELS = {
    "staff": [
        "Lire le règlement interne du staff",
        "Rejoindre et parcourir les salons staff sur Discord",
        "Compléter ma fiche dans l'annuaire",
        "Régler mes notifications dans Iris",
        "Renseigner mes disponibilités dans l'agenda",
        "Lire le cahier de passation",
        "Me présenter à l'équipe",
    ],
    "responsable": [
        "Découvrir le tableau de charge de l'équipe",
        "Passer en revue les modèles du parcours d'accueil",
        "Prendre connaissance des procédures d'escalade",
    ],
    "animateur": [
        "Découvrir le calendrier des animations",
        "Lire la charte d'animation",
        "Planifier ma première animation",
    ],
    "operateur": [
        "Découvrir la file des tickets d'opérateur",
        "Lire le guide de modération",
        "Assister à une session de binôme",
    ],
    "admin": [
        "Vérifier les accès et les rôles Discord",
        "Découvrir le tableau d'administration",
    ],
}


def default_items(role: str) -> list[dict]:
    return [{"id": f"{role}-{i}", "label": label} for i, label in enumerate(DEFAULT_LABELS.get(role, []), start=1)]


async def templates() -> dict[str, dict]:
    stored = {d["role"]: d for d in await db.onboarding_templates.find({}, {"_id": 0}).to_list(20)}
    out = {}
    for role in team.ROLE_KEYS:
        doc = stored.get(role)
        out[role] = {
            "role": role, "label": team.ROLE_LABELS[role], "customized": bool(doc),
            "items": doc["items"] if doc else default_items(role),
            "updated_at": doc.get("updated_at") if doc else None,
        }
    return out


def checklist(role_keys: list[str], tpls: dict[str, dict]) -> list[dict]:
    seen: set[str] = set()
    items: list[dict] = []
    for role in role_keys:
        for item in tpls[role]["items"]:
            if item["id"] not in seen:
                seen.add(item["id"])
                items.append({**item, "role": role, "role_label": team.ROLE_LABELS[role]})
    return items


def progress_view(items: list[dict], progress: dict | None) -> dict:
    done_map = (progress or {}).get("done", {})
    rows = [{**i, "done": i["id"] in done_map, "done_at": done_map.get(i["id"])} for i in items]
    done = sum(1 for r in rows if r["done"])
    total = len(rows)
    return {
        "items": rows, "done": done, "total": total,
        "percent": round(100 * done / total) if total else 100,
        "started_at": (progress or {}).get("started_at"),
        "last_activity": max(done_map.values(), default=None),
    }
