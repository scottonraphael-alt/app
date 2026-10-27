"""Textes statiques de la détection de crise (aucune action automatique envers le membre)."""

LEVELS = ("none", "vigilance", "eleve", "urgence")
LEVEL_RANK = {name: index for index, name in enumerate(LEVELS)}

GUIDANCE = {
    "title": "Marche à suivre en cas de risque suicidaire ou de danger",
    "steps": [
        "Reste présent·e et à l'écoute : écoute sans juger, sans minimiser, sans débattre.",
        "Pose la question directement et avec bienveillance : « Penses-tu à te faire du mal ou à mettre fin à tes jours ? ».",
        "Ne promets pas le secret : explique que la sécurité de la personne passe avant, et que tu devras en parler à un coordinateur.",
        "Oriente vers le 3114, numéro national de prévention du suicide, gratuit et joignable 24h/24 et 7j/7.",
        "En danger immédiat (passage à l'acte en cours ou imminent), conseille d'appeler le 15 (SAMU) ou le 112 sans attendre.",
        "SOS Amitié est aussi joignable 24h/24 au 09 72 39 40 50 pour parler à quelqu'un.",
        "Préviens un coordinateur ou un responsable dès maintenant et note ce qui a été dit dans le ticket.",
    ],
    "resources": [
        {"label": "3114 - prévention du suicide (24h/24, 7j/7)", "phone": "3114"},
        {"label": "SAMU - danger immédiat", "phone": "15"},
        {"label": "Numéro d'urgence européen", "phone": "112"},
        {"label": "SOS Amitié (24h/24)", "phone": "09 72 39 40 50"},
    ],
    "reminder": "Iris ne contacte jamais le membre automatiquement : toute réponse est rédigée et envoyée par un helper.",
}

REASON_LABELS = {
    "suicidaire": "Idées suicidaires exprimées",
    "automutilation": "Automutilation évoquée",
    "danger": "Mise en danger imminente possible",
    "violences": "Violences subies évoquées",
    "detresse": "Détresse ou mal-être marqué",
}
