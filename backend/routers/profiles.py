from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from models.ticket import AuthenticatedHelper, HelperProfile, HelperProfileUpdate
from services.auth_service import current_helper, get_helper_role_flags


router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/me", response_model=HelperProfile)
async def get_my_profile(
    helper: AuthenticatedHelper = Depends(current_helper),
) -> HelperProfile:
    profile = await db.helper_profiles.find_one({"helper_id": helper.id}, {"_id": 0})
    if not profile:
        return HelperProfile(helper_id=helper.id)
    return profile


@router.put("/me", response_model=HelperProfile)
async def update_my_profile(
    input_data: HelperProfileUpdate,
    helper: AuthenticatedHelper = Depends(current_helper),
) -> HelperProfile:
    profile = HelperProfile(
        helper_id=helper.id,
        triggers=input_data.triggers.strip(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    await db.helper_profiles.update_one(
        {"helper_id": helper.id},
        {"$set": profile.model_dump()},
        upsert=True,
    )
    return profile


MAX_FAVORITES = 12
# clé -> (libellé, chemin, rôles autorisés ; None = tout le monde, "helper" = helper/admin/responsable)
FAVORITE_PAGES = {
    "accueil": ("Accueil", "/", {"helper"}),
    "suivis": ("Suivis", "/suivis", {"helper"}),
    "archives": ("Archives", "/archives", {"helper"}),
    "ressources": ("Ressources", "/resources", {"helper"}),
    "coordination": ("Coordination", "/admin", {"admin", "responsable"}),
    "calendrier": ("Calendrier", "/staff/calendrier", {"helper", "staff", "operateur"}),
    "reunions": ("Réunions", "/staff/meetings", {"helper", "staff", "operateur"}),
    "decisions": ("Registre des décisions", "/staff/decisions", {"helper", "staff", "operateur"}),
    "taches": ("Tâches", "/staff/taches", {"helper", "staff", "operateur"}),
    "casier": ("Casier", "/moderation/casiers", {"operateur", "responsable"}),
    "projets": ("Projets", "/animateur/projects", {"animateur", "responsable"}),
    "calendrier_projets": ("Calendrier projets", "/animateur/calendrier", {"animateur", "responsable"}),
    "logs": ("Logs", "/responsable/auth-logs", {"responsable"}),
    "archives_salons": ("Archives salons", "/responsable/archives-salons", {"responsable"}),
    "annonces": ("Annonces", "/responsable/annonces", {"responsable"}),
    "statistiques": ("Statistiques", "/responsable/statistiques", {"responsable"}),
    "acces_sanctions": ("Accès sanctions", "/responsable/acces-sanctions", {"responsable"}),
    "passation": ("Passation", "/staff/passation", {"staff"}),
    "notifications": ("Notifications", "/notifications", None),
    "charge": ("Charge d'équipe", "/responsable/charge", {"responsable", "admin"}),
    "rapports": ("Rapports", "/responsable/rapports", {"responsable", "admin"}),
    "membres": ("Vue membre", "/moderation/membres", {"operateur", "responsable"}),
    "kanban": ("Tableau des suivis", "/kanban", {"helper"}),
    "sondages": ("Sondages de créneaux", "/staff/sondages", {"helper", "staff", "operateur"}),
    "revue_ia": ("Revue rapide IA", "/moderation/revue-ia", {"operateur", "responsable"}),
    "stats_moderation": ("Statistiques de modération", "/moderation/statistiques", {"responsable"}),
    "chronologie": ("Chronologie des projets", "/animateur/projects/chronologie", {"animateur", "responsable", "staff"}),
    "annuaire": ("Annuaire du staff", "/staff/annuaire", {"helper", "staff", "operateur", "animateur"}),
    "kudos": ("Remerciements", "/staff/kudos", {"helper", "staff", "operateur", "animateur"}),
    "parcours_accueil": ("Parcours d'accueil", "/staff/accueil", {"helper", "staff", "operateur", "animateur"}),
    "meteo_equipe": ("Météo de l'équipe", "/staff/meteo-equipe", {"helper", "staff", "operateur", "animateur"}),
    "fiches_reflexes": ("Fiches réflexes", "/staff/fiches-reflexes", {"helper", "staff", "operateur", "animateur"}),
    "formations": ("Mini-formations", "/staff/formations", {"helper", "staff", "operateur", "animateur"}),
    "sante_systeme": ("Santé du système", "/responsable/sante-systeme", {"responsable"}),
    "reglages": ("Réglages", "/responsable/reglages", {"responsable"}),
    "profil": ("Mon profil", "/profile", None),
}


def _allowed_pages(flags: dict) -> list[str]:
    roles = {name.removeprefix("is_") for name, value in flags.items() if value}
    if roles & {"admin", "responsable"}:
        roles.add("helper")
    return [key for key, (_, _, needed) in FAVORITE_PAGES.items() if needed is None or roles & needed]


def _default_favorites(allowed: list[str]) -> list[str]:
    wanted = ["suivis", "calendrier", "reunions", "taches", "casier", "projets", "calendrier_projets", "logs", "statistiques"]
    return [key for key in wanted if key in allowed][:6] or [key for key in allowed if key != "profil"][:4]


class FavoritesUpdate(BaseModel):
    favorites: list[str] = Field(max_length=MAX_FAVORITES)


async def _favorites_payload(helper_id: str, stored: list | None) -> dict:
    allowed = _allowed_pages(await get_helper_role_flags(helper_id))
    if stored is None:
        favorites, is_default = _default_favorites(allowed), True
    else:
        favorites, is_default = [key for key in stored if key in allowed], False
    return {
        "favorites": favorites,
        "is_default": is_default,
        "available": [{"key": key, "label": FAVORITE_PAGES[key][0], "path": FAVORITE_PAGES[key][1]} for key in allowed],
    }


@router.get("/me/favorites")
async def get_my_favorites(helper: AuthenticatedHelper = Depends(current_helper)) -> dict:
    profile = await db.helper_profiles.find_one({"helper_id": helper.id}, {"_id": 0, "favorites": 1})
    stored = (profile or {}).get("favorites")
    return await _favorites_payload(helper.id, stored if isinstance(stored, list) else None)


@router.put("/me/favorites")
async def update_my_favorites(
    input_data: FavoritesUpdate, helper: AuthenticatedHelper = Depends(current_helper),
) -> dict:
    allowed = _allowed_pages(await get_helper_role_flags(helper.id))
    keys = input_data.favorites
    if len(set(keys)) != len(keys):
        raise HTTPException(status_code=422, detail="Favoris en double.")
    if any(key not in allowed for key in keys):
        raise HTTPException(status_code=422, detail="Page inconnue ou non accessible.")
    await db.helper_profiles.update_one(
        {"helper_id": helper.id},
        {"$set": {"favorites": keys, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return await _favorites_payload(helper.id, keys)
