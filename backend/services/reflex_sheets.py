"""Fiches réflexes : contenu par défaut (texte statique) et personnalisations des responsables.

Une fiche par défaut peut être modifiée (la version modifiée est stockée dans `reflex_sheets`) et
rétablie ; les fiches ajoutées par les responsables n'existent qu'en base.
"""
from database import db

URG = {"label": "SAMU - danger immédiat", "phone": "15"}
EU = {"label": "Numéro d'urgence européen", "phone": "112"}

DEFAULT_SHEETS = [
    {
        "slug": "crise-suicidaire", "title": "Crise suicidaire", "icon": "heart-pulse",
        "summary": "Une personne exprime des idées suicidaires ou un projet de passage à l'acte.",
        "steps": [
            "Reste présent·e et à l'écoute, sans juger ni minimiser.",
            "Pose la question directement : « Penses-tu à mettre fin à tes jours ? ». Poser la question ne donne pas l'idée.",
            "Évalue l'urgence : un plan, un moyen, une date ? Si oui, c'est un danger immédiat.",
            "Oriente vers le 3114 (24h/24, gratuit). En danger immédiat, conseille le 15 ou le 112.",
            "Ne promets pas le secret : explique que tu dois en parler à un coordinateur.",
            "Préviens un coordinateur ou un responsable tout de suite et note les faits dans le ticket.",
        ],
        "do_not": ["Ne laisse pas la conversation sans réponse.", "Ne débats pas du bien-fondé de son geste.", "Ne rédige jamais de promesse de confidentialité."],
        "resources": [{"label": "3114 - prévention du suicide (24h/24)", "phone": "3114"}, URG, EU,
                      {"label": "SOS Amitié (24h/24)", "phone": "09 72 39 40 50"}],
    },
    {
        "slug": "automutilation", "title": "Automutilation", "icon": "bandage",
        "summary": "Une personne évoque des scarifications, une rechute ou une envie de se faire du mal.",
        "steps": [
            "Accueille sans dramatiser ni dégoûter : remercie la personne de t'en parler.",
            "Demande si elle est en sécurité maintenant et si des soins sont nécessaires (blessure à soigner).",
            "Ne demande pas de détails graphiques et ne demande pas de photos.",
            "Propose des alternatives de relais (respiration, glaçon, appeler quelqu'un) sans les imposer.",
            "Oriente vers un professionnel (médecin traitant, CMP) et le 3114 si des idées suicidaires apparaissent.",
            "Informe un coordinateur et note les éléments dans le ticket.",
        ],
        "do_not": ["Ne culpabilise pas et ne demande pas d'arrêter immédiatement.", "Ne partage pas de détails de méthode."],
        "resources": [{"label": "3114 - si idées suicidaires", "phone": "3114"}, URG],
    },
    {
        "slug": "violences", "title": "Violences subies", "icon": "shield-alert",
        "summary": "Violences physiques, sexuelles, conjugales ou familiales évoquées.",
        "steps": [
            "Crois la personne et rappelle que ce n'est pas sa faute.",
            "Vérifie sa sécurité immédiate : est-elle en sécurité là où elle se trouve ?",
            "En danger immédiat : 17 (police) ou 112 ; par SMS au 114 si elle ne peut pas parler.",
            "Oriente vers le 3919 (violences conjugales, 24h/24) ou le 119 si la personne est mineure.",
            "N'exige pas de preuve ni de récit détaillé ; ne la presse pas de porter plainte.",
            "Alerte un coordinateur et note les faits sans interprétation.",
        ],
        "do_not": ["Ne confronte jamais l'auteur présumé.", "Ne promets pas que tout ira bien."],
        "resources": [{"label": "3919 - violences conjugales (24h/24)", "phone": "3919"},
                      {"label": "Police secours", "phone": "17"}, EU,
                      {"label": "SMS d'urgence si on ne peut pas parler", "phone": "114"}],
    },
    {
        "slug": "harcelement", "title": "Harcèlement", "icon": "message-square-warning",
        "summary": "Harcèlement scolaire, en ligne ou au travail, subi par un membre.",
        "steps": [
            "Écoute et valide le ressenti : le harcèlement est réel, même s'il est « seulement » en ligne.",
            "Conseille de garder des preuves (captures d'écran, dates) et de ne pas répondre aux agresseurs.",
            "Oriente vers le 3018 (harcèlement en ligne) ou le 3020 (harcèlement scolaire).",
            "Évoque la possibilité d'en parler à un adulte de confiance, sans l'y forcer.",
            "Si des idées noires apparaissent, bascule sur la fiche « Crise suicidaire ».",
        ],
        "do_not": ["Ne minimise pas (« ça passera »).", "Ne conseille pas de se venger."],
        "resources": [{"label": "3018 - harcèlement en ligne", "phone": "3018"},
                      {"label": "3020 - harcèlement scolaire", "phone": "3020"}],
    },
    {
        "slug": "mineur-en-danger", "title": "Mineur en danger", "icon": "baby",
        "summary": "Une personne mineure semble en danger (maltraitance, abus, fugue, isolement grave).",
        "steps": [
            "Reste calme, écoute, et ne promets pas le secret : tu dois alerter.",
            "Évalue le danger immédiat. Si oui : 17 ou 112 sans attendre.",
            "Oriente la personne vers le 119 (Allô Enfance en danger, 24h/24, gratuit).",
            "Prévenir sans délai un coordinateur : une information préoccupante doit être transmise.",
            "Ne mène pas d'enquête et ne pose pas de questions suggestives ; note ses mots exacts.",
        ],
        "do_not": ["Ne contacte jamais la famille ou l'agresseur présumé.", "Ne garde pas l'information pour toi."],
        "resources": [{"label": "119 - Allô Enfance en danger (24h/24)", "phone": "119"},
                      {"label": "Police secours", "phone": "17"}, EU],
    },
]
DEFAULT_BY_SLUG = {s["slug"]: s for s in DEFAULT_SHEETS}

# Libellés de raisons de crise (ticket_crisis_constants.REASON_LABELS) -> fiche.
REASON_TO_SLUG = {
    "suicidaire": "crise-suicidaire", "automutilation": "automutilation",
    "danger": "mineur-en-danger", "violences": "violences", "detresse": "crise-suicidaire",
}
MAX_SHEETS = 30


def view(doc: dict, *, custom: bool, default: bool) -> dict:
    return {
        "slug": doc["slug"], "title": doc["title"], "icon": doc.get("icon", ""), "summary": doc.get("summary", ""),
        "steps": list(doc.get("steps") or []), "do_not": list(doc.get("do_not") or []),
        "resources": [dict(r) for r in doc.get("resources") or []],
        "customized": custom and default, "builtin": default,
        "updated_at": doc.get("updated_at"), "updated_by": doc.get("updated_by"),
    }


async def list_sheets() -> list[dict]:
    stored = {d["slug"]: d async for d in db.reflex_sheets.find({}, {"_id": 0})}
    out = [view(stored.get(s["slug"], s), custom=s["slug"] in stored, default=True) for s in DEFAULT_SHEETS]
    out += [view(d, custom=True, default=False) for slug, d in sorted(stored.items()) if slug not in DEFAULT_BY_SLUG]
    return out


async def get_sheet(slug: str) -> dict | None:
    stored = await db.reflex_sheets.find_one({"slug": slug}, {"_id": 0})
    if stored:
        return view(stored, custom=True, default=slug in DEFAULT_BY_SLUG)
    default = DEFAULT_BY_SLUG.get(slug)
    return view(default, custom=False, default=True) if default else None
