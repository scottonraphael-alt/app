"""Vérifications mécaniques automatiques basées sur le règlement de L'Oasis.

Ce module ne fait AUCUN appel réseau et ne nécessite aucun modèle d'IA.
Il détecte les violations explicites et non ambiguës du règlement, avant
de solliciter le classifieur ONNX ou le LLM local.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TRIGGER_WORDS = [
    "suicide", "suicidaire", "automutilation", "scarification",
    "sang", "agression", "agressé", "agressée",
    "mort", "mourir", "harcèlement", "harcelé", "harcelée",
    "viol", "violé", "violée", "violence", "drogue", "drogues",
]

SPOILER_PATTERN = re.compile(r"\|\|.*?\|\|", re.DOTALL)

DISCORD_INVITE_PATTERN = re.compile(
    r"(discord\.gg/|discord\.com/invite/)\S+", re.IGNORECASE
)

DONATION_PATTERN = re.compile(
    r"(leetchi\.com|paypal\.me|cagnotte|gofundme|ko-?fi\.com|patreon\.com)",
    re.IGNORECASE,
)

MP_REDIRECT_PATTERN = re.compile(
    r"\b(mp|dm|message priv[ée])\b.*\b(aide|aider|parler|écoute)\b"
    r"|\b(aide|aider|parler|écoute)\b.*\b(mp|dm|message priv[ée])\b",
    re.IGNORECASE,
)


@dataclass
class RuleViolation:
    rule: str
    reason: str


@dataclass
class RulesCheckResult:
    violations: list[RuleViolation] = field(default_factory=list)
    is_suspect: bool = False

    def add(self, rule: str, reason: str) -> None:
        self.violations.append(RuleViolation(rule=rule, reason=reason))
        self.is_suspect = True


def _strip_spoilers(content: str) -> str:
    """Retire les portions déjà correctement placées en spoiler."""
    return SPOILER_PATTERN.sub("", content)


def check_trigger_words_without_spoiler(content: str) -> RuleViolation | None:
    remaining = _strip_spoilers(content)
    lowered = remaining.lower()
    for word in TRIGGER_WORDS:
        if word in lowered:
            return RuleViolation(
                rule="Titre II.A – Mots triggers sans balises spoiler",
                reason=f"Le mot « {word} » apparaît sans être entouré de ||balises spoiler||.",
            )
    return None


def check_discord_invite_links(content: str) -> RuleViolation | None:
    if DISCORD_INVITE_PATTERN.search(content):
        return RuleViolation(
            rule="Titre II.C – Publicité",
            reason="Le message contient un lien d'invitation vers un autre serveur Discord.",
        )
    return None


def check_donation_links(content: str) -> RuleViolation | None:
    if DONATION_PATTERN.search(content):
        return RuleViolation(
            rule="Titre II.C – Cagnottes, prêt d'argent",
            reason="Le message contient un lien de cagnotte, don ou plateforme de paiement.",
        )
    return None


def check_mp_redirect_for_help(content: str) -> RuleViolation | None:
    if MP_REDIRECT_PATTERN.search(content):
        return RuleViolation(
            rule="Titre III.C – Aide des membres (redirection en MP interdite)",
            reason="Le message semble rediriger vers les messages privés pour de l'aide, ce qui est interdit.",
        )
    return None


CHECKS = [
    check_trigger_words_without_spoiler,
    check_discord_invite_links,
    check_donation_links,
    check_mp_redirect_for_help,
]


def run_mechanical_checks(content: str) -> RulesCheckResult:
    """Exécute toutes les vérifications mécaniques (regex) sur un message.

    Ne remplace jamais le jugement du LLM : sert uniquement à détecter
    les violations factuelles et évidentes, ou à décider si un message
    suspect doit être transmis au classifieur / LLM.
    """
    result = RulesCheckResult()
    for check in CHECKS:
        violation = check(content)
        if violation:
            result.add(violation.rule, violation.reason)
    return result
